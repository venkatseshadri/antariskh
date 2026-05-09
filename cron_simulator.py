#!/usr/bin/env python3
"""
Cron Job Simulator — test Phase 1 timing logic without installing actual crons.
Simulates all 5 cron jobs: token refresh, entry gate, exit, daily/weekly/monthly reports.
"""

import sys
import os
import logging
from pathlib import Path
from datetime import datetime, timedelta
import argparse

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "antariksh"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s"
)
logger = logging.getLogger("CronSimulator")

class CronSimulator:
    """Simulate Phase 1 cron jobs"""

    JOBS = {
        "token_refresh": {
            "time": "07:00",
            "script": "token_refresh_dual.py",
            "description": "Daily token refresh (Shoonya + Flattrade)"
        },
        "entry_gate": {
            "time": "09:30",
            "script": "session_orchestrator.py entry",
            "description": "9:30 AM entry gate check + trade plan"
        },
        "exit": {
            "time": "14:35",
            "script": "session_orchestrator.py exit",
            "description": "2:35 PM exit orchestration + backtest + CFO audit"
        },
        "exec_report_daily": {
            "time": "18:00",
            "script": "exec_report.py",
            "description": "Daily executive report (6 PM)"
        },
        "exec_report_weekly": {
            "time": "20:00 (Sun)",
            "script": "exec_report.py --weekly",
            "description": "Weekly executive report (Sun 8 PM)"
        }
    }

    @staticmethod
    def list_jobs():
        """List all Phase 1 cron jobs"""
        print("\n" + "=" * 80)
        print("PHASE 1 CRON JOBS")
        print("=" * 80)
        for job_id, job in CronSimulator.JOBS.items():
            print(f"\n{job_id}:")
            print(f"  Time: {job['time']} IST")
            print(f"  Script: {job['script']}")
            print(f"  {job['description']}")

    @staticmethod
    def simulate_entry(test_vix=None, test_nifty=None):
        """Simulate entry gate at 9:30 AM"""
        logger.info("=" * 80)
        logger.info("SIMULATING: 9:30 AM ENTRY GATE")
        logger.info("=" * 80)

        # Set mock mode if test values provided
        if test_vix is not None or test_nifty is not None:
            os.environ["ANTARIKSH_MOCK_MODE"] = "1"
            if test_vix is not None:
                os.environ["ANTARIKSH_MOCK_VIX"] = str(test_vix)
            if test_nifty is not None:
                os.environ["ANTARIKSH_MOCK_NIFTY"] = str(test_nifty)

        # Import after setting env vars
        from session_orchestrator import SessionOrchestrator
        SessionOrchestrator.run_entry_session()

    @staticmethod
    def simulate_exit():
        """Simulate exit at 2:35 PM"""
        logger.info("=" * 80)
        logger.info("SIMULATING: 2:35 PM EXIT")
        logger.info("=" * 80)

        from session_orchestrator import SessionOrchestrator
        SessionOrchestrator.run_exit_session()

    @staticmethod
    def simulate_full_day(vix=18.5, nifty=24500.0):
        """Simulate a full trading day (entry + exit)"""
        logger.info("=" * 80)
        logger.info(f"SIMULATING: FULL TRADING DAY (VIX={vix}, NIFTY={nifty:.0f})")
        logger.info("=" * 80)

        # Enable mock mode
        os.environ["ANTARIKSH_MOCK_MODE"] = "1"
        os.environ["ANTARIKSH_MOCK_VIX"] = str(vix)
        os.environ["ANTARIKSH_MOCK_NIFTY"] = str(nifty)
        os.environ["ANTARIKSH_MOCK_TIME"] = "10:30"  # Within entry window

        print("\n" + "🟢 " * 40 + "\n")
        logger.info("STEP 1: Entry Gate (9:30 AM)")
        print("🟢 " * 40 + "\n")
        CronSimulator.simulate_entry()

        print("\n" + "🔴 " * 40 + "\n")
        logger.info("STEP 2: Exit (2:35 PM)")
        print("🔴 " * 40 + "\n")
        CronSimulator.simulate_exit()

        print("\n" + "✅ " * 40 + "\n")
        logger.info("FULL DAY SIMULATION COMPLETE")

def main():
    parser = argparse.ArgumentParser(description="Phase 1 cron job simulator")
    parser.add_argument("command", choices=["list", "entry", "exit", "full-day"],
                       help="Command to run")
    parser.add_argument("--vix", type=float, help="Mock VIX value (for mock mode)")
    parser.add_argument("--nifty", type=float, help="Mock NIFTY spot (for mock mode)")
    args = parser.parse_args()

    if args.command == "list":
        CronSimulator.list_jobs()
    elif args.command == "entry":
        CronSimulator.simulate_entry(test_vix=args.vix, test_nifty=args.nifty)
    elif args.command == "exit":
        CronSimulator.simulate_exit()
    elif args.command == "full-day":
        vix = args.vix or 18.5
        nifty = args.nifty or 24500.0
        CronSimulator.simulate_full_day(vix=vix, nifty=nifty)

if __name__ == "__main__":
    main()
