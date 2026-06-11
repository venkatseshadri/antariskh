#!/usr/bin/env python3
"""
Per-instrument consumer. Reads raw bars from Redis feed:{INSTRUMENT} LIST,
buckets ticks into 1-min OHLCV bars, persists to SQLite, computes multi-TF.

Usage:
    python consumers/instrument_consumer.py --instrument NIFTY
    python consumers/instrument_consumer.py --instrument SENSEX
    python consumers/instrument_consumer.py --instrument MCX

Architecture:
    feed:{INSTRUMENT} → consumer → {instrument}.sqlite (market_data + market_data_multitf)
                                 → PUBLISH bars:{INSTRUMENT}:{tf} (downstream)
"""

import argparse
import json
import sys
import logging
import time
from datetime import datetime
from pathlib import Path
from collections import defaultdict

import redis

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.sqlite_schema import open_capture_db, init_schemas, get_sqlite_capture_path
from sim.sim_env import redis_kwargs  # PORCUPINE: redis target (prod 6379 / sim 6380)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [consumer] %(levelname)s %(message)s",
)
log = logging.getLogger("consumer")

TIMEFRAMES = [5, 15, 30, 60, 240, 1440]

# Newest bars scanned per cycle. Producer emits 1-min bars, so this comfortably
# covers a full trading-day catch-up (MCX ≈855 min/day) before the early-break.
HEAD_READ = 1000


# ── 1-min OHLCV bucketing from raw ticks ─────────────────────────────────────


class MinuteBuffer:
    """Buckets raw ticks into 1-min OHLCV bars. Flushes completed bar on minute change."""

    def __init__(self):
        self.bar = None

    def feed(self, bar: dict) -> dict | None:
        """Returns completed bar dict or None if bar still open."""
        minute = bar["timestamp"][:16]  # YYYY-MM-DDTHH:MM
        if self.bar is None:
            ltp = bar.get("close", 0) or 0
            self.bar = {
                "timestamp": minute + ":00",
                "instrument": bar.get("instrument", ""),
                "open": bar.get("open", ltp) or ltp,
                "high": bar.get("high", ltp) or ltp,
                "low": bar.get("low", ltp) or ltp,
                "close": ltp,
                "volume": bar.get("volume", 0) or 0,
                "ltp": ltp,
            }
            return None
        if minute != self.bar["timestamp"][:16]:
            flushed = self.bar
            ltp = bar.get("close", 0) or 0
            self.bar = {
                "timestamp": minute + ":00",
                "instrument": bar.get("instrument", ""),
                "open": bar.get("open", ltp) or ltp,
                "high": bar.get("high", ltp) or ltp,
                "low": bar.get("low", ltp) or ltp,
                "close": ltp,
                "volume": bar.get("volume", 0) or 0,
                "ltp": ltp,
            }
            return flushed
        ltp = bar.get("close", 0) or 0
        self.bar["high"] = max(self.bar["high"], ltp)
        self.bar["low"] = min(self.bar["low"], ltp)
        self.bar["close"] = ltp
        self.bar["volume"] = (self.bar.get("volume", 0) or 0) + (
            bar.get("volume", 0) or 0
        )
        self.bar["ltp"] = ltp
        return None


# ── Multi-TF OHLCV bucket aggregation ────────────────────────────────────────


class BarAggregator:
    """Rolling OHLCV buckets per timeframe. Lightweight, no external indicators."""

    def __init__(self):
        self.buckets = {}

    def process(self, bar: dict, tf: int) -> dict | None:
        """Returns completed bucket dict or None if bucket still open."""
        ts = bar["timestamp"]
        ts_dt = datetime.fromisoformat(ts)
        bucket_minute = (ts_dt.minute // tf) * tf
        bucket_key = ts_dt.strftime("%Y-%m-%dT%H:") + f"{bucket_minute:02d}:00"

        # Key by instrument too: the MCX consumer feeds 7 contracts through one
        # aggregator — without this they collide into one bucket per timeframe.
        key = (bar.get("instrument"), tf, bucket_key)
        if key not in self.buckets:
            self.buckets[key] = {
                "timestamp": bucket_key,
                "instrument": bar.get("instrument"),
                "timeframe_min": tf,
                "open": bar["open"],
                "high": bar["high"],
                "low": bar["low"],
                "close": bar["close"],
                "volume": bar.get("volume", 0) or 0,
            }
            return None

        bucket = self.buckets[key]
        bucket["high"] = max(bucket["high"], bar["high"])
        bucket["low"] = min(bucket["low"], bar["low"])
        bucket["close"] = bar["close"]
        bucket["volume"] = (bucket.get("volume", 0) or 0) + (bar.get("volume", 0) or 0)

        next_minute = ts_dt.minute + 1
        if next_minute % tf == 0 or (ts_dt.minute == 59 and tf > 60):
            del self.buckets[key]
            return bucket
        return None


# ── Main consumer loop ───────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--instrument", required=True, choices=["NIFTY", "SENSEX", "MCX"]
    )
    args = parser.parse_args()

    instrument = args.instrument

    # PORCUPINE: resolve via sim_env so SIM_MODE redirects to the sandbox.
    db_path = get_sqlite_capture_path(instrument)

    if instrument == "MCX":
        MCX_CONTRACTS = [
            "GOLD",
            "SILVERMIC",
            "CRUDEOILM",
            "NATGASMINI",
            "ZINCMINI",
            "LEADMINI",
            "ALUMINI",
        ]
        feed_keys = [f"feed:{c}" for c in MCX_CONTRACTS]
    else:
        feed_keys = [f"feed:{instrument}"]

    log.info(
        f"Consumer starting: instrument={instrument}, feeds={feed_keys}, db={db_path}"
    )

    r = redis.Redis(**redis_kwargs())
    r.ping()
    log.info("Redis connected — waiting for producer bars...")

    startup_deadline = time.time() + 60
    while time.time() < startup_deadline:
        if any(r.llen(fk) > 0 for fk in feed_keys):
            total = sum(r.llen(fk) for fk in feed_keys)
            log.info(f"Producer active — {total} total bars queued")
            break
        time.sleep(1)
    else:
        log.warning("No bars after 60s — entering loop anyway (idempotent)")

    conn = open_capture_db(instrument)
    init_schemas(conn)
    log.info("SQLite ready")

    # Per-source high-water marks: {source_name: last_bar_timestamp}.
    # Per-source (not a single scalar) so MCX's 7 contracts don't drop each
    # other's same-minute bars. Stored as one JSON row; a legacy scalar value
    # → start fresh (re-processing is idempotent via INSERT OR REPLACE).
    row = conn.execute(
        "SELECT value FROM consumer_state WHERE key = ?", (f"last_ts:{instrument}",)
    ).fetchone()
    try:
        last_ts = json.loads(row["value"]) if row else {}
        if not isinstance(last_ts, dict):
            last_ts = {}
    except (json.JSONDecodeError, TypeError):
        last_ts = {}
    if last_ts:
        log.info(f"Resuming from checkpoint: {last_ts}")

    aggregator = BarAggregator()
    bar_count = 0
    opt_count = 0

    try:
        while True:
            # ── Process OHLCV bars (existing) ──────────────────────────────────
            all_new_bars = []
            for feed_key in feed_keys:
                src = feed_key[len("feed:") :]
                seen = last_ts.get(src, "")
                # Newest→oldest; stop at the first already-processed bar. Steady
                # state breaks after ~1 entry, independent of the buffer size.
                for raw in r.lrange(feed_key, 0, HEAD_READ):
                    bar = json.loads(raw)
                    if bar["timestamp"] <= seen:
                        break
                    all_new_bars.append(bar)
            all_new_bars.sort(key=lambda b: b["timestamp"])

            for bar in all_new_bars:
                # Producer already aggregated to a completed 1-min bar.
                completed = bar

                # Reject zero/invalid-OHLC bars before they reach raw market_data:
                # a 0 in any price field poisons low-based indicators and reaches
                # the regime agent as spot=0 (A1). feed.py drops lp-less WS ticks,
                # but bars arriving pre-aggregated via the queue need the same guard
                # here — same bug class as #2, sibling write path. (Skipping is safe:
                # the checkpoint advances on later good bars.)
                if ((completed.get("close", 0) or 0) <= 0
                        or (completed.get("low", 0) or 0) <= 0
                        or (completed.get("high", 0) or 0) <= 0
                        or (completed.get("open", 0) or 0) <= 0):
                    continue

                # Write 1-min bar to market_data
                conn.execute(
                    """INSERT OR REPLACE INTO market_data
                       (timestamp, instrument, open, high, low, close, volume, ltp, source)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'feed')""",
                    (
                        completed["timestamp"],
                        completed.get("instrument", instrument),
                        completed["open"],
                        completed["high"],
                        completed["low"],
                        completed["close"],
                        completed.get("volume", 0),
                        completed.get("ltp", 0),
                    ),
                )
                bar_count += 1

                # 2b. Publish 1-min bar for enricher pickup
                r.publish(f"bars:{instrument}:1", json.dumps(completed))

                # 2c. Multi-TF bucket aggregation
                for tf in TIMEFRAMES:
                    bucket = aggregator.process(completed, tf)
                    if bucket is None:
                        continue
                    conn.execute(
                        """INSERT OR REPLACE INTO market_data_multitf
                           (timestamp, instrument, timeframe_min,
                            open, high, low, close, volume)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            bucket["timestamp"],
                            bucket.get("instrument", instrument),
                            tf,
                            bucket["open"],
                            bucket["high"],
                            bucket["low"],
                            bucket["close"],
                            bucket.get("volume", 0),
                        ),
                    )
                    pub_key = f"bars:{instrument}:{tf}"
                    r.publish(pub_key, json.dumps(bucket))

                last_ts[completed.get("instrument", instrument)] = completed[
                    "timestamp"
                ]

            # Commit bar batch immediately — release lock so enricher can write
            # market_data_enriched. Long transaction across option_prices was
            # the root cause of sqlite3.OperationalError: database is locked.
            if all_new_bars:
                conn.execute(
                    "INSERT OR REPLACE INTO consumer_state (key, value) VALUES (?, ?)",
                    (f"last_ts:{instrument}", json.dumps(last_ts)),
                )
                conn.commit()
                if bar_count % 60 == 0:
                    log.info(
                        f"Bars: {bar_count} (ckpt: {last_ts}), Options: {opt_count}"
                    )

            # ── Process option LTPs (NIFTY + SENSEX) ─────────────────────────
            # Separate transaction from bars — options are best-effort.
            if instrument in ("NIFTY", "SENSEX"):
                ltp_key = f"feed:{instrument}:options:ltp"
                window_key = f"feed:{instrument}:options:window"

                window_json = r.get(window_key)
                if window_json:
                    try:
                        valid_strikes = json.loads(window_json)
                        if valid_strikes:
                            placeholders = ",".join("?" * len(valid_strikes))
                            conn.execute(
                                f"DELETE FROM option_prices WHERE strike NOT IN ({placeholders})",
                                valid_strikes,
                            )
                    except Exception:
                        pass

                for raw in r.hgetall(ltp_key).values():
                    tick = json.loads(raw)
                    conn.execute(
                        """INSERT OR REPLACE INTO option_prices
                           (tsym, strike, option_type, ltp, oi, volume, timestamp)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            tick["tsym"],
                            tick["strike"],
                            tick["option_type"],
                            tick["ltp"],
                            tick.get("oi"),
                            tick.get("volume"),
                            tick["timestamp"],
                        ),
                    )
                    opt_count += 1

                conn.commit()

            r.set(
                f"consumer:{instrument}:heartbeat", datetime.now().isoformat(), ex=120
            )
            time.sleep(1 if all_new_bars else 5)

    except KeyboardInterrupt:
        log.info("Shutting down")
    finally:
        conn.commit()
        conn.close()
        log.info(f"Consumer stopped — {bar_count} bars written")


if __name__ == "__main__":
    main()
