"""Prompt: "buy 1 lot of delta neutral strategy for the index with the closest weekly expiry, fyi today is monday"

Tests the Librarian's ability to:
1. Identify the default index (NIFTY) when none specified
2. Find the ATM strike from live spot
3. Resolve both CE + PE ATM contracts (delta-neutral = Iron Butterfly body)
4. Return token, tsym, lot_size for both legs
"""

import os, sys, json
from pathlib import Path

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

from crewai import Agent, Task, Crew
from crewai.llm import LLM
from tools.contract_tools import LibrarianContractTool, ResolveContractTool
from tools.ta_strategy_tools import FetchOptionChainTool, FetchGreeksTool

ds_llm = LLM(
    model="deepseek/deepseek-chat",
    base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
    temperature=0.0,
    api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
)

librarian = Agent(
    role="Market Data Librarian (NFO Specialist)",
    goal="Resolve exactly one contract per request — token, symbol, lot size, expiry.",
    backstory="You resolve strikes into tokens. No analysis. No strategy. Just contracts.",
    tools=[
        LibrarianContractTool(),
        ResolveContractTool(),
        FetchOptionChainTool(),
        FetchGreeksTool(),
    ],
    llm=ds_llm,
    verbose=True,
    memory=False,
)

task = Task(
    description=(
        "A user asks: 'buy 1 lot of a delta neutral options strategy for "
        "the index with the closest weekly expiry. FYI today is Monday.'\n\n"
        "Your job as the Market Data Librarian:\n\n"
        "1. The default index is NIFTY. Monday means the nearest weekly expiry is "
        "this Thursday (2026-05-14).\n\n"
        "2. A delta-neutral strategy means you need BOTH an ATM Call (CE) and "
        "an ATM Put (PE) at the same strike. This is the body of an Iron Butterfly.\n\n"
        "3. First, call fetch_option_chain_from_duck_db to see what the current spot "
        "and available strikes are. Find the ATM strike.\n\n"
        "4. Then call contract_librarian_lookup TWICE — once for the ATM CE "
        "and once for the ATM PE — to get the exact token, trading_symbol, "
        "and lot_size for each.\n\n"
        "5. Return BOTH contracts with all metadata. Confirm the lot size.\n\n"
        "CRITICAL: Do NOT guess the ATM strike. Find it from live market data. "
        "The ATM strike = round(current_spot / 50) * 50."
    ),
    expected_output=(
        "Two resolved contracts: ATM CE and ATM PE. Each with token, tsym, lot_size, "
        "expiry. ATM strike confirmed from live data."
    ),
    agent=librarian,
)

print("\n" + "=" * 60)
print("PROMPT: 'buy 1 lot of delta neutral strategy, closest weekly expiry (Monday)'")
print("=" * 60)

crew = Crew(agents=[librarian], tasks=[task], memory=False)
result = crew.kickoff()

print("\n*** FINAL ANSWER ***")
print(result)
