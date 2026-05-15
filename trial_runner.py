#!/usr/bin/env python3
"""
Trial Run v1 Scheduler — Cron-driven deterministic pipeline.
No LLM. No API key. Reads DuckDB for market data, paper trades only.

Entry (10:30 AM): scan → plan → risk → execute
Exit  (14:35 PM): monitor → audit
"""

import os
import sys
import logging
from datetime import datetime as _dt
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.pop("ANTARIKSH_MOCK_MODE", None)

from crew_structure import (
    scan_market,
    generate_trade_plan,
    check_risk,
    execute_trade,
    monitor_positions,
    log_audit,
    market_state,
)

LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | TRIAL | %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "trial_runner.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("TrialRunner")


def run_entry():
    """10:30 AM: Entry session — scan, plan, risk, execute."""
    now = _dt.now().strftime("%H:%M")
    logger.info("=" * 60)
    logger.info(f"TRIAL ENTRY SESSION — {now}")
    logger.info("=" * 60)

    scan_market.run()
    vix = market_state.get("vix", 0)
    nifty = market_state.get("nifty_spot", 0)
    regime = market_state.get("regime", "UNKNOWN")
    gate = market_state.get("gate_pass", False)
    logger.info(f"[1/4] scan: VIX={vix} NIFTY={nifty} Regime={regime} gate={gate}")

    generate_trade_plan.run()
    plan = market_state.get("trade_plan")
    logger.info(f"[2/4] plan: {'generated' if plan else 'skipped'}")

    check_risk.run()
    risk_ok = market_state.get("risk_ok", True)
    halt = market_state.get("halt", False)
    logger.info(f"[3/4] risk: ok={risk_ok} halt={halt}")

    if halt or not risk_ok:
        logger.info(f"[4/4] execute: SKIPPED (halt={halt} risk={risk_ok})")
    else:
        execute_trade.run()
        legs = len(market_state.get("positions", {}).get("legs", []))
        logger.info(f"[4/4] execute: {legs} legs placed")

    logger.info("=" * 60)
    logger.info(
        f"ENTRY COMPLETE: gate={gate} plan={'yes' if plan else 'no'} risk_ok={risk_ok}"
    )
    logger.info("=" * 60)

    return {"gate_pass": gate, "has_plan": plan is not None, "risk_ok": risk_ok}


def run_exit():
    """14:35 PM: Exit session — monitor P&L, audit log."""
    now = _dt.now().strftime("%H:%M")
    logger.info("=" * 60)
    logger.info(f"TRIAL EXIT SESSION — {now}")
    logger.info("=" * 60)

    monitor_positions.run()
    pnl = market_state.get("session_pnl", 0.0)
    logger.info(f"[1/2] monitor: P&L=₹{pnl}")

    log_audit.run()
    mtd = market_state.get("mtd_pnl", 0.0)
    logger.info(f"[2/2] audit: MTD=₹{mtd}")

    logger.info("=" * 60)
    logger.info(f"EXIT COMPLETE: session_pnl=₹{pnl} mtd_pnl=₹{mtd}")
    logger.info("=" * 60)

    return {"session_pnl": pnl, "mtd_pnl": mtd}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Trial Run v1 Scheduler")
    parser.add_argument("--entry", action="store_true", help="Run entry session")
    parser.add_argument("--exit", action="store_true", help="Run exit session")
    parser.add_argument(
        "--full", action="store_true", help="Run full session (entry + exit)"
    )
    args = parser.parse_args()

    if args.full:
        entry = run_entry()
        exit_result = run_exit()
        print(
            f"\nTrial: entry_gate={entry['gate_pass']} exit_pnl=₹{exit_result['session_pnl']}"
        )
    elif args.exit:
        run_exit()
    else:
        run_entry()
