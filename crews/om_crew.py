"""Operations Manager Crew — 3-agent pre-flight infrastructure watchdog.

import os
import sys
from crewai import Agent, Task, Crew, Process
from crewai.llm import LLM
from crewai.tools import tool
from config_loader import load_agent_config
from tools.om_tools import (
    token_refresh_status as _token_refresh_status,
    verify_code_hash as _verify_code_hash,
    data_capture_health as _data_capture_health,
    disk_usage_check as _disk_usage_check,
    network_connectivity_check as _network_connectivity_check,
    cron_health_check as _cron_health_check,
    aggregate_health_report as _aggregate_health_report,
)
from dotenv import load_dotenv
load_dotenv()


Agents: PreFlightAgent (5 infra checks), CronWatchdog (cron health),
        Reporter (evidence-backed GO/NOGO report).

Uses CrewAI Process.hierarchical. Deterministic tools from tools/om_tools.py.
"""



sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MOCK_MODE = os.environ.get("ANTARIKSH_MOCK_MODE", "0") == "1"

# LLM for hierarchical manager (coordinates 3 agents)
DEEPSEEK_BASE = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
manager_llm = LLM(
    model="deepseek/deepseek-chat",
    base_url=DEEPSEEK_BASE,
    temperature=0.3,
    api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
)


# ============================================================
# Tools (CrewAI-wrapped)
# ============================================================


@tool
def token_refresh_status() -> dict:
    """Check Shoonya + Flattrade token validity. Returns ok status and evidence."""
    return _token_refresh_status()


@tool
def verify_code_hash() -> dict:
    """Hash all .py files and compare against last-known hash."""
    return _verify_code_hash()


@tool
def data_capture_health() -> dict:
    """Check DuckDB market data stream is receiving live data."""
    return _data_capture_health()


@tool
def disk_usage_check() -> dict:
    """Check disk usage percentage on logs/ directory."""
    return _disk_usage_check()


@tool
def network_connectivity_check() -> dict:
    """Check broker API and Telegram reachability with latency."""
    return _network_connectivity_check()


@tool
def cron_health_check() -> dict:
    """Verify expected cron jobs are present in system crontab."""
    return _cron_health_check()


@tool
def aggregate_health_report(checks: list) -> dict:
    """Synthesize check results into GO/NOGO decision with markdown report."""
    return _aggregate_health_report(checks)


# ============================================================
# Agents
# ============================================================

pre_flight_agent = Agent(
    **load_agent_config("om", "pre_flight_agent"),
    tools=[
        token_refresh_status,
        verify_code_hash,
        data_capture_health,
        disk_usage_check,
        network_connectivity_check,
    ],
    allow_delegation=False,
    verbose=True,
)

cron_watchdog = Agent(
    **load_agent_config("om", "cron_watchdog"),
    tools=[cron_health_check],
    allow_delegation=False,
    verbose=True,
)

reporter = Agent(
    **load_agent_config("om", "reporter"),
    tools=[aggregate_health_report],
    allow_delegation=False,
    verbose=True,
)


# ============================================================
# Tasks
# ============================================================

pre_flight_task = Task(
    description=(
        "Run all 5 pre-flight infrastructure checks:\n"
        "1. Broker token validity (Shoonya + Flattrade)\n"
        "2. Code integrity (verify no unauthorized changes)\n"
        "3. Market data stream health (DuckDB active)\n"
        "4. Disk space (logs/ directory)\n"
        "5. Network connectivity (broker APIs + Telegram)\n\n"
        "For each check return: ok (bool), evidence (string with "
        "timestamp and actual values)."
    ),
    expected_output=(
        "A structured summary of all 5 pre-flight checks with "
        "ok/FAILED status and concrete evidence for each. Format as:\n"
        "- tokens: {ok: True/False, evidence: '...'}\n"
        "- code: {ok: True/False, evidence: '...'}\n"
        "- data: {ok: True/False, evidence: '...'}\n"
        "- disk: {ok: True/False, evidence: '...'}\n"
        "- network: {ok: True/False, evidence: '...'}"
    ),
    agent=pre_flight_agent,
)

cron_task = Task(
    description=(
        "Verify all expected cron jobs are present in the system crontab. "
        "Check for: token_refresh_dual.py (07:00), session_orchestrator.py "
        "entry (09:30), session_orchestrator.py exit (14:35), "
        "exec_report.py daily (18:00), exec_report.py weekly (20:00 SUN)."
    ),
    expected_output=(
        "Cron health result with active list, missing list, ok status, "
        "and evidence string. Format: "
        "{active: [...], missing: [...], ok: True/False, evidence: '...'}"
    ),
    agent=cron_watchdog,
)

report_task = Task(
    description=(
        "Take the pre-flight check results and cron health results. "
        "Classify any failures as CRITICAL or WARNING. Generate the "
        "final GO/NOGO decision and a Telegram-ready markdown report "
        "with timestamps, concrete evidence values for every check, "
        "and the overall verdict."
    ),
    expected_output=(
        "A markdown report with:\n"
        "- Header: 'Antariksh Pre-Flight Report' with timestamp\n"
        "- Decision: GO or NOGO (emoji)\n"
        "- Each check with status icon (✅/❌) and evidence string\n"
        "- CRITICAL Failures section if any\n"
        "- Warnings section if any\n"
        "- Footer with generation timestamp\n\n"
        "Format as markdown suitable for Telegram delivery."
    ),
    agent=reporter,
)


# ============================================================
# Crew Builder
# ============================================================


def build_om_crew() -> Crew:
    """
    Build and return the OM crew with 3 agents in hierarchical process.

    Agents execute sequentially: PreFlight → CronWatchdog → Reporter.
    The hierarchical manager coordinates task delegation.

    Returns:
        Crew instance ready for kickoff().
    """
    crew = Crew(
        agents=[pre_flight_agent, cron_watchdog, reporter],
        tasks=[pre_flight_task, cron_task, report_task],
        process=Process.hierarchical,
        manager_llm=manager_llm,
        verbose=True,
    )
    return crew


if __name__ == "__main__":
    crew = build_om_crew()
    print(f"OM Crew: {len(crew.agents)} agents, {len(crew.tasks)} tasks")
    if MOCK_MODE:
        print("Mock mode — tools will use env-var simulated values")
