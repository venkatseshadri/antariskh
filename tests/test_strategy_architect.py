"""E2E test: Strategy Architect — regime → strategy → strike selection.

import os, sys
from pathlib import Path
from crewai import Agent, Task, Crew
from crewai.llm import LLM
from crews.ta_crew import strategy_architect as _architect, load_skill_file
from tools.ta_strategy_tools import FetchOptionChainTool, FetchGreeksTool
from dotenv import load_dotenv


Feeds the Architect a TRENDING_BEAR signal from the Technical Scout
and verifies it maps to a Call Credit Spread using DuckDB data + skill file.
"""


# Load .env
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text().split("\n"):
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

ds_key = os.environ.get("DEEPSEEK_API_KEY", "")
os.environ.setdefault("OPENAI_API_KEY", ds_key)
os.environ.setdefault(
    "OPENAI_BASE_URL",
    os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
)

sys.path.insert(0, str(Path(__file__).parent.parent))


ds_llm = LLM(
    model="deepseek/deepseek-chat",
    base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
    temperature=0.1,
    api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
)

architect = Agent(
    role=_architect.role,
    goal=_architect.goal,
    backstory=_architect.backstory,
    tools=[FetchOptionChainTool(), FetchGreeksTool(), load_skill_file],
    llm=ds_llm,
    verbose=True,
    memory=False,
)


def test_architect_bear_call_spread():
    """TRENDING_BEAR → Bear Call Credit Spread."""
    task = Task(
        description=(
            "The Technical Scout reports: Regime=TRENDING_BEAR, ADX=41.2, "
            "SuperTrend=BEARISH, VIX=18.5, Spot=23,810.\n\n"
            "Your job: design the optimal options strategy for this regime.\n\n"
            "Step 1: Call load_skill_file('strategy-architect.json') to read "
            "the decision matrix and find the correct strategy for TRENDING_BEAR.\n\n"
            "Step 2: Call Fetch Option Chain from DuckDB to see available strikes.\n\n"
            "Step 3: Call Fetch Aggregate Greeks from DuckDB to check current risk metrics.\n\n"
            "Step 4: Apply the 0.15 Delta Rule and Wing Width Sizing from the skill file.\n\n"
            "Step 5: Output a trade plan with exact strikes (leg name, action SELL/BUY, "
            "strike, option_type CE/PE, rationale). Do NOT pick ATM strikes — target "
            "0.15-0.20 Delta for the short leg per the skill file rule."
        ),
        expected_output=(
            "Trade plan with strategy name (must be Call Credit Spread / Bear Call), "
            "exact leg breakdown, and validation against Greek guardrails from the skill file."
        ),
        agent=architect,
    )

    crew = Crew(agents=[architect], tasks=[task], memory=False, verbose=True)
    print("\n--- Test: TRENDING_BEAR → Bear Call Credit Spread ---\n")
    result = crew.kickoff()
    print(f"\nFinal Output:\n{result}")
    return result


if __name__ == "__main__":
    test_architect_bear_call_spread()
