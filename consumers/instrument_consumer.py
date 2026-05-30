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

from config.sqlite_schema import open_capture_db, init_schemas

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [consumer] %(levelname)s %(message)s",
)
log = logging.getLogger("consumer")

TIMEFRAMES = [5, 15, 30, 60, 240, 1440]


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

        key = (tf, bucket_key)
        if key not in self.buckets:
            self.buckets[key] = {
                "timestamp": bucket_key,
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

    db_path = (
        PROJECT_ROOT.parent
        / "python-trader"
        / "varaha"
        / "data"
        / f"capture_{instrument.lower()}.sqlite"
    )

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

    r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
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

    row = conn.execute(
        "SELECT value FROM consumer_state WHERE key = ?", (f"last_ts:{instrument}",)
    ).fetchone()
    last_ts = row["value"] if row else None
    if last_ts:
        log.info(f"Resuming from checkpoint: {last_ts}")

    aggregator = BarAggregator()
    minute_buffer = MinuteBuffer()
    bar_count = 0
    opt_count = 0
    last_opt_ts = None

    try:
        while True:
            # ── Process OHLCV bars (existing) ──────────────────────────────────
            all_new_bars = []
            for feed_key in feed_keys:
                bars_raw = r.lrange(feed_key, 0, -1)
                for raw in reversed(bars_raw):
                    bar = json.loads(raw)
                    if last_ts and bar["timestamp"] <= last_ts:
                        continue
                    all_new_bars.append(bar)
            all_new_bars.sort(key=lambda b: b["timestamp"])

            for bar in all_new_bars:
                # 1. Bucket into 1-min OHLCV bars; skip incomplete minute
                completed = minute_buffer.feed(bar)
                if completed is None:
                    continue

                # 2. Write completed 1-min bar to market_data
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
                            instrument,
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

                last_ts = bar["timestamp"]

            # ── Process option ticks (NIFTY + SENSEX) ───────────────────────
            if instrument in ("NIFTY", "SENSEX"):
                opt_feed_key = f"feed:{instrument}:options"
                window_key = f"feed:{instrument}:options:window"

                # Purge stale strikes from feed window signal
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

                option_ticks = r.lrange(opt_feed_key, 0, -1)
                new_ticks = []
                for raw in reversed(option_ticks):
                    tick = json.loads(raw)
                    if last_opt_ts and tick["timestamp"] <= last_opt_ts:
                        continue
                    new_ticks.append(tick)

                for tick in new_ticks:
                    conn.execute(
                        """INSERT OR REPLACE INTO option_prices
                           (tsym, strike, option_type, ltp, timestamp)
                           VALUES (?, ?, ?, ?, ?)""",
                        (
                            tick["tsym"],
                            tick["strike"],
                            tick["option_type"],
                            tick["ltp"],
                            tick["timestamp"],
                        ),
                    )
                    opt_count += 1
                    last_opt_ts = tick["timestamp"]

            if all_new_bars:
                conn.execute(
                    "INSERT OR REPLACE INTO consumer_state (key, value) VALUES (?, ?)",
                    (f"last_ts:{instrument}", last_ts),
                )
                conn.commit()
                if bar_count % 60 == 0:
                    log.info(
                        f"Bars: {bar_count} (ckpt: {last_ts}), Options: {opt_count}"
                    )

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
