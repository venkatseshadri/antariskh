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

LIVE_DIR = Path(__file__).resolve().parent.parent / "data" / "live"
TIMEFRAMES = [5, 15, 30, 60, 240, 1440]
IND_COLS = [
    "ema5",
    "ema20",
    "ema50",
    "ema100",
    "ema200",
    "sma20",
    "sma50",
    "sma200",
    "rsi",
    "atr",
    "macd",
    "macd_signal",
    "macd_histogram",
    "adx",
    "di_plus",
    "di_minus",
    "bb_upper",
    "bb_middle",
    "bb_lower",
    "obv",
    "cmf",
    "cci",
    "st_consensus",
]
_EMA_PERIODS = [5, 20, 50, 100, 200]

# Reuse the v4 aggregator's pure indicator math WITHOUT its Redis/DuckDB __init__,
# so the SQLite path and the (interim) DuckDB path compute identically.
from data_capture_v4_queue_aggregator import MultiTFAggregatorQueue  # noqa: E402

_CALC = MultiTFAggregatorQueue.__new__(MultiTFAggregatorQueue)


def _compute_ema(closes: list, period: int) -> list:
    """Compute EMA list from closes. First bar seeds with SMA. Returns
    same-length list (None for first period-1 bars)."""
    if len(closes) < period:
        return [None] * len(closes)
    result = [None] * (period - 1)
    sma = sum(closes[:period]) / period
    multiplier = 2.0 / (period + 1)
    prev = sma
    result.append(round(prev, 2))
    for i in range(period, len(closes)):
        prev = (closes[i] - prev) * multiplier + prev
        result.append(round(prev, 2))
    return result


def compute_row_indicators(tf_bars: list, i: int, tf: int) -> dict:
    """Indicators for tf_bars[i] using context tf_bars[:i+1] (same as the aggregator).
    EMA computed independently (v4 aggregator uses SMA only)."""
    ind = _CALC._aggregate_bucket([tf_bars[i]], tf, tf_bars[: i + 1])
    result = {c: ind.get(c) for c in IND_COLS}
    # Compute EMAs from the close prices of this TF's history
    closes = [b["close"] for b in tf_bars[: i + 1] if b.get("close")]
    for period in _EMA_PERIODS:
        ema_list = _compute_ema(closes, period)
        result[f"ema{period}"] = ema_list[i] if i < len(ema_list) else None
    return result


def _open(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _write_indicators(
    conn: sqlite3.Connection, instrument: str, tf: int, rows: list, retries: int = 5
) -> int:
    """Lock-safe batched UPDATE (BEGIN IMMEDIATE + retry) — the SQLite multi-writer
    pattern the capture path already uses; SQLite serializes, never crashes."""
    if not rows:
        return 0
    sets = ", ".join(f"{c}=?" for c in IND_COLS)
    sql = (
        f"UPDATE market_data_multitf SET {sets} "
        f"WHERE timestamp=? AND instrument=? AND timeframe_min=?"
    )
    for attempt in range(retries):
        try:
            conn.execute("BEGIN IMMEDIATE")
            for r in rows:
                conn.execute(
                    sql, [r[c] for c in IND_COLS] + [r["timestamp"], instrument, tf]
                )
            conn.commit()
            return len(rows)
        except sqlite3.OperationalError as e:
            conn.rollback()
            if "locked" in str(e).lower() and attempt < retries - 1:
                time.sleep(0.5 * (attempt + 1))
                continue
            raise
    return 0


def enrich_tf(conn: sqlite3.Connection, instrument: str, tf: int, date: str) -> int:
    """Compute + write indicators for one TF's rows on one day (idempotent).
    Extends query to include previous day's tail so SMA20/SMA50/SMA200 have
    sufficient window from the first bar of the day (no separate state file)."""
    # Extend lookback: load bars from 2 days ago onward to seed indicator windows
    from datetime import datetime, timedelta

    dt = datetime.strptime(date, "%Y-%m-%d")
    lookback_date = (dt - timedelta(days=2)).strftime("%Y-%m-%d")
    tf_bars = [
        dict(r)
        for r in conn.execute(
            "SELECT timestamp, open, high, low, close, volume FROM market_data_multitf "
            "WHERE instrument=? AND timeframe_min=? AND timestamp >= substr(?,1,10) "
            "ORDER BY timestamp",
            (instrument, tf, lookback_date),
        ).fetchall()
    ]
    if not tf_bars:
        return 0
    # Only enrich today's rows, but use full lookback for indicator context
    today_prefix = date
    today_idxs = [
        i for i, b in enumerate(tf_bars) if b["timestamp"].startswith(today_prefix)
    ]
    if not today_idxs:
        return 0
    rows = [
        {"timestamp": tf_bars[i]["timestamp"], **compute_row_indicators(tf_bars, i, tf)}
        for i in today_idxs
    ]
    return _write_indicators(conn, instrument, tf, rows)


def enrich_day(db_path: str, instrument: str, date: str) -> dict:
    """Backfill: compute + write indicators for one day's per-TF rows. Returns
    {tf: rows_written}."""
    conn = _open(db_path)
    enriched = 0
    try:
        # 1-min bars are already in SQLite market_data; the log file triggered us.
        # We just backfill indicators every time a new bar arrives (idempotent).
        day = datetime.now().strftime("%Y-%m-%d")
        # Already have _load_today_1m using 2-day lookback

        for tf in TIMEFRAMES:
            n = enrich_tf(conn, instrument, tf, day)
            enriched += n

        # Heartbeat — file-based
        heartbeat = LIVE_DIR / f"multitf_enricher_{instrument}.heartbeat"
        heartbeat.write_text(datetime.now().isoformat())
    finally:
        conn.close()
    return written


def live(db_path: str, instrument: str):
    """Live mode: watches the instrument's 1-min log file. On each bar close,
    backfills all 6 TFs' indicators from SQLite market_data (idempotent).
    Heartbeat: data/live/multitf_enricher_{inst}.heartbeat."""
    import json
    import os
    import time
    from datetime import datetime

    print(
        f"[multitf_enricher] live: watching {LIVE_DIR}/{instrument}_1min.log",
        flush=True,
    )

    conn = _open(db_path)
    enriched = 0
    try:
        for message in pubsub.listen():
            if message["type"] != "message":
                continue
            try:
                bar = json.loads(message["data"])
            except (ValueError, json.JSONDecodeError):
                continue
            day = str(bar.get("timestamp", ""))[:10] or datetime.now().strftime(
                "%Y-%m-%d"
            )

            # Load today's 1-min bars to build TF context (lightweight)
            bars_1m = _load_today_1m(conn, instrument, day)

            for tf in TIMEFRAMES:
                candles = aggregate_1min_to_tf(bars_1m, tf)
                if not candles:
                    continue
                indicators_list = [
                    compute_row_indicators(candles, i, tf) for i in range(len(candles))
                ]
                rows = [
                    {"timestamp": c["timestamp"], **ind}
                    for c, ind in zip(candles, indicators_list)
                ]
                try:
                    n = _write_indicators(conn, instrument, tf, rows)
                    enriched += n
                    r.set(
                        f"multitf_enricher:{instrument}:heartbeat",
                        datetime.now().isoformat(),
                    )
                except sqlite3.OperationalError as e:
                    print(
                        f"[multitf_enricher] WRITE FAIL {tf}m: {e}",
                        flush=True,
                    )
                    continue
    finally:
        conn.close()


def _load_today_1m(conn, instrument, day):
    # 2-day lookback so aggregate_1min_to_tf has enough bars to seed indicator windows
    from datetime import datetime, timedelta

    dt = datetime.strptime(day, "%Y-%m-%d")
    lookback = (dt - timedelta(days=2)).strftime("%Y-%m-%d")
    return [
        dict(r)
        for r in conn.execute(
            "SELECT timestamp, open, high, low, close, volume "
            "FROM market_data "
            "WHERE instrument=? AND timestamp >= ? "
            "ORDER BY timestamp",
            (instrument, lookback),
        ).fetchall()
    ]


def main():
    ap = argparse.ArgumentParser(
        description="SQLite multi-TF indicator enricher (no DuckDB)"
    )
    ap.add_argument("--instrument", default="NIFTY", choices=["NIFTY", "SENSEX", "MCX"])
    ap.add_argument(
        "--backfill", help="YYYY-MM-DD: enrich a day's multitf rows in place"
    )
    ap.add_argument(
        "--live",
        action="store_true",
        help="subscribe bars:{inst}:{tf}, enrich on each closed TF bar",
    )
    ap.add_argument(
        "--db", help="capture sqlite path (default: prod capture for instrument)"
    )
    a = ap.parse_args()

    if a.db:
        db_path = a.db
    else:
        from config.sqlite_schema import get_sqlite_capture_path

        db_path = str(get_sqlite_capture_path(a.instrument))

    if a.backfill:
        res = enrich_day(db_path, a.instrument, a.backfill)
        print(
            f"[multitf_enricher] {a.instrument} {a.backfill}: "
            + " ".join(f"{tf}m={n}" for tf, n in res.items())
        )
    elif a.live:
        live(db_path, a.instrument)
    else:
        ap.error("pick a mode: --backfill YYYY-MM-DD or --live")


if __name__ == "__main__":
    main()
