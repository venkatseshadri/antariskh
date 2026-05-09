"""Post-Mortem Analyst deterministic tools.

Review trades, run counterfactuals, detect patterns, recommend PM adjustments.
"""

from typing import Dict, List, Any


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
