"""CEO Crew — 2-agent governance + board reporting."""

import os, sys
from crewai import Agent, Task, Crew, Process
from crewai.llm import LLM
from crewai.tools import tool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.ceo_tools import (
    alignment_check as _ac,
    aggregate_crew_performance as _acp,
    enforce_resource_caps as _erc,
    generate_board_report as _gbr,
    should_escalate as _se,
    check_authority as _ca,
    governance_veto as _gv,
)

manager_llm = LLM(
    model="deepseek/deepseek-chat",
    base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
    temperature=0.3,
    api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
)


@tool
def alignment_check(d: dict, g: list) -> dict:
    return _ac(d, g)


@tool
def aggregate_crew_performance(crews: list) -> dict:
    return _acp(crews)


@tool
def enforce_resource_caps(p: int, c: float, s: int) -> dict:
    return _erc(p, c, s)


@tool
def generate_board_report(summaries: dict) -> dict:
    return _gbr(summaries)


@tool
def should_escalate(fh: list, t: int = 3) -> bool:
    return _se(fh, t)


@tool
def check_authority(action: str) -> bool:
    return _ca(action)


@tool
def governance_veto(actor: str, action: str, detail: str) -> dict:
    return _gv(actor, action, detail)


guardian = Agent(
    role="Alignment Guardian",
    goal="Verify every crew decision against vision/goals. Enforce resource caps. Escalate violations.",
    backstory="Vishnu, the preserver. You ensure Antariksh stays true to its purpose.",
    tools=[alignment_check, enforce_resource_caps, should_escalate],
    allow_delegation=False,
    verbose=False,
)
reporter = Agent(
    role="Board Reporter",
    goal="Aggregate crew performance. Generate board report. Track authority chain.",
    backstory="The Board's window into operations. Your report is the single source of truth.",
    tools=[
        aggregate_crew_performance,
        generate_board_report,
        check_authority,
        governance_veto,
    ],
    allow_delegation=False,
    verbose=False,
)

t1 = Task(
    description="Check alignment, enforce caps, check escalation.",
    expected_output="Alignment results + caps + escalation flag",
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
        verbose=False,
    )
