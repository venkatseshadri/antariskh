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
        if_avg_pnl = sum(t.get("pnl", 0) for t in iron_fly_trades) / len(iron_fly_trades)
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
        support = max(pivot_s1, swing_low) if pivot_s1 and swing_low else pivot_s1 or swing_low
        resistance = min(pivot_r1, swing_high) if pivot_r1 and swing_high else pivot_r1 or swing_high

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
        entry_window = f"{w_hh:02d}:{w_mm:02d}-{(w_hh)%24:02d}:{(w_mm+30)%60:02d}"

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
                f"strategy_success: {trade_review_obj.strategy_score:.0%}" if trade_review_obj.strategy_score else None,
                f"entry_window: {trade_review_obj.entry_window}",
                f"sl_improvement: ₹{trade_review_obj.sl_improvement:+,.0f}" if trade_review_obj.sl_improvement else None,
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
            f"Win rate: {wins}/{len(trades)} ({wins/len(trades):.0%}). "
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
