"""Portfolio Manager Crew — 2-agent strategy definition + CEO reporting.

Agents: Strategist (selects strategy, calculates strikes, builds spec),
        StrategyReporter (CEO summary + performance metrics).

Uses CrewAI Process.hierarchical. Deterministic tools from tools/pm_tools.py.
"""

import os
import sys

from crewai import Agent, Task, Crew, Process
from crewai.llm import LLM
from crewai.tools import tool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.pm_tools import (
    select_strategy as _select_strategy,
    calculate_strikes as _calculate_strikes,
    build_strategy_spec as _build_strategy_spec,
    generate_strategy_summary as _generate_strategy_summary,
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
def select_strategy(market_state: dict) -> dict:
    """Select strategy type (IB/CS) based on VIX, indicators, sentiment."""
    return _select_strategy(market_state)


@tool
def calculate_strikes(
    nifty_spot: float, strategy_type: str, wing_width: int = 300, grid: int = 50
) -> list:
    """Calculate option strikes for a strategy type."""
    return _calculate_strikes(nifty_spot, strategy_type, wing_width, grid)


@tool
def build_strategy_spec(strategy_type: str, market_state: dict) -> dict:
    """Build complete strategy spec dict for TA validation."""
    return _build_strategy_spec(strategy_type, market_state)


@tool
def generate_strategy_summary(
    specs: list, win_rate: float, profit_factor: float, pa_actions_taken: int = 0
) -> dict:
    """Generate CEO strategy summary with WR, PF, active specs."""
    return _generate_strategy_summary(specs, win_rate, profit_factor, pa_actions_taken)


# ============================================================
# Agents
# ============================================================

strategist = Agent(
    role="Lead Portfolio Strategist",
    goal=(
        "Analyze market conditions and determine the optimal strategy. "
        "Select Iron Butterfly in normal conditions, Credit Spread in "
        "high VIX/bearish markets. Calculate strikes, respect resource "
        "limits (max 2 lots, 8 indicators), and publish the strategy spec "
        "for Trading Analyst validation."
    ),
    backstory=(
        "You are the strategy brain of Antariksh. Every morning at 08:55 IST "
        "you evaluate VIX, indicator alignment, sentiment, and events to "
        "pick the right weapon for the day's market. Your spec becomes the "
        "blueprint TA validates against. You don't execute — you define."
    ),
    tools=[select_strategy, calculate_strikes, build_strategy_spec],
    allow_delegation=False,
    verbose=False,
)

strategy_reporter = Agent(
    role="Strategy Performance Reporter",
    goal=(
        "Generate the CEO strategy summary — win rate, profit factor, "
        "active strategy specs, and PA recommendation adoption rate."
    ),
    backstory=(
        "The Board sees your report. You distill PM's performance into "
        "a clear verdict: green (above target), yellow (near floor), or "
        "red (below floor). You track how many PA recommendations were "
        "acted on. Your report is the single source of truth for strategy health."
    ),
    tools=[generate_strategy_summary],
    allow_delegation=False,
    verbose=False,
)


# ============================================================
# Tasks
# ============================================================

strategy_task = Task(
    description=(
        "Analyze market conditions and produce a strategy spec:\n"
        "1. Select strategy type (IRON_FLY or CREDIT_SPREAD)\n"
        "2. Calculate strikes on the 50-point grid\n"
        "3. Build complete spec with strikes, wings, lots, SL, TSL, indicators\n"
        "4. Respect resource limits (max 2 lots, 8 indicators)\n\n"
        "Output the complete strategy spec dict."
    ),
    expected_output="Strategy spec dict with type, strikes, wings, lots, sl, tsl, indicators",
    agent=strategist,
)

report_task = Task(
    description=(
        "Generate CEO strategy summary from the active spec and performance "
        "data. Include: number of active strategies, win rate, profit factor, "
        "PA actions taken, and an overall verdict."
    ),
    expected_output="CEO summary dict with strategies_active, win_rate, profit_factor, pa_actions, text",
    agent=strategy_reporter,
)


# ============================================================
# Crew Builder
# ============================================================


def build_pm_crew() -> Crew:
    """Build PM crew with 2 agents in hierarchical process."""
    return Crew(
        agents=[strategist, strategy_reporter],
        tasks=[strategy_task, report_task],
        process=Process.hierarchical,
        manager_llm=manager_llm,
        verbose=False,
    )


if __name__ == "__main__":
    crew = build_pm_crew()
    print(
        f"PM Crew: {len(crew.agents)} agents, {len(crew.tasks)} tasks, process={crew.process}"
    )
