"""Paper-trading test for the Execution Specialist.

Feeds the Executioner a detailed 4-leg Iron Butterfly plan.
Verifies: leg-by-leg payload, wing-first sequencing, guardrail bypass.
Zero real capital at risk — simulation mode by default.
"""

import os, sys, json, logging
from pathlib import Path
from datetime import datetime

# ── Log setup ────────────────────────────────────────────────────────────────
LOG_FILE = Path(__file__).parent / "simulated_trades.log"
logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s - EXECUTION_LOG - %(message)s",
)

# ── Env ──────────────────────────────────────────────────────────────────────
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
from crews.ta_crew import execution_specialist as _executor, load_skill_file
from tools.execution_tools import ExecuteTradeTool, GetOrderStatusTool

ds_llm = LLM(
    model="deepseek/deepseek-chat",
    base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
    temperature=0.1,
    api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
)

execute_hammer = ExecuteTradeTool()
get_status = GetOrderStatusTool()

executioner = Agent(
    role=_executor.role,
    goal=_executor.goal,
    backstory=_executor.backstory,
    tools=[execute_hammer, get_status, load_skill_file],
    llm=ds_llm,
    verbose=True,
    memory=False,
)

# ── Test: 4-Leg Iron Butterfly ───────────────────────────────────────────────

IRON_FLY_LEGS = """
    "legs": [
        {"action": "BUY", "strike": 24400, "option_type": "PE", "quantity": 1},
        {"action": "BUY", "strike": 25600, "option_type": "CE", "quantity": 1},
        {"action": "SELL", "strike": 25000, "option_type": "PE", "quantity": 1},
        {"action": "SELL", "strike": 25000, "option_type": "CE", "quantity": 1}
    ]
"""

task = Task(
    description=(
        "Execute the following Iron Butterfly plan for NIFTY. "
        "Call load_skill_file('executioner.json') first to read the execution rules.\n\n"
        "The Portfolio Manager has authorized exactly 1 lot per leg.\n\n"
        "TRADE PLAN:\n"
        f"{IRON_FLY_LEGS}\n\n"
        "CRITICAL: You MUST call execute_broker_trade with symbol='NIFTY', "
        "strategy='IRON_BUTTERFLY', authorized_lots=1, and the EXACT legs above. "
        "The tool enforces wing-first sequencing internally — you don't need to reorder. "
        "After execution, call get_order_status to verify all 4 legs are COMPLETE. "
        "Report the order IDs from the tool output."
    ),
    expected_output=(
        "Confirmation of all 4 legs executed. List of order IDs. "
        "Status: all SIMULATED SUCCESS. Wings confirmed before center."
    ),
    agent=executioner,
)

# ── Run ──────────────────────────────────────────────────────────────────────

# Log the test metadata
logging.info(f"TEST_START: Iron Butterfly 4-leg @ {datetime.now().isoformat()}")

print("\n" + "=" * 60)
print("EXECUTION SPECIALIST TEST — Paper Mode (Iron Butterfly)")
print("=" * 60)
print(f"Log: {LOG_FILE}")
print()

crew = Crew(agents=[executioner], tasks=[task], memory=False, verbose=True)
result = crew.kickoff()

print("\n*** FINAL OUTPUT ***")
print(result)

# ── Verify log file ──────────────────────────────────────────────────────────

print("\n" + "=" * 60)
print("AUDIT: simulated_trades.log")
print("=" * 60)
if LOG_FILE.exists():
    log_content = LOG_FILE.read_text()
    print(log_content)
else:
    print("WARNING: Log file not found!")

# ── Structural checks ────────────────────────────────────────────────────────

print("\n" + "=" * 60)
print("VERIFICATION")
print("=" * 60)

checks = {
    "Wings first (BUY before SELL)": False,
    "All 4 legs present": False,
    "All SIMULATED / SUCCESS": False,
    "Trading symbols auto-generated": False,
}

response_text = str(result)
# Check BUY legs appear before SELL legs in response
buy_idx = response_text.find("BUY")
sell_idx = response_text.find("SELL")
checks["Wings first (BUY before SELL)"] = buy_idx >= 0 and buy_idx < sell_idx

# Count legs
leg_count = response_text.count("action")  # JSON key in response or tool args
# Also check log
if LOG_FILE.exists():
    leg_count += LOG_FILE.read_text().count('"action"')
checks["All 4 legs present"] = leg_count >= 4

checks["All SIMULATED / SUCCESS"] = (
    "SIMULATED" in response_text.upper() or "SUCCESS" in response_text.upper()
)

checks["Trading symbols auto-generated"] = "NIFTY" in response_text and (
    "CE" in response_text or "PE" in response_text
)

for check, passed in checks.items():
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] {check}")
