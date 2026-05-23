"""Chain test: Librarian resolves contract → Executioner places paper trade.

import os, sys, json
from pathlib import Path
from crewai import Agent, Task, Crew
from crewai.llm import LLM
from tools.contract_tools import LibrarianContractTool
from tools.execution_tools import ExecuteTradeTool
from dotenv import load_dotenv


Validates the full assembly line:
  Architect request → Librarian lookup → Token/Symbol/Lot → Executioner paper order
All against live DuckDB (ATTACH READ_ONLY — zero lock contention).
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

LOG_FILE = Path(__file__).parent / "simulated_chain_trades.log"

librarian = Agent(
    role="Contract Specialist",
    goal="Find exact broker tokens and trading symbols for theoretical strikes.",
    backstory="Data expert. You take a strike and option_type and return the Shoonya token, tsym, and lot size. You use contract_librarian_lookup ONLY.",
    tools=[LibrarianContractTool()],
    llm=ds_llm,
    verbose=True,
    memory=False,
)

executioner = Agent(
    role="Execution Specialist",
    goal="Place paper trades using tokens provided by the Librarian.",
    backstory="High-speed executioner. You ONLY use tokens and symbols provided to you. Never invent symbols. You log everything to paper.",
    tools=[ExecuteTradeTool()],
    llm=ds_llm,
    verbose=True,
    memory=False,
)

# --- Task 1: Librarian resolves the Architect's request ---
task_lookup = Task(
    description=(
        "The Strategy Architect needs NIFTY 23800 CE for an Iron Butterfly. "
        "Call contract_librarian_lookup with index_name='NIFTY', strike=23800, "
        "option_type='CE' to find the exact token, trading symbol, and lot size. "
        "Return the full JSON result so the Executioner can use it."
    ),
    expected_output="JSON with token, trading_symbol, lot_size, expiry, strike, option_type.",
    agent=librarian,
)

# --- Task 2: Executioner trades using the Librarian's output ---
task_execute = Task(
    description=(
        "The Contract Specialist has found the exact contract. "
        "Take the token, trading_symbol, strike, option_type, and lot_size "
        "from the previous task and call execute_broker_trade to place a "
        "PAPER order. "
        "Use symbol='NIFTY', strategy='ARCHITECT_TEST', authorized_lots=1, "
        "and ONE leg: action=SELL, strike=23800, option_type=CE, quantity=1.\n\n"
        "YOU MUST USE THE EXACT VALUES FROM THE LIBRARIAN. Do NOT invent a "
        "different strike or symbol."
    ),
    expected_output="Confirmation of paper trade with order ID.",
    agent=executioner,
    context=[task_lookup],
)

# --- Run ---
print("\n" + "=" * 60)
print("CHAIN TEST: Librarian → Executioner")
print("=" * 60)

crew = Crew(
    agents=[librarian, executioner], tasks=[task_lookup, task_execute], memory=False
)
result = crew.kickoff()
output = str(result)

print("\n*** CHAIN RESULT ***")
print(output)

# --- Verify ---
print("\n" + "=" * 60)
print("VERIFICATION")
print("=" * 60)

checks = {
    "Token resolved": "35000" in output,
    "Trading symbol present": "NIFTY14MAY" in output,
    "Lot size correct (65)": "65" in output,
    "Paper order placed": "SIMULATED" in output or "SIM-" in output,
    "Wings-first sequence": "WING" in output,
    "No lock errors": "lock" not in output.lower()[:500],
}
for c, ok in checks.items():
    print(f"  [{'PASS' if ok else 'FAIL'}] {c}")

# Log the chain result
log = f"{'=' * 40}\nCHAIN TEST: {Path(__file__).name}\nResult: {output[:500]}\n"
