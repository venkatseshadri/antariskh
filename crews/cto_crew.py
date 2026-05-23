"""CTO Crew — technical strategy, gatekeeping, and Dev/QA pipeline orchestration.

import os
import sys
from crewai import Agent, Task, Crew, Process
from crewai.llm import LLM
from crewai.tools import tool
from config_loader import load_agent_config
from tools.cto_tools import (
    assess_change_risk as _assess_change_risk,
    preview_diff as _preview_diff,
    cto_signoff as _cto_signoff,
    generate_cto_brief as _generate_cto_brief,
    validate_change_spec as _validate_change_spec,
    scout_technology as _scout_technology,
    evaluate_architecture as _evaluate_architecture,
    design_poc_plan as _design_poc_plan,
)
from dotenv import load_dotenv
load_dotenv()


Single agent (CTO) with all technical authority:
- Scouts new tools/frameworks to reduce cost and maintenance
- Evaluates architecture and proposes improvements
- Designs POCs for CEO's new visions
- Gatekeeps ALL source code changes (blast radius, risk, signoff)
- Delegates implementation to Dev crew, validation to QA crew
- Reports to CEO

The CTO is a MANAGER agent in Process.hierarchical mode.
It receives change requests and delegates to Dev and QA agents.
"""



sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEEPSEEK_BASE = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
manager_llm = LLM(
    model="deepseek/deepseek-chat",
    base_url=DEEPSEEK_BASE,
    temperature=0.2,
    api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
)

# ============================================================
# Tools (CrewAI-wrapped)
# ============================================================


@tool
def assess_change_risk(change_spec: dict) -> dict:
    """Evaluate blast radius and risk level of a code change."""
    return _assess_change_risk(change_spec)


@tool
def preview_diff(change_spec: dict) -> dict:
    """Show what the diff will look like before applying."""
    return _preview_diff(change_spec)


@tool
def cto_signoff(change_spec: dict, risk_assessment: dict, override: str = None) -> dict:
    """CTO final YES/NO/NEEDS_CLARIFICATION on a change. Delegates to Dev if YES."""
    return _cto_signoff(change_spec, risk_assessment, override)


@tool
def validate_change_spec(change_spec: dict) -> dict:
    """Check change request has all required fields."""
    return _validate_change_spec(change_spec)


@tool
def scout_technology(category: str, constraints: dict = None) -> dict:
    """Research better/cheaper tools. Categories: broker_apis, llm_providers,
    agent_frameworks, monitoring, deployment, or 'all'."""
    return _scout_technology(category, constraints)


@tool
def evaluate_architecture(component: str = "all") -> dict:
    """Evaluate architecture and suggest improvements. Components:
    market_state, crew_orchestration, broker_integration, safety_systems, deployment, or 'all'."""
    return _evaluate_architecture(component)


@tool
def design_poc_plan(vision: str, scope: str = "minimal") -> dict:
    """Design POC plan for CEO vision (e.g., Crypto, MCX expansion)."""
    return _design_poc_plan(vision, scope)


@tool
def generate_cto_brief(change_spec: dict, risk_assessment: dict, signoff: dict) -> str:
    """Generate structured CTO decision brief for CEO/Board."""
    return _generate_cto_brief(change_spec, risk_assessment, signoff)


# ============================================================
# Agent
# ============================================================

cto = Agent(
    **load_agent_config("cto", "cto"),
    tools=[
        assess_change_risk,
        preview_diff,
        cto_signoff,
        validate_change_spec,
        scout_technology,
        evaluate_architecture,
        design_poc_plan,
        generate_cto_brief,
    ],
    allow_delegation=True,  # CTO delegates to Dev and QA
    verbose=True,
)

# ============================================================
# Tasks
# ============================================================

gatekeeping_task = Task(
    description=(
        "Gatekeep source code changes. When a change request arrives:\n"
        "1. Validate the change spec has all required fields\n"
        "2. Assess risk (blast radius, critical files, dependency impact)\n"
        "3. Preview the diff\n"
        "4. Make a decision: YES (delegate to Dev+QA), NO (block), or "
        "NEEDS_CLARIFICATION (request more detail)\n"
        "5. Generate a CTO brief for the Board\n\n"
        "Be paranoid. If it touches crew_structure.py or broker code, "
        "demand a test plan and rollback runbook. No exceptions."
    ),
    expected_output="CTO brief with risk assessment and YES/NO/NEEDS_CLARIFICATION decision",
    agent=cto,
)

scouting_task = Task(
    description=(
        "Proactively scout technology opportunities:\n"
        "1. Check broker APIs — is there something cheaper/faster than Shoonya?\n"
        "2. Check LLM providers — can we cut API costs with local models?\n"
        "3. Check monitoring — are we flying blind without AgentOps/Langfuse?\n"
        "4. Check deployment — can systemd or Docker improve reliability?\n"
        "5. Present top 3 recommendations to CEO with cost/benefit"
    ),
    expected_output="Technology radar report with top 3 recommendations for CEO",
    agent=cto,
)

poc_task = Task(
    description=(
        "When CEO has a vision (Crypto, MCX, multi-asset), design the POC:\n"
        "1. Research the technical landscape\n"
        "2. Design phases: smoke test → strategy port → paper trade → live\n"
        "3. Estimate duration, cost, risk per phase\n"
        "4. Identify prerequisites (accounts, APIs, capital)\n"
        "5. Present to CEO for go/no-go"
    ),
    expected_output="POC plan with phases, estimates, risks, and prerequisites",
    agent=cto,
)


# ============================================================
# Crew Builder
# ============================================================


def build_cto_crew() -> Crew:
    """Build CTO crew — single agent, manages Dev/QA delegation internally."""
    return Crew(
        agents=[cto],
        tasks=[gatekeeping_task, scouting_task, poc_task],
        process=Process.hierarchical,
        manager_llm=manager_llm,
        verbose=True,
    )


if __name__ == "__main__":
    crew = build_cto_crew()
    print(f"CTO Crew: {len(crew.agents)} agents, {len(crew.tasks)} tasks")
