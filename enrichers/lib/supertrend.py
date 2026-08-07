"""Multi-timeframe SuperTrend — lifted verbatim from varaha_multiframe_supertrend.py.

Pure function — operates on IndicatorBuffer, no DB/Redis/broker.
"""

from typing import Dict, Optional

import numpy as np


def compute_multiframe_supertrend(
    buf, period: int = 10, multiplier: float = 3.0
) -> Dict:
    result = {
        "st_5min_direction": None,
        "st_5min_value": None,
        "st_15min_direction": None,
        "st_15min_value": None,
        "st_consensus": None,
    }

    if len(buf.buf) < period:
        return result

    try:
        opens_5m, highs_5m, lows_5m, closes_5m = _aggregate_to_timeframe(buf, 5)
        if closes_5m is not None and len(closes_5m) >= period:
            st_5m = _st_from_bars(highs_5m, lows_5m, closes_5m, period, multiplier)
            result["st_5min_direction"] = st_5m["direction"]
            result["st_5min_value"] = st_5m["value"]
    except Exception:
        pass

    try:
        opens_15m, highs_15m, lows_15m, closes_15m = _aggregate_to_timeframe(buf, 15)
        if closes_15m is not None and len(closes_15m) >= period:
            st_15m = _st_from_bars(highs_15m, lows_15m, closes_15m, period, multiplier)
            result["st_15min_direction"] = st_15m["direction"]
            result["st_15min_value"] = st_15m["value"]
    except Exception:
        pass

    # 15m is the primary trend read (Board decision 2026-07-02): higher timeframe wins
    # outright on disagreement instead of abstaining to "mixed". 5m is a fallback only
    # when 15m has no data yet (early session / short buffer).
    if result["st_15min_direction"] is not None:
        result["st_consensus"] = result["st_15min_direction"]
    elif result["st_5min_direction"] is not None:
        result["st_consensus"] = result["st_5min_direction"]

    return result


def _aggregate_to_timeframe(buf, minutes: int):
    # Only the LATEST contiguous run counts as "current" data (IndicatorBuffer.
    # latest_contiguous_candles() — shared with smc.py's structure detection, same
    # class of bug, same fix). A chunk built purely from an old, internally-gap-free
    # stretch (e.g. entirely yesterday's bars) would still be real data, just STALE,
    # and reporting it as today's signal is the same bug as bridging the gap outright.
    candles = buf.latest_contiguous_candles()
    if len(candles) < minutes:
        return None, None, None, None

    opens, highs, lows, closes = [], [], [], []
    chunk: list = []
    for candle in candles:
        chunk.append(candle)
        if len(chunk) == minutes:
            opens.append(chunk[0]["open"])
            highs.append(max(c["high"] for c in chunk))
            lows.append(min(c["low"] for c in chunk))
            closes.append(chunk[-1]["close"])
            chunk = []

    if len(closes) < 2:
        return None, None, None, None
    return np.array(opens), np.array(highs), np.array(lows), np.array(closes)


def _st_from_bars(highs, lows, closes, period=10, multiplier=3.0) -> Dict:
    if len(closes) < period:
        return {"direction": None, "value": None}

    st_array, direction_array = _calculate_supertrend(
        highs, lows, closes, period, multiplier
    )
    latest_st = float(st_array[-1]) if not np.isnan(st_array[-1]) else None
    latest_dir = direction_array[-1]
    direction_str = (
        "bullish" if latest_dir > 0 else ("bearish" if latest_dir < 0 else None)
    )
    return {
        "direction": direction_str,
        "value": round(latest_st, 2) if latest_st else None,
    }


def _calculate_supertrend(highs, lows, closes, period=10, multiplier=3.0):
    atr = _calculate_atr(highs, lows, closes, period)
    hl2 = (highs + lows) / 2.0
    basic_ub = hl2 + multiplier * atr
    basic_lb = hl2 - multiplier * atr
    final_ub = np.copy(basic_ub)
    final_lb = np.copy(basic_lb)

    for i in range(1, len(closes)):
        if basic_ub[i] < final_ub[i - 1] or closes[i - 1] > final_ub[i - 1]:
            final_ub[i] = basic_ub[i]
        else:
            final_ub[i] = final_ub[i - 1]
        if basic_lb[i] > final_lb[i - 1] or closes[i - 1] < final_lb[i - 1]:
            final_lb[i] = basic_lb[i]
        else:
            final_lb[i] = final_lb[i - 1]

    st = np.zeros_like(closes)
    direction = np.zeros(len(closes), dtype=int)
    st[0] = final_ub[0]
    direction[0] = -1

    for i in range(1, len(closes)):
        if st[i - 1] == final_ub[i - 1]:
            st[i] = final_ub[i] if closes[i] <= final_ub[i] else final_lb[i]
            direction[i] = -1 if closes[i] <= final_ub[i] else 1
        else:
            st[i] = final_lb[i] if closes[i] >= final_lb[i] else final_ub[i]
            direction[i] = 1 if closes[i] >= final_lb[i] else -1

    return st, direction


def _calculate_atr(highs, lows, closes, period=14):
    tr = np.zeros_like(closes)
    tr[0] = highs[0] - lows[0]
    for i in range(1, len(closes)):
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
    atr = np.zeros_like(closes)
    atr[:period] = np.mean(tr[:period])
    for i in range(period, len(tr)):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return atr
