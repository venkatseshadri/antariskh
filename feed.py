#!/usr/bin/env python3
"""
feed.py — Thin WebSocket producer. One process, one Shoonya WebSocket session.
Subscribes to all instruments once at start. Publishes normalized bars to Redis.
No persistence. No aggregation. Pure pass-through.

Architecture:
  Shoonya WebSocket → normalize() → LPUSH feed:{instrument} → LTRIM (7-day cap)

Option feed: subscribes to NIFTY weekly ATM ±5 strikes on first tick.
Rebalances window when NIFTY spot crosses ±50 strike boundary.
Latest option LTPs published to feed:{instrument}:options:ltp Redis hash (one field per strike).

Runs 09:14→23:35 Mon–Fri (superset window for NSE/BSE + MCX).
Window filter in on_tick drops ticks outside each instrument's market hours.
"""

import os
import sys
import json
import re
import time
import yaml
import logging
from datetime import datetime, time as dtime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [feed] %(levelname)s %(message)s",
)
log = logging.getLogger("feed")

# ── Shoonya API path ─────────────────────────────────────────────────────────
SHOONYA_DIR = Path("/home/trading_ceo/python-trader/Shoonya_oAuthAPI-py")
sys.path.insert(0, str(SHOONYA_DIR))
# trading_ceo has an older NorenRestApiPy without injectOAuthHeader.
# Root's site-packages has the correct version.
sys.path.insert(0, "/usr/local/lib/python3.12/dist-packages")
from api_helper import NorenApiPy

sys.path.insert(0, str(PROJECT_ROOT))
from config.sqlite_schema import open_capture_db

CRED_FILE = SHOONYA_DIR / "cred.yml"
INSTRUMENTS_FILE = PROJECT_ROOT / "config" / "instruments.yaml"

LIVE_DIR = PROJECT_ROOT / "data" / "live"
LIVE_DIR.mkdir(parents=True, exist_ok=True)

_1min_logs: dict = {}  # instrument → file handle
_1min_logs_day: str = ""  # rotate at midnight


def load_instruments() -> dict:
    with open(INSTRUMENTS_FILE) as f:
        return yaml.safe_load(f)


def load_creds() -> dict:
    with open(CRED_FILE) as f:
        return yaml.safe_load(f)


IST = timezone(timedelta(hours=5, minutes=30))


def is_within_window(open_time: str, close_time: str) -> bool:
    now = datetime.now(IST).strftime("%H:%M")
    return open_time <= now <= close_time


def normalize(msg: dict, instrument: str) -> dict:
    return {
        "timestamp": datetime.now(IST).isoformat(),
        "instrument": instrument,
        "open": float(msg.get("o", 0) or 0),
        "high": float(msg.get("h", 0) or 0),
        "low": float(msg.get("l", 0) or 0),
        "close": float(msg.get("lp", 0) or 0),  # websocket sends LTP as 'lp'
        "volume": float(msg.get("v", 0) or 0),
        "ltp": float(msg.get("lp", 0) or 0),
    }


_minute_bars = {}  # instrument → in-progress 1-min OHLCV bar


def bucket_minute(instrument: str, tick: dict) -> dict | None:
    """Fold a tick into the instrument's current 1-min bar.

    Returns the completed bar when the minute rolls over (i.e. the first tick of
    a new minute arrives), else None. One in-progress bar held per instrument.
    """
    minute = tick["timestamp"][:16]  # YYYY-MM-DDTHH:MM
    ltp = tick.get("close", 0) or 0
    # Drop price-less ticks (lp=0): folding 0 into the bar permanently locks
    # low=min(0,·)=0 (high=max recovers, low never does) — corrupted low on
    # ~87% of bars, poisoning ATR/SuperTrend/pivots. A tick with no last price
    # carries no OHLC observation. (Caught by PORCUPINE 2026-06-05.)
    if ltp <= 0:
        return None
    cur = _minute_bars.get(instrument)
    if cur is not None and minute == cur["timestamp"][:16]:
        cur["high"] = max(cur["high"], ltp)
        cur["low"] = min(cur["low"], ltp)
        cur["close"] = ltp
        cur["volume"] = (cur.get("volume", 0) or 0) + (tick.get("volume", 0) or 0)
        cur["ltp"] = ltp
        return None
    completed = cur  # None on first tick; previous bar on minute rollover
    _minute_bars[instrument] = {
        "timestamp": minute + ":00",
        "instrument": instrument,
        "open": tick.get("open", ltp) or ltp,
        "high": tick.get("high", ltp) or ltp,
        "low": tick.get("low", ltp) or ltp,
        "close": ltp,
        "volume": tick.get("volume", 0) or 0,
        "ltp": ltp,
    }
    return completed


def build_token_map(instruments: list) -> dict:
    """Reverse-lookup: (exchange, token_str) → instrument name."""
    return {(cfg["exchange"], cfg["token"]): cfg["name"] for cfg in instruments}


def build_subscriptions(config: dict) -> list:
    """Flatten config into a list of dicts ready for subscribe()."""
    subs = []
    for sect in ("spot", "futures", "mcx"):
        for item in config.get(sect, []):
            subs.append(item)
    return subs


def _write_feed_heartbeat(instrument: str, ts: str):
    """Write feed heartbeat to file every 60s (DataHealth reads this)."""
    path = LIVE_DIR / f"feed_{instrument}.heartbeat"
    now = time.time()
    if (
        hasattr(_write_feed_heartbeat, "_last")
        and instrument in _write_feed_heartbeat._last
    ):
        if now - _write_feed_heartbeat._last[instrument] < 60:
            return
    if not hasattr(_write_feed_heartbeat, "_last"):
        _write_feed_heartbeat._last = {}
    _write_feed_heartbeat._last[instrument] = now
    path.write_text(ts)


def _write_1min_log(instrument: str, bar: dict):
    """Append completed 1-min bar to live log file. Rotates at midnight."""
    global _1min_logs, _1min_logs_day

    today_str = datetime.now(IST).strftime("%Y%m%d")
    if today_str != _1min_logs_day:
        for f in _1min_logs.values():
            f.close()
        _1min_logs.clear()
        _1min_logs_day = today_str

    if instrument not in _1min_logs:
        path = LIVE_DIR / f"{instrument}_1min.log"
        _1min_logs[instrument] = open(path, "a", buffering=1)

    line = (
        f"{bar['timestamp']}|{bar['instrument']}|"
        f"{bar['open']}|{bar['high']}|{bar['low']}|{bar['close']}|{bar['volume']}\n"
    )
    _1min_logs[instrument].write(line)


def _write_1min_sqlite(bar: dict):
    """Write 1-min bar to capture SQLite market_data (replaces consumer)."""
    try:
        db = open_capture_db(bar["instrument"])
        if not db:
            return
        db.execute(
            "INSERT OR REPLACE INTO market_data "
            "(timestamp, instrument, open, high, low, close, volume, ltp, source) "
            "VALUES (?,?,?,?,?,?,?,?,'feed')",
            (
                bar["timestamp"],
                bar["instrument"],
                bar["open"],
                bar["high"],
                bar["low"],
                bar["close"],
                bar.get("volume", 0),
                bar.get("ltp", bar["close"]),
            ),
        )
        db.commit()
    except Exception as e:
        log.warning(f"SQLite write failed for {bar['instrument']}: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# ATM Tracking + Option Feed (NIFTY + SENSEX)
# ═══════════════════════════════════════════════════════════════════════════════

OPTION_ATM_RANGE = 5  # ±5 strikes from ATM (11 strikes × CE/PE = 22 tokens)

INSTRUMENT_GAP = {"NIFTY": 50, "SENSEX": 100}

_option_state = {}  # instrument → {token_map, tsym_map, subscribed, atm, expiry}


def _init_option_feed(api, r, instrument: str, spot: float):
    """Resolve ATM ±5 strikes, subscribe all option tokens for one instrument."""
    from config.token_resolver import TokenResolver

    gap = INSTRUMENT_GAP[instrument]
    resolver = TokenResolver(
        nifty_spot=spot if instrument == "NIFTY" else None,
        sensex_spot=spot if instrument == "SENSEX" else None,
    )

    if instrument == "NIFTY":
        tokens = resolver.resolve_weekly_nifty(OPTION_ATM_RANGE)
    else:
        tokens = resolver.resolve_weekly_sensex(OPTION_ATM_RANGE)
        tokens += resolver.resolve_monthly_sensex(OPTION_ATM_RANGE)

    if not tokens:
        log.warning(f"No {instrument} option tokens resolved — skipping")
        return

    token_map = {}
    tsym_map = {}
    subscribed = set()

    for opt in tokens:
        tsym = opt["tsym"]
        tok = opt["token"]
        token_map[tok] = opt
        tsym_map[tsym] = opt
        subscribed.add(tsym)
        api.subscribe(f"{opt['exchange']}|{tok}", feed_type="d")

    atm = resolver.atm_strike(spot, gap)
    _option_state[instrument] = {
        "token_map": token_map,
        "tsym_map": tsym_map,
        "subscribed": subscribed,
        "atm": atm,
        "expiry": tokens[0].get("expiry_date", ""),
        "gap": gap,
    }
    log.info(
        f"Option feed [{instrument}]: ATM={atm}, "
        f"subscribed={len(subscribed)} tokens, "
        f"expiry={_option_state[instrument]['expiry']}"
    )


def _option_unsubscribe(api, token: str):
    """Unsubscribe a token from the depth feed via the public NorenApi method."""
    api.unsubscribe(token, feed_type="d")


def _rebalance_option_window(api, r, instrument: str, new_atm: int):
    """When ATM shifts at bar close, drop furthest OTM strikes, add new ones.
    Called once per 1-min bar — no per-tick thrash, no hysteresis needed."""
    from config.token_resolver import TokenResolver

    state = _option_state.get(instrument)
    if not state:
        return

    gap = state["gap"]
    old_atm = state["atm"]
    if new_atm == old_atm:
        return

    log.info(f"ATM shifted [{instrument}]: {old_atm} → {new_atm} — rebalancing")

    resolver = TokenResolver(
        nifty_spot=new_atm if instrument == "NIFTY" else None,
        sensex_spot=new_atm if instrument == "SENSEX" else None,
    )

    if instrument == "NIFTY":
        tokens = resolver.resolve_weekly_nifty(OPTION_ATM_RANGE)
    else:
        tokens = resolver.resolve_weekly_sensex(OPTION_ATM_RANGE)
        tokens += resolver.resolve_monthly_sensex(OPTION_ATM_RANGE)

    new_tokens_map = {t["tsym"]: t for t in tokens}
    new_window = set(new_tokens_map.keys())

    to_drop = state["subscribed"] - new_window
    to_add = new_window - state["subscribed"]

    for tsym in to_drop:
        opt = state["tsym_map"].get(tsym)
        if opt:
            _option_unsubscribe(api, f"{opt['exchange']}|{opt['token']}")
            state["token_map"].pop(opt["token"], None)
            state["tsym_map"].pop(tsym, None)

    for tsym in to_add:
        opt = new_tokens_map[tsym]
        state["token_map"][opt["token"]] = opt
        state["tsym_map"][tsym] = opt
        api.subscribe(f"{opt['exchange']}|{opt['token']}", feed_type="d")

    state["subscribed"] = new_window
    state["atm"] = new_atm

    log.info(
        f"  [{instrument}] dropped={len(to_drop)}, added={len(to_add)}, "
        f"window={min(new_window)}–{max(new_window)}"
    )


def _publish_option_tick(opt: dict, instrument: str):
    """Track option LTP locally (state lives in _apply_option_tick).
    No Redis — collector downstream reads SQLite option_prices or the feed log."""
    pass


def _apply_option_tick(opt: dict, msg: dict) -> dict:
    """Fold a WS tick into an option's running state (in place).

    Only overwrite ltp with a real (>0) price. Shoonya depth / stale / re-subscribe
    packets can arrive without an 'lp' field; an unconditional assignment would
    clobber the last good price to 0.0 — the bug behind option_prices ltp=0.0
    (seen as all-zero NIFTY *or* SENSEX snapshots depending on tick timing).
    oi/volume are likewise guarded: update only when the field is present.
    """
    lp = float(msg.get("lp", 0) or 0)
    if lp > 0:
        opt["ltp"] = lp
    if "oi" in msg:
        opt["oi"] = float(msg.get("oi") or 0)
    if "v" in msg:
        opt["volume"] = float(msg.get("v") or 0)
    return opt


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════


def main():
    config = load_instruments()
    creds = load_creds()
    subscriptions = build_subscriptions(config)
    token_map = build_token_map(subscriptions)
    active_instruments = [s["name"] for s in subscriptions]

    log.info(f"Instruments: {', '.join(active_instruments)}")
    log.info(f"Live log: {LIVE_DIR}")

    # ── Shoonya session ───────────────────────────────────────────────────
    api = NorenApiPy()
    ret = api.injectOAuthHeader(
        creds["Access_token"], creds["UID"], creds["Account_ID"]
    )
    api.set_credentials(creds["Access_token"], creds["UID"], creds["Account_ID"])
    log.info("Shoonya authenticated")

    socket_opened = False
    subscribed = set()

    def on_open():
        nonlocal socket_opened
        socket_opened = True
        log.info("WebSocket connected — subscribing to all instruments")
        for cfg in subscriptions:
            sub_str = f"{cfg['exchange']}|{cfg['token']}"
            api.subscribe(sub_str, feed_type=cfg["feed_type"])
            log.info(f"  subscribed: {cfg['name']} {sub_str}")
            subscribed.add(cfg["name"])
        log.info("Option feed: waiting for first index ticks to resolve ATM...")

    def on_tick(msg):
        exchange = msg.get("e", "")
        token = msg.get("tk", "")

        # ── Option token branch (NIFTY + SENSEX) ────────────────────────────
        for inst, state in _option_state.items():
            if token in state["token_map"]:
                opt = state["token_map"][token]
                _apply_option_tick(opt, msg)  # guards ltp against lp-less ticks
                _publish_option_tick(opt, inst)
                return  # Option tick — skip bucketing.

        # ── Index tick branch (existing) ───────────────────────────────────
        key = (exchange, str(token))
        instrument = token_map.get(key)
        if instrument is None:
            return
        cfg = next((s for s in subscriptions if s["name"] == instrument), None)
        if cfg is None:
            return
        if not is_within_window(cfg["market_open"], cfg["market_close"]):
            return

        bar = normalize(msg, instrument)

        # Aggregate ticks into 1-min OHLCV bars here; push only completed bars
        # (≈1/min) instead of every tick. Consumer persists them as-is.
        completed = bucket_minute(instrument, bar)
        if completed is not None:
            # ── Write 1-min bar to log file (append-only, crash-safe) ───
            _write_1min_log(instrument, completed)

            # ── Write to capture SQLite directly (no consumer needed) ─────
            _write_1min_sqlite(completed)

            # ── ATM shift check — ONCE PER MINUTE, bar close ─────────────
            if instrument in INSTRUMENT_GAP and completed["close"] > 0:
                gap = INSTRUMENT_GAP[instrument]
                new_atm = round(completed["close"] / gap) * gap
                if instrument not in _option_state:
                    _init_option_feed(api, r, instrument, completed["close"])
                else:
                    old_atm = _option_state[instrument]["atm"]
                    if new_atm != old_atm:
                        _rebalance_option_window(api, r, instrument, new_atm)

        # per-instrument heartbeat — write to file every 60s (DataHealth reads files)
        _write_feed_heartbeat(instrument, bar["timestamp"])

    def on_close():
        nonlocal socket_opened
        socket_opened = False
        log.warning("WebSocket closed — will reconnect")

    # ── Start with reconnect loop ──────────────────────────────────────────
    while True:
        socket_opened = False
        try:
            log.info("Starting WebSocket...")
            api.start_websocket(
                order_update_callback=lambda msg: None,
                subscribe_callback=on_tick,
                socket_open_callback=on_open,
            )

            for _ in range(30):
                if socket_opened:
                    break
                time.sleep(1)
            else:
                log.error("Socket open timeout (30s) — reconnecting")
                time.sleep(5)
                continue

            log.info("WebSocket active — waiting for events")
            while socket_opened:
                time.sleep(1)

        except Exception as e:
            log.error(f"WebSocket error: {e}")

        log.info("Reconnecting in 5s...")
        time.sleep(5)


if __name__ == "__main__":
    main()
