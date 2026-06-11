"""multitf_recompute.py — Phase B recompute-from-raw + drift-diff.

Aggregates 1-min ``market_data`` bars → 6 TFs (same bucket math as the enricher),
recomputes indicators via the shared ``compute_row_indicators`` callable, then
diffs every cell against the stored ``market_data_multitf`` rows.

Usage:
  python3 enrichers/multitf_recompute.py --instrument NIFTY --date 2026-06-10
  python3 enrichers/multitf_recompute.py --instrument NIFTY --date 2026-06-10 --heal

Exit 0 = clean (no drift beyond thresholds); exit 1 = drift / error.
"""

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_capture_v4_queue_aggregator import MultiTFAggregatorQueue

_GRANULARITY_MS = {
    5: 300_000,
    15: 900_000,
    30: 1_800_000,
    60: 3_600_000,
    240: 14_400_000,
    1440: 86_400_000,
}

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

_CALC = MultiTFAggregatorQueue.__new__(MultiTFAggregatorQueue)


# ── 1-min bar loading + poisoned-bar interpolation ─────────────────────────


def _iso_to_epoch_ms(iso_ts: str) -> int:
    from datetime import datetime, timezone, timedelta

    IST = timezone(timedelta(hours=5, minutes=30))
    if iso_ts.endswith("Z") or "+" in iso_ts or iso_ts[-6] == "-":
        return int(
            datetime.fromisoformat(iso_ts.replace("Z", "+00:00")).timestamp() * 1000
        )
    fmt = iso_ts if "T" in iso_ts else iso_ts + "T00:00:00"
    if "." in fmt:
        fmt = fmt[:19] + fmt[fmt.index(".") :]
    else:
        fmt = fmt[:19]
    dt = datetime.strptime(fmt[:19], "%Y-%m-%dT%H:%M:%S")
    return int(dt.replace(tzinfo=IST).timestamp() * 1000)


def load_1min_bars(db_path: str, instrument: str, date: str) -> list:
    """Return list of 1-min bar dicts from ``market_data``, sorted by timestamp.
    Interpolates low <= 0 bars (poison fix) and marks the count."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        raw = [
            dict(r)
            for r in conn.execute(
                "SELECT timestamp, open, high, low, close, volume "
                "FROM market_data "
                "WHERE instrument=? AND substr(timestamp,1,10)=? "
                "ORDER BY timestamp",
                (instrument, date),
            ).fetchall()
        ]
    finally:
        conn.close()
    if not raw:
        return []

    poisoned = 0
    prev_low = None
    for i, bar in enumerate(raw):
        low_val = bar.get("low", 0) or 0
        if low_val <= 0:
            open_p = bar.get("open", 0) or 0
            close_p = bar.get("close", 0) or 0
            candidates = [v for v in (open_p, close_p, prev_low) if v and v > 0]
            raw[i]["low"] = min(candidates) if candidates else open_p or close_p or 0.01
            poisoned += 1
        prev_low = raw[i].get("low", 0) or 0
    if poisoned:
        print(
            f"[multitf_recompute] {date}: interpolated low for {poisoned} poisoned bars"
        )
    return raw


# ── Multi-TF aggregation (session-start anchored) ──────────────────────────

_SESSION_START_MIN = 9 * 60 + 15  # 555 minutes past midnight IST


def _ts_to_session_min(ts: str) -> int:
    """Convert 'YYYY-MM-DDTHH:MM:SS' to minutes past 09:15 IST (session start)."""
    parts = ts[11:].split(":")
    hour, minute = int(parts[0]), int(parts[1])
    return hour * 60 + minute - _SESSION_START_MIN


def _bucket_minute(tf: int, session_min: int) -> int:
    """Bucket session_min into tf-minute grid anchored at session start.
    First bucket for 60m is 0-59 → label 09:15, 60-119 → 10:15, etc."""
    return (session_min // tf) * tf


def aggregate_1min_to_tf(bars_1min: list, tf: int) -> list[dict]:
    """Aggregate 1-min bars → TF candles anchored at session open (09:15)."""
    if not bars_1min:
        return []
    buckets: dict[int, list[dict]] = {}
    for bar in bars_1min:
        sm = _ts_to_session_min(bar["timestamp"])
        if sm < 0:
            continue  # pre-session bar, skip
        bucket = _bucket_minute(tf, sm)
        buckets.setdefault(bucket, []).append(bar)

    candles: list[dict] = []
    for bucket_min in sorted(buckets.keys()):
        bars = buckets[bucket_min]
        day_prefix = bars[0]["timestamp"][:10]
        # Reconstruct bucket start timestamp from session minutes
        abs_minutes = _SESSION_START_MIN + bucket_min
        hour, minute = abs_minutes // 60, abs_minutes % 60
        candle_ts = f"{day_prefix}T{hour:02d}:{minute:02d}:00"
        opens, highs, lows, closes, volumes = [], [], [], [], []
        for b in bars:
            o = b.get("open") or 0
            h = b.get("high") or 0
            lv = b.get("low") or 0
            c = b.get("close") or 0
            v = b.get("volume") or 0
            opens.append(o)
            if h > 0:
                highs.append(h)
            if lv > 0:
                lows.append(lv)
            if c > 0:
                closes.append(c)
            if v > 0:
                volumes.append(v)
        candle = {
            "timestamp": candle_ts,
            "open": opens[0] if opens else 0,
            "high": max(highs) if highs else 0,
            "low": min(lows) if lows else 0,
            "close": closes[-1] if closes else 0,
            "volume": sum(volumes),
        }
        candles.append(candle)
    return candles


def compute_row_indicators(tf_bars: list, i: int, tf: int) -> dict:
    """Indicators for tf_bars[i] using context tf_bars[:i+1] (same as the enricher).
    EMA computed independently (v4 aggregator returns None for EMA columns)."""
    ind = _CALC._aggregate_bucket([tf_bars[i]], tf, tf_bars[: i + 1])
    result = {c: ind.get(c) for c in IND_COLS}
    closes = [b["close"] for b in tf_bars[: i + 1] if b.get("close")]
    for period in [5, 20, 50, 100, 200]:
        ema_list = _compute_ema(closes, period)
        result[f"ema{period}"] = ema_list[i] if i < len(ema_list) else None
    return result


def _compute_ema(closes: list, period: int) -> list:
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


# ── Diff engine ─────────────────────────────────────────────────────────────


def _float_drift(a, b) -> Optional[float]:
    if a is None or b is None:
        return None
    try:
        return abs(float(a) - float(b))
    except (ValueError, TypeError):
        return None


def _enum_match(a, b) -> bool:
    return (a or "").strip().lower() == (b or "").strip().lower()


def recompute_and_diff(
    db_path: str, instrument: str, date: str
) -> tuple[list, int, int]:
    """Recompute indicators from 1-min bars and diff against stored rows.

    Returns: (drift_lines, total_cells, drift_count).  Enums must be exact;
    floats |Δ| ≤ 0.5 are PASS (0.5 tolerance per Board, plan §7.7).
    """
    bars_1min = load_1min_bars(db_path, instrument, date)
    if not bars_1min:
        return ([f"No 1-min bars for {instrument} {date}"], 0, 0)

    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    drift_lines = []
    total_cells = 0
    drift_count = 0

    for tf in TIMEFRAMES:
        candles = aggregate_1min_to_tf(bars_1min, tf)
        if not candles:
            drift_lines.append(f"  {tf}m: no bars aggregated")
            continue

        recomputed_ind = [
            compute_row_indicators(candles, i, tf) for i in range(len(candles))
        ]

        stored_rows = {}
        for r in conn.execute(
            "SELECT timestamp, " + ", ".join(IND_COLS) + " "
            "FROM market_data_multitf "
            "WHERE instrument=? AND timeframe_min=? AND substr(timestamp,1,10)=? "
            "ORDER BY timestamp",
            (instrument, tf, date),
        ).fetchall():
            stored_rows[r["timestamp"]] = dict(r)

        tf_cells = 0
        tf_drift = 0
        for candle, indicators in zip(candles, recomputed_ind):
            ts = candle["timestamp"]
            stored = stored_rows.get(ts)
            if not stored:
                ts_hhmm = ts[11:16] if len(ts) >= 16 else ""
                if "09:15" <= ts_hhmm <= "15:30":
                    drift_lines.append(f"  {tf}m {ts}: MISSING in stored rows")
                    tf_drift += len(IND_COLS)
                continue

            for col in IND_COLS:
                tf_cells += 1
                recomputed_val = indicators.get(col)
                stored_val = stored.get(col)

                # enum-like fields
                if col == "st_consensus":
                    if not _enum_match(recomputed_val, stored_val):
                        drift_lines.append(
                            f"  {tf}m {ts} {col}: stored={stored_val!r} "
                            f"recomputed={recomputed_val!r} (ENUM MISMATCH)"
                        )
                        tf_drift += 1
                    continue

                drift = _float_drift(recomputed_val, stored_val)
                if drift is None:
                    if recomputed_val is None and stored_val is None:
                        continue  # both NULL — no data, skip
                    tf_drift += 1
                    drift_lines.append(
                        f"  {tf}m {ts} {col}: stored={stored_val!r} "
                        f"recomputed={recomputed_val!r} (NULL / non-numeric)"
                    )
                elif drift > 0.5:
                    tf_drift += 1
                    drift_lines.append(
                        f"  {tf}m {ts} {col}: stored={stored_val!r} "
                        f"recomputed={recomputed_val!r} (DRIFT {drift:.4f})"
                    )

        if tf_drift == 0:
            drift_lines.append(
                f"  {tf}m: {''.join('' for _ in range(len('CLEAN')))}PASS ({tf_cells} cells)"
            )
        total_cells += tf_cells
        drift_count += tf_drift

    conn.close()
    return drift_lines, total_cells, drift_count


# ── Heal ────────────────────────────────────────────────────────────────────


def heal(db_path: str, instrument: str, date: str) -> int:
    """Recompute all indicator columns from 1-min bars and write them back.
    Returns number of rows updated."""
    bars_1min = load_1min_bars(db_path, instrument, date)
    if not bars_1min:
        print(f"[multitf_recompute] No 1-min bars for {instrument} {date}")
        return 0

    from multitf_enricher import _open, _write_indicators, IND_COLS as _COLS

    conn = _open(db_path)
    updated = 0
    try:
        for tf in TIMEFRAMES:
            candles = aggregate_1min_to_tf(bars_1min, tf)
            if not candles:
                continue
            indicators_list = [
                compute_row_indicators(candles, i, tf) for i in range(len(candles))
            ]
            rows = [
                {"timestamp": c["timestamp"], **ind}
                for c, ind in zip(candles, indicators_list)
            ]
            n = _write_indicators(conn, instrument, tf, rows)
            print(f"  {tf}m: {n} rows healed")
            updated += n
    finally:
        conn.close()
    return updated


# ── CLI ─────────────────────────────────────────────────────────────────────


def main():
    ap = argparse.ArgumentParser(
        description="Recompute multi-TF indicators from 1-min bars and diff/repair"
    )
    ap.add_argument("--instrument", default="NIFTY", choices=["NIFTY", "SENSEX", "MCX"])
    ap.add_argument("--date", required=True, help="YYYY-MM-DD")
    ap.add_argument("--heal", action="store_true", help="write recomputed values back")
    ap.add_argument("--db", help="capture sqlite path (default: prod)")
    args = ap.parse_args()

    if args.db:
        db_path = args.db
    else:
        from config.sqlite_schema import get_sqlite_capture_path

        db_path = str(get_sqlite_capture_path(args.instrument))

    print(f"[multitf_recompute] {args.instrument} {args.date}")

    if args.heal:
        n = heal(db_path, args.instrument, args.date)
        print(f"[multitf_recompute] healed {n} rows total")
        sys.exit(0 if n > 0 else 1)

    lines, cells, drifts = recompute_and_diff(db_path, args.instrument, args.date)
    print(f"[multitf_recompute] {cells} cells checked, {drifts} drifts")
    for line in sorted(lines):
        print(line)
    print(
        f"[multitf_recompute] {'' if drifts == 0 else 'NOT '}CLEAN — exit {1 if drifts > 0 else 0}"
    )
    sys.exit(1 if drifts > 0 else 0)


if __name__ == "__main__":
    main()
