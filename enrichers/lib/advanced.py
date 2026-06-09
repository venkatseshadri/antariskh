"""Advanced indicators — IV rank, HV, session metrics, pivot clusters.

Lifted from varaha_advanced_indicators.py. Refactored to accept
pre-fetched data instead of DB connections (pure functions).
"""

import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import numpy as np


def compute_iv_rank(current_vix: Optional[float], vix_history: List[float]) -> Dict:
    """IV Rank from pre-fetched VIX history (252 daily readings)."""
    if not current_vix or current_vix <= 0:
        return {
            "iv_current": None,
            "iv_52w_high": None,
            "iv_52w_low": None,
            "iv_rank": None,
            "iv_regime": None,
        }

    if not vix_history or len(vix_history) < 10:
        return {
            "iv_current": current_vix,
            "iv_52w_high": None,
            "iv_52w_low": None,
            "iv_rank": None,
            "iv_regime": None,
        }

    vix_high = max(vix_history)
    vix_low = min(vix_history)

    if vix_high == vix_low:
        iv_rank = 50.0
    else:
        iv_rank = ((current_vix - vix_low) / (vix_high - vix_low)) * 100
        iv_rank = max(0, min(100, iv_rank))

    if iv_rank < 33:
        regime = "low"
    elif iv_rank < 67:
        regime = "mid"
    else:
        regime = "high"

    return {
        "iv_current": round(current_vix, 2),
        "iv_52w_high": round(vix_high, 2),
        "iv_52w_low": round(vix_low, 2),
        "iv_rank": round(iv_rank, 1),
        "iv_regime": regime,
    }


def compute_iv_term_structure(
    weekly_iv: Optional[float], monthly_iv: Optional[float]
) -> Dict:
    """IV term structure from pre-fetched avg IVs."""
    if not weekly_iv or not monthly_iv:
        return {"iv_short": None, "iv_long": None, "iv_slope": None}
    slope = monthly_iv - weekly_iv
    return {
        "iv_short": round(weekly_iv, 2),
        "iv_long": round(monthly_iv, 2),
        "iv_slope": round(slope, 2),
    }


def compute_historical_volatility(buf) -> Dict:
    """HV-20 and HV-60 from IndicatorBuffer."""
    result = {"hv_20": None, "hv_60": None}
    if len(buf.buf) < 5:
        return result

    try:
        closes = [b["close"] for b in list(buf.buf)[-min(100, len(buf.buf)) :]]
        if len(closes) < 2:
            return result

        log_returns = [
            math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))
        ]

        if len(log_returns) >= 20:
            hv_20_std = float(np.std(log_returns[-20:]))
            result["hv_20"] = round(hv_20_std * math.sqrt(252) * 100, 2)

        if len(log_returns) >= 60:
            hv_60_std = float(np.std(log_returns[-60:]))
            result["hv_60"] = round(hv_60_std * math.sqrt(252) * 100, 2)
        elif len(log_returns) >= 20:
            hv_60_std = float(np.std(log_returns))
            result["hv_60"] = round(hv_60_std * math.sqrt(252) * 100, 2)

        return result
    except Exception:
        return result


def _coerce_dt(ts: Optional[object]) -> Optional[datetime]:
    """Best-effort parse of a bar timestamp (datetime or ISO-ish string) to a
    datetime. Returns None if it can't, so the caller falls back to now()."""
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "").strip()[:19])
    except (ValueError, TypeError):
        return None


def compute_session_metrics(
    spot: float,
    open_price: Optional[float],
    prev_close: Optional[float],
    pivot_pp: Optional[float],
    pivot_r1: Optional[float],
    pivot_s1: Optional[float],
    bar_ts: Optional[object] = None,
) -> Dict:
    # Derive the phase from the BAR's own timestamp, not wall-clock. A backfill
    # enrich run (e.g. nightly at 21:30) would otherwise stamp every bar "late"
    # because datetime.now() is past the close — poisoning session_phase for the
    # whole day. Live callers pass the live tick ts (or None → now()).
    now = _coerce_dt(bar_ts) or datetime.now()
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)

    if now < market_open:
        phase = "pre"
    elif now < market_open + timedelta(minutes=90):
        phase = "early"
    elif now > market_close - timedelta(minutes=60):
        phase = "late"
    else:
        phase = "mid"

    dist_to_pivot = None
    dist_to_r1 = None
    dist_to_s1 = None

    if spot and pivot_pp:
        dist_to_pivot = round(((spot - pivot_pp) / pivot_pp) * 100, 3)
    if spot and pivot_r1:
        dist_to_r1 = round(((spot - pivot_r1) / pivot_r1) * 100, 3)
    if spot and pivot_s1:
        dist_to_s1 = round(((spot - pivot_s1) / pivot_s1) * 100, 3)

    open_to_current_pct = None
    if spot and open_price and open_price > 0:
        open_to_current_pct = round(((spot - open_price) / open_price) * 100, 3)

    return {
        "session_phase": phase,
        "open_to_current_pct": open_to_current_pct,
        "distance_to_pivot_pct": dist_to_pivot,
        "distance_to_r1_pct": dist_to_r1,
        "distance_to_s1_pct": dist_to_s1,
    }


def compute_pivot_clusters(
    pivot_levels: List[float], current_spot: float, atr: float
) -> Dict:
    """Find support/resistance clusters from pre-fetched pivot levels."""
    if not pivot_levels or len(pivot_levels) < 5:
        return {
            "cluster_support": None,
            "cluster_resistance": None,
            "distance_to_support": None,
            "distance_to_resistance": None,
        }

    levels = sorted(pivot_levels)
    if atr <= 0:
        atr = 100

    clusters = []
    current_cluster = [levels[0]]
    for i in range(1, len(levels)):
        if abs(levels[i] - current_cluster[-1]) <= atr:
            current_cluster.append(levels[i])
        else:
            if len(current_cluster) >= 2:
                clusters.append(sum(current_cluster) / len(current_cluster))
            current_cluster = [levels[i]]
    if len(current_cluster) >= 2:
        clusters.append(sum(current_cluster) / len(current_cluster))

    support = [c for c in clusters if c < current_spot]
    resistance = [c for c in clusters if c > current_spot]

    nearest_support = max(support) if support else None
    nearest_resistance = min(resistance) if resistance else None

    return {
        "cluster_support": round(nearest_support, 2) if nearest_support else None,
        "cluster_resistance": round(nearest_resistance, 2)
        if nearest_resistance
        else None,
        "distance_to_support": round(current_spot - nearest_support, 2)
        if nearest_support
        else None,
        "distance_to_resistance": round(nearest_resistance - current_spot, 2)
        if nearest_resistance
        else None,
    }
