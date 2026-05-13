"""E2E test: Risk Sentry monitors a position and triggers exits.

Simulates: Entry → monitoring cycle → SL/TP/TSL check → exit signal.
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
from tools.risk_tools import MonitorPnLGreeksTool, TSLEngineTool, ExitSignalHandlerTool
from crews.ta_crew import load_skill_file

ds_llm = LLM(
    model="deepseek/deepseek-chat",
    base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
    temperature=0.0,
    api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
)

sentry = Agent(
    role="Risk & Compliance Sentry",
    goal="Monitor positions and trigger exits when SL/TSL/TP breached. Never enter trades.",
    backstory=(
        "High-speed risk controller. Zero emotion. You ONLY babysit positions "
        "and fire exit commands. Use monitor_pnl_greeks → tsl_engine → exit_signal_handler "
        "in that exact order every cycle."
    ),
    tools=[
        MonitorPnLGreeksTool(),
        TSLEngineTool(),
        ExitSignalHandlerTool(),
        load_skill_file,
    ],
    llm=ds_llm,
    verbose=True,
    memory=False,
)

# Simulated: an Iron Butterfly position was entered
#   SELL 23650 CE @ 58.50 (ATM call)
#   SELL 23650 PE @ 73.25 (ATM put)
#   BUY  23500 PE @ 17.80 (put wing)
#   BUY  23900 CE @ 7.45  (call wing)
# Net credit received: (58.5+73.25) - (17.8+7.45) = 106.50 per unit
# With lot=65, net credit = 106.50 * 65 = ₹6,922.50

POSITION_JSON = """
[
    {"tsym": "NIFTY14MAY202623650CE", "action": "SELL", "entry_price": 58.50, "quantity": 1, "lot_size": 65},
    {"tsym": "NIFTY14MAY202623650PE", "action": "SELL", "entry_price": 73.25, "quantity": 1, "lot_size": 65},
    {"tsym": "NIFTY14MAY202623500PE", "action": "BUY",  "entry_price": 17.80, "quantity": 1, "lot_size": 65},
    {"tsym": "NIFTY14MAY202623900CE", "action": "BUY",  "entry_price": 7.45,  "quantity": 1, "lot_size": 65}
]
"""

task = Task(
    description=(
        "You are monitoring an active Iron Butterfly position on NIFTY.\n\n"
        "POSITION LEGS:\n"
        f"{POSITION_JSON}\n\n"
        f"Net credit received: ₹6,922.50. Max profit = full credit if spot stays near 23,650.\n"
        "Max loss = wing_width - credit = (150 × 65) - 6,922.50 = ₹2,827.50.\n\n"
        "Your monitoring cycle:\n\n"
        "1. Call load_skill_file('risk-sentry.json') to read the rules.\n\n"
        "2. Call monitor_pnl_greeks with symbol='NIFTY' and the EXACT legs above.\n\n"
        "3. For the ATM SELL legs (23650 CE and 23650 PE), calculate the "
        "weighted entry price. Weighted entry = (58.50 * 65 + 73.25 * 65) / (65 + 65) = 65.875.\n\n"
        "4. Call tsl_engine with entry_price=65.875 (the weighted ATM sell entry), "
        "current_price=from monitor (whichever is higher: CE or PE current LTP), "
        "highest_favorable=65.875 (just entered, no favorable move yet).\n\n"
        "5. If tsl_engine returns decision=HOLD or TRAIL: report status. "
        "If decision=EXIT_SL or EXIT_TP or EXIT_TSL: call exit_signal_handler "
        "with ALL position legs and the MTM P&L.\n\n"
        "6. Output the current state: P&L, Greeks, SL/TP/TSL levels, decision."
    ),
    expected_output=(
        "Current position status: MTM P&L, Greeks, SL/TP/TSL levels, "
        "decision (HOLD/TRAIL/EXIT). If EXIT, the formatted exit payload."
    ),
    agent=sentry,
)

print("\n" + "=" * 60)
print("RISK SENTRY TEST — Position Monitoring & SL/TSL/TP")
print("=" * 60)

crew = Crew(agents=[sentry], tasks=[task], memory=False)
result = crew.kickoff()

print("\n*** FINAL ANSWER ***")
print(result)
