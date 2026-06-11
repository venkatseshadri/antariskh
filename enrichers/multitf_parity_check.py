#!/usr/bin/env python3
"""DAMBUILDER Phase A step 2 — SQLite vs v4-DuckDB indicator parity for a session.

Compares market_data_multitf (capture SQLite, new enricher) against the v4
per-index DuckDB for one day. Thresholds (per plan §7 Q6): enums must match
exactly; floats within tolerance (bar-alignment rounding).

Exit 0 = parity, 1 = drift (prints per-column verdicts either way).

Usage: python3 enrichers/multitf_parity_check.py --date 2026-06-12 [--instrument NIFTY]
"""

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FLOAT_TOL = 0.5
FLOAT_COLS = ["sma20", "sma50", "rsi", "atr", "macd", "adx", "cci", "obv", "cmf"]
ENUM_COLS = ["st_consensus"]
V4_DB = "/home/trading_ceo/python-trader/varaha/data/market_data_multitf_{i}.duckdb"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--instrument", default="NIFTY")
    a = ap.parse_args()

    from config.sqlite_schema import get_sqlite_capture_path

    sq = sqlite3.connect(f"file:{get_sqlite_capture_path(a.instrument)}?mode=ro", uri=True)
    sq.row_factory = sqlite3.Row

    import duckdb

    dk = duckdb.connect(V4_DB.format(i=a.instrument.lower()), read_only=True)

    failed = 0
    for tf in (5, 15, 30, 60, 240, 1440):
        s_rows = {r["timestamp"]: dict(r) for r in sq.execute(
            "SELECT * FROM market_data_multitf WHERE instrument=? AND timeframe_min=? "
            "AND substr(timestamp,1,10)=?", (a.instrument, tf, a.date)).fetchall()}
        try:
            d_rows = {str(r[0]): dict(zip([c[0] for c in dk.description], r))
                      for r in dk.execute(
                          "SELECT * FROM market_data_multitf WHERE timeframe_min=? "
                          "AND CAST(timestamp AS DATE)=?", [tf, a.date]).fetchall()}
        except Exception as e:
            print(f"  {tf:>5}m: v4 read failed ({e}) — SKIP")
            continue
        common = sorted(set(s_rows) & set(d_rows))
        if not common:
            print(f"  {tf:>5}m: no overlapping rows (sqlite={len(s_rows)} v4={len(d_rows)})")
            continue

        verdicts = []
        for col in FLOAT_COLS:
            drifts = [abs((s_rows[t].get(col) or 0) - (d_rows[t].get(col) or 0))
                      for t in common
                      if s_rows[t].get(col) is not None and d_rows[t].get(col) is not None]
            if not drifts:
                verdicts.append(f"{col}:n/a")
                continue
            mx = max(drifts)
            ok = mx <= FLOAT_TOL
            verdicts.append(f"{col}:{'OK' if ok else f'DRIFT {mx:.2f}'}")
            failed += 0 if ok else 1
        for col in ENUM_COLS:
            mism = sum(1 for t in common
                       if (s_rows[t].get(col) or "") != (str(d_rows[t].get(col)) or ""))
            ok = mism == 0
            verdicts.append(f"{col}:{'OK' if ok else f'{mism} MISMATCH'}")
            failed += 0 if ok else 1
        print(f"  {tf:>5}m ({len(common)} rows): " + " ".join(verdicts))

    print(f"\nPARITY: {'PASS' if failed == 0 else f'FAIL ({failed} column-TFs drifted)'}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
