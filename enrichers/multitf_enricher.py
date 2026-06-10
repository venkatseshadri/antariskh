"""Multi-TF indicator enricher — SQLite single-writer, NO DuckDB.

Replaces the v4 DuckDB aggregator (market_data_multitf_<index>.duckdb), whose
cross-process write lock kept crashing — a disaster for a capital-deployed system.
The Penguin capture path is already consolidated to SQLite (1-min, lock-safe via
BEGIN IMMEDIATE + busy_timeout + retry, which SQLite tolerates and DuckDB does not).

The consumer already aggregates 1-min bars into the per-TF OHLCV rows of the SQLite
`market_data_multitf` table (and publishes `bars:{inst}:{tf}`); it just leaves the
indicator columns NULL. This enricher fills them IN PLACE: read the per-TF OHLCV
bars, compute indicators (REUSING the v4 aggregator's exact math via _aggregate_bucket
— so parity is automatic and the ATR SuperTrend fix carries over), UPDATE the rows.

Once the trend reader (entry_tools/toolkit) is repointed at this SQLite table, the
DuckDB aggregator + its supervisor are retired and the lock class is gone for good.

Modes:
  --backfill <YYYY-MM-DD>   compute indicators for a day's existing multitf rows
  --live                    subscribe to bars:{inst}:{tf}, enrich on each closed bar
"""
import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TIMEFRAMES = [5, 15, 30, 60, 240, 1440]
IND_COLS = [
    "sma20", "sma50", "sma200", "rsi", "atr", "macd", "macd_signal",
    "macd_histogram", "adx", "di_plus", "di_minus", "bb_upper", "bb_middle",
    "bb_lower", "obv", "cmf", "cci", "st_consensus",
]

# Reuse the v4 aggregator's pure indicator math WITHOUT its Redis/DuckDB __init__,
# so the SQLite path and the (interim) DuckDB path compute identically.
from data_capture_v4_queue_aggregator import MultiTFAggregatorQueue  # noqa: E402

_CALC = MultiTFAggregatorQueue.__new__(MultiTFAggregatorQueue)


def compute_row_indicators(tf_bars: list, i: int, tf: int) -> dict:
    """Indicators for tf_bars[i] using context tf_bars[:i+1] (same as the aggregator)."""
    ind = _CALC._aggregate_bucket([tf_bars[i]], tf, tf_bars[: i + 1])
    return {c: ind.get(c) for c in IND_COLS}


def _open(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _write_indicators(conn: sqlite3.Connection, instrument: str, tf: int,
                      rows: list, retries: int = 5) -> int:
    """Lock-safe batched UPDATE (BEGIN IMMEDIATE + retry) — the SQLite multi-writer
    pattern the capture path already uses; SQLite serializes, never crashes."""
    if not rows:
        return 0
    sets = ", ".join(f"{c}=?" for c in IND_COLS)
    sql = (f"UPDATE market_data_multitf SET {sets} "
           f"WHERE timestamp=? AND instrument=? AND timeframe_min=?")
    for attempt in range(retries):
        try:
            conn.execute("BEGIN IMMEDIATE")
            for r in rows:
                conn.execute(sql, [r[c] for c in IND_COLS] + [r["timestamp"], instrument, tf])
            conn.commit()
            return len(rows)
        except sqlite3.OperationalError as e:
            conn.rollback()
            if "locked" in str(e).lower() and attempt < retries - 1:
                time.sleep(0.5 * (attempt + 1))
                continue
            raise
    return 0


def enrich_day(db_path: str, instrument: str, date: str) -> dict:
    """Backfill: compute + write indicators for one day's per-TF rows. Returns
    {tf: rows_written}."""
    conn = _open(db_path)
    written = {}
    try:
        for tf in TIMEFRAMES:
            tf_bars = [dict(r) for r in conn.execute(
                "SELECT timestamp, open, high, low, close, volume FROM market_data_multitf "
                "WHERE instrument=? AND timeframe_min=? AND substr(timestamp,1,10)=? "
                "ORDER BY timestamp", (instrument, tf, date)).fetchall()]
            if not tf_bars:
                written[tf] = 0
                continue
            rows = [{"timestamp": tf_bars[i]["timestamp"], **compute_row_indicators(tf_bars, i, tf)}
                    for i in range(len(tf_bars))]
            written[tf] = _write_indicators(conn, instrument, tf, rows)
    finally:
        conn.close()
    return written


def main():
    ap = argparse.ArgumentParser(description="SQLite multi-TF indicator enricher (no DuckDB)")
    ap.add_argument("--instrument", default="NIFTY", choices=["NIFTY", "SENSEX", "MCX"])
    ap.add_argument("--backfill", help="YYYY-MM-DD: enrich a day's multitf rows in place")
    ap.add_argument("--db", help="capture sqlite path (default: prod capture for instrument)")
    a = ap.parse_args()

    if a.db:
        db_path = a.db
    else:
        from config.sqlite_schema import get_sqlite_capture_path
        db_path = str(get_sqlite_capture_path(a.instrument))

    if a.backfill:
        res = enrich_day(db_path, a.instrument, a.backfill)
        print(f"[multitf_enricher] {a.instrument} {a.backfill}: "
              + " ".join(f"{tf}m={n}" for tf, n in res.items()))
    else:
        print("live subscribe mode not yet wired — use --backfill for now")


if __name__ == "__main__":
    main()
