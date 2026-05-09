"""Trading Analyst Crew — 2-agent trade validation + reporting.

Agents: TradeValidator (spec compliance), ComplianceReporter (reports to PM/AM).

Uses CrewAI Process.hierarchical. Deterministic tools from tools/ta_tools.py.
"""

import os
import sys

from crewai import Agent, Task, Crew, Process
from crewai.llm import LLM
from crewai.tools import tool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.ta_tools import (
    validate_trade as _validate_trade,
    check_slippage as _check_slippage,
    detect_duplicate as _detect_duplicate,
    generate_compliance_report as _generate_compliance_report,
    generate_execution_ledger as _generate_execution_ledger,
)

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
def validate_trade(spec: dict, trade: dict) -> dict:
    """Validate trade execution against PM strategy spec. Returns valid flag and violations."""
    return _validate_trade(spec, trade)


@tool
def check_slippage(
    expected_strike: float, actual_fill: float, tolerance: float = 50
) -> dict:
    """Check order fill slippage against tolerance in points."""
    return _check_slippage(expected_strike, actual_fill, tolerance)


@tool
def detect_duplicate(trade: dict, session_trades: list) -> dict:
    """Check if trade duplicates an existing one in the session."""
    return _detect_duplicate(trade, session_trades)


@tool
def generate_compliance_report(trade_id: str, spec: dict, violations: list) -> dict:
    """Generate compliance report for PM with accuracy score and violations."""
    return _generate_compliance_report(trade_id, spec, violations)


@tool
def generate_execution_ledger(trades: list, session: str) -> dict:
    """Generate P&L + broker + fees ledger for Asset Manager."""
    return _generate_execution_ledger(trades, session)


# ============================================================
# Agents
# ============================================================

trade_validator = Agent(
    role="Trade Compliance Validator",
    goal=(
        "Validate every trade execution against PM's strategy spec. "
        "Check: trade type, strikes, wings, lots, SL, TSL, broker. "
        "Check slippage on fills. Detect duplicate trades. "
        "CRITICAL violations (type, strikes, lots, SL) block execution."
    ),
    backstory=(
        "You are the gate between strategy and execution. PM defines the "
        "blueprint — you verify the execution matches it exactly. A single "
        "wrong strike or extra lot can turn a winning strategy into a loss. "
        "WARNING violations are advisory; CRITICAL violations halt the trade."
    ),
    tools=[validate_trade, check_slippage, detect_duplicate],
    allow_delegation=False,
    verbose=False,
)

compliance_reporter = Agent(
    role="Compliance & Execution Reporter",
    goal=(
        "Generate compliance reports for PM (accuracy %, violations list) "
        "and execution ledgers for AM (P&L, broker costs, fees, slippage). "
        "Every report includes concrete evidence, not LLM-generated opinions."
    ),
    backstory=(
        "PM needs to know if trades followed the spec. AM needs to know "
        "exactly what happened financially. You bridge both with data-driven "
        "reports. No interpretation — just facts: what was expected, what "
        "was executed, and the delta."
    ),
    tools=[generate_compliance_report, generate_execution_ledger],
    allow_delegation=False,
    verbose=False,
)


# ============================================================
# Tasks
# ============================================================

validation_task = Task(
    description=(
        "For each trade executed, validate against PM spec:\n"
        "1. Type matches (IRON_FLY vs CREDIT_SPREAD)\n"
        "2. Strike prices match exactly\n"
        "3. Wing width matches\n"
        "4. Lot count matches\n"
        "5. SL placement matches\n"
        "6. TSL configuration matches\n"
        "7. Broker matches\n"
        "8. Slippage check on each fill\n"
        "9. Duplicate detection (same type + strikes + lots in session)\n\n"
        "Return structured results with violations list, slippage results, "
        "and duplicate flag."
    ),
    expected_output=(
        "A dict with: valid (bool), violations (list), "
        "slippage_results (list), duplicate (bool)"
    ),
    agent=trade_validator,
)

report_task = Task(
    description=(
        "Take the validation results and generate:\n"
        "1. Compliance report for PM — accuracy %, violations with "
        "expected/actual/severity, trade ID\n"
        "2. Execution ledger for AM — session P&L, fees, slippage, "
        "broker per-trade breakdown\n\n"
        "Both reports must use concrete data from tools, not LLM synthesis."
    ),
    expected_output=(
        "Compliance report (dict) + execution ledger (dict) "
        "ready for routing to PM and AM"
    ),
    agent=compliance_reporter,
)


# ============================================================
# Crew Builder
# ============================================================


def build_ta_crew() -> Crew:
    """Build TA crew with 2 agents in hierarchical process."""
    return Crew(
        agents=[trade_validator, compliance_reporter],
        tasks=[validation_task, report_task],
        process=Process.hierarchical,
        manager_llm=manager_llm,
        verbose=False,
    )


if __name__ == "__main__":
    crew = build_ta_crew()
    print(
        f"TA Crew: {len(crew.agents)} agents, {len(crew.tasks)} tasks, process={crew.process}"
    )
