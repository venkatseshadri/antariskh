"""SMC (Smart Money Concepts) analysis — lifted verbatim from varaha_smc_and_logger.py.

Pure function — operates on IndicatorBuffer, no DB/Redis/broker.
"""

from typing import Dict, List, Optional


def compute_smc_indicators(buf) -> Dict:
    if len(buf.buf) < 5:
        return {
            "ob_zone_high": None,
            "ob_zone_low": None,
            "ob_strength": 0,
            "fvg_high": None,
            "fvg_low": None,
            "fvg_mitigated": False,
            "swing_high": None,
            "swing_low": None,
            "liquidity_swept": False,
            "structure_type": None,
            "structure_confirmed": False,
            "next_target": None,
            "smc_strength": None,
        }

    result = {}
    window = 50
    candles = list(buf.buf)[-window:]

    result.update(_find_order_blocks(candles))
    result.update(_find_fvg(candles))
    result.update(_find_liquidity_levels(candles))
    result.update(_analyze_structure(candles[-10:]))
    result["smc_strength"] = _score_smc(result)
    return result


def _find_order_blocks(candles: List[Dict]) -> Dict:
    if len(candles) < 10:
        return {"ob_zone_high": None, "ob_zone_low": None, "ob_strength": 0}

    closes = [c["close"] for c in candles[-20:]]
    atr = _calculate_atr(candles[-14:])

    for i in range(len(closes) - 4):
        window = closes[i : i + 4]
        if max(window) - min(window) <= atr * 0.5:
            return {
                "ob_zone_high": max(window),
                "ob_zone_low": min(window),
                "ob_strength": len(window),
            }
    return {"ob_zone_high": None, "ob_zone_low": None, "ob_strength": 0}


def _find_fvg(candles: List[Dict]) -> Dict:
    if len(candles) < 2:
        return {"fvg_high": None, "fvg_low": None, "fvg_mitigated": False}

    current = candles[-1]
    prev = candles[-2]
    atr = _calculate_atr(candles[-14:])

    if prev["low"] < current["high"] and prev["close"] < current["low"]:
        gap_size = current["low"] - prev["high"]
        if gap_size > atr * 0.2:
            return {
                "fvg_high": current["low"],
                "fvg_low": prev["high"],
                "fvg_mitigated": current["low"] <= prev["close"],
            }

    if prev["high"] > current["low"] and prev["close"] > current["high"]:
        gap_size = prev["low"] - current["high"]
        if gap_size > atr * 0.2:
            return {
                "fvg_high": prev["low"],
                "fvg_low": current["high"],
                "fvg_mitigated": current["high"] >= prev["close"],
            }

    return {"fvg_high": None, "fvg_low": None, "fvg_mitigated": False}


def _find_liquidity_levels(candles: List[Dict]) -> Dict:
    if len(candles) < 5:
        return {"swing_high": None, "swing_low": None, "liquidity_swept": False}

    last_20 = candles[-20:]
    swing_high = max(c["high"] for c in last_20)
    swing_low = min(c["low"] for c in last_20)
    current_close = candles[-1]["close"]
    liquidity_swept = current_close > swing_high or current_close < swing_low

    return {
        "swing_high": swing_high,
        "swing_low": swing_low,
        "liquidity_swept": liquidity_swept,
    }


def _analyze_structure(recent: List[Dict]) -> Dict:
    if len(recent) < 2:
        return {
            "structure_type": None,
            "structure_confirmed": False,
            "next_target": None,
        }

    highs = [c["high"] for c in recent]
    lows = [c["low"] for c in recent]

    if highs[-1] > highs[-2] and lows[-1] > lows[-2]:
        structure = "HH"
    elif highs[-1] < highs[-2] and lows[-1] < lows[-2]:
        structure = "LL"
    else:
        structure = "HH" if highs[-1] > highs[-2] else "LL"

    next_target = None
    if structure == "HH":
        next_target = highs[-1] + (highs[-1] - highs[-2])
    elif structure == "LL":
        next_target = lows[-1] - (lows[-2] - lows[-1])

    return {
        "structure_type": structure,
        "structure_confirmed": len(recent) >= 4,
        "next_target": next_target,
    }


def _calculate_atr(candles: List[Dict], period: int = 14) -> float:
    if len(candles) < period:
        return 0
    tr_values = []
    for i in range(len(candles)):
        if i == 0:
            tr = candles[i]["high"] - candles[i]["low"]
        else:
            tr = max(
                candles[i]["high"] - candles[i]["low"],
                abs(candles[i]["high"] - candles[i - 1]["close"]),
                abs(candles[i]["low"] - candles[i - 1]["close"]),
            )
        tr_values.append(tr)
    return sum(tr_values[-period:]) / period


def _score_smc(smc: Dict) -> Optional[float]:
    score = 0
    count = 0
    if smc.get("ob_strength", 0) >= 3:
        score += 25
        count += 1
    if smc.get("fvg_high") and not smc.get("fvg_mitigated"):
        score += 25
        count += 1
    if smc.get("liquidity_swept"):
        score += 25
        count += 1
    if smc.get("structure_confirmed"):
        score += 25
        count += 1
    return (score / (count * 25) * 100) if count > 0 else None
