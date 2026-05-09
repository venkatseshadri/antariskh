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


def test_AM_02_empty_session():
    """AM-02: No trades — zero P&L, zero fees."""
    from tools.am_tools import track_cumulative_pnl

    result = track_cumulative_pnl([], "2026-05-12")
    assert result["day_pnl"] == 0
    assert result["net_pnl"] == 0


# ============================================================
# Margin Tests (2)
# ============================================================


def test_AM_03_margin_within_limits():
    """AM-03: 50% margin utilization — within 70% target."""
    from tools.am_tools import check_margin

    result = check_margin(used_margin=125000, total_margin=250000)
    assert result["ok"] is True
    assert result["pct_used"] == 50.0


def test_AM_04_margin_exceeds_limit():
    """AM-04: 80% margin utilization — exceeds 70% target."""
    from tools.am_tools import check_margin

    result = check_margin(used_margin=200000, total_margin=250000)
    assert result["ok"] is False, f"80% should exceed 70% limit: {result}"
    assert result["pct_used"] == 80.0


# ============================================================
# Capital Limits Tests (3)
# ============================================================


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


def test_AM_06_daily_sl_breached():
    """AM-06: Day P&L = -4000 exceeds ₹3500 SL."""
    from tools.am_tools import check_capital_limits

    result = check_capital_limits(day_pnl=-4000, portfolio_pnl=-2000, free_cash=50000)
    assert result["daily_ok"] is False, f"Daily SL breached: {result}"
    assert result["overall_ok"] is False


def test_AM_07_free_cash_below_floor():
    """AM-07: Free cash ₹8000 < ₹11000 floor."""
    from tools.am_tools import check_capital_limits

    result = check_capital_limits(day_pnl=0, portfolio_pnl=0, free_cash=8000)
    assert result["free_cash_ok"] is False
    assert result["overall_ok"] is False


# ============================================================
# Reporting Tests (3)
# ============================================================


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
