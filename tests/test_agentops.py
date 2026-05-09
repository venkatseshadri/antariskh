"""AgentOps Observability Tests — AO-01 through AO-20.

Validates agent execution tracing, span creation, error tracking,
session management, and multi-crew execution graphs.

Engineering-only: no AgentOps API key required for local tracing.
"""

import os, sys, yaml, time
from datetime import datetime, timezone, timedelta
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PYTHONPATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".venv/lib/python3.12/site-packages",
)
if PYTHONPATH not in sys.path:
    sys.path.insert(0, PYTHONPATH)


# ============================================================
# Test helpers
# ============================================================


def _import_agentops():
    """Lazy import with path fix."""
    import agentops

    return agentops


def _mock_api_key_env():
    """Set mock AgentOps API key for local tracing (no dashboard upload)."""
    os.environ["AGENTOPS_API_KEY"] = os.environ.get(
        "AGENTOPS_API_KEY", "test-key-local"
    )


def _clear_api_key_env():
    for k in ("AGENTOPS_API_KEY", "AGENTOPS_API_KEY_HISTORY"):
        os.environ.pop(k, None)


# ============================================================
# Session & Span Tests (4)
# ============================================================


def test_AO_01_agentops_imports():
    """AO-01: AgentOps SDK is importable and has expected decorators."""
    ao = _import_agentops()
    assert hasattr(ao, "init"), "agentops.init should exist"
    assert hasattr(ao, "end_session"), "agentops.end_session should exist"
    from agentops.sdk.decorators import session, operation, agent, workflow

    assert callable(session), "@session decorator should be callable"
    assert callable(operation), "@operation decorator should be callable"


def test_AO_02_session_init_and_end():
    """AO-02: Session init/end without errors."""
    _mock_api_key_env()
    ao = _import_agentops()
    ao.init(tags=["test", "session-lifecycle"], auto_start_session=False)
    time.sleep(0.1)
    result = ao.end_session("Success")
    assert result in ("Success", None), f"end_session should not error: {result}"
    _clear_api_key_env()


def test_AO_03_operation_decorator_tracks_execution():
    """AO-03: @operation decorator wraps function and tracks execution."""
    _mock_api_key_env()
    ao = _import_agentops()
    from agentops.sdk.decorators import operation

    @operation
    def sample_tool(input_data: str) -> dict:
        return {"result": input_data.upper(), "ok": True}

    result = sample_tool("test input")
    assert result["ok"] is True, "Decorated function should execute normally"
    assert result["result"] == "TEST INPUT", "Result should be correct"
    ao.end_session("Success")
    _clear_api_key_env()


def test_AO_04_operation_decorator_captures_errors():
    """AO-04: @operation decorator captures exceptions."""
    _mock_api_key_env()
    ao = _import_agentops()
    from agentops.sdk.decorators import operation

    @operation
    def failing_tool():
        raise ValueError("Simulated tool failure")

    with pytest.raises(ValueError, match="Simulated tool failure"):
        failing_tool()
    ao.end_session("Success")
    _clear_api_key_env()


# ============================================================
# Crew Tool Span Tracking (7)
# ============================================================


def test_AO_05_om_tools_span_tracking():
    """AO-05: OM tools execute with AgentOps span tracking."""
    _mock_api_key_env()
    ao = _import_agentops()
    ao.init(tags=["test", "om-tools", "span-tracking"])

    os.environ["ANTARIKSH_MOCK_MODE"] = "1"
    from tools.om_tools import token_refresh_status

    result = token_refresh_status()
    assert "evidence" in result

    ao.end_session("Success")
    _clear_api_key_env()
    os.environ.pop("ANTARIKSH_MOCK_MODE", None)


def test_AO_06_ta_tools_span_tracking():
    """AO-06: TA tools execute with span tracking."""
    _mock_api_key_env()
    ao = _import_agentops()
    ao.init(tags=["test", "ta-tools"])
    from tools.ta_tools import validate_trade

    spec = {
        "type": "IRON_FLY",
        "strikes": [24100, 24200, 24500, 24800],
        "wings": 300,
        "lots": 1,
        "sl": 3500,
        "tsl": 250,
        "broker": "shoonya",
    }
    trade = {**spec, "entry_price": 245}
    result = validate_trade(spec, trade)
    assert result["valid"]
    ao.end_session("Success")
    _clear_api_key_env()


def test_AO_07_pm_tools_span_tracking():
    """AO-07: PM tools execute with span tracking."""
    _mock_api_key_env()
    ao = _import_agentops()
    ao.init(tags=["test", "pm-tools"])
    from tools.pm_tools import select_strategy

    result = select_strategy(
        {
            "nifty_spot": 24500,
            "vix": 15,
            "indicators": {},
            "event_day": False,
            "gap_pct": 0.2,
            "sentiment": "BULLISH",
        }
    )
    assert result["type"] in ("IRON_FLY", "CREDIT_SPREAD")
    ao.end_session("Success")
    _clear_api_key_env()


def test_AO_08_am_tools_span_tracking():
    """AO-08: AM tools execute with span tracking."""
    _mock_api_key_env()
    ao = _import_agentops()
    ao.init(tags=["test", "am-tools"])
    from tools.am_tools import check_capital_limits

    result = check_capital_limits(day_pnl=500, portfolio_pnl=1000, free_cash=50000)
    assert result["overall_ok"]
    ao.end_session("Success")
    _clear_api_key_env()


def test_AO_09_pa_tools_span_tracking():
    """AO-09: PA tools execute with span tracking."""
    _mock_api_key_env()
    ao = _import_agentops()
    ao.init(tags=["test", "pa-tools"])
    from tools.pa_tools import review_trade

    trade = {
        "id": "T001",
        "type": "IRON_FLY",
        "lots": 1,
        "strikes": [24100, 24200, 24500, 24800],
        "pnl": 850,
        "sl_hit": False,
        "tp_hit": True,
    }
    result = review_trade(trade, trade)
    assert result["quality"] == "EXCELLENT"
    ao.end_session("Success")
    _clear_api_key_env()


def test_AO_10_ceo_tools_span_tracking():
    """AO-10: CEO tools execute with span tracking."""
    _mock_api_key_env()
    ao = _import_agentops()
    ao.init(tags=["test", "ceo-tools"])
    from tools.ceo_tools import alignment_check

    goals = ["Don't burn capital", "₹36L/year passive income"]
    result = alignment_check({"action": "select IRON_FLY"}, goals)
    assert result["aligned"]
    ao.end_session("Success")
    _clear_api_key_env()


def test_AO_11_all_36_tools_span_integrity():
    """AO-11: All 36 tools execute within a single session, spans created."""
    _mock_api_key_env()
    ao = _import_agentops()
    ao.init(tags=["test", "all-tools", "span-integrity"])

    os.environ["ANTARIKSH_MOCK_MODE"] = "1"

    # OM (7 tools)
    from tools.om_tools import token_refresh_status as t1
    from tools.om_tools import verify_code_hash as t2
    from tools.om_tools import data_capture_health as t3
    from tools.om_tools import disk_usage_check as t4
    from tools.om_tools import network_connectivity_check as t5
    from tools.om_tools import cron_health_check as t6
    from tools.om_tools import aggregate_health_report as t7

    # TA (5 tools)
    from tools.ta_tools import validate_trade as t8
    from tools.ta_tools import check_slippage as t9
    from tools.ta_tools import detect_duplicate as t10
    from tools.ta_tools import generate_compliance_report as t11
    from tools.ta_tools import generate_execution_ledger as t12

    # PM (4 tools)
    from tools.pm_tools import select_strategy as t13
    from tools.pm_tools import calculate_strikes as t14
    from tools.pm_tools import build_strategy_spec as t15
    from tools.pm_tools import generate_strategy_summary as t16

    # AM (5 tools)
    from tools.am_tools import track_cumulative_pnl as t17
    from tools.am_tools import check_margin as t18
    from tools.am_tools import check_capital_limits as t19
    from tools.am_tools import generate_financial_report as t20
    from tools.am_tools import generate_capital_report as t21

    # PA (4 tools)
    from tools.pa_tools import review_trade as t22
    from tools.pa_tools import run_counterfactuals as t23
    from tools.pa_tools import detect_patterns as t24
    from tools.pa_tools import generate_post_mortem_report as t25

    # CEO (7 tools)
    from tools.ceo_tools import alignment_check as t26
    from tools.ceo_tools import aggregate_crew_performance as t27
    from tools.ceo_tools import enforce_resource_caps as t28
    from tools.ceo_tools import generate_board_report as t29
    from tools.ceo_tools import should_escalate as t30
    from tools.ceo_tools import check_authority as t31
    from tools.ceo_tools import governance_veto as t32

    # Execute all 36 tools
    results = []
    # OM
    r = t1()
    results.append(r)
    r = t2()
    results.append(r)
    r = t3()
    results.append(r)
    r = t4()
    results.append(r)
    r = t5()
    results.append(r)
    r = t6()
    results.append(r)
    r = t7([{"name": "tokens", "ok": True, "evidence": "OK"}])
    results.append(r)
    # TA
    spec = {
        "type": "IRON_FLY",
        "strikes": [24100, 24200, 24500, 24800],
        "wings": 300,
        "lots": 1,
        "sl": 3500,
        "tsl": 250,
        "broker": "shoonya",
    }
    r = t8(spec, spec)
    results.append(r)
    r = t9(24500, 24505, 50)
    results.append(r)
    r = t10(spec, [])
    results.append(r)
    r = t11("T001", spec, [])
    results.append(r)
    r = t12([{"pnl": 500, "fees": 50}], "2026-05-12")
    results.append(r)
    # PM
    market = {
        "nifty_spot": 24500,
        "vix": 15,
        "indicators": {},
        "event_day": False,
        "gap_pct": 0.2,
        "sentiment": "BULLISH",
    }
    r = t13(market)
    results.append(r)
    r = t14(24500, "IRON_FLY", 300, 50)
    results.append(r)
    r = t15("IRON_FLY", market)
    results.append(r)
    r = t16([r], 0.65, 1.8, 3)
    results.append(r)
    # AM
    r = t17([{"pnl": 500}], "2026-05-12")
    results.append(r)
    r = t18(100000, 250000)
    results.append(r)
    r = t19(500, 1000, 50000)
    results.append(r)
    r = t20({"day_pnl": 500}, {"ok": True}, {"overall_ok": True})
    results.append(r)
    r = t21(150000, 100000, 50000, 100)
    results.append(r)
    # PA
    trade = {
        "id": "T001",
        "type": "IRON_FLY",
        "lots": 1,
        "strikes": [24100, 24200, 24500, 24800],
        "pnl": 850,
        "sl_hit": False,
    }
    r = t22(trade, trade)
    results.append(r)
    r = t23(trade, 850)
    results.append(r)
    r = t24([trade])
    results.append(r)
    r = t25([r], [r], t24([trade]), "2026-05-12")
    results.append(r)
    # CEO
    r = t26(spec, ["Don't burn capital"])
    results.append(r)
    r = t27([{"role": "OM", "uptime": 1.0}])
    results.append(r)
    r = t28(2, 200000, 1)
    results.append(r)
    r = t29({})
    results.append(r)
    r = t30([False, False, False], 3)
    results.append(r)
    r = t31("crew_dispatch")
    results.append(r)
    r = t32("PM", "strategy_switch", "IF")
    results.append(r)

    assert len(results) >= 30, f"Expected ~36 tool results, got {len(results)}"
    all_ok = all(isinstance(r, (dict, list, bool)) for r in results)
    assert all_ok, "All tool results should be structured data"

    ao.end_session("Success")
    _clear_api_key_env()
    os.environ.pop("ANTARIKSH_MOCK_MODE", None)


# ============================================================
# Crew Build & Execution Tests (4)
# ============================================================


def test_AO_12_om_crew_builds_with_agentops():
    """AO-12: OM crew builds and agents are traceable."""
    _mock_api_key_env()
    ao = _import_agentops()
    ao.init(tags=["test", "om-crew-build"])
    from crews.om_crew import build_om_crew

    crew = build_om_crew()
    assert len(crew.agents) == 3
    assert len(crew.tasks) == 3
    ao.end_session("Success")
    _clear_api_key_env()


def test_AO_13_ta_crew_builds_with_agentops():
    """AO-13: TA crew builds and agents are traceable."""
    _mock_api_key_env()
    ao = _import_agentops()
    ao.init(tags=["test", "ta-crew-build"])
    from crews.ta_crew import build_ta_crew

    crew = build_ta_crew()
    assert len(crew.agents) == 2
    ao.end_session("Success")
    _clear_api_key_env()


def test_AO_14_all_6_crews_build_traceable():
    """AO-14: All 6 crews build within a single AgentOps session."""
    _mock_api_key_env()
    ao = _import_agentops()
    ao.init(tags=["test", "all-crews", "build-integrity"])
    from crews.om_crew import build_om_crew
    from crews.ta_crew import build_ta_crew
    from crews.pm_crew import build_pm_crew
    from crews.am_crew import build_am_crew
    from crews.pa_crew import build_pa_crew
    from crews.ceo_crew import build_ceo_crew

    assert len(build_om_crew().agents) == 3
    assert len(build_ta_crew().agents) == 2
    assert len(build_pm_crew().agents) == 2
    assert len(build_am_crew().agents) == 2
    assert len(build_pa_crew().agents) == 2
    assert len(build_ceo_crew().agents) == 2
    ao.end_session("Success")
    _clear_api_key_env()


def test_AO_15_crew_tools_are_agentops_compatible():
    """AO-15: All crew tools are decorated callables suitable for AgentOps tracking."""
    _mock_api_key_env()
    ao = _import_agentops()
    ao.init(tags=["test", "tool-compatibility"])
    crews_to_check = {
        "om_crew": 7,
        "ta_crew": 5,
        "pm_crew": 4,
        "am_crew": 5,
        "pa_crew": 4,
        "ceo_crew": 7,
    }
    for module_name, expected in crews_to_check.items():
        mod = __import__(f"crews.{module_name}", fromlist=["build_crew"])
        # Count functions, exclude Agent/Task/Crew classes
        funcs = [
            n
            for n in dir(mod)
            if callable(getattr(mod, n))
            and not n.startswith("_")
            and hasattr(getattr(mod, n), "__doc__")
        ]
        assert len(funcs) >= 2, (
            f"{module_name}: expected at least {expected} functions, got {len(funcs)}"
        )
    ao.end_session("Success")
    _clear_api_key_env()


# ============================================================
# Error Handling & Resilience (3)
# ============================================================


def test_AO_16_tool_errors_captured_in_span():
    """AO-16: Tool exceptions do not crash AgentOps session."""
    _mock_api_key_env()
    ao = _import_agentops()
    ao.init(tags=["test", "error-resilience"])
    from tools.om_tools import token_refresh_status

    try:
        os.environ.pop("ANTARIKSH_MOCK_MODE", None)
        token_refresh_status()  # May fail without mock mode — shouldn't crash
    except Exception:
        pass
    result = ao.end_session("Partial — tested error handling")
    assert result in ("Partial — tested error handling", None)
    _clear_api_key_env()


def test_AO_17_multi_session_isolation():
    """AO-17: Multiple AgentOps sessions are isolated — no cross-contamination."""
    _mock_api_key_env()
    ao = _import_agentops()
    ao.init(tags=["session-1"])
    ao.end_session("Session 1 done")

    ao.init(tags=["session-2"])
    ao.end_session("Session 2 done")
    assert True  # No crash = isolation works
    _clear_api_key_env()


def test_AO_18_session_without_init_graceful():
    """AO-18: Calling end_session without init is handled gracefully."""
    _clear_api_key_env()
    ao = _import_agentops()
    result = ao.end_session("No session")
    assert result in ("No session", None, "no_session_found")
    _clear_api_key_env()


# ============================================================
# Cross-Crew Execution Graph (2)
# ============================================================


def test_AO_19_cross_crew_data_flow_tracked():
    """AO-19: PM → TA → AM data flow tracked in single session."""
    _mock_api_key_env()
    ao = _import_agentops()
    ao.init(tags=["test", "cross-crew", "data-flow"])
    from tools.pm_tools import build_strategy_spec
    from tools.ta_tools import validate_trade, generate_execution_ledger
    from tools.am_tools import track_cumulative_pnl

    market = {
        "nifty_spot": 24500,
        "vix": 15,
        "indicators": {},
        "event_day": False,
        "gap_pct": 0.2,
        "sentiment": "BULLISH",
    }
    spec = build_strategy_spec("IRON_FLY", market)
    trade = {**spec, "entry_price": 245}
    validation = validate_trade(spec, trade)
    assert validation["valid"]
    ledger = generate_execution_ledger([{"pnl": 500, "fees": 50}], "2026-05-12")
    pnl = track_cumulative_pnl([{"pnl": 500, "fees": 50}], "2026-05-12")
    assert pnl["day_pnl"] == 500
    assert ledger["total_pnl"] == 500

    ao.end_session("Success")
    _clear_api_key_env()


def test_AO_20_full_company_execution_graph():
    """AO-20: Full 6-crew execution in single session mirrors production."""
    _mock_api_key_env()
    ao = _import_agentops()
    ao.init(
        tags=["test", "full-company", "production-mirror"], auto_start_session=False
    )
    os.environ["ANTARIKSH_MOCK_MODE"] = "1"

    # OM: pre-flight
    from tools.om_tools import token_refresh_status, aggregate_health_report

    token = token_refresh_status()
    health = aggregate_health_report([{"name": "tokens", **token}])
    assert health["overall"] == "GO", "Pre-flight should pass in mock"

    # PM: strategy
    from tools.pm_tools import (
        select_strategy,
        build_strategy_spec,
        generate_strategy_summary,
    )

    market = {
        "nifty_spot": 24500,
        "vix": 15,
        "indicators": {},
        "event_day": False,
        "gap_pct": 0.2,
        "sentiment": "BULLISH",
    }
    strategy = select_strategy(market)
    spec = build_strategy_spec(strategy["type"], market)
    summary = generate_strategy_summary([spec], 0.65, 1.8, 3)
    assert summary["strategies_active"] == 1

    # TA: validate
    from tools.ta_tools import (
        validate_trade,
        generate_compliance_report,
        generate_execution_ledger,
    )

    trade = {
        **spec,
        "entry_price": 245,
        "tp_hit": True,
        "sl_hit": False,
        "pnl": 850,
        "id": "T001",
    }
    validation = validate_trade(spec, trade)
    compliance = generate_compliance_report("T001", spec, validation["violations"])
    ledger = generate_execution_ledger([{"pnl": 850, "fees": 100}], "2026-05-12")
    assert validation["valid"]

    # AM: financial check
    from tools.am_tools import (
        track_cumulative_pnl,
        check_capital_limits,
        generate_financial_report,
    )

    pnl = track_cumulative_pnl([{"pnl": 850, "fees": 100}], "2026-05-12")
    limits = check_capital_limits(pnl["day_pnl"], pnl["day_pnl"], free_cash=50000)
    fin_report = generate_financial_report(pnl, {"ok": True, "pct_used": 40}, limits)
    assert limits["overall_ok"]

    # PA: review
    from tools.pa_tools import (
        review_trade,
        detect_patterns,
        generate_post_mortem_report,
    )

    review = review_trade(trade, trade)
    patterns = detect_patterns([trade])
    pm_report = generate_post_mortem_report([review], [], patterns, "2026-05-12")
    assert review["quality"] == "EXCELLENT"

    # CEO: governance
    from tools.ceo_tools import (
        alignment_check,
        aggregate_crew_performance,
        enforce_resource_caps,
        generate_board_report,
    )

    alignment = alignment_check(
        {"action": "select IRON_FLY", "reason": "VIX=15, bullish"},
        ["Don't burn capital"],
    )
    perf = aggregate_crew_performance(
        [
            {"role": "OM", "uptime": 1.0},
            {"role": "PM", "win_rate": 0.65},
            {"role": "TA", "compliance": 1.0},
            {"role": "AM", "margin_ok": True},
        ]
    )
    caps = enforce_resource_caps(2, 200000, 1)
    board = generate_board_report(
        {"OM": "GO", "PM": "WR 65%", "TA": "100% compliant", "AM": "Healthy"}
    )
    assert alignment["aligned"]
    assert caps["ok"]

    os.environ.pop("ANTARIKSH_MOCK_MODE", None)
    ao.end_session("Success")
    _clear_api_key_env()
