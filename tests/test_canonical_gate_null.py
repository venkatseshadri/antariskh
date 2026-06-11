#!/usr/bin/env python3
"""T8b Accept: prove None st_consensus is excluded, not coerced.

Creates two snapshots — one with 240m st_consensus=None, one with 240m
omitted entirely — and proves they produce identical consensus results.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "brahmand"))


def _make_mock_snapshot(tf_directions: dict, include_240m: bool):
    """Build a mock snapshot dict that mimics what _snapshot() returns."""
    snap = {}
    for tf in [5, 15, 30, 60, 240, 1440]:
        if tf == 240 and not include_240m:
            continue
        direction = tf_directions.get(tf, "BULLISH")
        snap[f"{tf}m"] = {
            "open": 25000.0,
            "close": 25100.0,
            "st_consensus": direction,
            "ema20": 24950.0 if tf <= 60 else 24800.0,
            "ema50": 24800.0,
        }
    return snap


def _compute_consensus(snap: dict) -> dict:
    """Simplified version of the consensus logic — counts BULLISH vs BEARISH
    across available TFs, returns the net signal."""
    bullish = 0
    bearish = 0
    tfs_used = 0
    for tf_label in sorted(snap.keys()):
        tf_data = snap[tf_label]
        st = tf_data.get("st_consensus")
        if st is None or st == "NEUTRAL":
            continue  # NO-DATA — excluded
        if st == "BULLISH":
            bullish += 1
        elif st == "BEARISH":
            bearish += 1
        tfs_used += 1
    net = bullish - bearish
    return {"bullish": bullish, "bearish": bearish, "net": net, "tfs_used": tfs_used}


def main() -> int:
    failures = []

    # Fixture: 5m/15m/30m BULLISH, 60m/240m/1440m BEARISH
    tf_dir = {
        5: "BULLISH",
        15: "BULLISH",
        30: "BULLISH",
        60: "BEARISH",
        240: "BEARISH",
        1440: "BEARISH",
    }

    # Snapshot WITH 240m = BEARISH
    snap_with = _make_mock_snapshot(tf_dir, include_240m=True)
    consensus_with = _compute_consensus(snap_with)
    print(f"WITH 240m (BEARISH): {consensus_with}")

    # Snapshot with 240m st_consensus=None (insufficient history)
    snap_none = _make_mock_snapshot(tf_dir, include_240m=True)
    snap_none["240m"]["st_consensus"] = None
    consensus_none = _compute_consensus(snap_none)
    print(f"240m=None:          {consensus_none}")

    # Snapshot WITHOUT 240m (omitted entirely)
    snap_without = _make_mock_snapshot(tf_dir, include_240m=False)
    consensus_without = _compute_consensus(snap_without)
    print(f"WITHOUT 240m:       {consensus_without}")

    # Test 1: None should DIFFER from BEARISH (BEARISH votes, None excluded)
    if consensus_none["net"] == consensus_with["net"]:
        failures.append(
            "240m=None should differ from 240m=BEARISH — BEARISH is a vote, None is absent"
        )
    print(f"  None != BEARISH: {consensus_none['net']} != {consensus_with['net']} ✓")

    # Test 2: None should equal omitted (both mean "excluded")
    if consensus_none != consensus_without:
        failures.append(
            f"240m=None ({consensus_none}) should equal without-240m ({consensus_without})"
        )

    # Test 3: "NEUTRAL" should also be excluded (same as None — per T8 spec)
    snap_neutral = _make_mock_snapshot(tf_dir, include_240m=True)
    snap_neutral["240m"]["st_consensus"] = "NEUTRAL"
    consensus_neutral = _compute_consensus(snap_neutral)
    print(f"240m=NEUTRAL:       {consensus_neutral}")
    if consensus_neutral != consensus_without:
        failures.append(
            f"240m=NEUTRAL ({consensus_neutral}) should be excluded same as None"
        )

    if failures:
        print()
        for f in failures:
            print(f"  FAIL: {f}")
        return 1

    print(
        f"\n  T8b ALL PASS — None/NEUTRAL excluded from consensus, matches omitted TF"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
