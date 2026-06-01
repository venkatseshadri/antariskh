#!/usr/bin/env python3
"""
feed.py — Thin WebSocket producer. One process, one Shoonya WebSocket session.
Subscribes to all instruments once at start. Publishes normalized bars to Redis.
No persistence. No aggregation. Pure pass-through.

Architecture:
  Shoonya WebSocket → normalize() → LPUSH feed:{instrument} → LTRIM (7-day cap)

Option feed: subscribes to NIFTY weekly ATM ±5 strikes on first tick.
Rebalances window when NIFTY spot crosses ±50 strike boundary.
Raw LTPs published to feed:NIFTY:options Redis stream.

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

import redis

PROJECT_ROOT = Path(__file__).resolve().parent
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

CRED_FILE = SHOONYA_DIR / "cred.yml"
INSTRUMENTS_FILE = PROJECT_ROOT / "config" / "instruments.yaml"
# 5-day cap: MCX ~14.25h/day × 66 ticks/min (peak) × 5 days ≈ 282,150
# With 25% buffer: 352,688 → round to 360,000
REDIS_CAP = 360_000


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
    """When ATM shifts by its gap, drop furthest OTM strikes, add new ones."""
    from config.token_resolver import TokenResolver

    state = _option_state.get(instrument)
    if not state:
        return

    gap = state["gap"]
    old_atm = state["atm"]
    # Hysteresis: only rebalance once ATM crosses 1.5 gaps away, so spot
    # sitting on a strike boundary doesn't thrash resubscribes every tick.
    if abs(new_atm - old_atm) < 1.5 * gap:
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

    # Signal consumer to purge stale strikes
    valid_strikes = sorted(
        {int(new_tokens_map[tsym]["strike"]) for tsym in new_window}
    )
    r.set(f"feed:{instrument}:options:window", json.dumps(valid_strikes))


def _publish_option_tick(r, opt: dict, instrument: str):
    """Push raw option LTP to per-instrument Redis stream."""
    ot = opt.get("opt_type", "")
    if not ot:
        ot = "CE" if opt["tsym"].endswith("CE") else "PE"
    r.lpush(
        f"feed:{instrument}:options",
        json.dumps(
            {
                "tsym": opt["tsym"],
                "strike": opt["strike"],
                "option_type": ot,
                "ltp": float(opt.get("ltp", 0)),
                "timestamp": datetime.now(IST).isoformat(),
            }
        ),
    )
    r.ltrim(f"feed:{instrument}:options", 0, 500_000)


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
    log.info(f"Redis cap: {REDIS_CAP} bars/instrument")

    r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
    r.ping()
    log.info("Redis connected")

    # ── Shoonya session ───────────────────────────────────────────────────
    api = NorenApiPy()
    ret = api.injectOAuthHeader(
        creds["Access_token"],
        creds["UID"],
        creds["Account_ID"],
    )
    if not ret:
        log.error("Shoonya OAuth injection failed")
        sys.exit(1)
    api.set_credentials(
        creds["Access_token"],
        creds["UID"],
        creds["Account_ID"],
    )
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
        ltp_val = float(msg.get("lp", 0))

        # ── Option token branch (NIFTY + SENSEX) ────────────────────────────
        for inst, state in _option_state.items():
            if token in state["token_map"]:
                opt = state["token_map"][token]
                opt["ltp"] = ltp_val
                _publish_option_tick(r, opt, inst)
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
        feed_key = f"feed:{instrument}"
        r.lpush(feed_key, json.dumps(bar))
        r.ltrim(feed_key, 0, REDIS_CAP)

        # per-instrument heartbeat (120s TTL)
        r.set(f"feed:{instrument}:heartbeat", bar["timestamp"], ex=120)

        # ── ATM shift check (NIFTY + SENSEX) ────────────────────────────────
        if instrument in INSTRUMENT_GAP and bar["ltp"] > 0:
            gap = INSTRUMENT_GAP[instrument]
            new_atm = round(bar["ltp"] / gap) * gap

            if instrument not in _option_state:
                _init_option_feed(api, r, instrument, bar["ltp"])
            else:
                old_atm = _option_state[instrument]["atm"]
                if abs(new_atm - old_atm) >= gap:
                    _rebalance_option_window(api, r, instrument, new_atm)

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
