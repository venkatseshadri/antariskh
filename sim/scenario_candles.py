"""PORCUPINE scenario candle generator — turn an intraday NARRATIVE into minute bars.

You describe the day in plain terms (open flat vs prev close, rise +0.5% intraday,
fade to -1% off the high); this realizes a 09:15–15:30 1-min OHLC path that hits
those waypoints exactly. The REAL enricher/aggregator then classify the regime off
these candles, so entry/morph decisions are driven by the system's own logic on a
market you scripted — letting you assert "it should have entered a put spread at
10:25, morphed to iron fly at 10:45, …".

Waypoint targets (relative to prev_close unless noted):
    "+5pts" / "-5pts"          absolute point offset from prev_close
    "+0.5%" / "-1%"            percent of prev_close
    "-1%_from_high"            percent off the running intraday HIGH (so far)
    "+0.8%_from_low"           percent off the running intraday LOW (so far)
    23310.0                    absolute level

This module only builds the INDEX path (and is option-pricing agnostic). The
synthetic option chain + timed replay + expected-timeline diff are layered on top
(see PORCUPINE_STATE NEXT). Pure/deterministic — unit-testable, no Redis/DB.
"""
import argparse
import json
import math
from datetime import datetime, timedelta

SESSION_OPEN = (9, 15)
SESSION_CLOSE = (15, 30)


def _minutes(date: str):
    d = datetime.fromisoformat(date)
    start = d.replace(hour=SESSION_OPEN[0], minute=SESSION_OPEN[1], second=0, microsecond=0)
    end = d.replace(hour=SESSION_CLOSE[0], minute=SESSION_CLOSE[1], second=0, microsecond=0)
    out, t = [], start
    while t <= end:
        out.append(t)
        t += timedelta(minutes=1)
    return out


def _resolve(target, prev_close, hi, lo):
    """Resolve a waypoint target to an absolute spot, given prev_close and the
    running high/low of already-resolved waypoints."""
    if isinstance(target, (int, float)):
        return float(target)
    s = str(target).strip().lower()
    if s.endswith("pts"):
        return prev_close + float(s[:-3])
    if "%_from_high" in s:
        return hi * (1 + float(s.split("%")[0]) / 100)
    if "%_from_low" in s:
        return lo * (1 + float(s.split("%")[0]) / 100)
    if s.endswith("%"):
        return prev_close * (1 + float(s[:-1]) / 100)
    return float(s)


def generate(spec: dict) -> list[dict]:
    """spec: {prev_close, date, path:[{t:'HH:MM', spot:<target>}], vix?}.
    Returns 1-min OHLC bars realizing the path through the waypoints."""
    prev_close = float(spec["prev_close"])
    date = spec.get("date") or "2026-06-16"  # template default; runner overrides per replay date
    mins = _minutes(date)
    tmap = {f"{m.hour:02d}:{m.minute:02d}": i for i, m in enumerate(mins)}

    # Resolve waypoints sequentially, tracking running high/low so "_from_high"
    # references the peak reached by earlier waypoints.
    wps, hi, lo = [], prev_close, prev_close
    for wp in spec["path"]:
        idx = tmap[wp["t"]]
        spot = round(_resolve(wp["spot"], prev_close, hi, lo), 2)
        hi, lo = max(hi, spot), min(lo, spot)
        wps.append((idx, spot))
    if wps[0][0] != 0:
        wps.insert(0, (0, prev_close + 5.0))  # default flat-ish open if unspecified

    # Piecewise-linear close path between waypoints.
    closes = [None] * len(mins)
    for (i0, s0), (i1, s1) in zip(wps, wps[1:]):
        for j in range(i0, i1 + 1):
            frac = (j - i0) / max(i1 - i0, 1)
            closes[j] = s0 + (s1 - s0) * frac
    for j in range(wps[-1][0], len(mins)):  # hold last level to close
        closes[j] = wps[-1][1]

    bars = []
    rng = prev_close * 0.0006  # ~0.06% intrabar wick
    for i, m in enumerate(mins):
        c = closes[i]
        o = closes[i - 1] if i else prev_close
        # deterministic tiny wick so high/low aren't degenerate
        wick = rng * (0.5 + 0.5 * math.sin(i / 7.0))
        hi_i = max(o, c) + wick
        lo_i = min(o, c) - wick
        bars.append({
            "timestamp": m.strftime("%Y-%m-%dT%H:%M:00"),
            "instrument": spec.get("instrument", "NIFTY"),
            "open": round(o, 2), "high": round(hi_i, 2),
            "low": round(lo_i, 2), "close": round(c, 2),
            "volume": 100000, "ltp": round(c, 2),
        })
    return bars


def summarize(spec: dict, bars: list[dict]) -> str:
    prev = float(spec["prev_close"])
    closes = [b["close"] for b in bars]
    hi = max(b["high"] for b in bars); lo = min(b["low"] for b in bars)
    hi_bar = max(bars, key=lambda b: b["high"]);
    lo_after_hi = min((b for b in bars if b["timestamp"] > hi_bar["timestamp"]),
                      key=lambda b: b["low"], default=bars[-1])
    o = bars[0]["open"]
    L = [
        f"prev_close={prev}",
        f"open={o} ({o - prev:+.0f}pts)",
        f"intraday_high={hi:.0f} ({(hi/prev - 1)*100:+.2f}% from prev) @ {hi_bar['timestamp'][11:]}",
        f"close={closes[-1]:.0f} ({(closes[-1]/prev - 1)*100:+.2f}% from prev, "
        f"{(closes[-1]/hi - 1)*100:+.2f}% from high)",
        f"bars={len(bars)}",
    ]
    return " | ".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True, help="JSON file with the scenario spec")
    ap.add_argument("--out", help="write bars JSON here")
    a = ap.parse_args()
    spec = json.loads(open(a.spec).read())
    bars = generate(spec)
    print(summarize(spec, bars))
    if a.out:
        open(a.out, "w").write(json.dumps(bars, indent=2))
        print(f"wrote {len(bars)} bars → {a.out}")


if __name__ == "__main__":
    main()
