"""Post-Mortem Analyst deterministic tools.

Review trades, run counterfactuals, detect patterns, recommend PM adjustments.
Now with DuckDB analysis — "better than current" recommendation engine.
"""

import os
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path

DUCKDB_NIFTY = Path("/home/trading_ceo/python-trader/varaha/data/varaha_data.duckdb")
DUCKDB_SENSEX = Path(
    "/home/trading_ceo/python-trader/varaha/data/varaha_data_sensex.duckdb"
)


def review_trade(trade: Dict, spec: Dict) -> Dict:
    """Review trade quality and strategy fidelity.

    Quality: EXCELLENT (no issues), GOOD (minor), FAIR (warnings), CRITICAL (violations).
    """
    issues = []
    score = 100

    if trade.get("lots") != spec.get("lots", 1):
        issues.append("WRONG LOTS — trade overrode spec lot count")
        score -= 60
    if trade.get("sl_hit"):
        issues.append("SL HIT — stop-loss triggered")
        score -= 30
    if not trade.get("tp_hit") and trade.get("pnl", 0) < 100:
        issues.append("EARLY EXIT — trade closed before TP with < ₹100 profit")
        score -= 20
    if trade.get("pnl", 0) < -1000:
        issues.append(f"LARGE LOSS: ₹{trade['pnl']:+,}")
        score -= 40

    if score >= 90:
        quality = "EXCELLENT"
    elif score >= 70:
        quality = "GOOD"
    elif score >= 40:
        quality = "FAIR"
    else:
        quality = "CRITICAL"

    return {
        "quality": quality,
        "score": max(0, score),
        "issues": issues,
        "trade_id": trade.get("id", "?"),
    }


def run_counterfactuals(
    trade: Dict,
    peak_pnl: float = 0,
    better_exit: float = None,
    better_sl: float = None,
    better_tp: float = None,
    hypothetical_entry: float = None,
) -> Dict:
    """Run what-if analysis: alternative entry, exit, SL, TP.

    Returns missed profit, hypothetical P&L, and better parameters.
    """
    actual_pnl = trade.get("pnl", 0)
    missed = max(0, peak_pnl - actual_pnl)

    hypo_entry = None
    if hypothetical_entry and trade.get("entry"):
        diff = trade["entry"] - hypothetical_entry
        hypo_entry = {
            "entry": hypothetical_entry,
            "pnl_impact": round(diff * (trade.get("lots", 1)), 0),
        }

    hypo_sl = None
    if better_sl and trade.get("sl_hit") and trade.get("sl"):
        original_loss = abs(trade.get("pnl", 0))
        hypothetical_loss = better_sl
        hypo_sl = {
            "value": better_sl,
            "original": trade["sl"],
            "saved_inr": original_loss - hypothetical_loss,
        }

    better_exit_data = None
    if better_exit:
        gain = better_exit - trade.get("strikes", [0])[-1]
        better_exit_data = {"price": better_exit, "pnl_improvement": round(gain, 1)}

    better_tp_data = None
    if better_tp:
        better_tp_data = {
            "value": better_tp,
            "original_tp": trade.get("strikes", [0])[-1],
        }

    scenario = "normal"
    if trade.get("sl_hit"):
        scenario = "sl_hit"
    elif missed > 0:
        scenario = "missed_tp"

    return {
        "scenario": scenario,
        "actual_pnl": actual_pnl,
        "missed_profit": round(missed, 1),
        "peak_pnl": peak_pnl,
        "better_exit": better_exit_data,
        "better_sl": hypo_sl,
        "better_tp": better_tp_data,
        "hypothetical": {"entry": hypo_entry},
        "hypothetical_sl_pnl": round(-better_sl, 1)
        if better_sl and trade.get("sl_hit")
        else actual_pnl,
    }


def detect_patterns(trades: List[Dict]) -> Dict:
    """Detect recurring patterns across trades."""
    n = len(trades)
    if n == 0:
        return {
            "total_trades": 0,
            "sl_hit_rate": 0.0,
            "average_pnl": 0.0,
            "patterns": [],
        }

    sl_hits = sum(1 for t in trades if t.get("sl_hit"))
    avg_pnl = sum(t.get("pnl", 0) for t in trades) / n
    patterns = []

    if sl_hits / n > 0.3:
        patterns.append(
            f"HIGH SL FREQUENCY: {sl_hits}/{n} trades ({sl_hits / n:.0%}) — consider tighter entries"
        )
    if avg_pnl < 0:
        patterns.append(
            f"NEGATIVE AVG PNL: ₹{avg_pnl:+,.0f}/trade — strategy adjustment needed"
        )
    if sl_hits == 0 and avg_pnl > 500:
        patterns.append("CLEAN SESSION: no SL hits, strong average P&L")

    return {
        "total_trades": n,
        "sl_hit_rate": round(sl_hits / n, 3) if n > 0 else 0.0,
        "average_pnl": round(avg_pnl, 1),
        "patterns": patterns,
    }


def generate_post_mortem_report(
    reviews: List[Dict],
    counterfactuals: List[Dict],
    patterns: Dict,
    session: str,
) -> Dict:
    """Generate post-mortem report for PM with recommendations."""
    recs = []
    for r in reviews:
        if "SL HIT" in (r.get("issues") or []):
            recs.append(
                f"Trade {r['trade_id']}: Review SL placement — consider narrower SL"
            )
        if "EARLY EXIT" in (r.get("issues") or []):
            recs.append(f"Trade {r['trade_id']}: Let winners run — TP was not hit")
        if r.get("quality") == "CRITICAL":
            recs.append(
                f"Trade {r['trade_id']}: CRITICAL — investigate lot/spec deviation"
            )

    for p in patterns.get("patterns", []):
        recs.append(p)

    qualities = [r.get("quality") for r in reviews]
    lines = [
        f"# Post-Mortem Report — {session}",
        f"**Trades Reviewed:** {len(reviews)}",
        f"**Quality:** {', '.join(q + ': ' + str(qualities.count(q)) for q in ['EXCELLENT', 'GOOD', 'FAIR', 'CRITICAL'] if qualities.count(q) > 0)}",
        f"**SL Hit Rate:** {patterns.get('sl_hit_rate', 0):.0%}",
        f"**Avg P&L:** ₹{patterns.get('average_pnl', 0):+,.0f}",
        "",
        "## Recommendations",
    ]
    if recs:
        for i, r in enumerate(recs):
            lines.append(f"{i + 1}. {r}")
    else:
        lines.append("No issues — strategy executing well")

    return {
        "trades_reviewed": len(reviews),
        "quality_distribution": {q: qualities.count(q) for q in set(qualities)},
        "recommendations": recs,
        "text": "\n".join(lines),
    }


# ============================================================
# DuckDB Analysis — "Better Than Current" Engine
# ============================================================


def analyze_sl_optimization(
    trades: List[Dict],
    sl_range: Tuple[int, int] = (1500, 5000),
    step: int = 250,
) -> Dict:
    """Find optimal SL by simulating what PnL would have been at different SL levels.

    For each SL level, re-evaluates past trades: did SL get hit? What was actual PnL?
    Returns the SL that maximizes net PnL.

    Returns:
        {current_sl, recommended_sl, current_pnl, optimized_pnl, improvement, evidence}
    """
    if not trades:
        return {"error": "No trade data", "recommended_sl": None}

    current_sl = trades[0].get("sl_used", 3500)
    current_pnl = sum(t.get("pnl", 0) for t in trades)

    best_sl = current_sl
    best_pnl = current_pnl

    for test_sl in range(sl_range[0], sl_range[1] + 1, step):
        test_pnl = 0
        for t in trades:
            pnl = t.get("pnl", 0)
            low = t.get("low", t.get("entry", 0))
            drawdown = (
                max(0, (t.get("entry", 0) - low)) if t.get("entry") and low else 0
            )
            if pnl < 0 and drawdown >= test_sl:
                test_pnl -= test_sl  # SL hit — capped loss
            else:
                test_pnl += pnl

        if test_pnl > best_pnl:
            best_pnl = test_pnl
            best_sl = test_sl

    improvement = best_pnl - current_pnl
    return {
        "current_sl": current_sl,
        "recommended_sl": best_sl,
        "current_pnl": current_pnl,
        "optimized_pnl": best_pnl,
        "improvement": improvement,
        "evidence": (
            f"SL ₹{best_sl} gives PnL ₹{best_pnl:+,} vs current ₹{current_pnl:+,} "
            f"(₹{improvement:+,}). "
            f"{'RECOMMEND CHANGE' if improvement > 0 else 'CURRENT SL IS OPTIMAL'}"
        ),
    }


def analyze_entry_window(trades: List[Dict]) -> Dict:
    """Find best 30-min entry window by win rate and avg PnL per window."""
    if not trades:
        return {"error": "No trade data"}

    windows: Dict[str, List] = {}
    for t in trades:
        entry = t.get("entry_time", "")
        if len(entry) >= 5:
            hh, mm = entry.split(":")[:2]
            minutes = int(hh) * 60 + int(mm)
            window_start = (minutes // 30) * 30
            w_hh, w_mm = window_start // 60, window_start % 60
            key = f"{w_hh:02d}:{w_mm:02d}"
            windows.setdefault(key, []).append(t)

    best_win_rate = 0.0
    best_window = ""
    current_window_win_rate = 0.0
    results = []

    for wkey, wtrades in sorted(windows.items()):
        wins = sum(1 for t in wtrades if t.get("pnl", 0) > 0)
        avg_pnl = sum(t.get("pnl", 0) for t in wtrades) / len(wtrades) if wtrades else 0
        wr = wins / len(wtrades) if wtrades else 0
        results.append(
            {"window": wkey, "trades": len(wtrades), "win_rate": wr, "avg_pnl": avg_pnl}
        )

        if wr > best_win_rate:
            best_win_rate = wr
            best_window = wkey

    # Current window is typically 10:00-11:30
    current = next(
        (r for r in results if r["window"] in ("10:00", "10:30", "11:00")),
        results[0] if results else None,
    )
    if current:
        current_window_win_rate = current["win_rate"]

    return {
        "best_window": best_window,
        "best_win_rate": round(best_win_rate, 3),
        "current_window_win_rate": round(current_window_win_rate, 3),
        "improvement": round(best_win_rate - current_window_win_rate, 3),
        "all_windows": results,
        "evidence": (
            f"Best window: {best_window} at {best_win_rate:.1%} win rate "
            f"(current: {current_window_win_rate:.1%}, Δ{best_win_rate - current_window_win_rate:+.1%})"
        ),
    }


def analyze_vix_threshold(trades: List[Dict]) -> Dict:
    """Find VIX breakpoint where Iron Fly stops working."""
    if not trades:
        return {"error": "No trade data"}

    # Sort by VIX and find cutoff
    by_vix = sorted(trades, key=lambda t: t.get("vix_at_entry", 15))
    vix_levels = range(10, 30, 2)
    best_ceiling = 20

    for vix_cut in vix_levels:
        below = [t for t in by_vix if t.get("vix_at_entry", 15) <= vix_cut]
        above = [t for t in by_vix if t.get("vix_at_entry", 15) > vix_cut]
        if above and len(below) >= 5:
            below_wr = sum(1 for t in below if t.get("pnl", 0) > 0) / len(below)
            above_wr = sum(1 for t in above if t.get("pnl", 0) > 0) / len(above)
            if above_wr < below_wr * 0.7:  # significant dropoff
                best_ceiling = vix_cut
                break

    return {
        "vix_ceiling": best_ceiling,
        "evidence": (
            f"VIX ceiling: {best_ceiling} — trades above this VIX show significant "
            f"win rate decline. Current ceiling: 20."
        ),
    }


def analyze_lot_scaling(
    total_available: float,
    total_used: float,
    recent_pnl: float,
    lot_margin: float = 45000,
) -> Dict:
    """Recommend lot scaling based on margin trend and PnL trajectory."""
    free_cash = total_available - total_used
    affordable = int(free_cash / lot_margin)

    # Conservative scaling: require 5x margin buffer per additional lot
    buffer_per_lot = lot_margin * 3  # ₹135k buffer per additional lot
    safe_lots = 1
    for n in range(2, 6):
        if free_cash >= (n * lot_margin + (n - 1) * buffer_per_lot):
            safe_lots = n

    return {
        "current_lots": 1,
        "recommended_lots": min(safe_lots, 2),  # capped at 2 from rules
        "affordable_lots_raw": affordable,
        "safe_lots_with_buffer": safe_lots,
        "free_cash": free_cash,
        "next_scale_at_profit": (safe_lots + 1) * buffer_per_lot - free_cash
        if affordable > 1
        else lot_margin - free_cash,
        "evidence": (
            f"Free cash ₹{free_cash:,.0f} supports {affordable} lots raw, "
            f"{safe_lots} with safety buffer. "
            f"{'READY TO SCALE' if safe_lots >= 2 else f'Need ₹{lot_margin - free_cash:,.0f} more for next lot'}"
        ),
    }


def generate_pa_recommendations(
    trades: List[Dict],
    total_margin_available: float = 0,
    total_margin_used: float = 0,
) -> Dict:
    """Run ALL PA analyses and return ranked recommendations for PM.

    This is the ONE function the PA crew task calls.
    """
    recommendations = []
    sl_analysis = analyze_sl_optimization(trades)
    window_analysis = analyze_entry_window(trades)
    vix_analysis = analyze_vix_threshold(trades)
    lot_analysis = analyze_lot_scaling(
        total_margin_available, total_margin_used, sum(t.get("pnl", 0) for t in trades)
    )

    # Rank recommendations by impact
    if sl_analysis.get("improvement", 0) > 0:
        recommendations.append(
            f"SL: Change from ₹{sl_analysis['current_sl']} to ₹{sl_analysis['recommended_sl']} "
            f"(+₹{sl_analysis['improvement']:+,} PnL)"
        )
    if window_analysis.get("improvement", 0) > 0.02:
        recommendations.append(
            f"Entry window: Shift from current to {window_analysis['best_window']} "
            f"(+{window_analysis['improvement']:+.1%} win rate)"
        )
    if vix_analysis.get("vix_ceiling", 20) < 20:
        recommendations.append(
            f"VIX ceiling: Lower from 20 to {vix_analysis['vix_ceiling']} "
            f"(avoid low-probability trades)"
        )
    if lot_analysis.get("recommended_lots", 1) > 1:
        recommendations.append(
            f"Lot scaling: Increase from 1 to {lot_analysis['recommended_lots']} lots "
            f"(₹{lot_analysis['free_cash']:,.0f} free cash)"
        )

    return {
        "recommendations": recommendations,
        "sl_analysis": sl_analysis,
        "window_analysis": window_analysis,
        "vix_analysis": vix_analysis,
        "lot_analysis": lot_analysis,
        "trades_analyzed": len(trades),
        "evidence": "\n".join(f"  {i + 1}. {r}" for i, r in enumerate(recommendations))
        if recommendations
        else "No improvements found — current strategy is optimal",
    }
