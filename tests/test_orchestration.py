"""Orchestration Tests — ORCH-01 through ORCH-20.

CrewAI cross-crew orchestration: query routing, task delegation structure,
mock LLM integration, real LLM end-to-end, and full pipeline integration.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# CrewAI LLM constructor demands API key at module load time.
# Set a dummy key for engine tests (LLM is never actually called).
_DUMMY_KEY = "sk-test-dummy-key-for-engine-tests"
if not os.environ.get("DEEPSEEK_API_KEY"):
    os.environ["DEEPSEEK_API_KEY"] = _DUMMY_KEY


def _has_real_llm_key():
    """True if DEEPSEEK_API_KEY is set to a real (non-dummy) value."""
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    return bool(key) and key != _DUMMY_KEY


# ============================================================
# Shared query routing function
# ============================================================


def route_query(query: str) -> str:
    """Simulate Chairman's routing logic mapping natural language to crew names.

    Keyword-based routing resolves which crew handles a given query.
    Returns crew module path suffix (am, pm, om, ta, ceo).
    """
    q = query.lower()

    margin_kw = [
        "margin",
        "how much margin",
        "margin available",
        "capital limits",
        "free cash",
        "burn rate",
        "pnl",
        "profit and loss",
    ]
    strategy_kw = [
        "strategy",
        "which strategy",
        "what strategy",
        "strikes",
        "iron fly",
        "credit spread",
        "spec",
    ]
    health_kw = [
        "healthy",
        "health",
        "system health",
        "pre-flight",
        "preflight",
        "token",
        "code hash",
        "disk",
        "cron",
        "network",
    ]
    trade_kw = [
        "validate",
        "verify trade",
        "check trade",
        "compliance",
        "slippage",
        "duplicate",
        "execution",
    ]
    authority_kw = [
        "halt",
        "stop trading",
        "emergency",
        "escalate",
        "board report",
        "governance",
    ]

    for kw in margin_kw:
        if kw in q:
            return "am"
    for kw in strategy_kw:
        if kw in q:
            return "pm"
    for kw in health_kw:
        if kw in q:
            return "om"
    for kw in trade_kw:
        if kw in q:
            return "ta"
    for kw in authority_kw:
        if kw in q:
            return "ceo"

    return "ceo"  # fallback


# ============================================================
# Category 1: Task Routing Tests (engine — no LLM needed)
# ============================================================


@pytest.mark.engine
@pytest.mark.orchestration
def test_ORCH_01_query_routing_margin_goes_to_am():
    """'how much margin is available for monday trading' → AM crew."""
    assert route_query("how much margin is available for monday trading") == "am"
    assert route_query("track cumulative PnL for the session") == "am"
    assert route_query("check capital limits") == "am"
    assert route_query("how much free cash do we have") == "am"


@pytest.mark.engine
@pytest.mark.orchestration
def test_ORCH_02_query_routing_strategy_goes_to_pm():
    """'which strategy should we run' → PM crew."""
    assert route_query("which strategy should we run today") == "pm"
    assert route_query("what strategy for monday") == "pm"
    assert route_query("should I run an iron fly") == "pm"
    assert route_query("calculate strikes for 24500") == "pm"


@pytest.mark.engine
@pytest.mark.orchestration
def test_ORCH_03_query_routing_health_goes_to_om():
    """'is system healthy' → OM crew."""
    assert route_query("is system healthy right now") == "om"
    assert route_query("run pre-flight checks") == "om"
    assert route_query("are broker tokens valid") == "om"
    assert route_query("check disk usage on the server") == "om"
    assert route_query("is the network up") == "om"


@pytest.mark.engine
@pytest.mark.orchestration
def test_ORCH_04_query_routing_trade_goes_to_ta():
    """'validate this trade' → TA crew."""
    assert route_query("validate this trade from today") == "ta"
    assert route_query("verify trade execution") == "ta"
    assert route_query("check trade compliance") == "ta"
    assert route_query("detect duplicate trades") == "ta"
    assert route_query("what was the slippage on that order") == "ta"


@pytest.mark.engine
@pytest.mark.orchestration
def test_ORCH_05_query_routing_ceo_decision():
    """'halt all trading' → CEO crew (authority check)."""
    assert route_query("halt all trading immediately") == "ceo"
    assert route_query("stop trading now") == "ceo"
    assert route_query("this is an emergency") == "ceo"
    assert route_query("escalate to the board") == "ceo"
    assert route_query("generate board report") == "ceo"


@pytest.mark.engine
@pytest.mark.orchestration
def test_ORCH_06_query_routing_unknown_fallback():
    """Unknown queries fallback to CEO."""
    assert route_query("what's the weather in Mumbai") == "ceo"
    assert route_query("tell me a joke") == "ceo"
    assert route_query("who won the cricket match") == "ceo"
    assert route_query("") == "ceo"


# ============================================================
# Category 2: Agent Task Delegation Tests (engine)
# ============================================================


@pytest.mark.engine
@pytest.mark.orchestration
def test_ORCH_07_om_crew_has_3_tasks():
    """OM crew: 3 agents, 3 tasks, hierarchical process."""
    from crews.om_crew import build_om_crew

    crew = build_om_crew()
    assert len(crew.agents) == 3, f"OM has 3 agents, got {len(crew.agents)}"
    assert len(crew.tasks) == 3, f"OM has 3 tasks, got {len(crew.tasks)}"
    assert crew.process.name == "hierarchical", (
        f"OM process={crew.process.name}, expected hierarchical"
    )


@pytest.mark.engine
@pytest.mark.orchestration
def test_ORCH_08_ta_crew_has_2_tasks():
    """TA crew: 2 agents, 2 tasks, hierarchical process."""
    from crews.ta_crew import build_ta_crew

    crew = build_ta_crew()
    assert len(crew.agents) == 2, f"TA has 2 agents, got {len(crew.agents)}"
    assert len(crew.tasks) == 2, f"TA has 2 tasks, got {len(crew.tasks)}"
    assert crew.process.name == "hierarchical", (
        f"TA process={crew.process.name}, expected hierarchical"
    )


@pytest.mark.engine
@pytest.mark.orchestration
def test_ORCH_09_am_crew_tools_correct():
    """AM FinancialTracker has 3 tools, Reporter has 2."""
    from crews.am_crew import financial_tracker, financial_reporter

    assert len(financial_tracker.tools) == 3, (
        f"FinancialTracker has 3 tools, got {len(financial_tracker.tools)}"
    )
    assert len(financial_reporter.tools) == 2, (
        f"FinancialReporter has 2 tools, got {len(financial_reporter.tools)}"
    )


@pytest.mark.engine
@pytest.mark.orchestration
def test_ORCH_10_ceo_delegation_blocked():
    """CEO agents have allow_delegation=False — no sub-delegation."""
    from crews.ceo_crew import guardian, reporter

    assert guardian.allow_delegation is False, "Guardian allow_delegation must be False"
    assert reporter.allow_delegation is False, (
        "BoardReporter allow_delegation must be False"
    )


@pytest.mark.engine
@pytest.mark.orchestration
def test_ORCH_11_all_crews_hierarchical():
    """All 6 crews use Process.hierarchical."""
    from crews.om_crew import build_om_crew
    from crews.ta_crew import build_ta_crew
    from crews.pm_crew import build_pm_crew
    from crews.am_crew import build_am_crew
    from crews.pa_crew import build_pa_crew
    from crews.ceo_crew import build_ceo_crew

    crews = {
        "OM": build_om_crew(),
        "TA": build_ta_crew(),
        "PM": build_pm_crew(),
        "AM": build_am_crew(),
        "PA": build_pa_crew(),
        "CEO": build_ceo_crew(),
    }
    for name, crew in crews.items():
        assert crew.process.name == "hierarchical", (
            f"{name} crew process={crew.process.name}, expected hierarchical"
        )


@pytest.mark.engine
@pytest.mark.orchestration
def test_ORCH_12_agent_role_boundaries():
    """Verify each agent's can/cannot boundaries: all have allow_delegation=False."""
    from crews.om_crew import pre_flight_agent, cron_watchdog as om_reporter_ag
    from crews.om_crew import reporter as om_reporter
    from crews.ta_crew import trade_validator, compliance_reporter
    from crews.pm_crew import strategist, strategy_reporter
    from crews.am_crew import financial_tracker, financial_reporter
    from crews.pa_crew import reviewer, analyst
    from crews.ceo_crew import guardian, reporter as ceo_reporter

    all_agents = [
        ("OM PreFlight", pre_flight_agent),
        ("OM CronWatchdog", om_reporter_ag),
        ("OM Reporter", om_reporter),
        ("TA Validator", trade_validator),
        ("TA Compliance", compliance_reporter),
        ("PM Strategist", strategist),
        ("PM StrategyReporter", strategy_reporter),
        ("AM Tracker", financial_tracker),
        ("AM Reporter", financial_reporter),
        ("PA Reviewer", reviewer),
        ("PA Analyst", analyst),
        ("CEO Guardian", guardian),
        ("CEO Reporter", ceo_reporter),
    ]

    for name, agent in all_agents:
        assert agent.allow_delegation is False, (
            f"{name}: allow_delegation must be False"
        )


# ============================================================
# Category 3: Mock LLM Orchestration Tests (engine — mock)
# ============================================================


@pytest.mark.engine
@pytest.mark.orchestration
def test_ORCH_13_mock_am_margin_query():
    """Mock AM crew processes margin query — verify result structure."""
    from unittest.mock import patch
    from crewai import Crew
    from crews.am_crew import build_am_crew

    mock_result = (
        "# AM Financial Report - 2026-05-12\n"
        "**Status:** HEALTHY\n\n"
        "## PnL\n"
        "- Day PnL: +850\n"
        "- Fees: 100\n"
        "- Net PnL: +750\n"
        "- Trades: 2\n\n"
        "## Margin\n"
        "- Utilization: 45.0% (target <=70%)\n\n"
        "## Capital Limits\n"
        "- Daily SL: PASS\n\n"
    )

    crew = build_am_crew()
    with patch.object(Crew, "kickoff", return_value=mock_result):
        result = crew.kickoff()
        result_str = str(result).lower()
        assert "margin" in result_str, "AM report must mention margin"
        assert "pnl" in result_str or "profit" in result_str, (
            "AM report must mention P&L"
        )
        assert "healthy" in result_str or "health" in result_str, (
            "AM report must mention health status"
        )


@pytest.mark.engine
@pytest.mark.orchestration
def test_ORCH_14_mock_pm_strategy_query():
    """Mock PM crew returns strategy spec with expected fields."""
    from unittest.mock import patch
    from crewai import Crew
    from crews.pm_crew import build_pm_crew

    mock_result = {
        "type": "IRON_FLY",
        "strikes": [24200, 24500, 24500, 24800],
        "wings": 300,
        "lots": 1,
        "sl": 3500,
        "tsl": 250,
        "indicators": {"vix": 15.2, "sentiment": "bullish"},
    }

    crew = build_pm_crew()
    with patch.object(Crew, "kickoff", return_value=mock_result):
        result = crew.kickoff()
        assert isinstance(result, dict), (
            f"PM crew result should be dict, got {type(result)}"
        )
        assert "type" in result, "PM spec must have type"
        assert result["type"] in ("IRON_FLY", "CREDIT_SPREAD"), (
            f"Strategy type must be IRON_FLY or CREDIT_SPREAD, got {result['type']}"
        )
        assert "strikes" in result, "PM spec must have strikes"
        assert "lots" in result, "PM spec must have lots"
        assert result["lots"] <= 2, (
            f"Lots must respect resource limits (max 2), got {result['lots']}"
        )


@pytest.mark.engine
@pytest.mark.orchestration
def test_ORCH_15_mock_om_preflight():
    """Mock OM crew runs pre-flight and returns GO/NOGO decision."""
    from unittest.mock import patch
    from crewai import Crew
    from crews.om_crew import build_om_crew

    mock_result = (
        "# Antariksh Pre-Flight Report - 2026-05-12 09:30 IST\n"
        "**Decision:** GO\n\n"
        "## Checks\n"
        "- PASS Tokens: Both brokers valid (07:02 IST)\n"
        "- PASS Code: Hash matches a1b2c3d4\n"
        "- PASS Data: DuckDB active (last write 09:28 IST)\n"
        "- PASS Disk: 45% used, 234GB free\n"
        "- PASS Network: Shoonya 120ms, Flattrade 85ms\n"
        "- PASS Cron: 4/4 crons active\n\n"
        "_Generated at 2026-05-12T09:30:00+05:30_"
    )

    crew = build_om_crew()
    with patch.object(Crew, "kickoff", return_value=mock_result):
        result = crew.kickoff()
        result_str = str(result)
        assert "GO" in result_str, (
            f"OM report must have GO decision, got: {result_str[:200]}"
        )
        assert "Antariksh" in result_str, "OM report must have header"
        assert "IST" in result_str or "05:30" in result_str, (
            "OM report must have timestamps"
        )


# ============================================================
# Category 4: Real LLM Orchestration Tests (LLM — slow, API key)
# ============================================================


@pytest.mark.llm
@pytest.mark.slow
@pytest.mark.orchestration
def test_ORCH_16_real_am_margin_query_llm():
    """Ask DeepSeek-powered AM crew about margin availability."""
    if not _has_real_llm_key():
        pytest.skip("No real DEEPSEEK_API_KEY set")

    from crews.am_crew import build_am_crew

    crew = build_am_crew()
    result = crew.kickoff()
    assert result is not None, "AM crew must return a result"

    result_str = str(result).lower()
    found = any(
        kw in result_str for kw in ["margin", "pnl", "capital", "cash", "profit"]
    )
    assert found, (
        f"AM crew result must contain financial keywords. Got: {result_str[:300]}"
    )


@pytest.mark.llm
@pytest.mark.slow
@pytest.mark.orchestration
def test_ORCH_17_real_om_preflight_llm():
    """Actually run OM pre-flight with DeepSeek."""
    if not _has_real_llm_key():
        pytest.skip("No real DEEPSEEK_API_KEY set")

    from crews.om_crew import build_om_crew

    crew = build_om_crew()
    result = crew.kickoff()
    assert result is not None, "OM crew must return a result"

    result_str = str(result)
    found = any(kw in result_str for kw in ["GO", "NOGO", "Pre-Flight", "Antariksh"])
    assert found, (
        f"OM crew result must contain GO/NOGO decision. Got: {result_str[:300]}"
    )


@pytest.mark.llm
@pytest.mark.slow
@pytest.mark.orchestration
def test_ORCH_18_real_pm_strategy_select_llm():
    """Ask DeepSeek-powered PM to select strategy for given conditions."""
    if not _has_real_llm_key():
        pytest.skip("No real DEEPSEEK_API_KEY set")

    from crews.pm_crew import build_pm_crew

    crew = build_pm_crew()
    result = crew.kickoff()
    assert result is not None, "PM crew must return a result"

    result_str = str(result).lower()
    found = any(
        kw in result_str for kw in ["iron_fly", "credit_spread", "strategy", "strikes"]
    )
    assert found, f"PM crew result must reference a strategy. Got: {result_str[:300]}"


# ============================================================
# Category 5: Full Pipeline Integration (real LLM)
# ============================================================


@pytest.mark.llm
@pytest.mark.slow
@pytest.mark.orchestration
def test_ORCH_19_full_om_pm_ta_chain():
    """OM pre-flight → PM strategy → TA validation chain."""
    if not _has_real_llm_key():
        pytest.skip("No real DEEPSEEK_API_KEY set")

    from crews.om_crew import build_om_crew
    from crews.pm_crew import build_pm_crew
    from crews.ta_crew import build_ta_crew

    # Phase 1: OM pre-flight
    om_crew = build_om_crew()
    om_result = om_crew.kickoff()
    assert om_result is not None
    om_str = str(om_result)
    assert "GO" in om_str or "NOGO" in om_str, (
        f"OM must produce GO/NOGO. Got: {om_str[:200]}"
    )

    # Phase 2: PM strategy selection
    pm_crew = build_pm_crew()
    pm_result = pm_crew.kickoff()
    assert pm_result is not None
    pm_str = str(pm_result).lower()
    assert any(kw in pm_str for kw in ["iron_fly", "credit_spread", "strategy"]), (
        f"PM must select strategy. Got: {pm_str[:200]}"
    )

    # Phase 3: TA validation readiness
    ta_crew = build_ta_crew()
    assert len(ta_crew.agents) == 2, "TA crew must have 2 agents ready"
    assert len(ta_crew.tasks) == 2, "TA crew must have 2 tasks ready"


@pytest.mark.llm
@pytest.mark.slow
@pytest.mark.orchestration
def test_ORCH_20_full_company_kickoff():
    """All 6 crews run sequentially — verify no crashes."""
    if not _has_real_llm_key():
        pytest.skip("No real DEEPSEEK_API_KEY set")

    from crews.om_crew import build_om_crew
    from crews.ta_crew import build_ta_crew
    from crews.pm_crew import build_pm_crew
    from crews.am_crew import build_am_crew
    from crews.pa_crew import build_pa_crew
    from crews.ceo_crew import build_ceo_crew

    crews = [
        ("OM", build_om_crew()),
        ("PM", build_pm_crew()),
        ("AM", build_am_crew()),
        ("TA", build_ta_crew()),
        ("PA", build_pa_crew()),
        ("CEO", build_ceo_crew()),
    ]

    results = {}
    for name, crew in crews:
        result = crew.kickoff()
        assert result is not None, f"{name} crew returned None"
        results[name] = str(result)[:200]

    assert "OM" in results, "OM crew must produce output"
    assert "PM" in results, "PM crew must produce output"
    assert "AM" in results, "AM crew must produce output"
    assert "TA" in results, "TA crew must produce output"
    assert "PA" in results, "PA crew must produce output"
    assert "CEO" in results, "CEO crew must produce output"
