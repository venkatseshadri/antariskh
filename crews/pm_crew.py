"""Portfolio Manager Crew — 2-agent strategy definition + CEO reporting.

Agents: Strategist (selects strategy, calculates strikes, builds spec),
        StrategyReporter (CEO summary + performance metrics).

Uses CrewAI Process.hierarchical. Deterministic tools from tools/pm_tools.py.
"""

import os
import sys
from dotenv import load_dotenv

from crewai import Agent, Task, Crew, Process
from crewai.llm import LLM
from crewai.tools import tool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from config_loader import load_agent_config
from tools.pm_tools import (
    select_strategy as _select_strategy,
    calculate_strikes as _calculate_strikes,
    build_strategy_spec as _build_strategy_spec,
    analyze_wing_margins as _analyze_wing_margins,
    recommend_optimal_wing as _recommend_optimal_wing,
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
def analyze_wing_margins(
    nifty_spot: float, lots: int = 1, expiry: str = None, dry_run: bool = False
) -> list:
    """Query broker SPAN calculator for all wing widths 50→500. Returns comparison."""
    return _analyze_wing_margins(nifty_spot, lots, expiry, dry_run=dry_run)


@tool
def recommend_optimal_wing(
    nifty_spot: float,
    vix: float,
    free_cash: float,
    lots: int = 1,
    expiry: str = None,
    dry_run: bool = False,
) -> dict:
    """Recommend optimal wing width balancing margin, breach risk, and free cash."""
    return _recommend_optimal_wing(
        nifty_spot, vix, free_cash, lots, expiry, dry_run=dry_run
    )


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
    **load_agent_config("pm", "strategist"),
    tools=[
        select_strategy,
        calculate_strikes,
        build_strategy_spec,
        analyze_wing_margins,
        recommend_optimal_wing,
    ],
    allow_delegation=False,
    verbose=True,
)

strategy_reporter = Agent(
    **load_agent_config("pm", "strategy_reporter"),
    tools=[generate_strategy_summary],
    allow_delegation=False,
    verbose=True,
)


# ============================================================
# Tasks
# ============================================================

strategy_task = Task(
    description=(
        "Analyze market conditions and produce an optimized strategy spec:\n"
        "1. Select strategy type (IRON_FLY or CREDIT_SPREAD)\n"
        "2. Call recommend_optimal_wing() with spot, VIX, and AM's free_cash\n"
        "   to compare margin across wing widths [50, 100, ..., 500]\n"
        "3. Calculate strikes using the recommended wing width\n"
        "4. Build complete spec with strikes, wings, lots, SL, TSL, indicators\n"
        "5. Respect resource limits (max 2 lots, 8 indicators)\n\n"
        "Output the complete strategy spec dict with margin optimization rationale."
    ),
    expected_output="Strategy spec dict with type, strikes, wings, lots, sl, tsl, indicators, margin_analysis",
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
        verbose=True,
    )


if __name__ == "__main__":
    crew = build_pm_crew()
    print(
        f"PM Crew: {len(crew.agents)} agents, {len(crew.tasks)} tasks, process={crew.process}"
    )
