"""Crew test: Technical Scout answering natural language queries."""

import os, sys
from pathlib import Path
from datetime import datetime, timedelta

# Load .env
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text().split("\n"):
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

# CrewAI default routing needs OPENAI_API_KEY set (even when using DeepSeek)
ds_key = os.environ.get("DEEPSEEK_API_KEY", "")
os.environ.setdefault("OPENAI_API_KEY", ds_key)
os.environ.setdefault(
    "OPENAI_BASE_URL",
    os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
)

sys.path.insert(0, str(Path(__file__).parent.parent))

from crewai import Agent, Task, Crew
from crewai.llm import LLM
from crews.ta_crew import (
    technical_scout as _scout,
    detect_market_regime,
    load_skill_file,
)

# Standalone agent needs its own LLM (hierarchical mode uses manager_llm)
ds_llm = LLM(
    model="deepseek/deepseek-chat",
    base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
    temperature=0.1,
    api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
)

scout_tools = [detect_market_regime, load_skill_file]

technical_scout = Agent(
    role=_scout.role,
    goal=_scout.goal,
    backstory=_scout.backstory,
    tools=scout_tools,
    llm=ds_llm,
    verbose=True,
    memory=False,
)


def test_ts_yesterday_regime():
    """Ask the Technical Scout: 'Was yesterday sideways?'"""
    yesterday = (datetime.now() - timedelta(1)).strftime("%Y-%m-%d")

    test_task = Task(
        description=(
            f"Check the NIFTY market data. Was the market trending or sideways "
            f"yesterday ({yesterday})? Call detect_market_regime with "
            f"target_date='{yesterday}' to find out. Return a short sentence "
            f"stating the ADX value and whether the market was Trending or Sideways."
        ),
        expected_output="Short sentence: ADX value + Trending or Sideways verdict for yesterday.",
        agent=technical_scout,
    )

    crew = Crew(agents=[technical_scout], tasks=[test_task], memory=False, verbose=True)
    print(f"\n--- Running Test: Was yesterday ({yesterday}) sideways? ---\n")
    result = crew.kickoff()
    print(f"\nFinal Output:\n{result}")
    return result


def test_ts_current_regime():
    """Ask the Technical Scout: 'How is the market today?'"""
    test_task = Task(
        description=(
            "What is the current market regime? Call detect_market_regime() "
            "with no arguments to get the latest data. Report the regime, "
            "ADX value, and which strategies are suitable."
        ),
        expected_output="Current market regime with ADX, SuperTrend, VIX, and suitable strategies.",
        agent=technical_scout,
    )

    crew = Crew(agents=[technical_scout], tasks=[test_task], memory=False, verbose=True)
    print("\n--- Running Test: Current market regime ---\n")
    result = crew.kickoff()
    print(f"\nFinal Output:\n{result}")
    return result


def test_supertrend_today():
    """Ask the Technical Scout: 'Can I measure today's sideways nature with SuperTrend?'"""
    test_task = Task(
        description=(
            "First, call detect_market_regime() with no arguments to get today's "
            "market data (ADX, SuperTrend direction, VIX). Then, look at the "
            "SuperTrend value. Can I use SuperTrend to measure whether the market "
            "is sideways? Explain what SuperTrend shows — does it measure trend "
            "direction only, or can it indicate a sideways/choppy market? Base your "
            "answer on today's actual data and the known definition of SuperTrend. "
            "If unsure about SuperTrend's definition, call load_skill_file('technical-scout.json') "
            "to look it up."
        ),
        expected_output=(
            "Explanation of whether SuperTrend can measure sideways markets, "
            "grounded in today's actual SuperTrend value from the tool output."
        ),
        agent=technical_scout,
    )

    crew = Crew(agents=[technical_scout], tasks=[test_task], memory=False, verbose=True)
    print("\n--- Running Test: Can SuperTrend measure sideways nature? ---\n")
    result = crew.kickoff()
    print(f"\nFinal Output:\n{result}")
    return result


if __name__ == "__main__":
    test_supertrend_today()
