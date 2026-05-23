#!/usr/bin/env python3
"""
One-time EMA state backfill: Update EMA files from v3.1 data
Updates the EMA rolling buffers as if v4 had processed the data live

Usage:
    python3 backfill_ema_from_v3.py
"""

import sys
from pathlib import Path
from datetime import datetime
import duckdb

sys.path.insert(0, str(Path(__file__).parent.parent / "brahmand"))

from ema_aggregator import update_ema, get_ema_status, TIMEFRAMES, PERIODS

V31_DB = "/home/trading_ceo/python-trader/varaha/data/varaha_data.duckdb"

def backfill_ema():
    """Process all v3.1 bars through EMA updater to populate state files."""
    print("=== EMA STATE BACKFILL ===\n")

    # Connect to v3.1 database
    conn = duckdb.connect(V31_DB, read_only=True)

    # Get all 1-min bars from v3.1 for today (May 20)
    bars = conn.execute("""
        SELECT timestamp, spot
        FROM market_data
        WHERE index_name = 'NIFTY' AND DATE(timestamp) = '2026-05-20'
        ORDER BY timestamp ASC
    """).fetchall()

    print(f"📊 Processing {len(bars)} 1-min bars from V3.1...\n")

    # Feed each bar to the EMA aggregator (1-min only, 5-min will auto-aggregate)
    success_count = 0
    error_count = 0

    for timestamp, close_price in bars:
        try:
            # Update 1-min EMA
            update_ema(close=float(close_price), tf="1min", periods=PERIODS)
            success_count += 1

            # Print progress every 50 bars
            if success_count % 50 == 0:
                print(f"  ✓ Processed {success_count} bars...")

        except Exception as e:
            error_count += 1
            print(f"  ✗ Bar {timestamp}: {e}")

    print(f"\n✅ Feed complete: {success_count} bars processed, {error_count} errors\n")

    # Show status of EMA files
    print("📈 EMA State Status:\n")

    for tf in TIMEFRAMES:
        print(f"  {tf:8}:", end=" ")
        status_dict = get_ema_status(tf)

        periods_ready = sum(1 for p in PERIODS if status_dict.get(p, {}).get('available'))
        print(f"{periods_ready}/{len(PERIODS)} periods ready")

    print(f"\n✅ BACKFILL COMPLETE")
    print(f"Next: v4 will process queue to update multi-TF EMAs")

    conn.close()

if __name__ == "__main__":
    backfill_ema()
