"""PORCUPINE mock websocket feed — drop-in replacement for feed.py.

Replays historical data from an existing capture SQLite (market_data bars +
option_prices) into the TEST Redis, in the exact key shape the real feed.py
emits, so the real consumer/enricher run downstream unchanged. Monday this
ReplayDriver is swapped for a live source; the key contract stays identical.

Safety: refuses to run unless SIM_MODE=1 (never writes to production redis 6379).

Usage (from antariksh root, with SIM env set):
    SIM_MODE=1 SIM_ROOT=... SIM_REDIS_PORT=6380 \
      python3 -m sim.mock_feed --instrument NIFTY \
        --source-db /home/trading_ceo/python-trader/varaha/data/capture_nifty.sqlite \
        --interval 0.2 --date 2026-06-05
"""
import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

import redis

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim.sim_env import redis_kwargs, sim_active


def _load_bars(src: sqlite3.Connection, instrument: str, date: str | None, limit: int | None):
    q = ("SELECT timestamp, instrument, open, high, low, close, volume, ltp "
         "FROM market_data WHERE instrument = ?")
    args = [instrument]
    if date:
        q += " AND substr(timestamp,1,10) = ?"
        args.append(date)
    q += " ORDER BY timestamp"
    if limit:
        q += f" LIMIT {int(limit)}"
    return src.execute(q, args).fetchall()


def _load_options(src: sqlite3.Connection):
    try:
        return src.execute(
            "SELECT tsym, strike, option_type, ltp, oi, volume, timestamp FROM option_prices"
        ).fetchall()
    except sqlite3.OperationalError:
        return []


def _bar_dict(b) -> dict:
    """Row (sqlite or dict) → the exact bar shape feed.py LPUSHes."""
    close = b["close"]
    return {
        "timestamp": b["timestamp"], "instrument": b["instrument"],
        "open": b["open"], "high": b["high"], "low": b["low"],
        "close": close, "volume": b["volume"] or 0,
        "ltp": b["ltp"] if b["ltp"] is not None else close,
    }


FAULTS = ("none", "gap", "freeze", "dup", "zero", "outlier")


def _inject_faults(bars: list[dict], fault: str, pct: float, window: int = 5) -> list[dict]:
    """Transform a clean replay stream to reproduce a known failure class.
    Pure (no Redis) so it is unit-testable. `pct` (0..1) is where in the stream
    the fault begins; `window` is how many bars it spans.

      none    — passthrough (clean replay)
      gap     — drop `window` contiguous bars (feed gap / missing minutes)
      freeze  — emit up to the fault point then stop (frozen feed; stale heartbeat)
      dup     — emit `window` bars twice (duplicate/replayed ticks)
      zero    — low/close/ltp = 0 on `window` bars (the lp-less tick class that
                poisons low-based indicators; the bug PORCUPINE #2 caught)
      outlier — a single absurd price spike (fat-finger / bad tick)
    """
    if fault == "none" or not bars:
        return list(bars)
    n = len(bars)
    i = max(0, min(n - 1, int(n * pct)))
    if fault == "freeze":
        return [dict(b) for b in bars[:max(1, i)]]
    if fault == "gap":
        return [dict(b) for j, b in enumerate(bars) if not (i <= j < i + window)]
    if fault == "dup":
        out = []
        for j, b in enumerate(bars):
            out.append(dict(b))
            if i <= j < i + window:
                out.append(dict(b))
        return out
    if fault == "zero":
        out = []
        for j, b in enumerate(bars):
            c = dict(b)
            if i <= j < i + window:
                c["low"] = 0
                c["close"] = 0
                c["ltp"] = 0
            out.append(c)
        return out
    if fault == "outlier":
        out = [dict(b) for b in bars]
        spike = out[i]
        spike["high"] = spike["high"] * 10
        spike["close"] = spike["close"] * 10
        spike["ltp"] = spike["close"]
        return out
    raise ValueError(f"unknown fault: {fault}")


def run(instrument: str, source_db: str, interval: float, realtime: bool,
        date: str | None, limit: int | None, fault: str = "none",
        fault_pct: float = 0.5):
    if not sim_active():
        raise SystemExit("REFUSING: SIM_MODE!=1 — mock_feed only writes to the test stack.")

    r = redis.Redis(**redis_kwargs())
    r.ping()

    src = sqlite3.connect(f"file:{source_db}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row

    bars = _load_bars(src, instrument, date, limit)
    if not bars:
        raise SystemExit(f"no market_data bars for {instrument} (date={date}) in {source_db}")

    # Seed prev_close from the first bar's open, and the option chain snapshot.
    r.set(f"prev_close_{instrument}", str(bars[0]["open"]))
    opts = _load_options(src)
    if opts:
        strikes = sorted({o["strike"] for o in opts})
        r.set(f"feed:{instrument}:options:window", json.dumps(strikes))
        mapping = {}
        for o in opts:
            mapping[o["tsym"]] = json.dumps({
                "tsym": o["tsym"], "strike": o["strike"], "option_type": o["option_type"],
                "ltp": o["ltp"], "oi": o["oi"], "volume": o["volume"], "timestamp": o["timestamp"],
            })
        if mapping:
            r.hset(f"feed:{instrument}:options:ltp", mapping=mapping)

    emit = _inject_faults([_bar_dict(b) for b in bars], fault, fault_pct)
    print(f"[mock_feed] replaying {len(emit)} bars for {instrument} "
          f"({'realtime' if realtime else f'{interval}s/bar'}, fault={fault}) "
          f"→ redis:{redis_kwargs()['port']}")

    prev_ts = None
    for i, bar in enumerate(emit):
        r.lpush(f"feed:{instrument}", json.dumps(bar))
        r.ltrim(f"feed:{instrument}", 0, 7000)
        # freeze: stop refreshing the heartbeat partway so it goes stale downstream
        r.set(f"feed:{instrument}:heartbeat", datetime.now().isoformat(), ex=120)

        if realtime and prev_ts:
            try:
                delta = (datetime.fromisoformat(bar["timestamp"]) -
                         datetime.fromisoformat(prev_ts)).total_seconds()
                time.sleep(max(0.0, min(delta, 60.0)))
            except ValueError:
                time.sleep(interval)
        else:
            time.sleep(interval)
        prev_ts = bar["timestamp"]
        if (i + 1) % 50 == 0:
            print(f"[mock_feed] emitted {i+1}/{len(emit)}")

    print(f"[mock_feed] done — {len(emit)} bars emitted (fault={fault})")
    src.close()


def main():
    p = argparse.ArgumentParser(description="PORCUPINE mock feed (replay from capture DB)")
    p.add_argument("--instrument", required=True, choices=["NIFTY", "SENSEX", "MCX"])
    p.add_argument("--source-db", required=True, help="historical capture_*.sqlite to replay from")
    p.add_argument("--interval", type=float, default=0.2, help="seconds between bars (fast mode)")
    p.add_argument("--realtime", action="store_true", help="use real timestamp deltas (cap 60s)")
    p.add_argument("--date", default=None, help="filter to YYYY-MM-DD")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--fault", choices=FAULTS, default="none",
                   help="inject a synthetic fault class into the replay (default: none)")
    p.add_argument("--fault-pct", type=float, default=0.5,
                   help="where in the stream (0..1) the fault begins")
    a = p.parse_args()
    run(a.instrument, a.source_db, a.interval, a.realtime, a.date, a.limit,
        a.fault, a.fault_pct)


if __name__ == "__main__":
    main()
