"""Prompt: "execute a vega positive strategy in the next weekly at ATM +2 strikes"

import os, sys, json
from pathlib import Path
from crewai import Agent, Task, Crew
from crewai.llm import LLM
from tools.contract_tools import LibrarianContractTool
from tools.ta_strategy_tools import FetchOptionChainTool
from dotenv import load_dotenv


Tests the Librarian's ability to:
1. Parse "vega positive" = buy options (long vega, not short)
2. "next weekly" = NOT the current Thursday, but the one after
3. "ATM +2 strikes" = offset +2 from ATM in the options chain
4. Resolve BUY legs at the correct offset strike
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
    temperature=0.0,
    api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
)

librarian = Agent(
    role="Market Data Librarian (NFO Specialist)",
    goal="Resolve exact contracts from ambiguous prompts. No strategy analysis — just contracts.",
    backstory="You resolve strikes into tokens. Vega-positive = BUY. You find offset strikes from live chain.",
    tools=[LibrarianContractTool(), FetchOptionChainTool()],
    llm=ds_llm,
    verbose=True,
    memory=False,
)

task = Task(
    description=(
        "A user says: 'execute a vega positive strategy in the next weekly "
        "at ATM +2 strikes.'\n\n"
        "Parse this carefully as the Market Data Librarian:\n\n"
        "1. 'vega positive' = BUY options (long options = positive vega). "
        "This is NOT a sell/short strategy — you BUY to get positive vega exposure.\n\n"
        "2. 'next weekly' = the weekly expiry AFTER the current one. "
        "Today is Monday (May 12). Current weekly is Thursday May 14. "
        "Next weekly is Thursday May 21.\n"
        "BUT: if the scrip_master only has May 14 expiry, use that — "
        "the tool will pick the nearest available.\n\n"
        "3. 'ATM +2 strikes' = find the ATM strike first, then go 2 offset steps "
        "OUT of the money. The offset column in the option chain tells you this. "
        "Offset 0 = ATM. Offset +2 = 2 steps OTM.\n\n"
        "4. Call fetch_option_chain_from_duck_db to see the chain. "
        "Find the strike at Offset=+2. Read both CE and PE at that offset.\n\n"
        "5. Call contract_librarian_lookup for BOTH the CE and PE at the Offset=+2 "
        "strike. Return both contracts with token, tsym, lot_size, expiry.\n\n"
        "CRITICAL: Do not guess the offset. Read it from the option chain output. "
        "Each strike step is 50 points for NIFTY, so Offset=+2 = ATM + 100 points."
    ),
    expected_output=(
        "Two contracts: CE and PE at Offset=+2 strike. Both with token, tsym, "
        "lot_size=65, expiry. Confirmed from live option chain data."
    ),
    agent=librarian,
)

print("\n" + "=" * 60)
print("PROMPT: 'execute a vega positive strategy, next weekly, ATM +2 strikes'")
print("=" * 60)

crew = Crew(agents=[librarian], tasks=[task], memory=False)
result = crew.kickoff()

print("\n*** FINAL ANSWER ***")
print(result)
