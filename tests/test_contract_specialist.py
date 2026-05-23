"""Validate Contract Specialist — full pipeline test.

import os, sys, json
from pathlib import Path
from crewai import Agent, Task, Crew
from crewai.llm import LLM
from crews.ta_crew import contract_specialist as _librarian, load_skill_file
from tools.contract_tools import LibrarianContractTool, EnrichTradePlanTool
from tools.ta_strategy_tools import FetchOptionChainTool, FetchGreeksTool
from dotenv import load_dotenv


Simulates: Architect trade plan → Librarian resolves each leg → PM-ready enriched payload.
Runs against live DuckDB (ATTACH READ_ONLY — zero lock contention with capture script).
"""


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

librarian = Agent(
    role=_librarian.role,
    goal=_librarian.goal,
    backstory=_librarian.backstory,
    tools=[
        LibrarianContractTool(),
        EnrichTradePlanTool(),
        FetchOptionChainTool(),
        FetchGreeksTool(),
        load_skill_file,
    ],
    llm=ds_llm,
    verbose=True,
    memory=False,
)

# Simulated: Architect says "Iron Butterfly at ATM (23800) with 300pt wings"
task = Task(
    description=(
        "A Strategy Architect has designed this Iron Butterfly for NIFTY:\n\n"
        "  BUY  1 lot of 23500 PE (put wing)\n"
        "  BUY  1 lot of 24100 CE (call wing)\n"
        "  SELL 1 lot of 23800 PE (ATM put)\n"
        "  SELL 1 lot of 23800 CE (ATM call)\n\n"
        "Your job as the Market Data Librarian:\n\n"
        "1. Call load_skill_file('librarian.json') to read the rules.\n\n"
        "2. For EACH leg above, call contract_librarian_lookup with the "
        "correct index_name, strike, and option_type to find the exact "
        "trading symbol, token, and lot size.\n\n"
        "3. Then call enrich_trade_plan to enrich the full 4-leg plan "
        "with all contract metadata (tsym, token, lot_size, ltp, per_lot_value).\n\n"
        "4. Output the PM-ready enriched plan. Flag any unresolved legs.\n\n"
        "CRITICAL: If ANY leg returns lot_size 0 or Null, REJECT the plan.\n"
        "If a token is missing, flag it clearly. NEVER fabricate a token."
    ),
    expected_output=(
        "PM-ready enriched trade plan with all 4 legs resolved. "
        "Each leg must show: tsym, token, lot_size, ltp, per_lot_value, expiry. "
        "Any missing strikes must be FLAGGED."
    ),
    agent=librarian,
)

print("\n" + "=" * 60)
print("CONTRACT SPECIALIST VALIDATION")
print("  Architect plan → Librarian → PM-ready enriched payload")
print("=" * 60)

crew = Crew(agents=[librarian], tasks=[task], memory=False, verbose=True)
result = crew.kickoff()

print("\n*** FINAL OUTPUT ***")
print(result)

# Quick structural check
result_str = str(result)
checks = {
    "4 legs resolved": "4" in result_str or "trading_symbol" in result_str,
    "Tokens present": "token" in result_str.lower(),
    "Lot sizes present": "lot_size" in result_str,
    "Expiry present": "expiry" in result_str.lower(),
    "LTP present": "ltp" in result_str.lower(),
    "No errors": "error" not in result_str.lower()[:500],
}
print("\n" + "=" * 60)
print("STRUCTURAL VALIDATION")
print("=" * 60)
for check, passed in checks.items():
    print(f"  [{'PASS' if passed else 'FAIL'}] {check}")
