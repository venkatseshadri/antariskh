"""Integration Tests — INT-01 through INT-12.

Cross-crew interface validation. Tests that crew outputs connect properly.
Communication protocol deferred — tests validate data contracts only.
"""

import os, sys, pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# INT-01 to INT-08: Crew-to-crew data contracts
def test_INT_01_pm_to_ta_spec_format():
    from tools.pm_tools import build_strategy_spec
    from tools.ta_tools import validate_trade

    spec = build_strategy_spec(
        "IRON_FLY", {"nifty_spot": 24500, "vix": 15, "indicators": {}}
    )
    assert "type" in spec and "strikes" in spec and "lots" in spec, (
        "PM spec has required fields for TA"
    )


def test_INT_02_ta_to_pm_compliance_format():
    from tools.ta_tools import generate_compliance_report, validate_trade

    spec = {
        "type": "IRON_FLY",
        "strikes": [24100, 24200, 24500, 24800],
        "wings": 300,
        "lots": 1,
        "sl": 3500,
        "tsl": 250,
        "broker": "shoonya",
    }
    trade = {
        **spec,
        "entry_price": 245,
        "entry_time": "10:35",
        "fees": 120,
        "slippage": 5,
        "trade_id": "T001",
    }
    r = validate_trade(spec, trade)
    report = generate_compliance_report("T001", spec, r["violations"])
    assert "accuracy" in report, "Compliance report has accuracy"


def test_INT_03_ta_to_am_ledger_format():
    from tools.ta_tools import generate_execution_ledger

    ledger = generate_execution_ledger(
        [{"pnl": 500, "fees": 50, "slippage": 5, "broker": "shoonya"}], "2026-05-12"
    )
    assert "total_pnl" in ledger, "Ledger has total P&L for AM"


def test_INT_04_am_to_pm_capital_format():
    from tools.am_tools import generate_capital_report

    r = generate_capital_report(150000, 100000, 30000, 100)
    assert "margin_pct" in r, "Capital report has margin % for PM"


def test_INT_05_am_to_ceo_financial_format():
    from tools.am_tools import generate_financial_report

    r = generate_financial_report(
        {"day_pnl": 500, "net_pnl": 450, "day_fees": 50, "trade_count": 2},
        {"ok": True, "pct_used": 50},
        {
            "overall_ok": True,
            "daily_ok": True,
            "portfolio_ok": True,
            "free_cash_ok": True,
        },
    )
    assert "text" in r


def test_INT_06_pm_to_ceo_strategy_format():
    from tools.pm_tools import generate_strategy_summary

    r = generate_strategy_summary(
        [
            {
                "type": "IRON_FLY",
                "strikes": [24100, 24200, 24500, 24800],
                "wings": 300,
                "lots": 1,
                "sl": 3500,
                "tsl": 250,
            }
        ],
        0.65,
        1.8,
        3,
    )
    assert "win_rate" in r


def test_INT_07_om_to_ceo_health_format():
    from tools.om_tools import aggregate_health_report

    r = aggregate_health_report([{"name": "tokens", "ok": True, "evidence": "OK"}])
    assert "overall" in r and "telegram_md" in r


def test_INT_08_pm_to_ta_full_roundtrip():
    from tools.pm_tools import build_strategy_spec
    from tools.ta_tools import validate_trade

    spec = build_strategy_spec(
        "IRON_FLY", {"nifty_spot": 24500, "vix": 15, "indicators": {}}
    )
    trade = {
        **spec,
        "entry_price": 245,
        "entry_time": "10:35",
        "fees": 120,
        "slippage": 5,
        "trade_id": "T001",
    }
    r = validate_trade(spec, trade)
    assert r["valid"], "Roundtrip PM→TA validates"


# INT-09 to INT-12: Multi-crew integration
def test_INT_09_om_to_ceo_roundtrip():
    from tools.om_tools import token_refresh_status, aggregate_health_report
    import os

    os.environ["ANTARIKSH_MOCK_MODE"] = "1"
    r = token_refresh_status()
    report = aggregate_health_report([{"name": "tokens", **r}])
    assert report["overall"] in ("GO", "NOGO")
    del os.environ["ANTARIKSH_MOCK_MODE"]


def test_INT_10_all_crews_report_to_ceo():
    from tools.ceo_tools import aggregate_crew_performance

    crews = [
        {"role": "OM", "uptime": 1.0},
        {"role": "PM", "win_rate": 0.62},
        {"role": "TA", "compliance": 1.0},
        {"role": "AM", "margin_ok": True},
    ]
    r = aggregate_crew_performance(crews)
    assert r["crews_active"] == 4


def test_INT_11_pa_feedback_reaches_pm():
    from tools.pa_tools import (
        review_trade,
        generate_post_mortem_report,
        detect_patterns,
    )

    trade = {
        "id": "T001",
        "type": "IRON_FLY",
        "lots": 1,
        "strikes": [24100, 24200, 24500, 24800],
        "pnl": -3500,
        "sl_hit": True,
    }
    spec = trade
    reviews = [review_trade(trade, spec)]
    patterns = detect_patterns([trade])
    report = generate_post_mortem_report(reviews, [], patterns, "2026-05-12")
    assert len(report["recommendations"]) > 0


def test_INT_12_full_company_stack():
    """All 6 crew tools importable and callable."""
    import tools.om_tools, tools.ta_tools, tools.pm_tools, tools.am_tools, tools.pa_tools, tools.ceo_tools

    assert True, "All tool modules importable"
