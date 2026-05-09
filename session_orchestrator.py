#!/usr/bin/env python3
"""
Session Orchestrator — entry point for Phase 1 MVS.
Called by cron at 9:30 AM (entry) and 2:35 PM (exit).
Orchestrates: gate check → trade plan → backtest → Telegram → CFO audit.
"""

import sys
import os
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional

# Setup paths
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "python-trader"))
sys.path.insert(0, str(PROJECT_ROOT / "antariksh"))

# Import modules
from phase1_mvs import Phase1Config, Phase1Orchestrator, GateChecker, TradeDecisionEngine
from backtester import backtest_trade
from telegram_bridge import TelegramBridge
from cfo_auditor import get_cfo_auditor
import logging

# Setup logging
Phase1Config.LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    handlers=[
        logging.FileHandler(Phase1Config.LOG_DIR / f"orchestrator_{datetime.now().strftime('%Y%m%d')}.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("SessionOrchestrator")

class SessionOrchestrator:
    """Main orchestrator for Phase 1 session"""

    @staticmethod
    def run_entry_session():
        """Run 9:30 AM entry session: gate check → trade plan → Telegram entry"""
        logger.info("=" * 70)
        logger.info("PHASE 1 ENTRY SESSION — 9:30 AM")
        logger.info("=" * 70)

        try:
            # Step 1: Gate check
            logger.info("Step 1: Gate check...")
            gate_pass, gate_reason = GateChecker.check_gate()
            logger.info(f"  Result: {gate_pass=}, {gate_reason=}")

            # Step 2: Generate trade plan if gate passes
            trade_plan = None
            if gate_pass:
                logger.info("Step 2: Gate PASS — generating trade plan...")
                trade_plan = TradeDecisionEngine.generate_trade_plan()
                if trade_plan:
                    logger.info(f"  Trade plan: {trade_plan.get('instrument')} {trade_plan.get('atm_strike'):.0f}")
            else:
                logger.info("Step 2: Gate SKIP — no trade plan")

            # Step 3: Send Telegram entry message
            logger.info("Step 3: Sending Telegram entry message...")
            TelegramBridge.send_entry_gate(gate_pass, gate_reason, trade_plan)

            # Step 4: Log session start
            cfo = get_cfo_auditor()
            cfo.log_session(gate_pass=gate_pass, trade_plan=trade_plan, backtest_result=None)

            logger.info("=" * 70)
            logger.info("ENTRY SESSION COMPLETE")
            logger.info("=" * 70)
            return gate_pass, trade_plan

        except Exception as e:
            logger.error(f"Entry session failed: {e}", exc_info=True)
            TelegramBridge.send_alert("critical", "Entry Session Error", str(e))
            return False, None

    @staticmethod
    def run_exit_session(trade_plan: Optional[Dict] = None):
        """Run 2:35 PM exit session: backtest → P&L → Telegram exit → CFO audit"""
        logger.info("=" * 70)
        logger.info("PHASE 1 EXIT SESSION — 2:35 PM")
        logger.info("=" * 70)

        try:
            # Step 1: Run backtest if trade was executed
            backtest_result = None
            if trade_plan:
                logger.info("Step 1: Running backtest (dry-run)...")
                backtest_result = backtest_trade(trade_plan)
                if backtest_result:
                    logger.info(f"  P&L: ₹{backtest_result.get('pnl_inr', 0):.0f}")
            else:
                logger.info("Step 1: No trade to backtest")

            # Step 2: Send Telegram exit message
            logger.info("Step 2: Sending Telegram exit message...")
            TelegramBridge.send_exit_report(trade_plan, backtest_result)

            # Step 3: CFO audit log
            logger.info("Step 3: CFO audit logging...")
            cfo = get_cfo_auditor()
            verdict = cfo.log_session(gate_pass=bool(trade_plan), trade_plan=trade_plan, backtest_result=backtest_result)
            logger.info(f"  CFO verdict: {verdict.get('summary')}")

            # Step 4: Check for L1 violations
            if not verdict.get('passed'):
                logger.warning(f"  L1 violation detected: {verdict.get('violations')}")
                TelegramBridge.send_alert("critical", "L1 Invariant Violated", json.dumps(verdict.get('violations')))

            logger.info("=" * 70)
            logger.info("EXIT SESSION COMPLETE")
            logger.info("=" * 70)
            return backtest_result

        except Exception as e:
            logger.error(f"Exit session failed: {e}", exc_info=True)
            TelegramBridge.send_alert("critical", "Exit Session Error", str(e))
            return None

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Antariksh Phase 1 session orchestrator")
    parser.add_argument("session", choices=["entry", "exit"], help="Session type (entry @ 9:30 AM or exit @ 2:35 PM)")
    args = parser.parse_args()

    logger.info(f"Session type: {args.session}")

    if args.session == "entry":
        SessionOrchestrator.run_entry_session()
    elif args.session == "exit":
        SessionOrchestrator.run_exit_session()

if __name__ == "__main__":
    main()
