#!/usr/bin/env python3
"""
Seed synthetic JSONL history for scenario tests.
"""

import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import List


def seed_jsonl(log_dir: Path, days_back: int, pnl_per_day: List[float]):
    """Write N days of synthetic JSONL files matching cfo_audit_*.jsonl schema."""
    log_dir.mkdir(parents=True, exist_ok=True)

    for i in range(days_back):
        date = (datetime.now() - timedelta(days=i + 1)).strftime("%Y-%m-%d")
        pnl = pnl_per_day[i] if i < len(pnl_per_day) else 0.0
        log_file = log_dir / f"cfo_audit_{date}.jsonl"

        entry = {
            "timestamp": f"{date}T10:30:00",
            "session_id": f"{date.replace('-', '')}_103000",
            "gate_pass": True,
            "trade_plan": {
                "instrument": "NIFTY",
                "atm_strike": 24500.0,
                "expiry": f"{date}",
                "lots": 1,
                "wing_width": 300,
                "target_profit": 1000,
                "max_loss": 3500,
            },
            "backtest_result": {"pnl_inr": pnl},
            "cfo_verdict": {
                "passed": pnl > -3500,
                "checks": {},
                "violations": [],
                "recommendations": [],
                "mtd_pnl": pnl,
                "summary": "PASS" if pnl > -3500 else "FAIL",
            },
            "capital_impact": {
                "gross_pnl": pnl,
                "brokerage_est": 50,
                "net_pnl": pnl - 50,
                "free_cash_after": 100000 + pnl - 50,
            },
        }
        with open(log_file, "w") as f:
            f.write(json.dumps(entry) + "\n")


def seed_consecutive_losses(log_dir: Path, count: int, sl_amount: float = 3500):
    """Write N consecutive SL-hit days."""
    log_dir.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        date = (datetime.now() - timedelta(days=i + 1)).strftime("%Y-%m-%d")
        log_file = log_dir / f"cfo_audit_{date}.jsonl"
        entry = {
            "timestamp": f"{date}T10:30:00",
            "session_id": f"{date.replace('-', '')}_103000",
            "gate_pass": True,
            "trade_plan": {},
            "backtest_result": {"pnl_inr": -sl_amount},
            "cfo_verdict": {
                "passed": False,
                "checks": {},
                "violations": [f"Daily SL {sl_amount} breached"],
                "recommendations": ["Halt trading"],
                "mtd_pnl": -sl_amount * (count - i),
                "summary": "FAIL",
            },
            "capital_impact": {
                "gross_pnl": -sl_amount,
                "brokerage_est": 50,
                "net_pnl": -sl_amount - 50,
                "free_cash_after": 100000 - sl_amount * (count - i) - 50,
            },
        }
        with open(log_file, "w") as f:
            f.write(json.dumps(entry) + "\n")


def seed_30day_dd_at_threshold(log_dir: Path, target_mtd: float = -26500):
    """Write 28 days summing to approximately target_mtd."""
    log_dir.mkdir(parents=True, exist_ok=True)
    daily = target_mtd / 28.0
    for i in range(28):
        date = (datetime.now() - timedelta(days=i + 1)).strftime("%Y-%m-%d")
        log_file = log_dir / f"cfo_audit_{date}.jsonl"
        entry = {
            "timestamp": f"{date}T10:30:00",
            "session_id": f"{date.replace('-', '')}_103000",
            "gate_pass": True,
            "trade_plan": {},
            "backtest_result": {"pnl_inr": daily},
            "cfo_verdict": {
                "passed": True,
                "checks": {},
                "violations": [],
                "recommendations": [],
                "mtd_pnl": daily * (i + 1),
                "summary": "PASS",
            },
            "capital_impact": {
                "gross_pnl": daily,
                "brokerage_est": 50,
                "net_pnl": daily - 50,
                "free_cash_after": 100000 + daily * (i + 1) - 50,
            },
        }
        with open(log_file, "w") as f:
            f.write(json.dumps(entry) + "\n")
