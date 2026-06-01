#!/usr/bin/env python3
"""EOD ETL: dump Project Penguin SQLite capture to DuckDB research warehouse.

Runs daily after market close via cron. Reads live SQLite via sqlite_scanner
(WAL allows concurrent reads — consumer keeps running). Writes immutable
DuckDB files to research/{YYYY-MM-DD}/{instrument}.duckdb.

Usage:
    python tools/eod_etl.py --instrument NIFTY
    python tools/eod_etl.py --instrument SENSEX
    python tools/eod_etl.py --instrument MCX
    python tools/eod_etl.py --exchange NSE,BSE
    python tools/eod_etl.py --exchange MCX
    python tools/eod_etl.py --all
"""

import argparse
import sys
import duckdb
from pathlib import Path
from datetime import date

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT.parent / "python-trader" / "varaha" / "data"
RESEARCH_DIR = PROJECT_ROOT.parent / "research"

INSTRUMENTS = {
    "NIFTY": DATA_DIR / "capture_nifty.sqlite",
    "SENSEX": DATA_DIR / "capture_sensex.sqlite",
    "MCX": DATA_DIR / "capture_mcx.sqlite",
}

EXCHANGE_TO_INSTRUMENTS = {
    "NSE": ["NIFTY"],
    "BSE": ["SENSEX"],
    "MCX": ["MCX"],
}

TABLES = ["market_data", "market_data_multitf", "market_data_enriched"]


def _table_exists(src_abs: str, table: str) -> bool:
    try:
        con = duckdb.connect(":memory:")
        con.execute("INSTALL sqlite_scanner; LOAD sqlite_scanner;")
        con.execute(f"SELECT 1 FROM sqlite_scan('{src_abs}', '{table}') LIMIT 0")
        con.close()
        return True
    except Exception:
        return False


def run_etl(instrument: str, target_date: str | None = None) -> str:
    src = INSTRUMENTS[instrument]
    if not src.exists():
        raise FileNotFoundError(f"Source not found: {src}")

    day = target_date or date.today().isoformat()
    dest_dir = RESEARCH_DIR / day
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{instrument.lower()}.duckdb"

    if dest.exists():
        print(f"[{instrument}] {dest} already exists — skipping")
        return str(dest)

    src_abs = str(src.resolve())
    dest_abs = str(dest.resolve())

    con = duckdb.connect(dest_abs)
    con.execute("INSTALL sqlite_scanner; LOAD sqlite_scanner;")

    row_counts = {}
    for table in TABLES:
        if not _table_exists(src_abs, table):
            continue
        if table == "market_data":
            con.execute(
                f"CREATE TABLE market_data AS "
                f"SELECT "
                f"  timestamp, "
                f"  substr(timestamp, 1, 10) AS date, "
                f"  instrument AS index_name, "
                f"  open   AS open_price, "
                f"  close  AS spot, "
                f"  high   AS intraday_high, "
                f"  low    AS intraday_low, "
                f"  volume "
                f"FROM sqlite_scan('{src_abs}', 'market_data') "
                f"WHERE substr(timestamp, 1, 10) = '{day}'"
            )
        elif table == "market_data_multitf":
            con.execute(
                f"CREATE TABLE market_data_multitf AS "
                f"SELECT *, instrument AS index_name "
                f"FROM sqlite_scan('{src_abs}', 'market_data_multitf') "
                f"WHERE substr(timestamp, 1, 10) = '{day}'"
            )
        elif table == "market_data_enriched":
            con.execute(
                f"CREATE TABLE market_data_enriched AS "
                f"SELECT * "
                f"FROM sqlite_scan('{src_abs}', 'market_data_enriched') "
                f"WHERE substr(timestamp, 1, 10) = '{day}'"
            )
        row_counts[table] = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    con.close()

    parts = " + ".join(f"{v} {k}" for k, v in row_counts.items())
    print(f"[{instrument}] EOD ETL: {parts} rows → {dest}")
    return str(dest)


def main():
    parser = argparse.ArgumentParser(description="EOD ETL: SQLite → DuckDB warehouse")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--instrument", choices=list(INSTRUMENTS.keys()))
    group.add_argument("--exchange", type=str, help="Comma-separated: NSE,BSE,MCX")
    group.add_argument("--all", action="store_true")
    parser.add_argument("--date", type=str, default=None, help="Target date YYYY-MM-DD")
    args = parser.parse_args()

    if args.all:
        instruments = list(INSTRUMENTS.keys())
    elif args.exchange:
        instruments = []
        for ex in args.exchange.split(","):
            ex = ex.strip().upper()
            if ex not in EXCHANGE_TO_INSTRUMENTS:
                print(f"Unknown exchange: {ex}", file=sys.stderr)
                sys.exit(1)
            instruments.extend(EXCHANGE_TO_INSTRUMENTS[ex])
    else:
        instruments = [args.instrument]

    for inst in instruments:
        try:
            run_etl(inst, target_date=args.date)
        except FileNotFoundError as e:
            print(f"[{inst}] SKIP — {e}")
        except Exception as e:
            print(f"[{inst}] ERROR: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
