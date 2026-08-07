"""Pivot point computation — pure function, no DB."""

from typing import Dict, Optional


def compute_pivots(
    prev_day_high: Optional[float],
    prev_day_low: Optional[float],
    prev_day_close: Optional[float],
) -> Dict:
    if not all([prev_day_high, prev_day_low, prev_day_close]):
        return {
            "pivot_pp": None,
            "pivot_r1": None,
            "pivot_r2": None,
            "pivot_r3": None,
            "pivot_s1": None,
            "pivot_s2": None,
            "pivot_s3": None,
            "cpr_tc": None,
            "cpr_bc": None,
            "cpr_width": None,
            "cpr_width_pct": None,
        }
    pp = round((prev_day_high + prev_day_low + prev_day_close) / 3, 2)
    r1 = round(2 * pp - prev_day_low, 2)
    r2 = round(pp + (prev_day_high - prev_day_low), 2)
    r3 = round(prev_day_high + 2 * (pp - prev_day_low), 2)
    s1 = round(2 * pp - prev_day_high, 2)
    s2 = round(pp - (prev_day_high - prev_day_low), 2)
    s3 = round(prev_day_low - 2 * (prev_day_high - pp), 2)
    # CPR (Central Pivot Range): BC = (H+L)/2, TC = Pivot + (Pivot - BC)
    bc = round((prev_day_high + prev_day_low) / 2, 2)
    tc = round(2 * pp - bc, 2)
    cpr_width = round(tc - bc, 2)
    cpr_width_pct = round(cpr_width / pp * 100, 3) if pp else None
    return {
        "pivot_pp": pp,
        "pivot_r1": r1,
        "pivot_r2": r2,
        "pivot_r3": r3,
        "pivot_s1": s1,
        "pivot_s2": s2,
        "pivot_s3": s3,
        "cpr_tc": tc,
        "cpr_bc": bc,
        "cpr_width": cpr_width,
        "cpr_width_pct": cpr_width_pct,
    }
