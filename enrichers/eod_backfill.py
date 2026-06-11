#!/usr/bin/env python3
"""EOD multi-TF backfill. Recomputes the day's 6-TF rows from 1-min
market_data into market_data_multitf (EMA columns included) + parquet export.

Usage:
  python3 enrichers/eod_backfill.py --date 2026-06-11 --instrument NIFTY
  python3 enrichers/eod_backfill.py --date 2026-06-11 --both

Cron line (install by validator):
  # insert into crontab once validated
"""

import argparse
import os
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from enrichers.multitf_recompute import (
    load_1min_bars,
    aggregate_1min_to_tf,
    compute_row_indicators,
    heal,
    recompute_and_diff as _diff,
)
from enrichers.multitf_enricher import _open, _write_indicators, TIMEFRAMES, IND_COLS
from config.sqlite_schema import get_sqlite_capture_path
from research.export_parquet import export_date


def backfill_date(instrument: str, date: str):
    db_path = str(get_sqlite_capture_path(instrument))
    print(f"[eod_backfill] {instrument} {date}")

    # 1. Heal (recompute indicators from 1-min bars, write to market_data_multitf)
    n = heal(db_path, instrument, date)
    if n == 0:
        print(f"  WARNING: 0 rows healed — check 1-min data for {date}")
    else:
        # Verify per-TF row counts
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        for tf in TIMEFRAMES:
            cnt = conn.execute(
                "SELECT COUNT(*) FROM market_data_multitf "
                "WHERE instrument=? AND timeframe_min=? AND substr(timestamp,1,10)=?",
                (instrument, tf, date),
            ).fetchone()[0]
            print(f"  TF {tf:>4}m: {cnt} rows")
        conn.close()

    # 2. Export to parquet
    export_date(instrument, date)
    print(f"  Parquet exported")


def main():
    ap = argparse.ArgumentParser(description="EOD multi-TF backfill + parquet export")
    ap.add_argument("--date", required=True, help="YYYY-MM-DD")
    ap.add_argument("--instrument", default="NIFTY", choices=["NIFTY", "SENSEX", "MCX"])
    ap.add_argument("--both", action="store_true", help="backfill both NIFTY + SENSEX")
    args = ap.parse_args()

    instruments = ["NIFTY", "SENSEX"] if args.both else [args.instrument]
    for inst in instruments:
        backfill_date(inst, args.date)


if __name__ == "__main__":
    main()
