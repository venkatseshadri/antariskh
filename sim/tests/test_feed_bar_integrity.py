"""PORCUPINE regression — feed bar OHLC integrity under lp-less ticks.

Reproduces the bug PORCUPINE caught 2026-06-05: lp=0 ticks folded into a 1-min
bar locked low=min(0,·)=0 on ~87% of bars. Asserts the feed now drops price-less
ticks so low/open/close never collapse to 0.

Run: python3 -m sim.tests.test_feed_bar_integrity   (from antariksh root)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import feed


def _tick(ts, lp):
    return {"timestamp": ts, "instrument": "NIFTY", "close": lp, "ltp": lp,
            "open": lp, "high": lp, "low": lp, "volume": 0}


def test_lpless_tick_does_not_zero_low():
    feed._minute_bars.clear()
    # minute 1: a price-less tick FIRST (the poison), then real prices
    seq = [
        ("2026-06-06T09:15:01", 0.0),     # lp-less — must be dropped
        ("2026-06-06T09:15:05", 23500.0),
        ("2026-06-06T09:15:30", 23480.0),
        ("2026-06-06T09:15:55", 23510.0),
        ("2026-06-06T09:16:01", 23490.0),  # rollover → completes minute 1
    ]
    completed = None
    for ts, lp in seq:
        out = feed.bucket_minute("NIFTY", _tick(ts, lp))
        if out:
            completed = out
    assert completed is not None, "minute should have completed on rollover"
    assert completed["low"] == 23480.0, f"low corrupted: {completed['low']}"
    assert completed["open"] == 23500.0, f"open corrupted: {completed['open']}"
    assert completed["high"] == 23510.0, f"high wrong: {completed['high']}"
    assert completed["close"] == 23510.0, f"close wrong: {completed['close']}"


def test_midbar_lpless_tick_ignored():
    feed._minute_bars.clear()
    seq = [
        ("2026-06-06T09:20:01", 23500.0),
        ("2026-06-06T09:20:10", 0.0),      # mid-bar lp-less — must not drop low to 0
        ("2026-06-06T09:20:40", 23495.0),
        ("2026-06-06T09:21:01", 23498.0),  # rollover
    ]
    completed = None
    for ts, lp in seq:
        out = feed.bucket_minute("NIFTY", _tick(ts, lp))
        if out:
            completed = out
    assert completed is not None
    assert completed["low"] == 23495.0, f"low corrupted by mid-bar lp-less tick: {completed['low']}"


if __name__ == "__main__":
    test_lpless_tick_does_not_zero_low(); print("✅ lp-less first tick does not zero low/open")
    test_midbar_lpless_tick_ignored();    print("✅ mid-bar lp-less tick ignored, low intact")
    print("\nfeed bar-integrity regression: 2/2 passed")
