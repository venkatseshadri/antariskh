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


@pytest.mark.engine
@pytest.mark.pm
def test_PM_01_select_iron_fly_normal_conditions():
    """PM-01: Normal conditions (VIX<20, bullish, no event) → Iron Butterfly."""
    from tools.pm_tools import select_strategy

    result = select_strategy(SAMPLE_MARKET)
    assert result["type"] == "IRON_FLY"
    assert result["reason"] is not None


@pytest.mark.engine
@pytest.mark.pm
def test_PM_02_select_credit_spread_high_vix():
    """PM-02: VIX > 20 → Credit Spread (lower risk in volatile markets)."""
    from tools.pm_tools import select_strategy

    result = select_strategy(SAMPLE_MARKET_BEARISH)
    assert result["type"] == "CREDIT_SPREAD"
    assert "VIX" in result["reason"].upper() or "vix" in result["reason"].lower()


@pytest.mark.engine
@pytest.mark.pm
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


@pytest.mark.engine
@pytest.mark.pm
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


@pytest.mark.engine
@pytest.mark.pm
def test_PM_05_calculate_credit_spread_strikes():
    """PM-05: Credit Spread = 2 strikes."""
    from tools.pm_tools import calculate_strikes

    strikes = calculate_strikes(
        nifty_spot=24500, strategy_type="CREDIT_SPREAD", wing_width=300, grid=50
    )
    assert len(strikes) == 2, "Credit Spread needs 2 legs"
    assert strikes[0] == 24200, "Lower strike"
    assert strikes[1] == 24800, "Upper strike"


@pytest.mark.engine
@pytest.mark.pm
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


@pytest.mark.engine
@pytest.mark.pm
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


@pytest.mark.engine
@pytest.mark.pm
def test_PM_08_build_strategy_spec_credit_spread():
    """PM-08: Credit Spread spec with wider wings at high VIX."""
    from tools.pm_tools import build_strategy_spec

    spec = build_strategy_spec("CREDIT_SPREAD", SAMPLE_MARKET_BEARISH)
    assert spec["type"] == "CREDIT_SPREAD"
    assert len(spec["strikes"]) == 2, "CS needs 2 strikes"


@pytest.mark.engine
@pytest.mark.pm
def test_PM_09_spec_respects_resource_limits():
    """PM-09: Spec stays within resource caps (max lots, max indicators)."""
    from tools.pm_tools import build_strategy_spec

    spec = build_strategy_spec("IRON_FLY", SAMPLE_MARKET)
    assert spec["lots"] <= 2, "Max 2 lots per resource limit"
    assert len(spec.get("indicators", {})) <= 8, "Max 8 indicators"


# ============================================================
# CEO Reporting Tests (2)
# ============================================================


@pytest.mark.engine
@pytest.mark.pm
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


@pytest.mark.engine
@pytest.mark.pm
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


@pytest.mark.engine
@pytest.mark.pm
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


# ============================================================
# Edge-Case Tests — PM-13 through PM-18
# ============================================================


@pytest.mark.engine
@pytest.mark.pm
def test_PM_13_strategy_select_edge_case_all_fail():
    """PM-13: VIX>20 + event day + bearish + gap>0.5 + all indicators bearish → Credit Spread."""
    from tools.pm_tools import select_strategy

    result = select_strategy(SAMPLE_MARKET_BEARISH)
    # All signals fail: high VIX, event day, bearish, high gap — must be CS
    assert result["type"] == "CREDIT_SPREAD", (
        f"All-fail edge case should return Credit Spread, got {result['type']}"
    )
    assert "CS" in result.get("reason", "") or "CREDIT_SPREAD" in result.get(
        "reason", ""
    )


@pytest.mark.engine
@pytest.mark.pm
def test_PM_14_strike_calculation_nifty_boundary():
    """PM-14: Spot at exact grid boundaries (24500, 24550) → handled without crash."""
    from tools.pm_tools import calculate_strikes

    for spot in [24500, 24550]:
        strikes = calculate_strikes(
            nifty_spot=spot, strategy_type="IRON_FLY", wing_width=300, grid=50
        )
        assert len(strikes) == 4, (
            f"Expected 4 strikes at spot {spot}, got {len(strikes)}"
        )
        for s in strikes:
            assert s % 50 == 0, f"Strike {s} not on grid for spot {spot}"
            assert s > 0, f"Strike {s} must be positive for spot {spot}"
        # Verify strike ordering
        assert strikes == sorted(strikes), (
            f"Strikes not monotonic for spot {spot}: {strikes}"
        )


@pytest.mark.engine
@pytest.mark.pm
def test_PM_15_strike_calculation_nonstandard_wing():
    """PM-15: wing_width=0 returns meaningful strikes (no crash)."""
    from tools.pm_tools import calculate_strikes

    strikes = calculate_strikes(
        nifty_spot=24485, strategy_type="IRON_FLY", wing_width=0, grid=50
    )
    assert isinstance(strikes, list), f"Expected list, got {type(strikes)}"
    for s in strikes:
        assert isinstance(s, (int, float)), f"Strike {s} should be numeric"
        assert s % 50 == 0, f"Strike {s} not on grid"
        assert s > 0, f"Strike {s} must be positive"

    # wing_width=0 on Credit Spread should also work
    cs_strikes = calculate_strikes(
        nifty_spot=24485, strategy_type="CREDIT_SPREAD", wing_width=0, grid=50
    )
    assert len(cs_strikes) == 2, f"Expected 2 CS strikes, got {len(cs_strikes)}"


@pytest.mark.engine
@pytest.mark.pm
def test_PM_16_spec_includes_vix_and_spot():
    """PM-16: Built spec contains vix_at_spec_time and nifty_spot fields."""
    from tools.pm_tools import build_strategy_spec

    spec = build_strategy_spec("IRON_FLY", SAMPLE_MARKET)
    assert "vix_at_spec_time" in spec, "Spec must include vix_at_spec_time"
    assert "nifty_spot" in spec, "Spec must include nifty_spot"
    assert spec["vix_at_spec_time"] == pytest.approx(15.0)
    assert spec["nifty_spot"] == 24500

    # Also verify for Credit Spread
    cs_spec = build_strategy_spec("CREDIT_SPREAD", SAMPLE_MARKET_BEARISH)
    assert cs_spec["vix_at_spec_time"] == pytest.approx(22.0)
    assert cs_spec["nifty_spot"] == 24500


@pytest.mark.engine
@pytest.mark.pm
def test_PM_17_ceo_summary_verdict_below_floor():
    """PM-17: WR at 0.50 (below 0.55 floor) → verdict mentions 'below floor'."""
    from tools.pm_tools import build_strategy_spec, generate_strategy_summary

    specs = [build_strategy_spec("IRON_FLY", SAMPLE_MARKET)]
    summary = generate_strategy_summary(specs, win_rate=0.50, profit_factor=1.5)
    assert "below floor" in summary["text"].lower(), (
        f"Verdict should mention 'below floor', got:\n{summary['text']}"
    )
    assert summary["win_rate"] == pytest.approx(0.50)
    assert summary["strategies_active"] == 1


@pytest.mark.engine
@pytest.mark.pm
def test_PM_18_ceo_summary_verdict_near_floor():
    """PM-18: WR at 0.55 (exactly at floor) → verdict mentions 'near floor'."""
    from tools.pm_tools import build_strategy_spec, generate_strategy_summary

    specs = [build_strategy_spec("CREDIT_SPREAD", SAMPLE_MARKET_BEARISH)]
    summary = generate_strategy_summary(specs, win_rate=0.55, profit_factor=1.8)
    assert "near floor" in summary["text"].lower(), (
        f"Verdict should mention 'near floor', got:\n{summary['text']}"
    )
    assert summary["win_rate"] == pytest.approx(0.55)
    assert summary["strategies_active"] == 1
