"""Asset Manager Tests — AM-01 through AM-11.

Engine-only, deterministic. Tracks P&L, margin, burn rate, capital limits.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================
# P&L Tracking Tests (2)
# ============================================================


@pytest.mark.engine
@pytest.mark.am
def test_AM_01_cumulative_pnl_tracking():
    """AM-01: Daily P&L accumulates across trades."""
    from tools.am_tools import track_cumulative_pnl

    trades = [
        {"pnl": 500, "fees": 50},
        {"pnl": -200, "fees": 50},
        {"pnl": 800, "fees": 50},
    ]
    result = track_cumulative_pnl(trades, session="2026-05-12")
    assert result["day_pnl"] == 1100, (
        f"500 + (-200) + 800 = 1100, got {result['day_pnl']}"
    )
    assert result["day_fees"] == 150
    assert result["net_pnl"] == 950  # 1100 - 150


@pytest.mark.engine
@pytest.mark.am
def test_AM_02_empty_session():
    """AM-02: No trades — zero P&L, zero fees."""
    from tools.am_tools import track_cumulative_pnl

    result = track_cumulative_pnl([], "2026-05-12")
    assert result["day_pnl"] == 0
    assert result["net_pnl"] == 0


# ============================================================
# Margin Tests (2)
# ============================================================


@pytest.mark.engine
@pytest.mark.am
def test_AM_03_margin_within_limits():
    """AM-03: 50% margin utilization — within 70% target."""
    from tools.am_tools import check_margin

    result = check_margin(used_margin=125000, total_margin=250000)
    assert result["ok"] is True
    assert result["pct_used"] == 50.0


@pytest.mark.engine
@pytest.mark.am
def test_AM_04_margin_exceeds_limit():
    """AM-04: 80% margin utilization — exceeds 70% target."""
    from tools.am_tools import check_margin

    result = check_margin(used_margin=200000, total_margin=250000)
    assert result["ok"] is False, f"80% should exceed 70% limit: {result}"
    assert result["pct_used"] == 80.0


# ============================================================
# Capital Limits Tests (3)
# ============================================================


@pytest.mark.engine
@pytest.mark.am
def test_AM_05_capital_within_limits():
    """AM-05: All capital limits respected."""
    from tools.am_tools import check_capital_limits

    result = check_capital_limits(
        day_pnl=-1000,
        portfolio_pnl=-2000,
        free_cash=50000,
        daily_sl=3500,
        portfolio_sl=4500,
        free_cash_floor=11000,
    )
    assert result["daily_ok"] is True
    assert result["portfolio_ok"] is True
    assert result["free_cash_ok"] is True
    assert result["overall_ok"] is True


@pytest.mark.engine
@pytest.mark.am
def test_AM_06_daily_sl_breached():
    """AM-06: Day P&L = -4000 exceeds ₹3500 SL."""
    from tools.am_tools import check_capital_limits

    result = check_capital_limits(day_pnl=-4000, portfolio_pnl=-2000, free_cash=50000)
    assert result["daily_ok"] is False, f"Daily SL breached: {result}"
    assert result["overall_ok"] is False


@pytest.mark.engine
@pytest.mark.am
def test_AM_07_free_cash_below_floor():
    """AM-07: Free cash ₹8000 < ₹11000 floor."""
    from tools.am_tools import check_capital_limits

    result = check_capital_limits(day_pnl=0, portfolio_pnl=0, free_cash=8000)
    assert result["free_cash_ok"] is False
    assert result["overall_ok"] is False


# ============================================================
# Reporting Tests (3)
# ============================================================


@pytest.mark.engine
@pytest.mark.am
def test_AM_08_financial_report_ceo():
    """AM-08: CEO financial summary with P&L, margin, limits."""
    from tools.am_tools import generate_financial_report

    pnl_data = {"day_pnl": 850, "net_pnl": 750, "day_fees": 100}
    margin = {"ok": True, "pct_used": 45.0}
    limits = {
        "overall_ok": True,
        "daily_ok": True,
        "portfolio_ok": True,
        "free_cash_ok": True,
    }
    report = generate_financial_report(pnl_data, margin, limits, session="2026-05-12")
    assert (
        "P&L" in report["text"]
        or "pnl" in report["text"].lower()
        or "profit" in report["text"].lower()
    )
    assert report["overall_healthy"] is True


@pytest.mark.engine
@pytest.mark.am
def test_AM_09_financial_report_unhealthy():
    """AM-09: Limits breached — unhealthy report."""
    from tools.am_tools import generate_financial_report

    limits = {
        "overall_ok": False,
        "daily_ok": False,
        "portfolio_ok": True,
        "free_cash_ok": True,
    }
    report = generate_financial_report(
        {"day_pnl": -4000, "net_pnl": -4100, "day_fees": 100},
        {"ok": True, "pct_used": 50.0},
        limits,
    )
    assert report["overall_healthy"] is False


@pytest.mark.engine
@pytest.mark.am
def test_AM_10_capital_report_pm():
    """AM-10: Capital report for PM with margin + burn rate."""
    from tools.am_tools import generate_capital_report

    report = generate_capital_report(
        available_margin=125000,
        used_margin=75000,
        free_cash=50000,
        burn_rate_daily=120,
    )
    assert report["margin_pct"] == 37.5, (
        f"(75000/200000)*100 = 37.5, got {report['margin_pct']}"
    )
    assert report["free_cash"] == 50000
    assert "text" in report


# ============================================================
# Integration Test (1)
# ============================================================


@pytest.mark.engine
@pytest.mark.am
def test_AM_11_full_am_pipeline():
    """AM-11: P&L → capital limits → reports — full AM workflow."""
    from tools.am_tools import (
        track_cumulative_pnl,
        check_capital_limits,
        check_margin,
        generate_financial_report,
        generate_capital_report,
    )

    trades = [{"pnl": 500, "fees": 50}, {"pnl": 300, "fees": 50}]
    pnl = track_cumulative_pnl(trades, "2026-05-12")
    limits = check_capital_limits(pnl["day_pnl"], pnl["day_pnl"], free_cash=30000)
    margin = check_margin(used_margin=100000, total_margin=250000)

    ceo_report = generate_financial_report(pnl, margin, limits)
    pm_report = generate_capital_report(150000, 100000, 30000, 100)

    assert ceo_report["overall_healthy"] is True
    assert pm_report["margin_pct"] == 40.0


# ============================================================
# Edge-Case Tests — AM-12 through AM-16
# ============================================================


@pytest.mark.engine
@pytest.mark.am
def test_AM_12_margin_exactly_at_target():
    """AM-12: 70% margin exactly at target → ok=True (not exceeded)."""
    from tools.am_tools import check_margin

    result = check_margin(used_margin=175000, total_margin=250000)
    assert result["ok"] is True, f"70% at target should be ok, got {result}"
    assert result["pct_used"] == 70.0


@pytest.mark.engine
@pytest.mark.am
def test_AM_13_margin_above_limit():
    """AM-13: 86% margin > 85% limit → ok=False."""
    from tools.am_tools import check_margin

    result = check_margin(used_margin=215000, total_margin=250000)
    assert result["ok"] is False, f"86% above 85% limit should fail, got {result}"
    assert result["pct_used"] == 86.0
    # pct_used should exceed both target and limit
    assert result["pct_used"] > result["target_pct"]
    assert result["pct_used"] > result["limit_pct"]


@pytest.mark.engine
@pytest.mark.am
def test_AM_14_burn_rate_accumulation():
    """AM-14: 5-day burn (fees) totals correctly."""
    from tools.am_tools import track_cumulative_pnl

    sessions = [
        [{"pnl": 200, "fees": 50}, {"pnl": -100, "fees": 50}],
        [{"pnl": 500, "fees": 60}],
        [{"pnl": -300, "fees": 50}],
        [{"pnl": 100, "fees": 55}, {"pnl": 400, "fees": 50}],
        [{"pnl": -200, "fees": 50}],
    ]

    total_fees = 0
    total_pnl = 0
    for i, trades in enumerate(sessions):
        result = track_cumulative_pnl(trades, f"2026-05-{12 + i}")
        total_fees += result["day_fees"]
        total_pnl += result["day_pnl"]

    expected_fees = sum(sum(t.get("fees", 0) for t in session) for session in sessions)
    expected_pnl = sum(sum(t.get("pnl", 0) for t in session) for session in sessions)
    assert total_fees == expected_fees, (
        f"5-day fees {total_fees} != expected {expected_fees}"
    )
    assert total_pnl == expected_pnl, (
        f"5-day P&L {total_pnl} != expected {expected_pnl}"
    )
    assert total_fees == pytest.approx(365.0)
    assert total_pnl == pytest.approx(600.0)


@pytest.mark.engine
@pytest.mark.am
def test_AM_15_all_simultaneous_breaches():
    """AM-15: Daily SL hit + free cash below floor + portfolio SL hit → all three fail."""
    from tools.am_tools import check_capital_limits

    result = check_capital_limits(
        day_pnl=-4000,
        portfolio_pnl=-5000,
        free_cash=5000,
        daily_sl=3500,
        portfolio_sl=4500,
        free_cash_floor=11000,
    )
    assert result["daily_ok"] is False, f"Day P&L ₹-4000 exceeds ₹3500 SL"
    assert result["portfolio_ok"] is False, f"Portfolio P&L ₹-5000 exceeds ₹4500 SL"
    assert result["free_cash_ok"] is False, f"Free cash ₹5000 < ₹11000 floor"
    assert result["overall_ok"] is False, "All three breached, overall must be False"


@pytest.mark.engine
@pytest.mark.am
def test_AM_16_zero_trades_non_zero_fees():
    """AM-16: Fees without trades (broker inactivity charge) → handled gracefully."""
    from tools.am_tools import track_cumulative_pnl

    # Zero trades — base case
    result = track_cumulative_pnl([], "2026-05-12")
    assert result["day_pnl"] == 0
    assert result["day_fees"] == 0
    assert result["net_pnl"] == 0
    assert result["trade_count"] == 0

    # Single zero-pnl trade with fees (inactivity charge scenario)
    result_with_fees = track_cumulative_pnl([{"pnl": 0, "fees": 100}], "2026-05-13")
    assert result_with_fees["day_pnl"] == 0
    assert result_with_fees["day_fees"] == 100
    assert result_with_fees["net_pnl"] == -100
    assert result_with_fees["trade_count"] == 1
