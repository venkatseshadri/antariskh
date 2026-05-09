#!/usr/bin/env python3
"""
Full end-to-end test scenario: entry → trade plan → backtest → exit → CFO audit
Simulates a complete trading day with mock data.
"""

import sys
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "antariksh"))

# Enable mock mode
os.environ["ANTARIKSH_MOCK_MODE"] = "1"
os.environ["ANTARIKSH_MOCK_TIME"] = "10:30"
os.environ["ANTARIKSH_MOCK_VIX"] = "18.5"
os.environ["ANTARIKSH_MOCK_NIFTY"] = "24500"

from phase1_mvs import GateChecker, TradeDecisionEngine
from backtester import backtest_trade
from telegram_bridge import TelegramBridge
from cfo_auditor import get_cfo_auditor
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")
logger = logging.getLogger("TestScenario")

def test_scenario_pass():
    """Test scenario: Gate PASS → Trade plan → Backtest → Exit"""
    print("\n" + "=" * 80)
    print("TEST SCENARIO: GATE PASS → TRADE PLAN → BACKTEST")
    print("=" * 80)

    # Step 1: Gate check
    logger.info("Step 1: Gate check (VIX=18.5, Time=10:30)...")
    gate_pass, gate_reason = GateChecker.check_gate()
    print(f"\nGate result: {gate_pass} ({gate_reason})")

    if not gate_pass:
        logger.error("Gate failed - cannot proceed")
        return

    # Step 2: Generate trade plan
    logger.info("Step 2: Generate trade plan...")
    trade_plan = TradeDecisionEngine.generate_trade_plan()
    print(f"\nTrade plan: {trade_plan.get('instrument')} @ {trade_plan.get('atm_strike')}")
    print(f"  Legs: {trade_plan.get('wing_width')}pt wings")
    print(f"  Target: ₹{trade_plan.get('target_profit')}, Max Loss: ₹{trade_plan.get('max_loss')}")

    # Step 3: Log entry
    logger.info("Step 3: Log entry to CFO auditor...")
    cfo = get_cfo_auditor()
    cfo.log_session(gate_pass=True, trade_plan=trade_plan, backtest_result=None)
    print("✅ Entry session logged")

    # Step 4: Simulate market move (NIFTY +200)
    logger.info("Step 4: Backtest with spot move (NIFTY +200)...")
    exit_spot = 24500 + 200  # Spot moved up
    backtest_result = backtest_trade(trade_plan, exit_spot=exit_spot)
    print(f"\nBacktest result:")
    print(f"  P&L: ₹{backtest_result.get('pnl_inr'):.0f}")
    print(f"  Return: {backtest_result.get('return_pct'):.2f}%")
    print(f"  Hit target: {backtest_result.get('hit_target')}")
    print(f"  Hit SL: {backtest_result.get('hit_stoploss')}")

    # Step 5: Log exit + CFO audit
    logger.info("Step 5: Log exit and CFO audit...")
    verdict = cfo.log_session(gate_pass=True, trade_plan=trade_plan, backtest_result=backtest_result)
    print(f"\nCFO verdict: {verdict.get('summary')}")
    print(f"  Daily SL check: {verdict.get('checks', {}).get('daily_sl')}")
    print(f"  MTD P&L: ₹{verdict.get('mtd_pnl', 0):.0f}")
    print(f"  Avg daily: ₹{verdict.get('avg_daily', 0):.0f}")

    # Step 6: Send exit message
    logger.info("Step 6: Send Telegram exit message...")
    TelegramBridge.send_exit_report(trade_plan, backtest_result)
    print("✅ Exit message sent")

    print("\n" + "=" * 80)
    print("✅ FULL SCENARIO COMPLETE")
    print("=" * 80)

if __name__ == "__main__":
    test_scenario_pass()
