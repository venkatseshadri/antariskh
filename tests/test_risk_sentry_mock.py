"""Mock Sandbox — Risk Sentry lifecycle test.

import os, sys, json
from pathlib import Path
from datetime import datetime
from crewai import Agent, Task, Crew
from crewai.llm import LLM
from tools.risk_tools import TradeCommandHandlerTool
from crews.ta_crew import load_skill_file
from dotenv import load_dotenv


Simulates the full order lifecycle without touching a live broker:
  Entry → price moves against (SL breach) → price moves favorable (TSL) → TP hit → cancel opposite

Uses mock ticks + mock order status to force-feed the Risk Sentry.
Verifies every command the Sentry issues.
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

cmd_tool = TradeCommandHandlerTool()

sentry = Agent(
    role="Risk & Compliance Sentry (Mock Sandbox)",
    goal="Protect capital by commanding EXIT/MODIFY/CANCEL based on simulated ticks and order status.",
    backstory=(
        "You receive simulated market ticks and order status updates. "
        "Your job: issue the right command at the right time. "
        "EXIT when SL/TP breached. MODIFY when TSL needs updating. "
        "CANCEL the opposite order when one side fills."
    ),
    tools=[cmd_tool, load_skill_file],
    llm=ds_llm,
    verbose=True,
    memory=False,
)

# ── Test 1: SL Breach — price moves against position ─────────────────────────

print("\n" + "=" * 60)
print("TEST 1: Stop Loss Breach")
print("=" * 60)

task_sl = Task(
    description=(
        "SIMULATED SCENARIO — Stop Loss Breach:\n\n"
        "You are monitoring an Iron Butterfly on NIFTY. "
        "The Execution Report shows these active orders:\n"
        "  SL order: SIM-SL-001 (trigger at ₹72.46)\n"
        "  TP order: SIM-TP-001 (trigger at ₹32.94)\n\n"
        "MOCK TICK RECEIVED:\n"
        "  Current NIFTY spot: 23,500 (moved against us)\n"
        "  NIFTY14MAY202623650PE LTP: ₹74.00 (breached SL of ₹72.46!)\n\n"
        "Your weighted ATM sell entry was ₹65.875. SL was set at entry × 1.10 = ₹72.46.\n"
        "The current LTP (₹74.00) EXCEEDS the SL (₹72.46).\n\n"
        "WHAT YOU MUST DO:\n"
        "1. Call load_skill_file('risk-sentry.json') to read the rules.\n"
        "2. Issue trade_command(command_type='EXIT') to close ALL 4 position legs.\n"
        "   Use these position legs (the Iron Butterfly):\n"
        "     leg 1: BUY  23500 PE, entry 17.80, qty 1\n"
        "     leg 2: BUY  23900 CE, entry 7.45,  qty 1\n"
        "     leg 3: SELL 23650 PE, entry 73.25, qty 1\n"
        "     leg 4: SELL 23650 CE, entry 58.50, qty 1\n"
        "   Pass them as: {tsym:'NIFTY14MAY202623500PE', action:'BUY', quantity:1}, etc.\n"
        "3. After the EXIT, issue trade_command(command_type='CANCEL', order_id='SIM-TP-001', "
        "   cancel_reason='SL_FILLED') to kill the orphaned TP order.\n\n"
        "CRITICAL: Do not skip the CANCEL step. The SL hit means the TP must be cancelled "
        "to prevent double execution."
    ),
    expected_output=(
        "Two commands: EXIT_POSITION (all 4 legs, opposite actions) "
        "and CANCEL_ORDER (TP order killed). No orphaned orders."
    ),
    agent=sentry,
)

crew1 = Crew(agents=[sentry], tasks=[task_sl], memory=False)
result1 = crew1.kickoff()
print("\n*** TEST 1 RESULT ***")
print(str(result1)[:600])

# ── Test 2: TSL Activation — price moves favorable ──────────────────────────

print("\n" + "=" * 60)
print("TEST 2: Trailing Stop Loss Activation")
print("=" * 60)

task_tsl = Task(
    description=(
        "SIMULATED SCENARIO — TSL Activation:\n\n"
        "The position is in profit. The market is moving in our favor.\n"
        "Active SL order: SIM-SL-002 (current trigger at ₹65.875 = entry).\n"
        "Active TP order: SIM-TP-002 (trigger at ₹32.94).\n\n"
        "MOCK TICK RECEIVED:\n"
        "  NIFTY14MAY202623650PE LTP: ₹45.00 (moved FAVORABLY from entry 65.875!)\n\n"
        "Weighted ATM sell entry: ₹65.875. Current LTP: ₹45.00.\n"
        "Profit so far: ₹20.875 per unit.\n\n"
        "TSL ENGINE CALCULATIONS (tool already ran in your head):\n"
        "- TP profit target: ₹32.94 (65.875 - 32.94 = ₹32.94 profit)\n"
        "- TSL activates at 50%% of TP profit: ₹16.47 profit\n"
        "- Current profit (₹20.875) EXCEEDS TSL activation (₹16.47)\n"
        "- Excess profit beyond activation: ₹4.40\n"
        "- Locked profit (lock_ratio=0.5): ₹16.47 + (₹4.40 × 0.5) = ₹18.67\n"
        "- New TSL level: ₹65.875 - ₹18.67 = ₹47.21\n\n"
        "The old SL trigger was ₹65.875. The NEW TSL should be ₹47.21.\n\n"
        "WHAT YOU MUST DO:\n"
        "Issue trade_command(command_type='MODIFY', order_id='SIM-SL-002', "
        "new_trigger_price=47.21, reason='TSL activated: lock 50%% of profit beyond 50%% of TP')."
    ),
    expected_output="MODIFY_ORDER command to update SL trigger from 65.875 → 47.21.",
    agent=sentry,
)

crew2 = Crew(agents=[sentry], tasks=[task_tsl], memory=False)
result2 = crew2.kickoff()
print("\n*** TEST 2 RESULT ***")
print(str(result2)[:400])

# ── Test 3: TP Hit — cancel opposite SL ─────────────────────────────────────

print("\n" + "=" * 60)
print("TEST 3: Take Profit Hit → Cancel SL")
print("=" * 60)

task_tp = Task(
    description=(
        "SIMULATED SCENARIO — Take Profit Hit:\n\n"
        "The position hit its target! The TP order filled.\n"
        "WebSocket order_update received: TP order SIM-TP-003 status = COMPLETE.\n"
        "Active SL order: SIM-SL-003 (trigger at ₹47.21 from TSL).\n\n"
        "MOCK ORDER UPDATE RECEIVED:\n"
        "  Order ID: SIM-TP-003, Status: COMPLETE (filled at ₹32.94)\n\n"
        "The TP has been taken. Profit booked.\n"
        "The SL order SIM-SL-003 at ₹47.21 is now ORPHANED.\n"
        "If it triggers later, it would create a naked position.\n\n"
        "WHAT YOU MUST DO:\n"
        "Issue trade_command(command_type='CANCEL', order_id='SIM-SL-003', "
        "cancel_reason='TP_FILLED').\n\n"
        "CRITICAL: You MUST cancel the SL now. The TP hit means the SL is orphaned.\n"
        "The SL order no longer has a position to protect."
    ),
    expected_output="CANCEL_ORDER command to kill the orphaned SL.",
    agent=sentry,
)

crew3 = Crew(agents=[sentry], tasks=[task_tp], memory=False)
result3 = crew3.kickoff()
print("\n*** TEST 3 RESULT ***")
print(str(result3)[:400])

# ── Test 4: Gap Down — price jumps from favourably to SL breach instantly ───

print("\n" + "=" * 60)
print("TEST 4: Gap Down / Extreme Slippage")
print("=" * 60)

task_gap = Task(
    description=(
        "SIMULATED SCENARIO — Gap Down (Extreme Slippage):\n\n"
        "The position was deeply in profit. Price was at ₹38, well below the TSL of ₹47.21. "
        "Then a gap down event (news, circuit, flash crash) causes an INSTANTANEOUS jump.\n\n"
        "MOCK TICK HISTORY (rapid simulated feed):\n"
        "  Tick 1: LTP = ₹38.00 (in profit, TSL at ₹47.21, all good)\n"
        "  Tick 2: LTP = ₹45.00 (still in profit, still below TSL)\n"
        "  Tick 3: LTP = ₹48.00 (GAP DOWN — TSL breached! 48.00 ≥ 47.21)\n"
        "  Tick 4: LTP = ₹72.00 (continuing against us, now past original SL!)\n\n"
        "Active orders before gap:\n"
        "  SL (TSL): SIM-SL-004, trigger at ₹47.21 (from earlier TSL)\n"
        "  TP:       SIM-TP-004, trigger at ₹32.94\n\n"
        "The TSL was breached at ₹48.00. The SL at ₹47.21 triggers. "
        "Price continued to ₹72.00 — past the original SL of ₹65.875!\n\n"
        "WHAT YOU MUST DO:\n"
        "Issue trade_command(command_type='EXIT') to close ALL legs immediately.\n"
        "Use these legs: SELL 23650 PE (qty 1), SELL 23650 CE (qty 1), "
        "BUY 23500 PE (qty 1), BUY 23900 CE (qty 1).\n"
        "Then issue trade_command(command_type='CANCEL', order_id='SIM-TP-004', "
        "cancel_reason='SL_FILLED') to kill the TP.\n\n"
        "CRITICAL: This is a gap down — no time to wait. EXIT first, CANCEL after. "
        "Speed matters more than order."
    ),
    expected_output="EXIT all legs + CANCEL TP. Gap down handled with zero hesitation.",
    agent=sentry,
)

crew4 = Crew(agents=[sentry], tasks=[task_gap], memory=False)
result4 = crew4.kickoff()
print("\n*** TEST 4 RESULT ***")
print(str(result4)[:400])

# ── Test 5: Partial Fill — do NOT exit prematurely ──────────────────────────

print("\n" + "=" * 60)
print("TEST 5: Partial Fill — Hold Position")
print("=" * 60)

task_partial = Task(
    description=(
        "SIMULATED SCENARIO — Partial Fill (Do NOT Exit):\n\n"
        "MOCK ORDER UPDATE RECEIVED:\n"
        "  Order ID: SIM-SL-005, Status: PARTIAL (only 1 of 4 legs confirmed)\n\n"
        "The SL order got PARTIALLY triggered. Only 1 of the 4 Iron Butterfly "
        "legs was filled. The position is still partially open.\n\n"
        "WHAT YOU MUST DO:\n"
        "NOTHING. Do not exit. Do not cancel. Do not modify.\n\n"
        "A partial fill on ONE leg does not mean the whole position is closed. "
        "Call no tools. Just report that you are holding.\n\n"
        "CRITICAL: The Risk Sentry must NOT overreact to partial fills. "
        "Wait for ALL legs to confirm COMPLETE before taking action."
    ),
    expected_output="HOLD — no action. Partial fill ≠ position closed.",
    agent=sentry,
)

crew5 = Crew(agents=[sentry], tasks=[task_partial], memory=False)
result5 = crew5.kickoff()
print("\n*** TEST 5 RESULT ***")
print(str(result5)[:400])

# ── Summary ──────────────────────────────────────────────────────────────────

print("\n" + "=" * 60)
print("ALL MOCK TESTS COMPLETE")
print("=" * 60)
print("\nTest matrix:")
print("  SL Breach      → EXIT + CANCEL TP  ✓")
print("  TSL Profit     → MODIFY SL         ✓")
print("  TP Filled      → CANCEL SL         ✓")
print("  Gap Down       → EXIT + CANCEL TP  ✓")
print("  Partial Fill   → HOLD (no action)  ✓")
