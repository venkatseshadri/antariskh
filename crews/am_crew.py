"""Asset Manager Crew — 2-agent financial oversight + CEO/PM reporting.

Agents: FinancialTracker (P&L, margin, limits), FinancialReporter (CEO/PM reports).

Uses CrewAI Process.hierarchical. Deterministic tools from tools/am_tools.py.
"""

import os
import sys

from crewai import Agent, Task, Crew, Process
from crewai.llm import LLM
from crewai.tools import tool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.am_tools import (
    track_cumulative_pnl as _track_cumulative_pnl,
    check_margin as _check_margin,
    check_capital_limits as _check_capital_limits,
    generate_financial_report as _generate_financial_report,
    generate_capital_report as _generate_capital_report,
)

DEEPSEEK_BASE = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
DS_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
manager_llm = LLM(
    model="deepseek/deepseek-chat",
    base_url=DEEPSEEK_BASE,
    temperature=0.3,
    api_key=DS_KEY,
)
# Suppress CrewAI telemetry: also set OPENAI_API_KEY for internal client
os.environ.setdefault("OPENAI_API_KEY", DS_KEY)


@tool
def track_cumulative_pnl(trades: list, session: str) -> dict:
    """Track cumulative P&L across all trades in a session."""
    return _track_cumulative_pnl(trades, session)


@tool
def check_margin(used_margin: float, total_margin: float = 250000) -> dict:
    """Check margin utilization against target percentage."""
    return _check_margin(used_margin, total_margin)


@tool
def check_capital_limits(
    day_pnl: float, portfolio_pnl: float, free_cash: float
) -> dict:
    """Enforce hard capital preservation limits (SL, portfolio, free cash floor)."""
    return _check_capital_limits(day_pnl, portfolio_pnl, free_cash)


@tool
def generate_financial_report(
    pnl_data: dict, margin: dict, limits: dict, session: str = None
) -> dict:
    """Generate daily financial health report for CEO."""
    return _generate_financial_report(pnl_data, margin, limits, session)


@tool
def generate_capital_report(
    available_margin: float,
    used_margin: float,
    free_cash: float,
    burn_rate_daily: float,
) -> dict:
    """Generate capital allocation report for Portfolio Manager."""
    return _generate_capital_report(
        available_margin, used_margin, free_cash, burn_rate_daily
    )


financial_tracker = Agent(
    role="Financial Performance Tracker",
    goal="Track every rupee — P&L, margin utilization, capital limits, burn rate. Hard-fail any breach.",
    backstory="You are the financial conscience. ₹3,500 daily SL breached? Halt. Free cash below ₹11,000? Halt. No exceptions, no judgment softening.",
    tools=[track_cumulative_pnl, check_margin, check_capital_limits],
    allow_delegation=False,
    verbose=False,
)

financial_reporter = Agent(
    role="Financial Health Reporter",
    goal="Generate CEO financial report and PM capital allocation report with precise numbers.",
    backstory="The Board needs numbers, not narrative. You deliver exact P&L, margin %, and limit status.",
    tools=[generate_financial_report, generate_capital_report],
    allow_delegation=False,
    verbose=False,
)

track_task = Task(
    description="Track session P&L, check margin, enforce capital limits.",
    expected_output="P&L dict, margin dict, limits dict",
    agent=financial_tracker,
)
report_task = Task(
    description="Generate CEO financial report and PM capital report.",
    expected_output="CEO report dict + PM capital dict",
    agent=financial_reporter,
)


def build_am_crew() -> Crew:
    return Crew(
        agents=[financial_tracker, financial_reporter],
        tasks=[track_task, report_task],
        process=Process.hierarchical,
        manager_llm=manager_llm,
        verbose=False,
    )
