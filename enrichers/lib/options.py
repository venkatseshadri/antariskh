"""PCR + OI analysis — pure functions taking option chain data as input.

Lifted from varaha_advanced_indicators.py, but refactored to accept
pre-fetched data instead of DB connections.
"""

from typing import Dict, List, Optional, Tuple


def compute_pcr(option_data: List[Dict], atm_strike: int, step: int = 50) -> Dict:
    """Compute PCR from option chain data.

    Args:
        option_data: list of dicts with keys: strike, option_type ('CE'/'PE'), oi
        atm_strike: current ATM strike
        step: strike step (50 for NIFTY)
    """
    if not option_data:
        return {"pcr_total": None, "pcr_atm": None, "sentiment": None}

    calls_oi = sum(d["oi"] for d in option_data if d["option_type"] == "CE" and d.get("oi"))
    puts_oi = sum(d["oi"] for d in option_data if d["option_type"] == "PE" and d.get("oi"))

    if not calls_oi or calls_oi <= 0:
        return {"pcr_total": None, "pcr_atm": None, "sentiment": None}

    pcr_total = puts_oi / calls_oi

    atm_strikes = [atm_strike - step, atm_strike, atm_strike + step]
    atm_calls_oi = sum(
        d["oi"]
        for d in option_data
        if d["option_type"] == "CE" and d["strike"] in atm_strikes and d.get("oi")
    )
    atm_puts_oi = sum(
        d["oi"]
        for d in option_data
        if d["option_type"] == "PE" and d["strike"] in atm_strikes and d.get("oi")
    )

    pcr_atm = None
    if atm_calls_oi and atm_calls_oi > 0 and atm_puts_oi:
        pcr_atm = atm_puts_oi / atm_calls_oi

    if pcr_total > 1.0:
        sentiment = "bearish"
    elif pcr_total > 0.8:
        sentiment = "neutral"
    else:
        sentiment = "bullish"

    return {
        "pcr_total": round(pcr_total, 3),
        "pcr_atm": round(pcr_atm, 3) if pcr_atm else None,
        "sentiment": sentiment,
    }


def compute_oi_analysis(option_data: List[Dict], atm_strike: int, step: int = 50) -> Dict:
    """Compute OI analysis from option chain data — true Max Pain.

    Max Pain = strike where total pain is minimized:
      Pain(k) = Σ(Call_oi[i] * 1 for strikes[i] <= k) + Σ(Put_oi[i] * 1 for strikes[i] >= k)
    I.e. sum of CE OI for strikes at or below k (ITM calls at expiry)
    + sum of PE OI for strikes at or above k (ITM puts at expiry).
    Lowest total = least amount option writers lose → strongest magnetic pull.
    """
    if not option_data:
        return _empty_oi()
    nearby = [d for d in option_data if abs(d["strike"] - atm_strike) <= 250]
    if not nearby:
        return _empty_oi()

    # Build OI map per strike
    strikes = sorted(set(d["strike"] for d in nearby))
    ce_oi = {}
    pe_oi = {}
    for d in nearby:
        if d["option_type"] == "CE":
            ce_oi[d["strike"]] = ce_oi.get(d["strike"], 0) + (d.get("oi") or 0)
        else:
            pe_oi[d["strike"]] = pe_oi.get(d["strike"], 0) + (d.get("oi") or 0)

    # Max Pain: for each strike, total = sum(CE OI below) + sum(PE OI above)
    # Precompute prefix sums for efficiency
    total_ce = sum(ce_oi.values())
    total_pe = sum(pe_oi.values())
    ce_below = 0
    min_pain = float("inf")
    max_pain_strike = atm_strike
    for k in strikes:
        ce_below += ce_oi.get(k, 0)
        # PE above = total_pe - PE below (exclusive of k for puts above)
        pe_below = sum(pe_oi.get(s, 0) for s in strikes if s < k)
        pe_above = total_pe - pe_below
        pain = ce_below + pe_above
        if pain < min_pain:
            min_pain = pain
            max_pain_strike = k

    total_call_oi = sum(d.get("oi", 0) for d in nearby if d["option_type"] == "CE")
    total_put_oi = sum(d.get("oi", 0) for d in nearby if d["option_type"] == "PE")

    call_concentration = None
    put_concentration = None
    total = total_call_oi + total_put_oi
    if total > 0:
        call_concentration = round((total_call_oi / total) * 100, 1)
        put_concentration = round((total_put_oi / total) * 100, 1)

    oi_skew = round(total_put_oi / total_call_oi, 2) if total_call_oi > 0 else None

    return {
        "max_pain_strike": max_pain_strike,
        "call_oi_concentration": call_concentration,
        "put_oi_concentration": put_concentration,
        "oi_skew": oi_skew,
    }


def _empty_oi() -> Dict:
    return {
        "max_pain_strike": None,
        "call_oi_concentration": None,
        "put_oi_concentration": None,
        "oi_skew": None,
    }
