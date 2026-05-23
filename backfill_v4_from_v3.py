#!/usr/bin/env python3
"""
One-time backfill: Fill v4 database with missing bars from v3.1
Backfills the gap: v3.1 has bars until 15:29, v4 only has until 15:26

Usage:
    python3 backfill_v4_from_v3.py [--index NIFTY|SENSEX]
"""

import duckdb
import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict

V31_DB = "/home/trading_ceo/python-trader/varaha/data/varaha_data.duckdb"
V4_DB = "/home/trading_ceo/python-trader/varaha/data/market_data_multitf.duckdb"

def get_latest_timestamp(conn, index_name, timeframe_min):
    """Get the latest timestamp for a given index+timeframe in v4."""
    result = conn.execute(f"""
        SELECT MAX(timestamp) FROM market_data_multitf
        WHERE index_name = '{index_name}' AND timeframe_min = {timeframe_min}
    """).fetchone()
    return result[0] if result[0] else None

def get_missing_bars(v31_conn, v4_conn, index_name, last_timestamp):
    """Get all bars from v3.1 AFTER the last v4 bar."""
    if not last_timestamp:
        # If v4 is empty, get all bars from v3.1
        query = f"""
            SELECT timestamp, index_name, spot, spot, spot, spot, 0
            FROM market_data
            WHERE index_name = '{index_name}' AND DATE(timestamp) = CURRENT_DATE()
            ORDER BY timestamp ASC
        """
    else:
        query = f"""
            SELECT timestamp, index_name, spot, spot, spot, spot, 0
            FROM market_data
            WHERE index_name = '{index_name}'
              AND timestamp > '{last_timestamp}'
            ORDER BY timestamp ASC
        """

    return v31_conn.execute(query).fetchall()

def aggregate_bars(bars, timeframe_min):
    """Aggregate 1-min bars to a specific timeframe."""
    if not bars:
        return []

    aggregated = []
    current_bucket = []
    current_time = None

    for bar in bars:
        timestamp, index, o, h, l, c, v = bar
        bar_dt = datetime.fromisoformat(timestamp)

        # Calculate bucket start time
        minute = bar_dt.minute
        bucket_minute = (minute // timeframe_min) * timeframe_min
        bucket_start = bar_dt.replace(minute=bucket_minute, second=0, microsecond=0)

        if current_time is None:
            current_time = bucket_start

        if bucket_start != current_time:
            # New bucket - finalize previous
            if current_bucket:
                agg_bar = {
                    "timestamp": current_time.isoformat(),
                    "index_name": index,
                    "open": current_bucket[0][3],
                    "high": max(b[4] for b in current_bucket),
                    "low": min(b[5] for b in current_bucket),
                    "close": current_bucket[-1][5],
                    "volume": sum(b[6] for b in current_bucket)
                }
                aggregated.append(agg_bar)

            current_bucket = [bar]
            current_time = bucket_start
        else:
            current_bucket.append(bar)

    # Final bucket
    if current_bucket:
        agg_bar = {
            "timestamp": current_time.isoformat(),
            "index_name": current_bucket[0][1],
            "open": current_bucket[0][3],
            "high": max(b[4] for b in current_bucket),
            "low": min(b[5] for b in current_bucket),
            "close": current_bucket[-1][5],
            "volume": sum(b[6] for b in current_bucket)
        }
        aggregated.append(agg_bar)

    return aggregated

def write_to_v4(v4_conn, bars, index_name, timeframe_min):
    """Write aggregated bars to v4 database."""
    if not bars:
        return 0

    count = 0
    for bar in bars:
        try:
            v4_conn.execute(f"""
                INSERT INTO market_data_multitf
                (timestamp, index_name, timeframe_min, open, high, low, close, volume,
                 sma20, sma50, sma200, rsi, atr, macd, macd_signal, macd_histogram,
                 adx, di_plus, di_minus, bb_upper, bb_middle, bb_lower, obv, cmf, cci, st_consensus)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
                        NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL)
                ON CONFLICT (timestamp, index_name, timeframe_min) DO UPDATE SET
                    open = EXCLUDED.open,
                    high = EXCLUDED.high,
                    low = EXCLUDED.low,
                    close = EXCLUDED.close,
                    volume = EXCLUDED.volume
            """, (bar["timestamp"], bar["index_name"], timeframe_min,
                  bar["open"], bar["high"], bar["low"], bar["close"], bar["volume"]))
            count += 1
        except Exception as e:
            print(f"  Error writing bar {bar['timestamp']}: {e}")

    return count

def backfill(index_name="NIFTY"):
    """Backfill v4 database from v3.1 for missing bars."""
    print(f"=== BACKFILLING {index_name} ===\n")

    # Connect to databases
    v31_conn = duckdb.connect(V31_DB, read_only=True)
    v4_conn = duckdb.connect(V4_DB, read_only=False)

    timeframes = [5, 15, 30, 60, 240, 1440]
    total_written = 0

    for tf in timeframes:
        print(f"Processing {tf}-min timeframe...")

        # Get last timestamp in v4 for this timeframe
        last_ts = get_latest_timestamp(v4_conn, index_name, tf)
        print(f"  Last v4 bar: {last_ts or 'None (empty)'}")

        # Get missing bars from v3.1
        missing = get_missing_bars(v31_conn, v4_conn, index_name, last_ts)
        print(f"  Missing 1-min bars in v3.1: {len(missing)}")

        if missing:
            # Aggregate to timeframe
            agg_bars = aggregate_bars(missing, tf)
            print(f"  Aggregated to {len(agg_bars)} {tf}-min bars")

            # Write to v4
            written = write_to_v4(v4_conn, agg_bars, index_name, tf)
            print(f"  ✅ Written: {written} bars")
            total_written += written
        else:
            print(f"  ✓ No missing bars")

        print()

    v4_conn.close()
    v31_conn.close()

    print(f"\n{'='*50}")
    print(f"✅ BACKFILL COMPLETE: {total_written} bars written to v4")
    print(f"{'='*50}")

if __name__ == "__main__":
    index = sys.argv[1] if len(sys.argv) > 1 else "NIFTY"
    backfill(index)
