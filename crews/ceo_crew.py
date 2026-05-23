"""CEO Crew — 2-agent governance + board reporting."""

import os, sys
from crewai import Agent, Task, Crew, Process
from crewai.llm import LLM
from crewai.tools import tool
from config_loader import load_agent_config
from tools.ceo_tools import (
    alignment_check as _ac,
    aggregate_crew_performance as _acp,
    enforce_resource_caps as _erc,
    generate_board_report as _gbr,
    should_escalate as _se,
    check_authority as _ca,
    governance_veto as _gv,
    scout_growth_opportunity as _sgo,
    market_research as _mr,
    explore_opportunity as _eo,
)
from dotenv import load_dotenv
load_dotenv()



sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

manager_llm = LLM(
    model="deepseek/deepseek-chat",
    base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
    temperature=0.3,
    api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
)


@tool
def alignment_check(d: dict, g: list) -> dict:
    """Check if a crew decision aligns with company goals."""
    return _ac(d, g)


@tool
def aggregate_crew_performance(crews: list) -> dict:
    """Aggregate performance metrics from all crews."""
    return _acp(crews)


@tool
def enforce_resource_caps(p: int, c: float, s: int) -> dict:
    """Enforce resource limits: max positions, capital, strategies."""
    return _erc(p, c, s)


@tool
def generate_board_report(summaries: dict) -> dict:
    """Generate board report from crew summaries."""
    return _gbr(summaries)


@tool
def should_escalate(fh: list, t: int = 3) -> bool:
    """Check if consecutive failures warrant escalation to Board."""
    return _se(fh, t)


@tool
def check_authority(action: str) -> bool:
    """Check if CEO can perform a given action."""
    return _ca(action)


@tool
def governance_veto(actor: str, action: str, detail: str) -> dict:
    """Check governance veto chain for cross-crew decisions."""
    return _gv(actor, action, detail)


@tool
def scout_growth_opportunity(
    current_pnl_trajectory: float = 0,
    current_margin_available: float = 0,
    crew_skills: list = None,
    days_clean_execution: int = 0,
) -> dict:
    """Scout new business opportunities: crypto, MCX, new strategies. Use this to plan growth."""
    if crew_skills is None:
        crew_skills = ["trading", "automation", "api_integration"]
    return _sgo(
        current_pnl_trajectory,
        current_margin_available,
        crew_skills,
        days_clean_execution,
    )


@tool
def market_research() -> dict:
    """Scan external environment: VIX, market hours, upcoming events, expiry weeks."""
    return _mr()


@tool
def explore_opportunity(domain: str = "") -> dict:
    """Deep-dive a growth opportunity. Pass 'crypto', 'mcx', 'condor', 'sensex', 'banknifty', 'flattrade', or '' for all."""
    return _eo(domain)


guardian = Agent(
    **load_agent_config("ceo", "guardian"),
    tools=[
        alignment_check,
        enforce_resource_caps,
        should_escalate,
        scout_growth_opportunity,
        market_research,
        explore_opportunity,
    ],
    allow_delegation=False,
    verbose=True,
)
reporter = Agent(
    **load_agent_config("ceo", "reporter"),
    tools=[
        aggregate_crew_performance,
        generate_board_report,
        check_authority,
        governance_veto,
    ],
    allow_delegation=False,
    verbose=True,
)

t1 = Task(
    description=(
        "Answer the Chairman's query honestly. If asked about plans or opportunities, "
        "explain your Phase 1/2/3 strategy. If asked about live trading, explain what "
        "conditions must be met first (30 days clean execution, PnL trajectory). "
        "Use real data from tools — alignment_check with actual decisions, "
        "enforce_resource_caps with actual counts, should_escalate with actual history. "
        "NEVER fabricate numbers. If you don't have real data, say so."
    ),
    expected_output="Honest assessment of company state + CEO plan + conditions for live trading",
    agent=guardian,
)
t2 = Task(
    description="Aggregate performance, generate board report.",
    expected_output="Performance summary + board report",
    agent=reporter,
)


def build_ceo_crew() -> Crew:
    return Crew(
        agents=[guardian, reporter],
        tasks=[t1, t2],
        process=Process.hierarchical,
        manager_llm=manager_llm,
        verbose=True,
    )
