"""PORCUPINE regression — bug #3 (real cause) guard for the v4 aggregator's
SuperTrend consensus.

Bug: data_capture_v4_queue_aggregator hardcoded st_consensus="NEUTRAL" on every
multi-TF bar (the `_calculate_supertrend` method existed but was a crude proxy and
was never wired in). The entry-gate deterministic fallback builds its whole trend
score from st_consensus, so it was blind across 5m–1440m → avg_super_trend≈0.

Fix (Board-approved 2026-06-09): a proper ATR-band SuperTrend, wired into the
aggregation. This pins the corrected behaviour so it can't silently revert to a
constant.

Pure test: `_calculate_supertrend` uses no instance state, so we call it unbound
(self=None) — no Redis/DuckDB side effects, safe to run anywhere.

Run: python3 -m sim.tests.test_supertrend_consensus   (from antariksh root)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_capture_v4_queue_aggregator import MultiTFAggregatorQueue

st = MultiTFAggregatorQueue._calculate_supertrend  # unbound; pass self=None


def _series(start, step, n, jitter=0.0):
    """A monotone-ish OHLC series. highs/lows bracket the close by a fixed band."""
    closes = [start + step * i + (jitter if i % 2 else -jitter) for i in range(n)]
    highs = [c + 5 for c in closes]
    lows = [c - 5 for c in closes]
    return closes, highs, lows


def _check(name, cond):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    return cond


def main():
    ok = True

    # Strong uptrend → BULLISH
    c, h, l = _series(100, +10, 60)
    ok &= _check("strong uptrend → BULLISH", st(None, c, h, l) == "BULLISH")

    # Strong downtrend → BEARISH
    c, h, l = _series(1000, -10, 60)
    ok &= _check("strong downtrend → BEARISH", st(None, c, h, l) == "BEARISH")

    # Insufficient data → NEUTRAL (only here)
    c, h, l = _series(100, +10, 5)
    ok &= _check("insufficient data → NEUTRAL", st(None, c, h, l) == "NEUTRAL")

    # NOT constant: up vs down must differ (the bug was a constant)
    cu, hu, lu = _series(100, +10, 60)
    cd, hd, ld = _series(1000, -10, 60)
    ok &= _check("output varies with trend (not hardcoded)",
                 st(None, cu, hu, lu) != st(None, cd, hd, ld))

    # Reversal: rise then fall ends BEARISH
    cu, hu, lu = _series(100, +10, 40)
    cd, hd, ld = _series(cu[-1], -15, 40)
    c = cu + cd; h = hu + hd; l = lu + ld
    ok &= _check("up-then-down reversal → BEARISH", st(None, c, h, l) == "BEARISH")

    # Never returns "NEUTRAL" once a trend is established (would zero the gate)
    c, h, l = _series(100, +8, 80)
    ok &= _check("established trend is never NEUTRAL", st(None, c, h, l) in ("BULLISH", "BEARISH"))

    # Maps cleanly through the fallback's st_scores vocabulary
    ok &= _check("value lowercases into st_scores keys",
                 st(None, cu, hu, lu).lower() in ("bullish", "bearish", "neutral"))

    print(f"\n{'ALL PASS' if ok else 'FAILURES'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
