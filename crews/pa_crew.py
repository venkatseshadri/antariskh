"""Post-Mortem Analyst Crew — 2-agent trade review + PM recommendations.

Agents: TradeReviewer, PatternAnalyst.
"""

import os, sys
from crewai import Agent, Task, Crew, Process
from crewai.llm import LLM
from crewai.tools import tool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.pa_tools import (
    review_trade as _review_trade,
    run_counterfactuals as _run_counterfactuals,
    detect_patterns as _detect_patterns,
    generate_post_mortem_report as _generate_post_mortem_report,
)

manager_llm = LLM(
    model="deepseek/deepseek-chat",
    base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
    temperature=0.3,
    api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
)


@tool
def review_trade(trade: dict, spec: dict) -> dict:
    return _review_trade(trade, spec)


@tool
def run_counterfactuals(
    trade: dict,
    peak_pnl: float = 0,
    better_exit: float = None,
    better_sl: float = None,
    better_tp: float = None,
    hypothetical_entry: float = None,
) -> dict:
    return _run_counterfactuals(
        trade, peak_pnl, better_exit, better_sl, better_tp, hypothetical_entry
    )


@tool
def detect_patterns(trades: list) -> dict:
    return _detect_patterns(trades)


@tool
def generate_post_mortem_report(
    reviews: list, counterfactuals: list, patterns: dict, session: str
) -> dict:
    return _generate_post_mortem_report(reviews, counterfactuals, patterns, session)


reviewer = Agent(
    role="Trade Quality Reviewer",
    goal="Review every trade for spec compliance, SL hits, early exits. Run counterfactuals on alt entry/exit/TP/SL.",
    backstory="Every trade tells a story. You find the missed opportunities.",
    tools=[review_trade, run_counterfactuals],
    allow_delegation=False,
    verbose=False,
)
analyst = Agent(
    role="Pattern & Recommendation Analyst",
    goal="Detect recurring patterns across trades. Generate actionable PM recommendations.",
    backstory="Patterns predict future losses. You catch them before they repeat.",
    tools=[detect_patterns, generate_post_mortem_report],
    allow_delegation=False,
    verbose=False,
)

review_task = Task(
    description="Review all session trades. Run counterfactuals for SL-hit trades.",
    expected_output="Review dicts + counterfactual dicts",
    agent=reviewer,
)
report_task = Task(
    description="Detect patterns. Generate post-mortem report with recommendations for PM.",
    expected_output="Post-mortem report dict",
    agent=analyst,
)


def build_pa_crew() -> Crew:
    return Crew(
        agents=[reviewer, analyst],
        tasks=[review_task, report_task],
        process=Process.hierarchical,
        manager_llm=manager_llm,
        verbose=False,
    )
