#!/usr/bin/env python3
"""
Rebuild EMA state fresh from v3.1 data
Resets the EMA files and rebuilds them from scratch

Usage:
    python3 rebuild_ema_from_v3.py
"""

import sys
import json
from pathlib import Path
from datetime import datetime
import duckdb

sys.path.insert(0, str(Path(__file__).parent.parent / "brahmand"))

from ema_aggregator import (
    reset_ema, seed_ema, PERIODS, TIMEFRAMES,
    _state_file, MULTIPLIERS
)

V31_DB = "/home/trading_ceo/python-trader/varaha/data/varaha_data.duckdb"
EMA_BASE_DIR = Path("/home/trading_ceo/brahmand/data/ema_state")

def rebuild_ema_1min():
    """Rebuild 1-min EMA state from v3.1 data."""
    print("=== REBUILDING 1-MIN EMA ===\n")

    # Connect to v3.1
    conn = duckdb.connect(V31_DB, read_only=True)

    # Get all 1-min bars for today
    bars = conn.execute("""
        SELECT spot FROM market_data
        WHERE index_name = 'NIFTY' AND DATE(timestamp) = '2026-05-20'
        ORDER BY timestamp ASC
    """).fetchall()

    closes = [b[0] for b in bars]
    print(f"📊 Got {len(closes)} close prices from V3.1\n")

    # Reset 1-min EMA
    print("Resetting 1-min EMA state...")
    reset_ema("1min")

    # Seed with historical data (use closes as seed)
    print("Seeding 1-min EMA with today's data...")
    for period in PERIODS:
        state = {
            "tf": "1min",
            "period": period,
            "ema_value": None,
            "available": False,
            "status": "not_enough_data",
            "last_bars": closes[:period],
            "buffer_count": len(closes[:period]),
            "multiplier": MULTIPLIERS[period],
            "threshold_crossed_at": None,
            "timestamp": datetime.now().isoformat(),
        }

        # Calculate initial EMA if we have enough bars
        if len(closes) >= period:
            state["ema_value"] = round(sum(closes[:period]) / period, 4)
            state["available"] = True
            state["status"] = "ready"
            state["threshold_crossed_at"] = datetime.now().isoformat()

            # Update with remaining bars
            for close in closes[period:]:
                state["last_bars"].append(close)
                if len(state["last_bars"]) > period:
                    state["last_bars"].pop(0)

                # EMA calculation: EMA = (Close - EMA(prev)) * Multiplier + EMA(prev)
                state["ema_value"] = round(
                    (close - state["ema_value"]) * state["multiplier"] + state["ema_value"],
                    4
                )

        # Write state file
        state_file = _state_file("1min", period)
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps(state, indent=2))

        print(f"  ✓ EMA-{period}: {state['ema_value']} (available: {state['available']})")

    conn.close()
    print(f"\n✅ 1-min EMA rebuilt\n")

if __name__ == "__main__":
    rebuild_ema_1min()
    print("✅ EMA state rebuilt with fresh timestamps")
    print("   Multi-TF EMAs will be updated when v4 runs tomorrow")
