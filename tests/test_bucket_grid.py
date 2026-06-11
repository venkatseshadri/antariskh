#!/usr/bin/env python3
"""T7 Accept: bucket-grid test — synthetic 09:15–15:29 day, assert
exact bucket start timestamps + bar counts for all 6 TFs."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from enrichers.multitf_recompute import aggregate_1min_to_tf

EXPECTED = {
    5: {"first": "09:15", "last": "15:25", "count": 75},
    15: {"first": "09:15", "last": "15:15", "count": 25},
    30: {"first": "09:15", "last": "15:15", "count": 13},
    60: {"first": "09:15", "last": "15:15", "count": 7},
    240: {"first": "09:15", "last": "13:15", "count": 2},
    1440: {"first": "09:15", "last": "09:15", "count": 1},
}


def main() -> int:
    # Generate a full 09:15–15:29 synthetic day
    bars = []
    px = 25000.0
    for minute in range(0, 375):  # 375 minutes
        hour = 9 + (15 + minute) // 60
        m = (15 + minute) % 60
        ts = f"2026-06-11T{hour:02d}:{m:02d}:00"
        px += (-1) ** minute * 3 + (minute % 7)
        bars.append(
            {
                "timestamp": ts,
                "open": px,
                "high": px + 5,
                "low": px - 3,
                "close": px + 1,
                "volume": 1000,
            }
        )

    failures = []
    for tf, expected in EXPECTED.items():
        candles = aggregate_1min_to_tf(bars, tf)
        starts = [c["timestamp"][11:16] for c in candles]
        expected_first = expected["first"]
        expected_last = expected["last"]
        expected_count = expected["count"]

        if len(candles) != expected_count:
            failures.append(
                f"TF {tf}m: count={len(candles)}, expected={expected_count}"
            )
        if starts[0] != expected["first"]:
            failures.append(
                f"TF {tf}m: first={starts[0]}, expected={expected['first']}"
            )
        if starts[-1] != expected["last"]:
            failures.append(f"TF {tf}m: last={starts[-1]}, expected={expected['last']}")
        print(
            f"  TF {tf:>4}m: {len(candles):>3} bars, "
            f"first={starts[0]} last={starts[-1]}"
        )

    if failures:
        print()
        for f in failures:
            print(f"  FAIL: {f}")
        return 1

    print(f"\n  ALL 6 TFs: bucket grid PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
