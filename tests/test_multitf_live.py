#!/usr/bin/env python3
"""DAMBUILDER: file-watch test of multitf_enricher --live.

Sandbox SQLite + log file: write a 1-min bar to the log, assert the
live loop backfills indicator columns for all TFs. No Redis, no prod.
"""

import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SANDBOX = ROOT / "tests" / "fixtures" / "multitf_live_sandbox"


def _make_db(db: Path, n_bars: int = 40) -> str:
    conn = sqlite3.connect(db)
    # Create market_data (1-min table) + market_data_multitf
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS market_data (
            timestamp TEXT, instrument TEXT, open REAL, high REAL,
            low REAL, close REAL, volume REAL, ltp REAL, source TEXT,
            PRIMARY KEY (timestamp, instrument)
        );
        CREATE TABLE IF NOT EXISTS market_data_multitf (
            timestamp TEXT, instrument TEXT, timeframe_min INTEGER,
            open REAL, high REAL, low REAL, close REAL, volume REAL,
            ema5 REAL, ema20 REAL, ema50 REAL, ema100 REAL, ema200 REAL,
            sma20 REAL, sma50 REAL, sma200 REAL, rsi REAL, atr REAL,
            macd REAL, macd_signal REAL, macd_histogram REAL, adx REAL,
            di_plus REAL, di_minus REAL, bb_upper REAL, bb_middle REAL,
            bb_lower REAL, obv REAL, cmf REAL, cci REAL, st_consensus TEXT,
            PRIMARY KEY (timestamp, instrument, timeframe_min)
        );
    """)
    day = "2026-06-10"
    px = 25000.0
    last_ts = None
    # Seed 1-min bars so enrich_tf has context
    for i in range(40):
        ts = f"{day}T{9 + (15 + i) // 60:02d}:{(15 + i) % 60:02d}:00"
        px += (-1) ** i * 7 + (i % 5)
        conn.execute(
            "INSERT OR REPLACE INTO market_data (timestamp, instrument, open, high, low, close, volume, ltp, source) "
            "VALUES (?,?,?,?,?,?,?,?,'feed')",
            (ts, "NIFTY", px - 3, px + 5, px - 6, px, 1000 + i, px),
        )
        last_ts = ts
    # Also seed market_data_multitf for 5m OHLCV (consumer had written these)
    for i in range(0, n_bars):
        ts_5m = f"{day}T{9 + (15 + i * 5) // 60:02d}:{(15 + i * 5) % 60:02d}:00"
        conn.execute(
            "INSERT OR REPLACE INTO market_data_multitf (timestamp, instrument, timeframe_min, "
            "open, high, low, close, volume) VALUES (?,?,?,?,?,?,?,?)",
            (ts_5m, "NIFTY", 5, px - 10, px + 20, px - 15, px, 5000),
        )
    conn.commit()
    conn.close()
    return last_ts


def main() -> int:
    if SANDBOX.exists():
        shutil.rmtree(SANDBOX)
    for sub in ("data", "live", "logs"):
        (SANDBOX / sub).mkdir(parents=True)
    db = SANDBOX / "data" / "capture_nifty.sqlite"
    last_ts = _make_db(db)

    # Write one new bar to the log file (simulates feed.py write)
    log_file = SANDBOX / "live" / "NIFTY_1min.log"
    log_file.write_text(f"{last_ts}|NIFTY|25000.0|25010.0|24990.0|25005.0|1000\n")

    env = {
        **os.environ,
        "SIM_MODE": "1",
        "CAPTURE_SQLITE": str(db),
        "LIVE_DIR": str(SANDBOX / "live"),
    }
    proc = subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "enrichers/multitf_enricher.py"),
            "--instrument",
            "NIFTY",
            "--live",
            "--db",
            str(db),
        ],
        cwd=ROOT,
        env=env,
        stdout=open(SANDBOX / "logs/live.out", "w"),
        stderr=subprocess.STDOUT,
    )

    failures = []
    try:
        deadline = time.time() + 20
        filled = 0
        hb_ok = False
        while time.time() < deadline:
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            filled = conn.execute(
                "SELECT COUNT(*) FROM market_data_multitf "
                "WHERE timeframe_min=5 AND rsi IS NOT NULL"
            ).fetchone()[0]
            conn.close()
            hb = SANDBOX / "live" / "multitf_enricher_NIFTY.heartbeat"
            if hb.exists() and filled > 0:
                hb_ok = True
                break
            time.sleep(1)

        if filled == 0:
            failures.append("indicator columns not filled")
        if not hb_ok:
            failures.append("heartbeat file missing or enrichment incomplete")
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        st = conn.execute(
            "SELECT st_consensus FROM market_data_multitf "
            "WHERE timeframe_min=5 AND st_consensus IS NOT NULL "
            "ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        if st and st[0] not in ("BULLISH", "BEARISH", "NEUTRAL"):
            failures.append(f"st_consensus bad value: {st[0]}")
        conn.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    if failures:
        for f in failures:
            print(f"  FAIL: {f}")
        out = SANDBOX / "logs" / "live.out"
        if out.exists():
            print(out.read_text()[-2000:])
        return 1

    print(f"  OK multitf-live: {filled} rows enriched, heartbeat present")
    shutil.rmtree(SANDBOX, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
