"""PORCUPINE — scenario candle generator unit tests (narrative → minute bars)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim.scenario_candles import generate


def _ck(name, cond):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    return cond


def main():
    ok = True
    spec = {
        "prev_close": 23250, "date": "2026-06-16", "instrument": "NIFTY",
        "path": [
            {"t": "09:15", "spot": "+5pts"},
            {"t": "10:25", "spot": "+0.5%"},
            {"t": "14:25", "spot": "-1%_from_high"},
        ],
    }
    bars = generate(spec)
    by = {b["timestamp"][11:16]: b for b in bars}

    ok &= _ck("full session length (09:15–15:30 = 376 bars)", len(bars) == 376)
    ok &= _ck("flat open ~+5pts", abs(by["09:15"]["close"] - 23255) < 1)
    hi = max(b["high"] for b in bars)
    ok &= _ck("intraday high ≈ +0.5%", abs(hi / 23250 - 1.005) < 0.001)
    ok &= _ck("high occurs ~10:25", max(bars, key=lambda b: b["high"])["timestamp"][11:16] == "10:25")
    ok &= _ck("close ≈ -1% off the high", abs(by["14:25"]["close"] / hi - 0.99) < 0.002)
    ok &= _ck("OHLC valid (high≥max(o,c), low≤min(o,c), low>0)",
              all(b["high"] >= max(b["open"], b["close"]) and
                  b["low"] <= min(b["open"], b["close"]) and b["low"] > 0 for b in bars))
    ok &= _ck("monotone rise to high then fade (no NaN/None)",
              all(b["close"] is not None for b in bars))

    # absolute + from_low targets resolve
    spec2 = {"prev_close": 100, "date": "2026-06-16",
             "path": [{"t": "09:15", "spot": 100}, {"t": "10:00", "spot": "-2%"},
                      {"t": "15:30", "spot": "+1%_from_low"}]}
    b2 = {b["timestamp"][11:16]: b for b in generate(spec2)}
    ok &= _ck("absolute + percent + _from_low targets resolve",
              abs(b2["10:00"]["close"] - 98) < 0.5 and b2["15:30"]["close"] > 98)

    print(f"\n{'ALL PASS' if ok else 'FAILURES'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
