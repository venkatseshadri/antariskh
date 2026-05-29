#!/usr/bin/env python3
"""Per-instrument enricher. Subscribes to bars:{INST}:1 pub/sub, computes
104-column enrichment, writes to market_data_enriched in per-instrument SQLite.

Usage:
    python enrichers/instrument_enricher.py --instrument NIFTY
    python enrichers/instrument_enricher.py --instrument NIFTY --backfill 2026-05-01:2026-05-28
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import redis

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.sqlite_schema import open_capture_db, init_enriched_schema
from enrichers.lib.buffer import IndicatorBuffer
from enrichers.lib.pivots import compute_pivots
from enrichers.lib.fibs import compute_fibs
from enrichers.lib.smc import compute_smc_indicators
from enrichers.lib.supertrend import compute_multiframe_supertrend
from enrichers.lib.greeks import compute_aggregate_greeks
from enrichers.lib.options import compute_pcr, compute_oi_analysis
from enrichers.lib.advanced import (
    compute_iv_rank,
    compute_iv_term_structure,
    compute_historical_volatility,
    compute_session_metrics,
    compute_pivot_clusters,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [enricher] %(levelname)s %(message)s",
)
log = logging.getLogger("enricher")

ENRICHED_COLUMNS = [
    "timestamp",
    "instrument",
    "spot",
    "futures",
    "open_price",
    "prev_close",
    "atm_strike",
    "expiry_weekly",
    "days_to_weekly",
    "expiry_next_weekly",
    "days_to_next_weekly",
    "expiry_monthly",
    "days_to_monthly",
    "ema_5",
    "ema_20",
    "ema_50",
    "supertrend_value",
    "supertrend_direction",
    "adx",
    "atr",
    "rsi",
    "india_vix",
    "vwap",
    "bb_pct_b",
    "bb_width",
    "ema20_slope",
    "gap_pct",
    "prev_day_high",
    "prev_day_low",
    "prev_day_range",
    "intraday_high",
    "intraday_low",
    "pivot_pp",
    "pivot_r1",
    "pivot_r2",
    "pivot_r3",
    "pivot_s1",
    "pivot_s2",
    "pivot_s3",
    "fib_0",
    "fib_236",
    "fib_382",
    "fib_50",
    "fib_618",
    "fib_786",
    "fib_100",
    "open_range_high",
    "open_range_low",
    "iv_current",
    "iv_52w_high",
    "iv_52w_low",
    "iv_rank",
    "iv_regime",
    "iv_short",
    "iv_long",
    "iv_slope",
    "hv_20",
    "hv_60",
    "agg_delta",
    "agg_gamma",
    "agg_vega",
    "agg_theta",
    "wings_delta",
    "body_delta",
    "pcr_total",
    "pcr_atm",
    "sentiment",
    "max_pain_strike",
    "call_oi_concentration",
    "put_oi_concentration",
    "oi_skew",
    "ob_zone_high",
    "ob_zone_low",
    "ob_strength",
    "fvg_high",
    "fvg_low",
    "fvg_mitigated",
    "swing_high",
    "swing_low",
    "liquidity_swept",
    "structure_type",
    "structure_confirmed",
    "next_target",
    "smc_strength",
    "cluster_support",
    "cluster_resistance",
    "distance_to_support",
    "distance_to_resistance",
    "st_5min_value",
    "st_5min_direction",
    "st_15min_value",
    "st_15min_direction",
    "st_consensus",
    "session_phase",
    "open_to_current_pct",
    "distance_to_pivot_pct",
    "distance_to_r1_pct",
    "distance_to_s1_pct",
]


class BrokerSession:
    """Thin wrapper for option chain fetches. Gracefully degrades if unavailable."""

    def __init__(self):
        self.api = None
        self.connected = False
        self._connect()

    def _connect(self):
        try:
            sys.path.insert(0, str(PROJECT_ROOT.parent / "python-trader"))
            sys.path.insert(0, "/usr/local/lib/python3.12/dist-packages")
            from varaha_auth import VarahaConnect

            vc = VarahaConnect()
            if vc.start_session():
                self.api = vc.api
                self.connected = True
                log.info("Broker connected for option chain fetches")
            else:
                log.warning("Broker login failed — options columns will be NULL")
        except Exception as e:
            log.warning(f"Broker unavailable ({e}) — options columns will be NULL")

    def get_vix(self) -> Optional[float]:
        if not self.connected:
            return None
        try:
            q = self.api.get_quotes("NSE", "26017")
            if q and q.get("lp"):
                return float(q["lp"])
        except Exception:
            pass
        return None

    def get_quotes(self, exchange: str, token: str) -> Optional[dict]:
        if not self.connected:
            return None
        try:
            return self.api.get_quotes(exchange, token)
        except Exception:
            return None

    def get_option_chain(
        self, exchange: str, expiry: str, atm_strike: int, step: int = 50
    ) -> List[Dict]:
        if not self.connected:
            return []
        try:
            chain = []
            for i in range(-5, 6):
                strike = atm_strike + i * step
                for otype in ["CE", "PE"]:
                    tsym = f"NIFTY{expiry}{strike}{otype}"
                    q = self.api.get_quotes(exchange, tsym)
                    if q and q.get("oi"):
                        chain.append(
                            {
                                "strike": strike,
                                "option_type": otype,
                                "oi": int(q.get("oi", 0)),
                                "iv": float(q["iv"]) if q.get("iv") else None,
                                "ltp": float(q["lp"]) if q.get("lp") else None,
                            }
                        )
            return chain
        except Exception:
            return []


class Enricher:
    def __init__(self, instrument: str, conn, broker: Optional[BrokerSession] = None):
        self.instrument = instrument
        self.conn = conn
        self.broker = broker
        self.buf = IndicatorBuffer(maxlen=200)
        self.open_price = None
        self.intraday_high = None
        self.intraday_low = None
        self.prev_day_data = None
        self.open_range_high = None
        self.open_range_low = None
        self._warmup()

    def _warmup(self):
        rows = self.conn.execute(
            """SELECT open, high, low, close, volume FROM market_data
               WHERE instrument = ? ORDER BY timestamp DESC LIMIT 200""",
            (self.instrument,),
        ).fetchall()
        for row in reversed(rows):
            self.buf.append(
                row[0] or 0, row[1] or 0, row[2] or 0, row[3] or 0, row[4] or 0
            )
        if rows:
            log.info(f"Warmup: {len(rows)} bars loaded into buffer")

        today = date.today().isoformat()
        today_rows = self.conn.execute(
            """SELECT open, high, low, close FROM market_data
               WHERE instrument = ? AND timestamp >= ? ORDER BY timestamp""",
            (self.instrument, today),
        ).fetchall()
        if today_rows:
            self.open_price = today_rows[0][0]
            highs = [r[1] for r in today_rows if r[1]]
            lows = [r[2] for r in today_rows if r[2]]
            if highs:
                self.intraday_high = max(highs)
            if lows:
                self.intraday_low = min(lows)
            first_15 = today_rows[:15]
            if first_15:
                or_highs = [r[1] for r in first_15 if r[1]]
                or_lows = [r[2] for r in first_15 if r[2]]
                if or_highs:
                    self.open_range_high = max(or_highs)
                if or_lows:
                    self.open_range_low = min(or_lows)

        yesterday = (date.today() - timedelta(days=1)).isoformat()
        prev = self.conn.execute(
            """SELECT MAX(high), MIN(low), close FROM market_data
               WHERE instrument = ? AND timestamp >= ? AND timestamp < ?
               ORDER BY timestamp DESC LIMIT 1""",
            (self.instrument, yesterday, today),
        ).fetchone()
        if prev and prev[0]:
            self.prev_day_data = {
                "high": prev[0],
                "low": prev[1],
                "close": prev[2],
            }

    def enrich_bar(self, bar: Dict) -> Dict:
        spot = bar.get("close") or bar.get("ltp")
        if not spot:
            return {}

        self.buf.append(
            bar.get("open", spot),
            bar.get("high", spot),
            bar.get("low", spot),
            spot,
            bar.get("volume", 0) or 0,
        )

        if self.open_price is None:
            self.open_price = bar.get("open", spot)
        if self.intraday_high is None or bar.get("high", spot) > self.intraday_high:
            self.intraday_high = bar.get("high", spot)
        if self.intraday_low is None or bar.get("low", spot) < self.intraday_low:
            self.intraday_low = bar.get("low", spot)

        indicators = self.buf.compute_indicators()

        prev_high = self.prev_day_data["high"] if self.prev_day_data else None
        prev_low = self.prev_day_data["low"] if self.prev_day_data else None
        prev_close = self.prev_day_data["close"] if self.prev_day_data else None
        prev_range = round(prev_high - prev_low, 2) if prev_high and prev_low else None

        pivots = compute_pivots(prev_high, prev_low, prev_close)
        fibs = compute_fibs(prev_high, prev_low)
        smc = compute_smc_indicators(self.buf)
        st_multi = compute_multiframe_supertrend(self.buf)
        hv = compute_historical_volatility(self.buf)
        session = compute_session_metrics(
            spot,
            self.open_price,
            prev_close,
            pivots.get("pivot_pp"),
            pivots.get("pivot_r1"),
            pivots.get("pivot_s1"),
        )

        gap_pct = None
        if self.open_price and prev_close and prev_close > 0:
            gap_pct = round(((self.open_price - prev_close) / prev_close) * 100, 3)

        india_vix = None
        iv_data = {
            "iv_current": None,
            "iv_52w_high": None,
            "iv_52w_low": None,
            "iv_rank": None,
            "iv_regime": None,
        }
        iv_term = {"iv_short": None, "iv_long": None, "iv_slope": None}
        greeks = {
            "agg_delta": None,
            "agg_gamma": None,
            "agg_vega": None,
            "agg_theta": None,
            "wings_delta": None,
            "body_delta": None,
        }
        pcr = {"pcr_total": None, "pcr_atm": None, "sentiment": None}
        oi = {
            "max_pain_strike": None,
            "call_oi_concentration": None,
            "put_oi_concentration": None,
            "oi_skew": None,
        }
        clusters = {
            "cluster_support": None,
            "cluster_resistance": None,
            "distance_to_support": None,
            "distance_to_resistance": None,
        }

        atm_strike = round(spot / 50) * 50 if spot else None
        india_vix = None
        futures_ltp = None

        _FUTURES_CFG = {
            "NIFTY": ("NFO", "62329"),
            "SENSEX": ("BFO", "1105863"),
        }

        if self.broker and self.broker.connected:
            try:
                india_vix = self.broker.get_vix()

                fut_cfg = _FUTURES_CFG.get(self.instrument)
                if fut_cfg:
                    q = self.broker.get_quotes(*fut_cfg)
                    if q and q.get("lp"):
                        futures_ltp = float(q["lp"])

                if india_vix:
                    vix_history = self._get_vix_history()
                    iv_data = compute_iv_rank(india_vix, vix_history)

                if atm_strike:
                    greeks = compute_aggregate_greeks(
                        spot, self._get_weekly_expiry(), atm_strike, india_vix
                    )
                    option_data = self.broker.get_option_chain(
                        "NFO", self._get_weekly_expiry_short(), atm_strike
                    )
                    if option_data:
                        pcr = compute_pcr(option_data, atm_strike)
                        oi = compute_oi_analysis(option_data, atm_strike)
            except Exception as e:
                log.debug(f"Broker enrichment error: {e}")

        atr_val = indicators.get("atr") or 100
        pivot_levels = self._get_pivot_levels()
        if pivot_levels and spot:
            clusters = compute_pivot_clusters(pivot_levels, spot, atr_val)

        row = {
            "timestamp": bar["timestamp"],
            "instrument": self.instrument,
            "spot": spot,
            "futures": futures_ltp,
            "open_price": self.open_price,
            "prev_close": prev_close,
            "atm_strike": atm_strike,
            "expiry_weekly": None,
            "days_to_weekly": None,
            "expiry_next_weekly": None,
            "days_to_next_weekly": None,
            "expiry_monthly": None,
            "days_to_monthly": None,
            "ema_5": indicators.get("ema_5"),
            "ema_20": indicators.get("ema_20"),
            "ema_50": indicators.get("ema_50"),
            "supertrend_value": indicators.get("supertrend_value"),
            "supertrend_direction": indicators.get("supertrend_direction"),
            "adx": indicators.get("adx"),
            "atr": indicators.get("atr"),
            "rsi": indicators.get("rsi"),
            "india_vix": india_vix,
            "vwap": indicators.get("vwap"),
            "bb_pct_b": indicators.get("bb_pct_b"),
            "bb_width": indicators.get("bb_width"),
            "ema20_slope": indicators.get("ema20_slope"),
            "gap_pct": gap_pct,
            "prev_day_high": prev_high,
            "prev_day_low": prev_low,
            "prev_day_range": prev_range,
            "intraday_high": self.intraday_high,
            "intraday_low": self.intraday_low,
            **pivots,
            **fibs,
            "open_range_high": self.open_range_high,
            "open_range_low": self.open_range_low,
            **iv_data,
            **iv_term,
            **hv,
            **greeks,
            **pcr,
            **oi,
            "ob_zone_high": smc.get("ob_zone_high"),
            "ob_zone_low": smc.get("ob_zone_low"),
            "ob_strength": smc.get("ob_strength"),
            "fvg_high": smc.get("fvg_high"),
            "fvg_low": smc.get("fvg_low"),
            "fvg_mitigated": int(smc.get("fvg_mitigated", False)),
            "swing_high": smc.get("swing_high"),
            "swing_low": smc.get("swing_low"),
            "liquidity_swept": int(smc.get("liquidity_swept", False)),
            "structure_type": smc.get("structure_type"),
            "structure_confirmed": int(smc.get("structure_confirmed", False)),
            "next_target": smc.get("next_target"),
            "smc_strength": smc.get("smc_strength"),
            **clusters,
            **st_multi,
            **session,
        }
        return row

    def write_enriched(self, row: Dict):
        placeholders = ", ".join(["?"] * len(ENRICHED_COLUMNS))
        cols = ", ".join(ENRICHED_COLUMNS)
        values = [row.get(c) for c in ENRICHED_COLUMNS]
        self.conn.execute(
            f"INSERT OR REPLACE INTO market_data_enriched ({cols}) VALUES ({placeholders})",
            values,
        )
        self.conn.execute(
            "INSERT OR REPLACE INTO consumer_state (key, value) VALUES (?, ?)",
            (f"last_enriched_bar_ts:{self.instrument}", row["timestamp"]),
        )
        self.conn.commit()

    def _get_vix_history(self) -> List[float]:
        rows = self.conn.execute(
            """SELECT india_vix FROM market_data_enriched
               WHERE instrument = ? AND india_vix IS NOT NULL
               ORDER BY timestamp DESC LIMIT 1440""",
            (self.instrument,),
        ).fetchall()
        return [r[0] for r in rows] if rows else []

    def _get_pivot_levels(self) -> List[float]:
        rows = self.conn.execute(
            """SELECT pivot_pp, pivot_r1, pivot_s1 FROM market_data_enriched
               WHERE instrument = ? AND pivot_pp IS NOT NULL
               ORDER BY timestamp DESC LIMIT 1440""",
            (self.instrument,),
        ).fetchall()
        levels = []
        for r in rows:
            if r[0]:
                levels.append(r[0])
            if r[1]:
                levels.append(r[1])
            if r[2]:
                levels.append(r[2])
        return levels

    def _get_weekly_expiry(self) -> str:
        today = date.today()
        days_ahead = 1 - today.weekday()  # Tuesday = 1
        if days_ahead <= 0:
            days_ahead += 7
        next_tue = today + timedelta(days=days_ahead)
        return next_tue.strftime("%d-%b-%Y").upper()

    def _get_weekly_expiry_short(self) -> str:
        today = date.today()
        days_ahead = 1 - today.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        next_tue = today + timedelta(days=days_ahead)
        return next_tue.strftime("%d%b%y").upper()


def _init_ema_hook():
    """Load brahmand EMA integration hook if available."""
    try:
        import sys

        sys.path.insert(0, str(PROJECT_ROOT.parent / "brahmand"))
        from ema_integration_hook import on_new_bar

        return on_new_bar
    except ImportError:
        return None


def run_live(instrument: str):
    conn = open_capture_db(instrument)
    init_enriched_schema(conn)

    broker = BrokerSession()
    enricher = Enricher(instrument, conn, broker)

    ema_hook = _init_ema_hook()
    if ema_hook:
        log.info("EMA integration hook loaded")

    r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
    r.ping()

    pubsub = r.pubsub()
    channel = f"bars:{instrument}:1"
    pubsub.subscribe(channel)
    log.info(f"Subscribed to {channel} — waiting for bars...")

    row = conn.execute(
        "SELECT value FROM consumer_state WHERE key = ?",
        (f"last_enriched_bar_ts:{instrument}",),
    ).fetchone()
    last_ts = row[0] if row else None
    if last_ts:
        log.info(f"Resuming from: {last_ts}")

    bar_count = 0
    try:
        for message in pubsub.listen():
            if message["type"] != "message":
                continue
            try:
                bar = json.loads(message["data"])
            except (json.JSONDecodeError, TypeError):
                continue

            if last_ts and bar.get("timestamp", "") <= last_ts:
                continue

            t0 = time.time()
            row = enricher.enrich_bar(bar)
            if row:
                enricher.write_enriched(row)
                bar_count += 1
                last_ts = row["timestamp"]

                queue_key = f"v3_ohlcv_queue_{instrument}"
                try:
                    bridge_bar = {
                        "timestamp": row["timestamp"],
                        "index": instrument,
                        "open": row.get("open_price") or bar.get("open", 0),
                        "high": bar.get("high", bar.get("open", 0)),
                        "low": bar.get("low", bar.get("open", 0)),
                        "close": bar.get("close", bar.get("open", 0)),
                        "volume": bar.get("volume", 0),
                        "ema5": row.get("ema_5"),
                        "ema20": row.get("ema_20"),
                        "ema50": row.get("ema_50"),
                        "rsi": row.get("rsi"),
                        "atr": row.get("atr"),
                        "adx": row.get("adx"),
                        "st_direction": row.get("supertrend_direction"),
                        "bb_pct_b": row.get("bb_pct_b"),
                    }
                    r.lpush(queue_key, json.dumps(bridge_bar))
                    r.ltrim(queue_key, 0, 10079)
                except Exception:
                    pass

                if ema_hook and bar.get("close"):
                    try:
                        ema_hook(bar, index=instrument)
                    except Exception:
                        pass

                elapsed = time.time() - t0
                if elapsed > 5:
                    log.warning(
                        f"Enrichment took {elapsed:.1f}s for {row['timestamp']}"
                    )
                if bar_count % 30 == 0:
                    log.info(f"Enriched {bar_count} bars (last: {last_ts})")

            r.set(
                f"enricher:{instrument}:heartbeat", datetime.now().isoformat(), ex=120
            )

    except KeyboardInterrupt:
        log.info("Shutting down")
    finally:
        conn.close()
        log.info(f"Enricher stopped — {bar_count} bars enriched")


def run_backfill(instrument: str, date_from: str, date_to: str):
    conn = open_capture_db(instrument)
    init_enriched_schema(conn)

    enricher = Enricher(instrument, conn, broker=None)

    rows = conn.execute(
        """SELECT timestamp, instrument, open, high, low, close, volume
           FROM market_data
           WHERE instrument = ? AND timestamp >= ? AND timestamp < ?
           ORDER BY timestamp""",
        (instrument, date_from, date_to + "T99"),
    ).fetchall()

    log.info(f"Backfill: {len(rows)} bars from {date_from} to {date_to}")
    count = 0
    for row in rows:
        bar = {
            "timestamp": row[0],
            "instrument": row[1],
            "open": row[2],
            "high": row[3],
            "low": row[4],
            "close": row[5],
            "volume": row[6],
        }
        enriched = enricher.enrich_bar(bar)
        if enriched:
            enricher.write_enriched(enriched)
            count += 1
            if count % 100 == 0:
                log.info(f"Backfill progress: {count}/{len(rows)}")

    log.info(f"Backfill complete — {count} bars enriched")
    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Per-instrument enricher")
    parser.add_argument(
        "--instrument", required=True, choices=["NIFTY", "SENSEX", "MCX"]
    )
    parser.add_argument(
        "--backfill",
        type=str,
        default=None,
        help="Backfill mode: YYYY-MM-DD:YYYY-MM-DD",
    )
    args = parser.parse_args()

    if args.backfill:
        parts = args.backfill.split(":")
        if len(parts) != 2:
            log.error("--backfill format: YYYY-MM-DD:YYYY-MM-DD")
            sys.exit(1)
        run_backfill(args.instrument, parts[0], parts[1])
    else:
        run_live(args.instrument)


if __name__ == "__main__":
    main()
