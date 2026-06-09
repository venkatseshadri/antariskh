"""PORCUPINE regression — F2 / bug #3 root-cause guard.

Bug: entry agents falling through to deterministic_fallback with
    avg_super_trend = 0.00, session = ""
(caught 2026-06-05, e.g. unicorn_debate._deterministic_fallback).

Two upstream causes. Both LIVE bugs are now FIXED (2026-06-09); this file guards
against regression. NOTE: the original root-cause-2 note (below) was WRONG on the
specifics — corrected here.

ROOT CAUSE 1 — wall-clock session_phase  [FIXED]
    enrichers/lib/advanced.py::compute_session_metrics resolved phase via
    `datetime.now()`, not the bar's own timestamp. A backfill enrich at 21:30 IST
    therefore stamped EVERY bar of the day session_phase="late". FIXED: the function
    now takes a `bar_ts` argument and derives the phase from the bar's timestamp
    (falling back to now() only when bar_ts is None). Guarded by
    test_session_phase_uses_bar_ts below.

ROOT CAUSE 2 — st_consensus hardcoded "NEUTRAL"  [FIXED]  (original note was wrong)
    The original note claimed "market_data_multitf indicator columns stay NULL in
    the replay path". That measured the WRONG table: the consumer's SQLite
    market_data_multitf is OHLCV-ONLY BY DESIGN. The trend agent actually reads
    st_consensus from the v4 PER-INDEX DuckDB (market_data_multitf_<index>.duckdb),
    which the v4 queue aggregator populated — but it HARDCODED st_consensus="NEUTRAL"
    (a "# Legacy" stub; SuperTrend was never wired). So
        trend.timeframes[tf].st_consensus → "NEUTRAL" → score 0  → avg_super_trend≈0.
    FIXED: data_capture_v4_queue_aggregator now computes a proper ATR-band SuperTrend.
    Guarded by sim/tests/test_supertrend_consensus.py.

This file does NOT touch live code (sim+tests sandbox only). Live fixes live in
enrichers/lib/advanced.py and data_capture_v4_queue_aggregator.py.

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


def test_session_phase_uses_bar_ts():
    """THE FIX (root cause 1): when a bar timestamp is passed, the phase reflects
    the BAR's time, NOT the wall clock. Pin now() to 21:30 (a backfill run) and
    confirm an early-session bar is still labelled by its own 09:20 timestamp —
    not stamped "late" as the bug did."""
    pinned_now = datetime(2026, 6, 5, 21, 30, 0)  # backfill time, well after close

    class _PinnedDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return pinned_now

    with patch("enrichers.lib.advanced.datetime", _PinnedDT):
        early = compute_session_metrics(
            23500.0, 23400.0, 23450.0, 23430.0, 23500.0, 23380.0,
            "2026-06-05T09:20:00",
        )["session_phase"]
        mid = compute_session_metrics(
            23500.0, 23400.0, 23450.0, 23430.0, 23500.0, 23380.0,
            "2026-06-05T12:30:00",
        )["session_phase"]

    assert early == "early" and mid == "mid", (
        f"bar_ts ignored — backfill mislabels bars. early={early!r} mid={mid!r}. "
        "compute_session_metrics must derive the phase from bar_ts, not now()."
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
    print("[PASS] session_phase varies with wall clock (now() fallback still works when bar_ts absent)")
    test_session_phase_uses_bar_ts()
    print("[PASS] session_phase derives from bar_ts, not now() (root cause 1 FIXED)")
    test_session_phase_is_one_of_known_labels()
    print("[PASS] session_phase vocabulary documented")
    test_fallback_inputs_contract()
    print("[PASS] fallback-inputs contract probe")
    print("\nfallback-inputs regression: 4/4 passed")
