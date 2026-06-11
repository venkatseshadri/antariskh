#!/usr/bin/env python3
"""DAMBUILDER Phase A: hermetic test of multitf_enricher --live.

Sandbox SQLite + test Redis (6380): publish a closed-TF-bar message, assert the
live loop fills the indicator columns for that TF's day. No prod touch.
"""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SANDBOX = ROOT / "tests" / "fixtures" / "multitf_live_sandbox"
REDIS_PORT = "6380"


def _make_db(db: Path, n_bars: int = 40) -> str:
    conn = sqlite3.connect(db)
    src = sqlite3.connect("/home/trading_ceo/python-trader/varaha/data/capture_nifty.sqlite")
    schema = src.execute(
        "SELECT sql FROM sqlite_master WHERE name='market_data_multitf'"
    ).fetchone()[0]
    src.close()
    conn.execute(schema)
    day = "2026-06-10"
    px = 25000.0
    last_ts = None
    for i in range(n_bars):
        ts = f"{day} {9 + (15 + i * 5) // 60:02d}:{(15 + i * 5) % 60:02d}:00"
        px += (-1) ** i * 7 + (i % 5)
        conn.execute(
            "INSERT INTO market_data_multitf (timestamp, instrument, timeframe_min, "
            "open, high, low, close, volume) VALUES (?,?,?,?,?,?,?,?)",
            (ts, "NIFTY", 5, px - 3, px + 5, px - 6, px, 1000 + i),
        )
        last_ts = ts
    conn.commit()
    conn.close()
    return last_ts


def main() -> int:
    if SANDBOX.exists():
        shutil.rmtree(SANDBOX)
    for sub in ("data", "logs", "redis"):
        (SANDBOX / sub).mkdir(parents=True)
    db = SANDBOX / "data" / "capture_nifty.sqlite"
    last_ts = _make_db(db)

    subprocess.run(["bash", str(ROOT / "sim/start_test_redis.sh"), "start",
                    str(SANDBOX), REDIS_PORT], check=True, capture_output=True)
    env = {**os.environ, "SIM_MODE": "1", "SIM_ROOT": str(SANDBOX),
           "SIM_REDIS_PORT": REDIS_PORT}
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "enrichers/multitf_enricher.py"),
         "--instrument", "NIFTY", "--live", "--db", str(db)],
        cwd=ROOT, env=env,
        stdout=open(SANDBOX / "logs/live.out", "w"), stderr=subprocess.STDOUT,
    )
    failures = []
    try:
        time.sleep(2.5)  # subscribe settle
        import redis as rds

        r = rds.Redis(host="localhost", port=int(REDIS_PORT), decode_responses=True)
        bar = {"timestamp": last_ts, "instrument": "NIFTY", "timeframe_min": 5,
               "open": 25000, "high": 25010, "low": 24990, "close": 25005}
        n_subs = r.publish("bars:NIFTY:5", json.dumps(bar))
        if n_subs < 1:
            failures.append("live loop not subscribed to bars:NIFTY:5")
        deadline = time.time() + 15
        filled = 0
        while time.time() < deadline:
            conn = sqlite3.connect(db)
            filled = conn.execute(
                "SELECT COUNT(*) FROM market_data_multitf "
                "WHERE timeframe_min=5 AND rsi IS NOT NULL"
            ).fetchone()[0]
            hb = r.get("multitf_enricher:NIFTY:heartbeat")
            conn.close()
            if filled > 0 and hb:
                break
            time.sleep(1)
        if filled == 0:
            failures.append("indicator columns not filled after publish")
        if not r.get("multitf_enricher:NIFTY:heartbeat"):
            failures.append("heartbeat key missing")
        st = sqlite3.connect(db).execute(
            "SELECT st_consensus FROM market_data_multitf WHERE timeframe_min=5 "
            "AND st_consensus IS NOT NULL ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        if st and st[0] not in ("BULLISH", "BEARISH", "NEUTRAL"):
            failures.append(f"st_consensus bad value: {st[0]}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        subprocess.run(["bash", str(ROOT / "sim/start_test_redis.sh"), "stop",
                        str(SANDBOX), REDIS_PORT], capture_output=True)

    if failures:
        for f in failures:
            print(f"  FAIL: {f}")
        print((SANDBOX / "logs/live.out").read_text()[-1500:])
        return 1
    print(f"  OK multitf-live: {filled} rows enriched, heartbeat present")
    shutil.rmtree(SANDBOX, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
