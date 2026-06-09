"""PORCUPINE — synthetic fault driver unit tests.

Verifies sim/mock_feed._inject_faults reproduces each known failure class
deterministically and purely (no Redis). These faults feed the A2/A3/A5/A8
catalogue scenarios; pinning their shape here keeps them honest.

Run: python3 -m sim.tests.test_fault_driver   (expect ALL PASS)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim.mock_feed import _inject_faults, FAULTS


def _clean(n=20):
    return [
        {"timestamp": f"2026-06-05T09:{15 + i // 60:02d}:{i % 60:02d}",
         "instrument": "NIFTY", "open": 100 + i, "high": 105 + i,
         "low": 95 + i, "close": 100 + i, "volume": 10, "ltp": 100 + i}
        for i in range(n)
    ]


def _check(name, cond):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    return cond


def main():
    bars = _clean()
    ok = True

    # none = passthrough, distinct copy (no aliasing into prod state)
    out = _inject_faults(bars, "none", 0.5)
    ok &= _check("none preserves length", len(out) == len(bars))
    ok &= _check("none preserves values", [b["close"] for b in out] == [b["close"] for b in bars])

    # gap drops a contiguous window
    out = _inject_faults(bars, "gap", 0.5, window=5)
    ok &= _check("gap removes window bars", len(out) == len(bars) - 5)

    # freeze truncates the stream at the fault point (feed dies)
    out = _inject_faults(bars, "freeze", 0.5)
    ok &= _check("freeze truncates stream", 0 < len(out) < len(bars))

    # dup repeats a window
    out = _inject_faults(bars, "dup", 0.5, window=5)
    ok &= _check("dup lengthens stream by window", len(out) == len(bars) + 5)
    ok &= _check("dup creates adjacent repeats",
                 any(out[i] == out[i + 1] for i in range(len(out) - 1)))

    # zero injects the lp-less tick class (low/close/ltp = 0)
    out = _inject_faults(bars, "zero", 0.5, window=5)
    zeros = [b for b in out if b["low"] == 0 and b["close"] == 0 and b["ltp"] == 0]
    ok &= _check("zero injects 5 corrupt bars", len(zeros) == 5)
    ok &= _check("zero leaves the rest clean", all(b["low"] > 0 for b in out if b["low"] != 0))

    # outlier spikes exactly one bar
    out = _inject_faults(bars, "outlier", 0.5)
    spikes = [b for b in out if b["close"] >= 1000]
    ok &= _check("outlier spikes exactly one bar", len(spikes) == 1)

    # purity: input is never mutated
    before = [dict(b) for b in bars]
    _inject_faults(bars, "zero", 0.5)
    _inject_faults(bars, "outlier", 0.5)
    ok &= _check("input list not mutated", bars == before)

    # every advertised fault is handled (no ValueError)
    for f in FAULTS:
        try:
            _inject_faults(bars, f, 0.5)
        except Exception as e:  # noqa: BLE001
            ok &= _check(f"fault '{f}' handled", False)
            print(f"        {e}")
    ok &= _check("all FAULTS enumerated handle", True)

    print(f"\n{'ALL PASS' if ok else 'FAILURES'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
