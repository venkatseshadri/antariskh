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
import os
import sqlite3
import sys
import time
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

LIVE_DIR = PROJECT_ROOT / "data" / "live"


def _read_latest_close(log_path: Path) -> Optional[float]:
    """Read the last close price from a 1-min log file."""
    if not log_path.exists():
        return None
    try:
        with open(log_path, "rb") as f:
            f.seek(0, 2)  # end
            size = f.tell()
            if size < 20:
                return None
            f.seek(max(0, size - 200))  # last ~200 bytes
            lines = f.read().decode("utf-8", errors="replace").strip().split("\n")
            if not lines:
                return None
            last_line = lines[-1]
            parts = last_line.split("|")
            if len(parts) >= 6:
                return float(parts[5])  # close is index 5
    except (OSError, ValueError):
        pass
    return None


from config.sqlite_schema import (
    open_capture_db,
    init_enriched_schema,
    init_option_prices_schema,
)

_TEXT_COLS = {
    "timestamp",
    "instrument",
    "expiry_weekly",
    "expiry_next_weekly",
    "expiry_monthly",
    "supertrend_direction",
    "iv_regime",
    "sentiment",
    "structure_type",
    "st_5min_direction",
    "st_15min_direction",
    "st_consensus",
    "session_phase",
    "data_source",
}
_INTEGER_COLS = {
    "atm_strike",
    "days_to_weekly",
    "days_to_next_weekly",
    "days_to_monthly",
    "max_pain_strike",
    "ob_strength",
    "fvg_mitigated",
    "liquidity_swept",
    "structure_confirmed",
    "buffer_bars",
}


def _reconcile_enriched_schema(conn, expected_cols):
    """Forward schema evolution: ALTER TABLE ADD COLUMN for any expected col
    missing from the live market_data_enriched table. Per MIGRATION_PLAN.md
    Phase 1.4 spec — prevents schema-drift crashes when ENRICHED_COLUMNS grows."""
    live = {
        r[1] for r in conn.execute("PRAGMA table_info(market_data_enriched)").fetchall()
    }
    added = []
    for col in expected_cols:
        if col in live:
            continue
        sqltype = (
            "TEXT"
            if col in _TEXT_COLS
            else "INTEGER"
            if col in _INTEGER_COLS
            else "REAL"
        )
        conn.execute(f"ALTER TABLE market_data_enriched ADD COLUMN {col} {sqltype}")
        added.append(f"{col} {sqltype}")
    if added:
        conn.commit()
        log.info(f"Schema reconcile: added {len(added)} columns -> {added}")


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

    def __init__(self, instrument: str = "NIFTY"):
        self.api = None
        self.connected = False
        self.instrument = instrument
        self._connect()

    def _connect(self):
        try:
            sys.path.insert(0, str(PROJECT_ROOT.parent / "python-trader"))
            sys.path.insert(0, str(PROJECT_ROOT.parent / "python-trader" / "varaha"))
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
        # Batched enriched writes — see PENGUIN_ENRICHER_LOCK_FIX.md. Rows
        # accumulate and flush in one BEGIN IMMEDIATE txn so busy_timeout is
        # honored on write-lock acquisition. _flush_interval=5s yields a per-bar
        # flush in live mode (bars are 60s apart) and batching only during fast
        # backfill (the size trigger) — so enriched never lags the 5-min kickoff.
        self._write_buffer: List[Dict] = []
        self._last_flush = time.time()
        self._flush_interval = 5.0
        self._flush_batch_size = 5
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

        # Prior-day OHLC for pivots/fibs/gap. Use the last trading day that
        # actually has data — calendar "yesterday" misses weekends/holidays/gaps
        # (e.g. every Monday), which left prev_day_data None → pivots/fibs/gap all
        # NULL. Guard high/low > 0 (some ticks carry 0).
        prev_day = self.conn.execute(
            """SELECT MAX(substr(timestamp, 1, 10)) FROM market_data
               WHERE instrument = ? AND substr(timestamp, 1, 10) < ?""",
            (self.instrument, today),
        ).fetchone()
        prev_day = prev_day[0] if prev_day else None
        if prev_day:
            agg = self.conn.execute(
                """SELECT MAX(high), MIN(low) FROM market_data
                   WHERE instrument = ? AND substr(timestamp, 1, 10) = ?
                     AND high > 0 AND low > 0""",
                (self.instrument, prev_day),
            ).fetchone()
            lc = self.conn.execute(
                """SELECT close FROM market_data
                   WHERE instrument = ? AND substr(timestamp, 1, 10) = ?
                   ORDER BY timestamp DESC LIMIT 1""",
                (self.instrument, prev_day),
            ).fetchone()
            if agg and agg[0]:
                self.prev_day_data = {
                    "high": agg[0],
                    "low": agg[1],
                    "close": lc[0] if lc else None,
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

        if self.prev_day_data is None:
            today = date.today().isoformat()
            prev_day = self.conn.execute(
                """SELECT MAX(substr(timestamp, 1, 10)) FROM market_data
                   WHERE instrument = ? AND substr(timestamp, 1, 10) < ?""",
                (self.instrument, today),
            ).fetchone()
            prev_day = prev_day[0] if prev_day else None
            if prev_day:
                agg = self.conn.execute(
                    """SELECT MAX(high), MIN(low) FROM market_data
                       WHERE instrument = ? AND substr(timestamp, 1, 10) = ?
                         AND high > 0 AND low > 0""",
                    (self.instrument, prev_day),
                ).fetchone()
                lc = self.conn.execute(
                    """SELECT close FROM market_data
                       WHERE instrument = ? AND substr(timestamp, 1, 10) = ?
                       ORDER BY timestamp DESC LIMIT 1""",
                    (self.instrument, prev_day),
                ).fetchone()
                if agg and agg[0]:
                    self.prev_day_data = {
                        "high": agg[0],
                        "low": agg[1],
                        "close": lc[0] if lc else None,
                    }

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
            bar.get("timestamp"),
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

        if self.broker and self.broker.connected:
            try:
                # ── VIX + futures read from live log files (zero REST, zero Redis) ──
                india_vix = _read_latest_close(LIVE_DIR / "INDIAVIX_1min.log")
                fut_path = LIVE_DIR / f"{self.instrument}-FUT_1min.log"
                if fut_path.exists():
                    futures_ltp = _read_latest_close(fut_path)

                if india_vix:
                    vix_history = self._get_vix_history()
                    iv_data = compute_iv_rank(india_vix, vix_history)

                if atm_strike:
                    greeks = compute_aggregate_greeks(
                        spot, self._get_weekly_expiry(), atm_strike, india_vix
                    )
                    option_data = self._read_option_prices_from_db()
                    if option_data:
                        pcr = compute_pcr(option_data, atm_strike)
                        oi = compute_oi_analysis(option_data, atm_strike)
            except Exception as e:
                log.debug(f"Broker enrichment error: {e}")

        atr_val = indicators.get("atr") or 100
        pivot_levels = self._get_pivot_levels()
        if pivot_levels and spot:
            clusters = compute_pivot_clusters(pivot_levels, spot, atr_val)

        _today = date.today()
        wk_date = self._weekly_expiry_date()
        nx_date = wk_date + timedelta(days=7)

        row = {
            "timestamp": bar["timestamp"],
            "instrument": self.instrument,
            "spot": spot,
            "futures": futures_ltp,
            "open_price": self.open_price,
            "prev_close": prev_close,
            "atm_strike": atm_strike,
            "expiry_weekly": wk_date.strftime("%d-%b-%Y").upper(),
            "days_to_weekly": (wk_date - _today).days,
            "expiry_next_weekly": nx_date.strftime("%d-%b-%Y").upper(),
            "days_to_next_weekly": (nx_date - _today).days,
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
        """Accumulate the row; persisted by flush_enriched_batch()."""
        self._write_buffer.append(row)

    def flush_enriched_batch(self):
        """Write all buffered rows in one BEGIN IMMEDIATE transaction.

        BEGIN IMMEDIATE acquires the write lock up front, where busy_timeout (5s)
        is honored — fixing the deferred-transaction crash. Retries with backoff
        on lock contention. On final failure the buffer is KEPT (never dropped)
        and the error is raised: systemd restarts and re-enriches from the
        last_enriched_bar_ts checkpoint. Silent drops would leave NULL atm_strike
        → BRAHMAND "No market data". See PENGUIN_ENRICHER_LOCK_FIX.md.
        """
        if not self._write_buffer:
            return
        placeholders = ", ".join(["?"] * len(ENRICHED_COLUMNS))
        cols = ", ".join(ENRICHED_COLUMNS)
        max_retries = 5
        for attempt in range(max_retries):
            try:
                self.conn.execute("BEGIN IMMEDIATE")
                for row in self._write_buffer:
                    values = [row.get(c) for c in ENRICHED_COLUMNS]
                    self.conn.execute(
                        f"INSERT OR REPLACE INTO market_data_enriched ({cols}) VALUES ({placeholders})",
                        values,
                    )
                last_bar = self._write_buffer[-1]
                self.conn.execute(
                    "INSERT OR REPLACE INTO consumer_state (key, value) VALUES (?, ?)",
                    (f"last_enriched_bar_ts:{self.instrument}", last_bar["timestamp"]),
                )
                self.conn.commit()
                self._write_buffer.clear()
                self._last_flush = time.time()
                return
            except sqlite3.OperationalError as e:
                try:
                    self.conn.rollback()
                except sqlite3.Error:
                    pass
                if attempt < max_retries - 1:
                    backoff = 0.5 * (2**attempt)
                    log.warning(
                        f"Enriched flush locked ({e}); retry "
                        f"{attempt + 1}/{max_retries} in {backoff:.1f}s"
                    )
                    time.sleep(backoff)
                else:
                    log.error(
                        f"Enriched flush failed after {max_retries} retries — "
                        f"keeping {len(self._write_buffer)} rows for restart"
                    )
                    raise

    def _persist_option_premiums(self, option_data: List[Dict], bar_ts: str):
        # Retired — feed.py now persists option data from WebSocket (T13).
        pass

    def _read_option_prices_from_db(self) -> List[Dict]:
        try:
            latest = self.conn.execute(
                "SELECT MAX(timestamp) FROM option_prices"
            ).fetchone()
            if not latest or not latest[0]:
                return []
            rows = self.conn.execute(
                """SELECT tsym, strike, option_type, ltp, oi
                   FROM option_prices WHERE timestamp = ?""",
                (latest[0],),
            ).fetchall()
            return [
                {
                    "tsym": r["tsym"],
                    "strike": r["strike"],
                    "option_type": r["option_type"],
                    "oi": r["oi"],
                    "iv": None,
                    "ltp": r["ltp"],
                }
                for r in rows
            ]
        except Exception:
            return []

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

    def _weekly_expiry_date(self):
        # Weekly option expiry weekday: NIFTY=Tuesday(1), SENSEX=Thursday(3).
        # NOTE: exchange expiry-day rules change periodically and holiday shifts
        # are not handled here — this is a calendar approximation. The broker
        # contract master (TokenResolver) is authoritative when available.
        dow = {"NIFTY": 1, "SENSEX": 3}.get(self.instrument, 1)
        today = date.today()
        days_ahead = dow - today.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        return today + timedelta(days=days_ahead)

    def _get_weekly_expiry(self) -> str:
        return self._weekly_expiry_date().strftime("%d-%b-%Y").upper()

    def _get_weekly_expiry_short(self) -> str:
        return self._weekly_expiry_date().strftime("%d%b%y").upper()


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
    conn = open_capture_db(instrument, autocommit=True)
    init_enriched_schema(conn)
    init_option_prices_schema(conn)
    _reconcile_enriched_schema(conn, ENRICHED_COLUMNS)

    broker = BrokerSession(instrument)
    enricher = Enricher(instrument, conn, broker)

    ema_hook = _init_ema_hook()
    if ema_hook:
        log.info("EMA integration hook loaded")

    log_path = LIVE_DIR / f"{instrument}_1min.log"
    log.info(f"Watching {log_path}")

    # Resume from last enriched bar
    row = conn.execute(
        "SELECT value FROM consumer_state WHERE key = ?",
        (f"last_enriched_bar_ts:{instrument}",),
    ).fetchone()
    last_ts = row[0] if row else None
    if last_ts:
        log.info(f"Resuming from: {last_ts}")

    bar_count = 0
    last_size = 0
    try:
        while True:
            time.sleep(1)
            try:
                current_size = os.path.getsize(log_path)
            except OSError:
                time.sleep(5)
                continue
            if current_size <= last_size:
                continue
            # Read new bytes
            with open(log_path, "r") as f:
                f.seek(last_size)
                raw = f.read(current_size - last_size)
            last_size = current_size

            for line in raw.strip().split("\n"):
                line = line.strip()
                if not line or line.count("|") < 5:
                    continue
                parts = line.split("|")
                try:
                    bar = {
                        "timestamp": parts[0],
                        "instrument": parts[1],
                        "open": float(parts[2]),
                        "high": float(parts[3]),
                        "low": float(parts[4]),
                        "close": float(parts[5]),
                        "volume": float(parts[6]) if len(parts) > 6 else 0,
                    }
                except (ValueError, IndexError):
                    continue

                if last_ts and bar.get("timestamp", "") <= last_ts:
                    continue

                t0 = time.time()
                row = enricher.enrich_bar(bar)
                if row:
                    enricher.write_enriched(row)
                    bar_count += 1
                    last_ts = row["timestamp"]

                    if (
                        len(enricher._write_buffer) >= enricher._flush_batch_size
                        or (time.time() - enricher._last_flush)
                        >= enricher._flush_interval
                    ):
                        enricher.flush_enriched_batch()

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

                # Heartbeat — file-based
                heartbeat = LIVE_DIR / f"enricher_{instrument}.heartbeat"
                heartbeat.write_text(datetime.now().isoformat())
    finally:
        conn.close()
        log.info(f"Enricher stopped — {bar_count} bars enriched")


def run_backfill(instrument: str, date_from: str, date_to: str):
    conn = open_capture_db(instrument, autocommit=True)
    init_enriched_schema(conn)
    init_option_prices_schema(conn)
    _reconcile_enriched_schema(conn, ENRICHED_COLUMNS)

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

    enricher.flush_enriched_batch()
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
