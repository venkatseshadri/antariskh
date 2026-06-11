"""export_parquet.py — Nightly research parquet export from capture SQLite.

Usage:
  python3 research/export_parquet.py --date 2026-06-10 --instrument NIFTY
  python3 research/export_parquet.py --date 2026-06-10 --both  # NIFTY + SENSEX

Exports per-index per-date parquet files:
  research/export/nifty/2026-06-10/indicators_5m.parquet
  research/export/nifty/2026-06-10/indicators_15m.parquet
  ... etc per TF
  research/export/nifty/2026-06-10/decision_trace.parquet
  research/export/nifty/2026-06-10/trade_outcomes.parquet
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _capture_path(instrument: str) -> Path:
    return Path(
        os.environ.get(
            "CAPTURE_SQLITE",
            f"/home/trading_ceo/python-trader/varaha/data/capture_{instrument.lower()}.sqlite",
        )
    )


def _export_tf(sqlite_path: Path, out_dir: Path, instrument: str, date: str, tf: int):
    import duckdb

    con = duckdb.connect()
    try:
        con.execute(f"ATTACH '{sqlite_path}' AS capture (READ_ONLY)")
        con.execute(
            f"""
            COPY (
              SELECT * FROM capture.market_data_multitf
              WHERE instrument = '{instrument}'
                AND timeframe_min = {tf}
                AND substr(timestamp, 1, 10) = '{date}'
              ORDER BY timestamp
            ) TO '{out_dir}/indicators_{tf}m.parquet'
            (FORMAT 'parquet', COMPRESSION 'zstd')
            """
        )
    finally:
        con.close()


def _export_table(con, sqlite_path: Path, table: str, out_dir: Path, date: str):
    con.execute(f"ATTACH '{sqlite_path}' AS capture (READ_ONLY)")
    con.execute(
        f"""
        COPY (
          SELECT * FROM capture.{table}
          WHERE substr(timestamp, 1, 10) = '{date}'
          ORDER BY timestamp
        ) TO '{out_dir}/{table}.parquet'
        (FORMAT 'parquet', COMPRESSION 'zstd')
        """
    )


def export_date(instrument: str, date: str):
    sqlite_path = _capture_path(instrument)
    if not sqlite_path.exists():
        print(f"SKIP: {sqlite_path} not found")
        return

    out_dir = (
        Path(__file__).parent.parent / "data" / "export" / instrument.lower() / date
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    import duckdb

    con = duckdb.connect()
    try:
        for tf in (5, 15, 30, 60, 240, 1440):
            _export_tf(sqlite_path, str(out_dir), instrument, date, tf)
            print(f"  indicators_{tf}m.parquet")

        for tbl in ("decision_trace", "trade_outcomes"):
            try:
                _export_table(con, sqlite_path, tbl, str(out_dir), date)
                print(f"  {tbl}.parquet")
            except Exception:
                # Table may not exist yet (pre-T5 deploy)
                pass
    finally:
        con.close()

    print(f"[export_parquet] {instrument} {date} → {out_dir}")


def main():
    ap = argparse.ArgumentParser(description="Nightly research parquet export")
    ap.add_argument("--date", required=True, help="YYYY-MM-DD")
    ap.add_argument("--instrument", default="NIFTY", help="NIFTY | SENSEX")
    ap.add_argument("--both", action="store_true", help="export both indices")
    args = ap.parse_args()

    instruments = ["NIFTY", "SENSEX"] if args.both else [args.instrument]
    for inst in instruments:
        export_date(inst, args.date)


if __name__ == "__main__":
    main()
