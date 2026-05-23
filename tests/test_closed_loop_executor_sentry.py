"""Chain test: Executioner → Risk Sentry state hand-off.

import os, sys, json
from pathlib import Path
from crewai import Agent, Task, Crew
from crewai.llm import LLM
from tools.execution_tools import ExecuteTradeTool, GetOrderStatusTool
from tools.risk_tools import MonitorPnLGreeksTool, TSLEngineTool, TradeCommandHandlerTool
from crews.ta_crew import load_skill_file
from dotenv import load_dotenv


Validates the closed loop:
  Executioner places trade → outputs ExecutionReport (fill prices, tokens, order IDs)
  Risk Sentry receives report → monitors with actual fill prices → checks SL/TP/TSL

This prevents "Ghost Positions" — the Sentry monitors what was ACTUALLY filled.
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

executioner = Agent(
    role="Execution Specialist",
    goal="Execute the authorized Iron Butterfly and produce a detailed Execution Report with fill prices and order IDs.",
    backstory="You execute with precision. You output a structured report with every leg's fill price, token, and order ID.",
    tools=[ExecuteTradeTool(), GetOrderStatusTool()],
    llm=ds_llm,
    verbose=True,
    memory=False,
)

sentry = Agent(
    role="Risk & State Sentry",
    goal="Receive the Execution Report and begin live monitoring. Use ACTUAL fill prices for SL/TP/TSL — not theoretical targets.",
    backstory="You babysit positions with real fill data. Never trust theoretical prices — only the Executioner's actual fills.",
    tools=[
        MonitorPnLGreeksTool(),
        TSLEngineTool(),
        TradeCommandHandlerTool(),
        load_skill_file,
    ],
    llm=ds_llm,
    verbose=True,
    memory=False,
)

# --- TASK 1: Executioner places the trade ---
task_execute = Task(
    description=(
        "The Portfolio Manager has authorized this Iron Butterfly for NIFTY. "
        "Execute it using execute_broker_trade:\n\n"
        "  symbol='NIFTY'\n"
        "  strategy='IRON_BUTTERFLY'\n"
        "  authorized_lots=1\n"
        "  legs=[\n"
        "    {action: 'BUY',  strike: 23500, option_type: 'PE', quantity: 1},\n"
        "    {action: 'BUY',  strike: 23900, option_type: 'CE', quantity: 1},\n"
        "    {action: 'SELL', strike: 23650, option_type: 'PE', quantity: 1},\n"
        "    {action: 'SELL', strike: 23650, option_type: 'CE', quantity: 1}\n"
        "  ]\n\n"
        "IMPORTANT: In your answer, extract the following from the tool output:\n"
        "- The trading symbol (tsym), action, and order ID for each leg.\n"
        "- The lot_size used (should be 65).\n"
        "- The guardrail status.\n\n"
        "Call get_order_status AFTER execution to confirm ALL 4 legs are SIMULATED SUCCESS.\n"
        "Format your output as a clear EXECUTION REPORT that the Risk Sentry can consume."
    ),
    expected_output="Execution Report with all 4 legs, tsyms, order IDs, lot_size=65, guardrail status.",
    agent=executioner,
)

# --- TASK 2: Risk Sentry monitors using the execution report ---
task_monitor = Task(
    description=(
        "You have received the Execution Report from the Execution Specialist. "
        "The report contains the ACTUAL fill prices, trading symbols, and lot_size "
        "for each of the 4 Iron Butterfly legs.\n\n"
        "Your monitoring cycle:\n\n"
        "1. Call load_skill_file('risk-sentry.json') to read the rules.\n\n"
        "2. Call monitor_pnl_greeks with the EXACT legs from the Execution Report. "
        "Use the actual tsyms and entry prices — do NOT use theoretical values.\n\n"
        "3. Calculate the weighted ATM sell entry price from the SELL legs.\n\n"
        "4. Call tsl_engine with:\n"
        "   - entry_price = weighted ATM sell entry\n"
        "   - current_price = whichever SELL leg LTP is higher (from monitor_pnl_greeks)\n"
        "   - highest_favorable = entry_price (just entered)\n\n"
        "5. Report: current P&L, Greeks, SL/TP/TSL levels, decision (HOLD/TRAIL/EXIT).\n\n"
        "CRITICAL: The Execution Report is in the context from the previous task. "
        "Extract the LEG DETAILS from it. Do NOT invent entry prices."
    ),
    expected_output="Monitoring report: P&L, Greeks, SL/TP/TSL levels, decision based on ACTUAL fill prices from Execution Report.",
    agent=sentry,
    context=[task_execute],
)

print("\n" + "=" * 60)
print("CLOSED LOOP: Executioner → Execution Report → Risk Sentry")
print("=" * 60)

crew = Crew(
    agents=[executioner, sentry],
    tasks=[task_execute, task_monitor],
    memory=False,
    verbose=True,
)
result = crew.kickoff()

print("\n*** FINAL RESULT ***")
print(result)
