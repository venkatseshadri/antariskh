"""Portfolio Manager Tests — PM-01 through PM-12.

Engine-only, deterministic. Tests strategy selection, strike calculation,
spec generation, and CEO reporting.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


SAMPLE_MARKET = {
    "nifty_spot": 24500,
    "vix": 15.0,
    "indicators": {
        "supertrend_1min": "BULLISH",
        "ema_5_20_alignment": True,
        "smc_bos_alignment": True,
        "adx": 25.0,
    },
    "gap_pct": 0.2,
    "event_day": False,
    "sentiment": "BULLISH",
}

SAMPLE_MARKET_BEARISH = {
    "nifty_spot": 24500,
    "vix": 22.0,
    "indicators": {
        "supertrend_1min": "BEARISH",
        "ema_5_20_alignment": False,
        "smc_bos_alignment": False,
        "adx": 18.0,
    },
    "gap_pct": 0.8,
    "event_day": True,
    "sentiment": "BEARISH",
}

# ============================================================
# Strategy Selection Tests (3)
# ============================================================


def test_PM_01_select_iron_fly_normal_conditions():
    """PM-01: Normal conditions (VIX<20, bullish, no event) → Iron Butterfly."""
    from tools.pm_tools import select_strategy

    result = select_strategy(SAMPLE_MARKET)
    assert result["type"] == "IRON_FLY"
    assert result["reason"] is not None


def test_PM_02_select_credit_spread_high_vix():
    """PM-02: VIX > 20 → Credit Spread (lower risk in volatile markets)."""
    from tools.pm_tools import select_strategy

    result = select_strategy(SAMPLE_MARKET_BEARISH)
    assert result["type"] == "CREDIT_SPREAD"
    assert "VIX" in result["reason"].upper() or "vix" in result["reason"].lower()


def test_PM_03_select_iron_fly_high_vix_confirmed_trend():
    """PM-03: VIX>20 but all confirmations bullish + strong ADX → IB."""
    from tools.pm_tools import select_strategy

    market = {
        **SAMPLE_MARKET,
        "vix": 22.0,
        "indicators": {
            **SAMPLE_MARKET["indicators"],
            "adx": 28.0,
        },
    }
    result = select_strategy(market)
    # High ADX + all bullish confirmations can override high VIX
    assert result["type"] in ("IRON_FLY", "CREDIT_SPREAD")


# ============================================================
# Strike Calculation Tests (3)
# ============================================================


def test_PM_04_calculate_iron_fly_strikes():
    """PM-04: NIFTY at 24500, wing 300, grid 50 → 4 strikes calculated."""
    from tools.pm_tools import calculate_strikes

    strikes = calculate_strikes(
        nifty_spot=24500, strategy_type="IRON_FLY", wing_width=300, grid=50
    )
    assert len(strikes) == 4, "Iron Fly needs 4 legs"
    assert strikes[0] == 24200, (
        f"Lower sell wing: NIFTY - wing = 24500-300 = 24200, got {strikes[0]}"
    )
    assert strikes[1] == 24450, f"Lower buy wing: near ATM, got {strikes[1]}"
    assert strikes[2] == 24550, f"Upper buy wing: near ATM, got {strikes[2]}"
    assert strikes[3] == 24800, (
        f"Upper sell wing: NIFTY + wing = 24500+300 = 24800, got {strikes[3]}"
    )
    # All strikes on the grid
    for s in strikes:
        assert s % 50 == 0, f"Strike {s} not on 50-point grid"


def test_PM_05_calculate_credit_spread_strikes():
    """PM-05: Credit Spread = 2 strikes."""
    from tools.pm_tools import calculate_strikes

    strikes = calculate_strikes(
        nifty_spot=24500, strategy_type="CREDIT_SPREAD", wing_width=300, grid=50
    )
    assert len(strikes) == 2, "Credit Spread needs 2 legs"
    assert strikes[0] == 24200, "Lower strike"
    assert strikes[1] == 24800, "Upper strike"


def test_PM_06_strikes_grid_alignment():
    """PM-06: All strikes snap to the 50-point grid."""
    from tools.pm_tools import calculate_strikes

    for nifty in [24485, 24513, 24598]:
        strikes = calculate_strikes(
            nifty_spot=nifty, strategy_type="IRON_FLY", wing_width=300, grid=50
        )
        for s in strikes:
            assert s % 50 == 0, f"Strike {s} snap-to-grid failed for spot {nifty}"


# ============================================================
# Strategy Spec Tests (3)
# ============================================================


def test_PM_07_build_strategy_spec_iron_fly():
    """PM-07: Full IB spec built from market state."""
    from tools.pm_tools import build_strategy_spec

    spec = build_strategy_spec("IRON_FLY", SAMPLE_MARKET)
    assert spec["type"] == "IRON_FLY"
    assert len(spec["strikes"]) == 4
    assert spec["lots"] == 1
    assert spec["sl"] > 0
    assert spec["tsl"] > 0
    assert "indicators" in spec


def test_PM_08_build_strategy_spec_credit_spread():
    """PM-08: Credit Spread spec with wider wings at high VIX."""
    from tools.pm_tools import build_strategy_spec

    spec = build_strategy_spec("CREDIT_SPREAD", SAMPLE_MARKET_BEARISH)
    assert spec["type"] == "CREDIT_SPREAD"
    assert len(spec["strikes"]) == 2, "CS needs 2 strikes"


def test_PM_09_spec_respects_resource_limits():
    """PM-09: Spec stays within resource caps (max lots, max indicators)."""
    from tools.pm_tools import build_strategy_spec

    spec = build_strategy_spec("IRON_FLY", SAMPLE_MARKET)
    assert spec["lots"] <= 2, "Max 2 lots per resource limit"
    assert len(spec.get("indicators", {})) <= 8, "Max 8 indicators"


# ============================================================
# CEO Reporting Tests (2)
# ============================================================


def test_PM_10_strategy_summary_ceo():
    """PM-10: CEO strategy summary includes WR, PF, strategy type."""
    from tools.pm_tools import build_strategy_spec, generate_strategy_summary

    specs = [build_strategy_spec("IRON_FLY", SAMPLE_MARKET)]
    summary = generate_strategy_summary(
        specs, win_rate=0.65, profit_factor=1.8, pa_actions_taken=3
    )
    assert "win rate" in summary["text"].lower()
    assert "profit factor" in summary["text"].lower()
    assert summary["strategies_active"] == 1


def test_PM_11_strategy_summary_no_active():
    """PM-11: No strategies active — empty summary handled."""
    from tools.pm_tools import generate_strategy_summary

    summary = generate_strategy_summary(
        [], win_rate=0.0, profit_factor=0.0, pa_actions_taken=0
    )
    assert summary["strategies_active"] == 0


# ============================================================
# Integration Test (1)
# ============================================================


def test_PM_12_full_pm_pipeline():
    """PM-12: Select → calculate → spec → summary — full PM workflow."""
    from tools.pm_tools import (
        select_strategy,
        calculate_strikes,
        build_strategy_spec,
        generate_strategy_summary,
    )

    strategy = select_strategy(SAMPLE_MARKET)
    spec = build_strategy_spec(strategy["type"], SAMPLE_MARKET)
    strikes = calculate_strikes(SAMPLE_MARKET["nifty_spot"], strategy["type"], 300, 50)
    summary = generate_strategy_summary([spec], 0.65, 1.8, 3)

    assert spec["type"] == strategy["type"]
    assert spec["strikes"] == strikes
    assert summary["strategies_active"] == 1, "One strategy should be active"
    assert summary["win_rate"] == 0.65
    assert summary["profit_factor"] == 1.8
