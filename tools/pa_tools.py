"""Post-Mortem Analyst deterministic tools.

Review trades, run counterfactuals, detect patterns, recommend PM adjustments.
Now with DuckDB analysis, strategy selection, and ChromaDB RAG learning.
"""

import os
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path

DUCKDB_NIFTY = Path("/home/trading_ceo/python-trader/varaha/data/varaha_data.duckdb")
DUCKDB_SENSEX = Path(
    "/home/trading_ceo/python-trader/varaha/data/varaha_data_sensex.duckdb"
)

# Lazy-load managers to avoid import errors if not installed
_rag_manager = None
_state_manager = None


def _get_rag_manager():
    """Lazy-load RAGManager on first use."""
    global _rag_manager
    if _rag_manager is None:
        try:
            from brahmand.persistence.rag_manager import RAGManager

            _rag_manager = RAGManager(verbose=False)
        except Exception:
            _rag_manager = False
    return _rag_manager if _rag_manager else None


def _get_state_manager():
    """Lazy-load StateManager on first use."""
    global _state_manager
    if _state_manager is None:
        try:
            from brahmand.persistence.state_manager import StateManager

            _state_manager = StateManager(verbose=False)
        except Exception:
            _state_manager = False
    return _state_manager if _state_manager else None


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


def analyze_strategy_selection(
    trades: List[Dict],
    market_regime: str = "UNKNOWN",
    current_vix: float = 18.0,
    trend_strength: float = 0.5,
) -> Dict:
    """Recommend strategy (Iron Fly vs Credit Spread) based on regime + historical performance.

    Iron Fly: best in sideways/low-VIX markets. Credit Spread: better in trending/high-VIX.

    Returns: {recommended_strategy, score, rationale, evidence}
    """
    if not trades:
        return {
            "recommended_strategy": "IRON_FLY",  # default conservative
            "confidence": 0.5,
            "evidence": "No trade history",
        }

    # Categorize past trades by strategy type (assume Iron Fly by default if not specified)
    iron_fly_trades = [t for t in trades if t.get("strategy", "IRON_FLY") == "IRON_FLY"]
    credit_spread_trades = [t for t in trades if t.get("strategy") == "CREDIT_SPREAD"]

    # Calculate win rates by strategy
    if iron_fly_trades:
        if_win_rate = sum(1 for t in iron_fly_trades if t.get("pnl", 0) > 0) / len(
            iron_fly_trades
        )
        if_avg_pnl = sum(t.get("pnl", 0) for t in iron_fly_trades) / len(
            iron_fly_trades
        )
    else:
        if_win_rate, if_avg_pnl = 0.0, 0.0

    if credit_spread_trades:
        cs_win_rate = sum(1 for t in credit_spread_trades if t.get("pnl", 0) > 0) / len(
            credit_spread_trades
        )
        cs_avg_pnl = sum(t.get("pnl", 0) for t in credit_spread_trades) / len(
            credit_spread_trades
        )
    else:
        cs_win_rate, cs_avg_pnl = 0.0, 0.0

    # Score based on regime + performance
    if_score = 0.0
    cs_score = 0.0

    # Regime signal
    if market_regime == "SIDEWAYS" or (current_vix >= 15 and current_vix <= 22):
        if_score += 60  # Iron Fly thrives in low-volatility, sideways
    elif market_regime == "TRENDING" or current_vix > 25:
        cs_score += 60  # Credit Spread better in trending, high-vol

    # Historical performance
    if if_win_rate > cs_win_rate:
        if_score += 20
    elif cs_win_rate > if_win_rate:
        cs_score += 20

    if if_avg_pnl > cs_avg_pnl:
        if_score += 20
    elif cs_avg_pnl > if_avg_pnl:
        cs_score += 20

    recommended = "IRON_FLY" if if_score >= cs_score else "CREDIT_SPREAD"
    confidence = abs(if_score - cs_score) / max(100, if_score + cs_score)
    confidence = min(1.0, max(0.0, confidence))

    return {
        "recommended_strategy": recommended,
        "confidence": round(confidence, 3),
        "iron_fly_score": round(if_score, 1),
        "credit_spread_score": round(cs_score, 1),
        "iron_fly_wr": round(if_win_rate, 3) if iron_fly_trades else None,
        "credit_spread_wr": round(cs_win_rate, 3) if credit_spread_trades else None,
        "iron_fly_avg_pnl": round(if_avg_pnl, 1),
        "credit_spread_avg_pnl": round(cs_avg_pnl, 1),
        "evidence": (
            f"Market regime: {market_regime} (VIX={current_vix}). "
            f"{recommended} recommended ({confidence:.0%} confidence). "
            f"IF: {if_win_rate:.0%} WR, ₹{if_avg_pnl:+,.0f} avg. "
            f"CS: {cs_win_rate:.0%} WR, ₹{cs_avg_pnl:+,.0f} avg."
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


# ============================================================
# Breakout Analysis Tools — Foundation Layer
# ============================================================


def track_missed_opportunities(
    trades_taken: List[Dict],
    potential_setups: List[Dict],
) -> Dict:
    """Identify HIGH-CONFIDENCE setups that were NOT traded.

    Opportunity cost analysis: "I could have made ₹X but didn't"

    Args:
        trades_taken: Actual trades executed {trade_id, entry_time, pnl}
        potential_setups: All high-confidence setups identified {entry_time, direction, confidence, estimated_pnl}

    Returns:
        {
          total_setups: N,
          trades_taken: M,
          missed_opportunities: K,
          missed_pnl_estimate: ₹X,
          opportunity_cost: ₹X,
          missed_details: [{time, direction, confidence, reason}]
        }
    """
    if not potential_setups:
        return {
            "success": True,
            "total_setups": 0,
            "trades_taken": len(trades_taken),
            "missed_opportunities": 0,
            "missed_pnl_estimate": 0,
            "opportunity_cost": 0,
            "message": "No potential setups identified",
        }

    try:
        # Get entry times of actual trades
        taken_times = {t.get("entry_time") for t in trades_taken if t.get("entry_time")}

        missed = []
        total_potential_pnl = 0

        for setup in potential_setups:
            entry_time = setup.get("entry_time")
            confidence = setup.get("confidence", 0)
            estimated_pnl = setup.get("estimated_pnl", 500)  # Default estimate

            # High-confidence setups only
            if confidence >= 70 and entry_time not in taken_times:
                missed.append(
                    {
                        "entry_time": entry_time,
                        "direction": setup.get("direction", "?"),
                        "confidence": confidence,
                        "estimated_pnl": estimated_pnl,
                        "reason": f"High confidence ({confidence}%) but no trade taken",
                    }
                )
                total_potential_pnl += estimated_pnl

        # Summary
        actual_pnl = sum(t.get("pnl", 0) for t in trades_taken)
        potential_total = actual_pnl + total_potential_pnl
        opportunity_cost = total_potential_pnl

        return {
            "success": True,
            "total_setups": len(potential_setups),
            "trades_taken": len(trades_taken),
            "missed_opportunities": len(missed),
            "actual_pnl": round(actual_pnl, 0),
            "missed_pnl_estimate": round(total_potential_pnl, 0),
            "potential_total_pnl": round(potential_total, 0),
            "opportunity_cost": round(opportunity_cost, 0),
            "efficiency_pct": round(
                (actual_pnl / potential_total * 100) if potential_total != 0 else 0, 1
            ),
            "missed_details": sorted(
                missed, key=lambda x: x["estimated_pnl"], reverse=True
            )[:5],  # Top 5 missed
            "summary": f"Actual P&L: ₹{actual_pnl:+,.0f}. "
            f"Could have made: ₹{potential_total:+,.0f}. "
            f"Missed opportunity: ₹{opportunity_cost:+,.0f} "
            f"({len(missed)} high-confidence setups not taken). "
            f"Efficiency: {round(actual_pnl / potential_total * 100) if potential_total != 0 else 0:.0f}%",
        }

    except Exception as e:
        return {"success": False, "message": f"Failed to track: {str(e)}"}


def score_confidence(snapshot: Dict, direction: str = "UP") -> Dict:
    """Score how confident the setup is (0-100%).

    Counts how many indicators align with the direction.
    Used for rating breakout reliability.

    Args:
        snapshot: Output from snapshot_indicators()
        direction: "UP" or "DOWN" or "SIDEWAYS"

    Returns:
        {
          confidence_pct: 0-100,
          aligned_indicators: list of aligned indicators,
          misaligned_indicators: list of misaligned,
          reasoning: explanation,
          recommendation: STRONG_BUY/BUY/HOLD/SELL/STRONG_SELL
        }
    """
    if not snapshot.get("success"):
        return {"success": False, "message": "Invalid snapshot"}

    direction = direction.upper()
    if direction not in ["UP", "DOWN", "SIDEWAYS"]:
        return {"success": False, "message": "Direction must be UP/DOWN/SIDEWAYS"}

    aligned = []
    misaligned = []
    max_indicators = 0

    try:
        trend = snapshot["trend"]
        momentum = snapshot["momentum"]
        volatility = snapshot["volatility"]
        structure = snapshot["structure"]
        greeks = snapshot["greeks"]

        # === TREND INDICATORS ===
        st_consensus = trend.get("supertrend_consensus", "")
        st_1m = trend.get("supertrend_1min_direction", "")
        st_5m = trend.get("supertrend_5min_direction", "")
        st_15m = trend.get("supertrend_15min_direction", "")
        adx = trend.get("adx", 0)

        if direction == "UP":
            # ST consensus
            if st_consensus == "BULLISH":
                aligned.append("ST_consensus_BULLISH")
            elif st_consensus == "BEARISH":
                misaligned.append("ST_consensus_BEARISH")
            max_indicators += 1

            # ST alignment across timeframes
            st_count = sum(1 for st in [st_1m, st_5m, st_15m] if st == "UP")
            if st_count >= 2:
                aligned.append(f"SuperTrend_{st_count}/3_UP")
            elif st_count == 0:
                misaligned.append("SuperTrend_0/3_UP")
            max_indicators += 1

            # ADX (trend strength)
            if adx and adx > 25:
                aligned.append(f"ADX_{adx:.0f}_strong")
            elif adx and adx < 20:
                misaligned.append(f"ADX_{adx:.0f}_weak")
            max_indicators += 1

        elif direction == "DOWN":
            if st_consensus == "BEARISH":
                aligned.append("ST_consensus_BEARISH")
            elif st_consensus == "BULLISH":
                misaligned.append("ST_consensus_BULLISH")
            max_indicators += 1

            st_count = sum(1 for st in [st_1m, st_5m, st_15m] if st == "DOWN")
            if st_count >= 2:
                aligned.append(f"SuperTrend_{st_count}/3_DOWN")
            elif st_count == 0:
                misaligned.append("SuperTrend_0/3_DOWN")
            max_indicators += 1

            if adx and adx > 25:
                aligned.append(f"ADX_{adx:.0f}_strong")
            elif adx and adx < 20:
                misaligned.append(f"ADX_{adx:.0f}_weak")
            max_indicators += 1

        elif direction == "SIDEWAYS":
            if st_consensus in ["NEUTRAL", ""]:
                aligned.append("ST_sideways")
            else:
                misaligned.append(f"ST_{st_consensus}_not_sideways")
            max_indicators += 1

            if adx and adx < 20:
                aligned.append(f"ADX_{adx:.0f}_low")
            elif adx and adx > 25:
                misaligned.append(f"ADX_{adx:.0f}_trending")
            max_indicators += 1

        # === MOMENTUM INDICATORS ===
        rsi = momentum.get("rsi", 50)
        ema_cross = momentum.get("ema_crossover", "NONE")

        if direction == "UP":
            if rsi and rsi > 50:
                aligned.append(f"RSI_{rsi:.0f}_bullish")
            elif rsi and rsi < 50:
                misaligned.append(f"RSI_{rsi:.0f}_bearish")
            max_indicators += 1

            if ema_cross == "BULLISH":
                aligned.append("EMA_bullish_cross")
            elif ema_cross == "BEARISH":
                misaligned.append("EMA_bearish_cross")
            max_indicators += 1

        elif direction == "DOWN":
            if rsi and rsi < 50:
                aligned.append(f"RSI_{rsi:.0f}_bearish")
            elif rsi and rsi > 50:
                misaligned.append(f"RSI_{rsi:.0f}_bullish")
            max_indicators += 1

            if ema_cross == "BEARISH":
                aligned.append("EMA_bearish_cross")
            elif ema_cross == "BULLISH":
                misaligned.append("EMA_bullish_cross")
            max_indicators += 1

        # === VOLATILITY INDICATORS ===
        atr = volatility.get("atr", 0)
        iv_regime = volatility.get("iv_regime", "")

        if atr and atr > 100:
            aligned.append(f"ATR_{atr:.0f}_expanding")
        elif atr and atr < 50:
            misaligned.append(f"ATR_{atr:.0f}_contracting")
        max_indicators += 1

        if iv_regime == "HIGH":
            aligned.append("IV_regime_HIGH")
        elif iv_regime == "LOW":
            misaligned.append("IV_regime_LOW")
        max_indicators += 1

        # === STRUCTURE INDICATORS ===
        spot = snapshot["price"]["spot"]
        resistance = structure.get("resistance_level")
        support = structure.get("support_level")

        if direction == "UP" and resistance:
            if spot < resistance:
                aligned.append(f"Price_below_resistance_{resistance:.0f}")
            else:
                aligned.append(f"Price_above_resistance_{resistance:.0f}")
            max_indicators += 1

        elif direction == "DOWN" and support:
            if spot > support:
                aligned.append(f"Price_above_support_{support:.0f}")
            else:
                aligned.append(f"Price_below_support_{support:.0f}")
            max_indicators += 1

        # === CALCULATE CONFIDENCE ===
        confidence_pct = (
            (len(aligned) / max_indicators * 100) if max_indicators > 0 else 0
        )

        # Recommendation
        if confidence_pct >= 80:
            recommendation = "STRONG_BUY" if direction == "UP" else "STRONG_SELL"
        elif confidence_pct >= 60:
            recommendation = "BUY" if direction == "UP" else "SELL"
        elif confidence_pct >= 40:
            recommendation = "HOLD"
        elif confidence_pct >= 20:
            recommendation = "WEAK_" + ("BUY" if direction == "UP" else "SELL")
        else:
            recommendation = "WAIT"

        return {
            "success": True,
            "direction": direction,
            "confidence_pct": round(confidence_pct, 1),
            "aligned_count": len(aligned),
            "misaligned_count": len(misaligned),
            "max_indicators": max_indicators,
            "aligned_indicators": aligned[:5],  # Top 5
            "misaligned_indicators": misaligned[:5],
            "recommendation": recommendation,
            "reasoning": f"{direction} setup: {len(aligned)}/{max_indicators} indicators aligned ({confidence_pct:.0f}%). "
            f"Aligned: {', '.join(aligned[:3])}. "
            f"Misaligned: {', '.join(misaligned[:2]) if misaligned else 'None'}.",
        }

    except Exception as e:
        return {"success": False, "message": f"Failed to score: {str(e)}"}


def snapshot_indicators(timestamp: str, index_name: str = "NIFTY") -> Dict:
    """Snapshot ALL indicators at a specific moment.

    Used for analyzing what indicators showed at:
    - Breakout moment
    - Range formation start
    - Key trade events

    Args:
        timestamp: ISO timestamp (e.g., "2026-05-15 10:45:00")
        index_name: NIFTY or SENSEX

    Returns:
        {
          price: {spot, futures, atm_strike},
          trend: {supertrend_1min, supertrend_5min, supertrend_15min, st_consensus, adx},
          momentum: {rsi, ema_5, ema_20, ema_50, ema_crossover_status},
          volatility: {atr, india_vix, iv_rank, iv_regime},
          structure: {pivot_pp, pivot_r1/s1, swing_high, swing_low, support, resistance},
          energy: {bb_pct_b, vwap, smc_strength},
          greeks: {agg_delta, agg_gamma, agg_vega},
          timestamp, success
        }
    """
    try:
        import duckdb
        from pathlib import Path

        db_path = Path("/home/trading_ceo/python-trader/varaha/data/varaha_data.duckdb")
        if not db_path.exists():
            return {"success": False, "message": "DuckDB not found"}

        db = duckdb.connect(str(db_path), read_only=True)

        # Query exact timestamp
        result = db.execute(
            f"""
            SELECT
                -- Price
                spot, futures, atm_strike,
                -- Trend (multi-timeframe)
                supertrend_value, supertrend_direction,
                st_5min_value, st_5min_direction,
                st_15min_value, st_15min_direction,
                st_consensus,
                adx,
                -- Momentum
                rsi,
                ema_5, ema_20, ema_50,
                -- Volatility
                atr, india_vix, iv_rank, iv_regime,
                -- Structure
                pivot_pp, pivot_r1, pivot_s1,
                swing_high, swing_low,
                open_range_high, open_range_low,
                intraday_high, intraday_low,
                -- Energy
                bb_pct_b, vwap, smc_strength,
                -- Greeks
                agg_delta, agg_gamma, agg_vega
            FROM market_data
            WHERE timestamp = ? AND index_name = ?
            LIMIT 1
            """,
            (timestamp, index_name),
        ).fetchone()

        db.close()

        if not result:
            return {
                "success": False,
                "message": f"No data for {timestamp}",
                "timestamp": timestamp,
            }

        # Determine EMA crossover status
        ema_5, ema_20, ema_50 = result[14], result[15], result[16]
        ema_crossover = "NONE"
        if ema_5 > ema_20 > ema_50:
            ema_crossover = "BULLISH"
        elif ema_5 < ema_20 < ema_50:
            ema_crossover = "BEARISH"

        # Determine support/resistance relative to price
        spot = result[0]
        pivot_pp, pivot_r1, pivot_s1 = result[26], result[27], result[28]
        swing_high, swing_low = result[29], result[30]
        support = (
            max(pivot_s1, swing_low)
            if pivot_s1 and swing_low
            else pivot_s1 or swing_low
        )
        resistance = (
            min(pivot_r1, swing_high)
            if pivot_r1 and swing_high
            else pivot_r1 or swing_high
        )

        snapshot = {
            "success": True,
            "timestamp": timestamp,
            "index": index_name,
            "price": {
                "spot": result[0],
                "futures": result[1],
                "atm_strike": result[2],
            },
            "trend": {
                "supertrend_1min_value": result[3],
                "supertrend_1min_direction": result[4],
                "supertrend_5min_value": result[5],
                "supertrend_5min_direction": result[6],
                "supertrend_15min_value": result[7],
                "supertrend_15min_direction": result[8],
                "supertrend_consensus": result[9],
                "adx": result[10],
            },
            "momentum": {
                "rsi": result[11],
                "ema_5": ema_5,
                "ema_20": ema_20,
                "ema_50": ema_50,
                "ema_crossover": ema_crossover,
            },
            "volatility": {
                "atr": result[19],
                "india_vix": result[20],
                "iv_rank": result[21],
                "iv_regime": result[22],
            },
            "structure": {
                "pivot_pp": pivot_pp,
                "pivot_r1": pivot_r1,
                "pivot_s1": pivot_s1,
                "swing_high": swing_high,
                "swing_low": swing_low,
                "support_level": support,
                "resistance_level": resistance,
                "open_range_high": result[31],
                "open_range_low": result[32],
                "intraday_high": result[33],
                "intraday_low": result[34],
            },
            "energy": {
                "bb_pct_b": result[35],
                "vwap": result[36],
                "smc_strength": result[37],
            },
            "greeks": {
                "agg_delta": result[38],
                "agg_gamma": result[39],
                "agg_vega": result[40],
            },
        }

        return snapshot

    except Exception as e:
        return {"success": False, "message": f"Failed to snapshot: {str(e)}"}


# ============================================================
# ChromaDB RAG Learning — Store & Query Trade Reviews
# ============================================================


def write_trade_review_to_rag(
    trade: Dict,
    review: Dict,
    market_regime: str = "UNKNOWN",
    strategy_analysis: Optional[Dict] = None,
    entry_analysis: Optional[Dict] = None,
    sl_analysis: Optional[Dict] = None,
    vix_analysis: Optional[Dict] = None,
    lot_analysis: Optional[Dict] = None,
    date: str = None,
) -> Dict:
    """Write a comprehensive trade review to ChromaDB for RAG learning.

    Captures all PA learning dimensions:
    - strategy_success (from strategy_analysis)
    - entry_window_patterns (from entry_analysis)
    - sl_optimization (from sl_analysis)
    - vix_thresholds (from vix_analysis)
    - lot_scaling (from lot_analysis)

    Args:
        trade: Trade {trade_id, strategy, pnl, entry, exit, entry_time, sl, vix_at_entry, ...}
        review: Review from PA {quality, score, issues}
        market_regime: Market regime (SIDEWAYS, TRENDING, etc.)
        strategy_analysis: {recommended_strategy, confidence, iron_fly_wr, credit_spread_wr}
        entry_analysis: {best_window, best_win_rate, improvement}
        sl_analysis: {recommended_sl, improvement}
        vix_analysis: {vix_ceiling}
        lot_analysis: {recommended_lots}
        date: Date (defaults to today)

    Returns:
        {success, doc_id, message}
    """
    rag = _get_rag_manager()
    if rag is None:
        return {"success": False, "message": "ChromaDB not available"}

    from datetime import datetime
    from brahmand.state import TradeReview

    date = date or datetime.now().strftime("%Y-%m-%d")

    # Extract entry time window
    entry_time = trade.get("entry_time", "")
    entry_window = ""
    if entry_time and len(entry_time) >= 5:
        hh, mm = entry_time.split(":")[:2]
        minutes = int(hh) * 60 + int(mm)
        window_start = (minutes // 30) * 30
        w_hh, w_mm = window_start // 60, window_start % 60
        entry_window = f"{w_hh:02d}:{w_mm:02d}-{(w_hh) % 24:02d}:{(w_mm + 30) % 60:02d}"

    # Build lesson learned
    lesson = ""
    if review.get("quality") == "EXCELLENT":
        lesson = f"✅ Clean {trade.get('strategy')} trade in {market_regime}. Replicate this setup."
    elif review.get("quality") == "CRITICAL":
        lesson = (
            f"❌ AVOID this setup. {trade.get('strategy')} in {market_regime} failed. "
            f"Issues: {', '.join(review.get('issues', []))}"
        )
    else:
        lesson = (
            f"Learn: {review.get('quality')} execution. "
            f"{', '.join(review.get('issues', []))}"
        )

    # Build comprehensive execution summary for RAG embedding
    execution_summary = (
        f"{trade.get('strategy')} in {market_regime} regime "
        f"(VIX={trade.get('vix_at_entry', 18)}, Entry={entry_time}). "
        f"Quality: {review.get('quality')}, P&L: ₹{trade.get('pnl', 0):+,}. "
        f"Strategy WR: {strategy_analysis.get('iron_fly_wr') if trade.get('strategy') == 'IRON_FLY' else strategy_analysis.get('credit_spread_wr')}. "
        f"Entry window: {entry_analysis.get('best_window')} ({entry_analysis.get('best_win_rate'):.0%} WR). "
        f"SL optimization: ₹{sl_analysis.get('improvement', 0):+,} available. "
        f"VIX ceiling: {vix_analysis.get('vix_ceiling', 20)}. "
        f"Lot scaling: {lot_analysis.get('recommended_lots', 1)} lots safe. "
        f"Lesson: {lesson}"
    )

    # Create TradeReview with all learning dimensions
    trade_review_obj = TradeReview(
        date=date,
        trade_id=trade.get("trade_id", "unknown"),
        strategy=trade.get("strategy", "IRON_FLY"),
        market_regime=market_regime,
        vix_at_entry=trade.get("vix_at_entry", 18.0),
        entry_time=entry_time,
        entry_window=entry_window,
        entry_price=trade.get("entry", 0),
        exit_price=trade.get("exit", 0),
        pnl=trade.get("pnl", 0),
        lots=trade.get("lots", 1),
        success=trade.get("pnl", 0) > 0,
        sl_hit=review.get("sl_hit", False),
        tp_hit=review.get("tp_hit", False),
        entry_quality=review.get("quality", "unknown"),
        sl_used=trade.get("sl", 3500.0),
        optimal_sl=sl_analysis.get("recommended_sl") if sl_analysis else None,
        sl_improvement=sl_analysis.get("improvement") if sl_analysis else None,
        strategy_score=(
            strategy_analysis.get("confidence") if strategy_analysis else None
        ),
        vix_ceiling=vix_analysis.get("vix_ceiling") if vix_analysis else None,
        margin_available=trade.get("margin_available"),
        margin_used=trade.get("margin_used"),
        recommended_lots=lot_analysis.get("recommended_lots") if lot_analysis else None,
        lesson_learned=lesson,
        execution_summary=execution_summary,
    )

    try:
        doc_id = rag.store_trade_review(trade_review_obj.model_dump())
        return {
            "success": True,
            "doc_id": doc_id,
            "learning_dimensions": [
                f"strategy_success: {trade_review_obj.strategy_score:.0%}"
                if trade_review_obj.strategy_score
                else None,
                f"entry_window: {trade_review_obj.entry_window}",
                f"sl_improvement: ₹{trade_review_obj.sl_improvement:+,.0f}"
                if trade_review_obj.sl_improvement
                else None,
                f"vix_ceiling: {trade_review_obj.vix_ceiling}",
                f"lot_recommendation: {trade_review_obj.recommended_lots} lots",
            ],
            "message": f"Stored comprehensive {trade_review_obj.strategy} review to RAG with all learning dimensions",
        }
    except Exception as e:
        return {"success": False, "message": f"Failed to store: {str(e)}"}


def query_similar_trades_from_rag(
    query_text: str,
    strategy_filter: Optional[str] = None,
    regime_filter: Optional[str] = None,
    n_results: int = 5,
) -> Dict:
    """Query similar trades from ChromaDB RAG.

    Used by Executor before deciding on a trade. Semantic search over past trade reviews.

    Args:
        query_text: e.g., "Iron Fly in sideways market with low VIX"
        strategy_filter: Filter by strategy (IRON_FLY, CREDIT_SPREAD)
        regime_filter: Filter by regime (SIDEWAYS, TRENDING)
        n_results: Number of similar trades to return

    Returns:
        {found, count, similar_trades, evidence}
    """
    rag = _get_rag_manager()
    if rag is None:
        return {"found": False, "count": 0, "similar_trades": []}

    try:
        trades = rag.query_similar_trades(
            query_text=query_text,
            n_results=n_results,
            strategy_filter=strategy_filter,
            regime_filter=regime_filter,
        )

        if not trades:
            return {
                "found": False,
                "count": 0,
                "similar_trades": [],
                "evidence": "No similar trades found in history",
            }

        # Summarize findings
        wins = sum(1 for t in trades if t.get("success"))
        avg_pnl = sum(t.get("pnl", 0) for t in trades) / len(trades) if trades else 0

        return {
            "found": True,
            "count": len(trades),
            "similar_trades": [
                {
                    "strategy": t.get("strategy", ""),
                    "pnl": t.get("pnl", 0),
                    "success": t.get("success", False),
                }
                for t in trades
            ],
            "evidence": f"Found {len(trades)} similar {strategy_filter or 'any'} trades. "
            f"Win rate: {wins}/{len(trades)} ({wins / len(trades):.0%}). "
            f"Avg P&L: ₹{avg_pnl:+,.0f}.",
        }
    except Exception as e:
        return {"found": False, "count": 0, "similar_trades": [], "error": str(e)}


# ============================================================
# SQLite State Persistence — Load/Save BrahmandState
# ============================================================


def load_portfolio_state() -> Dict:
    """Load latest portfolio state from SQLite.

    Returns:
        {success, portfolio_value, margin_available, margin_used, active_trades_count, daily_pnl}
    """
    sm = _get_state_manager()
    if sm is None:
        return {"success": False, "message": "SQLite state not available"}

    try:
        state = sm.load_latest_state()
        if state is None:
            return {"success": False, "message": "No state found"}

        return {
            "success": True,
            "portfolio_value": state.portfolio_value,
            "margin_available": state.margin_available,
            "margin_used": state.margin_used,
            "active_trades_count": len(state.active_trades),
            "daily_pnl": state.daily_pnl,
            "session_pnl": state.session_pnl,
            "market_regime": state.market_regime,
            "vix_level": state.vix_level,
            "completed_trades_count": len(state.completed_trades),
        }
    except Exception as e:
        return {"success": False, "message": f"Failed to load state: {str(e)}"}


def save_session_state(
    portfolio_value: float = 100000.0,
    daily_pnl: float = 0.0,
    session_pnl: float = 0.0,
    margin_available: float = 200000.0,
    margin_used: float = 0.0,
    active_trades: List[Dict] = None,
    completed_trades: List[Dict] = None,
) -> Dict:
    """Save session state to SQLite for next session to load.

    Called by PA crew at EOD to persist current portfolio metrics.

    Returns:
        {success, message}
    """
    sm = _get_state_manager()
    if sm is None:
        return {"success": False, "message": "SQLite state not available"}

    try:
        from brahmand.state import BrahmandState

        state = BrahmandState(
            portfolio_value=portfolio_value,
            daily_pnl=daily_pnl,
            session_pnl=session_pnl,
            margin_available=margin_available,
            margin_used=margin_used,
            active_trades=active_trades or [],
            completed_trades=completed_trades or [],
        )

        success = sm.save_state(state)

        return {
            "success": success,
            "message": f"Saved portfolio state: PV=₹{portfolio_value:,.0f}, P&L=₹{daily_pnl:+,.0f}",
        }
    except Exception as e:
        return {"success": False, "message": f"Failed to save state: {str(e)}"}


def generate_pa_recommendations(
    trades: List[Dict],
    total_margin_available: float = 0,
    total_margin_used: float = 0,
    market_regime: str = "UNKNOWN",
    current_vix: float = 18.0,
) -> Dict:
    """Run ALL PA analyses and return ranked recommendations for PM.

    This is the ONE function the PA crew task calls.
    Includes: strategy selection, entry window, SL optimization, lot scaling, VIX ceiling.
    """
    recommendations = []
    strategy_analysis = analyze_strategy_selection(trades, market_regime, current_vix)
    sl_analysis = analyze_sl_optimization(trades)
    window_analysis = analyze_entry_window(trades)
    vix_analysis = analyze_vix_threshold(trades)
    lot_analysis = analyze_lot_scaling(
        total_margin_available, total_margin_used, sum(t.get("pnl", 0) for t in trades)
    )

    # Rank recommendations by impact (strategy first, then entry, then risk/sizing)
    if strategy_analysis.get("confidence", 0) > 0.5:
        recommendations.append(
            f"STRATEGY: Use {strategy_analysis['recommended_strategy']} "
            f"({strategy_analysis['confidence']:.0%} confidence). "
            f"IF WR: {strategy_analysis.get('iron_fly_wr', '?')}, "
            f"CS WR: {strategy_analysis.get('credit_spread_wr', '?')}"
        )
    if window_analysis.get("improvement", 0) > 0.02:
        recommendations.append(
            f"ENTRY: Shift from current to {window_analysis['best_window']} "
            f"(+{window_analysis['improvement']:+.1%} win rate)"
        )
    if sl_analysis.get("improvement", 0) > 0:
        recommendations.append(
            f"SL: Change from ₹{sl_analysis['current_sl']} to ₹{sl_analysis['recommended_sl']} "
            f"(+₹{sl_analysis['improvement']:+,} PnL)"
        )
    if vix_analysis.get("vix_ceiling", 20) < 20:
        recommendations.append(
            f"VIX: Lower ceiling from 20 to {vix_analysis['vix_ceiling']} "
            f"(avoid low-probability trades)"
        )
    if lot_analysis.get("recommended_lots", 1) > 1:
        recommendations.append(
            f"SCALING: Increase from 1 to {lot_analysis['recommended_lots']} lots "
            f"(₹{lot_analysis['free_cash']:,.0f} free cash)"
        )

    return {
        "recommendations": recommendations,
        "strategy_analysis": strategy_analysis,
        "sl_analysis": sl_analysis,
        "window_analysis": window_analysis,
        "vix_analysis": vix_analysis,
        "lot_analysis": lot_analysis,
        "trades_analyzed": len(trades),
        "evidence": "\n".join(f"  {i + 1}. {r}" for i, r in enumerate(recommendations))
        if recommendations
        else "No improvements found — current strategy is optimal",
    }


# ============================================================
# Multi-TF OHLC Analysis Tools — For Phase Detection
# ============================================================


def snapshot_multitf(timestamp: str, index_name: str = "NIFTY") -> Dict:
    """Get raw OHLCV across all timeframes at a specific moment.

    Used for analyzing market structure across timeframes.
    PA researcher reads raw data and reasons about PHASES.

    Reads from market_data_multitf (v4 aggregated rolling bars).

    Args:
        timestamp: ISO timestamp (e.g., "2026-05-15 12:30:00")
        index_name: NIFTY or SENSEX

    Returns:
        {
            "success": True,
            "timestamp": "2026-05-15 12:30:00",
            "multitf": {
                "5min": {"open": 25280, "high": 25320, "low": 25275, "close": 25300, "volume": 9000, "adx": 35, "rsi": 72, "st": "BULLISH"},
                "15min": {...},
                "30min": {...},
                "60min": {...},
                "240min": {...},
                "1440min": {...}
            }
        }
    """
    try:
        import duckdb
        from pathlib import Path

        # Use v4 per-index database with rolling multi-TF aggregates
        db_path = Path(
            f"/home/trading_ceo/python-trader/varaha/data/market_data_multitf_{index_name.lower()}.duckdb"
        )
        if not db_path.exists():
            return {
                "success": False,
                "message": f"V4 multi-TF database not found at {db_path}",
            }

        db = duckdb.connect(str(db_path), read_only=True)

        timeframes = [5, 15, 30, 60, 240, 1440]
        multitf = {}

        for tf_min in timeframes:
            # Query for bars where timestamp is <= query timestamp, order by descending
            # Gets the latest bar up to the query timestamp
            result = db.execute(
                f"""
                SELECT timestamp, open, high, low, close, volume,
                       sma20, sma50, sma200, rsi, atr, macd, macd_signal, macd_histogram,
                       adx, di_plus, di_minus, bb_upper, bb_middle, bb_lower, obv, cmf, cci
                FROM market_data_multitf
                WHERE timeframe_min = ? AND index_name = ? AND timestamp <= ?
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                (tf_min, index_name, timestamp),
            ).fetchone()

            if result:
                multitf[f"{tf_min}min"] = {
                    "timestamp": result[0],
                    "open": result[1],
                    "high": result[2],
                    "low": result[3],
                    "close": result[4],
                    "volume": result[5],
                    # Batch 1: Gap-Capable
                    "sma20": result[6],
                    "sma50": result[7],
                    "sma200": result[8],
                    "rsi": result[9],
                    "atr": result[10],
                    "macd": result[11],
                    "macd_signal": result[12],
                    "macd_histogram": result[13],
                    # Batch 2: Gap-Sensitive
                    "adx": result[14],
                    "di_plus": result[15],
                    "di_minus": result[16],
                    "bb_upper": result[17],
                    "bb_middle": result[18],
                    "bb_lower": result[19],
                    "obv": result[20],
                    "cmf": result[21],
                    "cci": result[22],
                }
            else:
                multitf[f"{tf_min}min"] = {
                    "timestamp": timestamp,
                    "open": None,
                    "high": None,
                    "low": None,
                    "close": None,
                    "volume": None,
                    "sma20": None,
                    "sma50": None,
                    "sma200": None,
                    "rsi": None,
                    "atr": None,
                    "macd": None,
                    "macd_signal": None,
                    "macd_histogram": None,
                    "adx": None,
                    "di_plus": None,
                    "di_minus": None,
                    "bb_upper": None,
                    "bb_middle": None,
                    "bb_lower": None,
                    "obv": None,
                    "cmf": None,
                    "cci": None,
                }

        db.close()

        return {
            "success": True,
            "timestamp": timestamp,
            "index": index_name,
            "multitf": multitf,
        }

    except Exception as e:
        return {"success": False, "message": f"Failed to snapshot multi-TF: {str(e)}"}


def analyze_ohlc_shape(ohlc: Dict) -> Dict:
    """Analyze OHLC to extract shape characteristics.

    PA researcher uses this to understand OHLC patterns:
    - Where did price close? (top/middle/bottom)
    - What was the range? (expanding/contracting)
    - Body size? (strong conviction or weak)

    Args:
        ohlc: {open, high, low, close, adx}

    Returns:
        {
            "close_position": 0.92,  # 0=low, 0.5=mid, 1=high
            "range_pct": 0.17,       # (high-low)/open * 100
            "body_pct": 0.70,        # |close-open|/range * 100
            "wick_ratio": 0.3,       # (smaller_wick / larger_wick)
            "hl_range": 43,          # (high - low) in points
            "adx_interpretation": "STRONG" or "WEAK"
        }
    """
    try:
        open_price = float(ohlc.get("open", 0))
        high = float(ohlc.get("high", 0))
        low = float(ohlc.get("low", 0))
        close = float(ohlc.get("close", 0))
        adx = float(ohlc.get("adx", 0))

        if open_price == 0 or high == 0 or low == 0:
            return {"success": False, "message": "Invalid OHLC"}

        # Range calculations
        hl_range = high - low
        range_pct = (hl_range / open_price) * 100

        # Close position (0=near low, 1=near high)
        close_position = (close - low) / hl_range if hl_range > 0 else 0.5

        # Body size (strength of conviction)
        body = abs(close - open_price)
        body_pct = (body / hl_range * 100) if hl_range > 0 else 0

        # Wick sizes
        upper_wick = high - max(open_price, close)
        lower_wick = min(open_price, close) - low

        if upper_wick > 0 or lower_wick > 0:
            wick_ratio = min(upper_wick, lower_wick) / max(upper_wick, lower_wick)
        else:
            wick_ratio = 0

        # ADX interpretation
        adx_interpretation = (
            "STRONG" if adx > 25 else "WEAK" if adx < 20 else "BORDERLINE"
        )

        return {
            "success": True,
            "close_position": round(close_position, 2),  # 0=low, 1=high
            "range_pct": round(range_pct, 2),
            "body_pct": round(body_pct, 2),
            "wick_ratio": round(wick_ratio, 2),
            "hl_range": round(hl_range, 0),
            "adx_interpretation": adx_interpretation,
        }

    except Exception as e:
        return {"success": False, "message": f"Failed to analyze OHLC shape: {str(e)}"}


def compare_ohlc_sequence(bars: list) -> Dict:
    """Compare sequence of bars to detect momentum and direction.

    PA researcher uses this to understand PROGRESSION:
    - Are closes getting higher or lower?
    - Is range expanding or shrinking?
    - Is momentum accelerating or decelerating?

    Args:
        bars: List of {open, high, low, close, adx} dicts, chronological order
              [bar_t-2, bar_t-1, bar_t] or just [bar_t-1, bar_t]

    Returns:
        {
            "higher_high": True/False,      # current high > prev high
            "higher_low": True/False,       # current low > prev low
            "higher_close": True/False,     # current close > prev close
            "direction": "UP" | "DOWN" | "MIXED",
            "momentum": "ACCELERATING" | "STABLE" | "DECELERATING",
            "pattern": "BULL_CONTINUATION" | "BEAR_CONTINUATION" | "REVERSAL" | "CONSOLIDATION",
            "closes_at_top": True/False,    # close > open (bullish) or close < open (bearish)
            "range_change": "EXPANDING" | "CONTRACTING" | "STABLE",
        }
    """
    try:
        if len(bars) < 2:
            return {"success": False, "message": "Need at least 2 bars"}

        # Current and previous bars
        prev = bars[-2]
        curr = bars[-1]

        prev_close = float(prev.get("close", 0))
        curr_close = float(curr.get("close", 0))

        prev_high = float(prev.get("high", 0))
        prev_low = float(prev.get("low", 0))
        curr_high = float(curr.get("high", 0))
        curr_low = float(curr.get("low", 0))

        curr_open = float(curr.get("open", 0))
        curr_adx = float(curr.get("adx", 20))

        # Direction signals
        higher_high = curr_high > prev_high
        higher_low = curr_low > prev_low
        higher_close = curr_close > prev_close

        # Overall direction
        if higher_high and higher_low and higher_close:
            direction = "UP"
        elif not higher_high and not higher_low and not higher_close:
            direction = "DOWN"
        else:
            direction = "MIXED"

        # Momentum (using ADX and direction consistency)
        if len(bars) >= 3:
            prev_prev = bars[-3]
            prev_prev_close = float(prev_prev.get("close", 0))
            prev_prev_adx = float(prev_prev.get("adx", 20))

            # Check if ADX is increasing (accelerating) or decreasing (decelerating)
            adx_trend = "UP" if curr_adx > prev_prev_adx else "DOWN"
            momentum = (
                "ACCELERATING"
                if adx_trend == "UP" and direction != "MIXED"
                else "DECELERATING"
                if adx_trend == "DOWN"
                else "STABLE"
            )
        else:
            momentum = "STABLE"  # Can't determine with only 2 bars

        # Closes at top or bottom
        curr_range = curr_high - curr_low
        if curr_range > 0:
            close_position = (curr_close - curr_low) / curr_range
            closes_at_top = close_position > 0.7
            closes_at_bottom = close_position < 0.3
        else:
            closes_at_top = False
            closes_at_bottom = False

        # Pattern identification
        if direction == "UP" and closes_at_top:
            pattern = "BULL_CONTINUATION"
        elif direction == "DOWN" and closes_at_bottom:
            pattern = "BEAR_CONTINUATION"
        elif direction == "MIXED":
            pattern = "CONSOLIDATION"
        elif (prev_close > curr_open and curr_close < prev_close) or (
            prev_close < curr_open and curr_close > prev_close
        ):
            pattern = "REVERSAL"
        else:
            pattern = "CONTINUATION"

        # Range change (expanding or contracting)
        prev_range = prev_high - prev_low
        curr_range_val = curr_high - curr_low

        if curr_range_val > prev_range * 1.1:
            range_change = "EXPANDING"
        elif curr_range_val < prev_range * 0.9:
            range_change = "CONTRACTING"
        else:
            range_change = "STABLE"

        return {
            "success": True,
            "higher_high": higher_high,
            "higher_low": higher_low,
            "higher_close": higher_close,
            "direction": direction,
            "momentum": momentum,
            "pattern": pattern,
            "closes_at_top": closes_at_top,
            "range_change": range_change,
        }

    except Exception as e:
        return {"success": False, "message": f"Failed to compare sequence: {str(e)}"}
