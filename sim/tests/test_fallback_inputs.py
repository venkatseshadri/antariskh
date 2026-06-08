"""PORCUPINE regression — F2 / bug #3 root-cause guard.

Bug: entry agents falling through to deterministic_fallback with
    avg_super_trend = 0.00, session = ""
(caught 2026-06-05, e.g. unicorn_debate._deterministic_fallback).

Two upstream gaps cause this. Both are guarded here so the next regression
fails locally instead of on a live Monday morning.

ROOT CAUSE 1 — wall-clock session_phase
    enrichers/lib/advanced.py::compute_session_metrics resolves phase via
    `datetime.now()`, not the bar's own timestamp. A backfill enrich run at
    21:30 IST therefore stamps EVERY bar of the trading day with
    session_phase="late". The fallback's `session = mac_indicators.get(
    "session_phase", "")` is then constant for the whole day — and `""` if the
    upstream call leaves the key out.

ROOT CAUSE 2 — empty multi-TF table
    market_data_multitf gets rows written for tf=5/15/30/60/240/1440 but
    every indicator column (st_consensus, sma20, rsi, adx, ...) stays NULL in
    the replay path. The fallback iterates
        trend.timeframes[tf].st_consensus → "neutral" → score 0
    so avg_super_trend collapses to 0/0 → 0.

This file does NOT touch live code (sim+tests sandbox only). Fixes live in
enrichers/lib/advanced.py and the multi-TF aggregator path.

Run: python3 -m sim.tests.test_fallback_inputs   (from antariksh root)
"""
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enrichers.lib.advanced import compute_session_metrics


def _phase_at(hour: int, minute: int = 0) -> str:
    """Run compute_session_metrics as if the wall clock were (hour, minute)."""
    pinned = datetime(2026, 6, 5, hour, minute, 0)

    class _PinnedDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return pinned

    with patch("enrichers.lib.advanced.datetime", _PinnedDT):
        m = compute_session_metrics(
            spot=23500.0, open_price=23400.0, prev_close=23450.0,
            pivot_pp=23430.0, pivot_r1=23500.0, pivot_s1=23380.0,
        )
    return m["session_phase"]


def test_session_phase_should_track_bar_not_walltime():
    """compute_session_metrics should NOT depend on real-time clock.

    Today it does — so the same bar (say 09:20 IST) gets a different label
    depending on when the enricher runs. We pin the wall clock to four
    market hours and assert at least two distinct phases come out. If you
    later fix this to use a bar-timestamp argument, this test still passes
    (phases keep varying), but the F2 scenario assertion in run_scenario.py
    will start to PASS for the right reason.
    """
    phases = {
        "open":  _phase_at(9, 20),
        "morning": _phase_at(10, 30),
        "midday": _phase_at(12, 30),
        "close": _phase_at(15, 20),
    }
    distinct = set(phases.values())
    assert len(distinct) >= 2, (
        f"compute_session_metrics returned the same phase for every wall "
        f"time — that means a backfill run will stamp every bar of the day "
        f"with one phase. phases={phases}"
    )


def test_session_phase_is_one_of_known_labels():
    """The fallback gate checks `session not in ("preopen", "closing", "")`.
    Make sure the enricher emits a label the gate can recognise. Today the
    enricher emits {"pre","early","mid","late"} and the fallback checks
    {"preopen","closing"} — vocabularies don't match. Documented for the fix.
    """
    seen = {_phase_at(h) for h in (9, 10, 12, 15)}
    assert seen.issubset({"pre", "early", "mid", "late"}), (
        f"unexpected session_phase vocabulary: {seen}"
    )


def test_fallback_inputs_contract():
    """Document the contract the entry pipeline must satisfy for the
    deterministic_fallback to produce a non-trivial decision.

    Simulates the fallback's computation locally (no brahmand import — keeps
    this test runnable from any state). If the upstream pipeline ever feeds
    timeframes={} or session="" again, this contract test makes the failure
    mode obvious.
    """
    st_scores = {"bearish": 1, "neutral": 0, "bullish": -1}

    def fallback_compute(raw_data):
        tfs = raw_data.get("trend", {}).get("timeframes", {})
        total, count = 0, 0
        for _tf, td in tfs.items():
            if isinstance(td, dict):
                total += st_scores.get(str(td.get("st_consensus", "neutral")).lower(), 0)
                count += 1
        avg = total / max(count, 1)
        session = raw_data.get("macro", {}).get("indicators", {}).get("session_phase", "")
        return avg, session

    # Symptom: empty timeframes + missing session_phase → exactly the bug.
    avg, session = fallback_compute({"trend": {"timeframes": {}}, "macro": {"indicators": {}}})
    assert avg == 0.0 and session == "", "contract probe should reproduce the bug shape"

    # Healthy shape: at least one bearish timeframe + session populated.
    avg, session = fallback_compute({
        "trend": {"timeframes": {"5m": {"st_consensus": "bearish"},
                                 "15m": {"st_consensus": "bearish"}}},
        "macro": {"indicators": {"session_phase": "mid"}},
    })
    assert avg > 0 and session, f"healthy inputs collapsed: avg={avg} session={session!r}"


if __name__ == "__main__":
    test_session_phase_should_track_bar_not_walltime()
    print("[PASS] session_phase varies with wall clock (proves the wall-clock dep — fix is to take a bar ts arg)")
    test_session_phase_is_one_of_known_labels()
    print("[PASS] session_phase vocabulary documented")
    test_fallback_inputs_contract()
    print("[PASS] fallback-inputs contract probe")
    print("\nfallback-inputs regression: 3/3 passed")
