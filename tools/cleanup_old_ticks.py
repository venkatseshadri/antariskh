#!/usr/bin/env python3
"""Clean old bars from live SQLite capture files (>7 days).

EOD ETL archives daily slices to DuckDB warehouse. This script reclaims
disk space by deleting bars older than 7 days from the live SQLite files.
Chunked DELETE (10K rows/commit) keeps lock duration <100ms.

Cron: 50 23 * * 1-5  (after MCX close, before next-day open)

Usage:
    python tools/cleanup_old_ticks.py
    python tools/cleanup_old_ticks.py --days 14  # custom retention
"""

import argparse
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.sqlite_schema import get_sqlite_capture_path

INSTRUMENTS = ["NIFTY", "SENSEX", "MCX"]
TABLES = ["market_data", "market_data_multitf", "market_data_enriched"]
CHUNK_SIZE = 10_000


def cleanup_instrument(instrument: str, cutoff_date: str) -> dict[str, int]:
    path = get_sqlite_capture_path(instrument)
    if not path.exists():
        print(f"[{instrument}] {path} not found — skipping")
        return {}

    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA busy_timeout=5000")
    deleted = {}

    for table in TABLES:
        try:
            conn.execute(f"SELECT 1 FROM {table} LIMIT 0")
        except sqlite3.OperationalError:
            continue

        total = 0
        while True:
            cur = conn.execute(
                f"DELETE FROM {table} WHERE rowid IN "
                f"(SELECT rowid FROM {table} "
                f" WHERE substr(timestamp, 1, 10) < ? LIMIT ?)",
                (cutoff_date, CHUNK_SIZE),
            )
            batch = cur.rowcount
            conn.commit()
            total += batch
            if batch < CHUNK_SIZE:
                break

        if total > 0:
            deleted[table] = total

    conn.close()
    return deleted


def main():
    parser = argparse.ArgumentParser(description="Clean old bars from live SQLite")
    parser.add_argument(
        "--days", type=int, default=7, help="Retention days (default: 7)"
    )
    args = parser.parse_args()

    cutoff = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")
    print(f"Cleaning bars older than {cutoff} ({args.days} days)")

    for inst in INSTRUMENTS:
        deleted = cleanup_instrument(inst, cutoff)
        if deleted:
            parts = ", ".join(f"{v} from {k}" for k, v in deleted.items())
            print(f"[{inst}] Deleted {parts}")
        else:
            print(f"[{inst}] Nothing to clean")


if __name__ == "__main__":
    main()
