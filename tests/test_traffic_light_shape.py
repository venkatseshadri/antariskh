#!/usr/bin/env python3
"""Regression: traffic-light scorer must read get_live_candles' string shape.

get_live_candles returns candles_by_tf values as plain "GREEN"/"RED" strings.
The old dict-only check (`isinstance(c, dict)`) scored every TF "neutral",
so the traffic-light family was permanently NEUTRAL 0% — half the canonical
entry signal was dead in production (found during SHERPA Phase 2, 2026-06-11).
"""

import importlib.util
import sys
from pathlib import Path


def _load_entry_tools():
    path = Path(__file__).parent.parent / "tools" / "entry_tools.py"
    spec = importlib.util.spec_from_file_location("antariksh_entry_tools", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    et = _load_entry_tools()
    failures = []

    # Bullish-continuation day in the REAL get_live_candles string shape
    # (higher TFs GREEN, lower TFs RED → green_weight 6.25 (60m+240m+1440m) → BULLISH_CONTINUATION;
    # deliberately NOT all-green, which is MOMENTUM_PEAK = exhaustion, score 0)
    bull_colors = {"1m": "RED", "5m": "RED", "15m": "RED",
                   "30m": "RED", "60m": "GREEN", "240m": "GREEN", "1440m": "GREEN"}
    et.get_live_candles = lambda index="NIFTY", lookback_bars=360: {
        "latest_1m": {"open": 100, "close": 101, "timestamp": "2026-06-11 10:00:00"},
        "candles_by_tf": dict(bull_colors),
        "n_bars": 100,
    }
    et._get_gap_from_redis = lambda index, latest: {"gap": "none"}
    et._compute_completion_by_tf = lambda: {
        tf: 1.0 for tf in ["1m", "5m", "15m", "30m", "60m", "240m", "1440m"]
    }

    res = et.score_traffic_light_redis("NIFTY")
    if res["signal"] != "BULLISH":
        failures.append(f"bullish-continuation day scored {res['signal']} (expected "
                        f"BULLISH) — string candles ignored again? {res['reasoning']}")

    # All-RED day
    et.get_live_candles = lambda index="NIFTY", lookback_bars=360: {
        "latest_1m": {"open": 101, "close": 100, "timestamp": "2026-06-11 10:00:00"},
        "candles_by_tf": {tf: "RED" for tf in
                          ["1m", "5m", "15m", "30m", "60m", "240m", "1440m"]},
        "n_bars": 100,
    }
    res = et.score_traffic_light_redis("NIFTY")
    if res["signal"] != "BEARISH":
        failures.append(f"all-RED day scored {res['signal']} (expected BEARISH)")

    # no_data stays neutral
    et.get_live_candles = lambda index="NIFTY", lookback_bars=360: {
        "latest_1m": None,
        "candles_by_tf": {tf: "no_data" for tf in ["1m", "5m"]},
        "n_bars": 0,
    }
    res = et.score_traffic_light_redis("NIFTY")
    if res["signal"] != "NEUTRAL":
        failures.append(f"no_data day scored {res['signal']} (expected NEUTRAL)")

    if failures:
        for f in failures:
            print(f"  FAIL: {f}")
        return 1
    print("  OK traffic-light-shape 3/3")
    return 0


if __name__ == "__main__":
    sys.exit(main())
