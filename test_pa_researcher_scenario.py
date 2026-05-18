"""Test PA researcher logic against a real market scenario:
Market: UP 3hrs → PAUSE 0.5hrs → REVERSAL back to start by EOD.

Simulates snapshots at key moments and tests decision logic.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tools.pa_tools import (
    score_confidence,
    detect_patterns,
    analyze_entry_window,
    analyze_strategy_selection,
)


def simulate_market_scenario():
    """Market behavior: UP 3hrs → PAUSE 0.5hrs → REVERSAL."""

    print("=" * 80)
    print("PA RESEARCHER TEST: Market UP→PAUSE→REVERSAL Scenario")
    print("=" * 80)
    print()

    # Scenario timeline
    # 09:15 - Market open (NIFTY = 25000, baseline)
    # 12:15 - Up 3 hours (NIFTY = 25300, +300pts, trending up)
    # 12:45 - Pause 0.5hr (NIFTY = 25280, consolidating)
    # 15:30 - EOD reversal (NIFTY = 25000, back to start, -300pts)

    # ─────────────────────────────────────────────────────────────────────────────
    # MOMENT 1: 09:15 AM — Market Open (Baseline)
    # ─────────────────────────────────────────────────────────────────────────────
    print("📊 MOMENT 1: 09:15 AM — MARKET OPEN (Baseline)")
    print("   NIFTY Spot: 25000 | Market just opening")
    print()

    snapshot_open = {
        "price": {"spot": 25000.0, "futures": 25010.0, "atm_strike": 25000.0},
        "trend": {
            "supertrend_1min": {"value": 25000.0, "signal": "UP"},
            "supertrend_5min": {"value": 24950.0, "signal": "UP"},
            "supertrend_15min": {"value": 24900.0, "signal": "UP"},
            "st_consensus": "UP",
            "adx": 15.0,  # Weak trend
        },
        "momentum": {"rsi": 50.0, "ema_5": 25000.0, "ema_20": 24990.0, "ema_50": 24980.0, "ema_crossover": False},
        "volatility": {"atr": 45.0, "india_vix": 18.5, "iv_rank": 0.45, "iv_regime": "NORMAL"},
        "structure": {"support": 24950.0, "resistance": 25050.0},
        "energy": {"bb_pct_b": 0.5, "vwap": 24995.0},
        "greeks": {"agg_delta": 0.0, "agg_gamma": 0.0, "agg_vega": 0.0},
    }

    conf_open = score_confidence(snapshot_open, direction="UP")
    print(f"   🔍 PA Confidence UP: {conf_open['confidence_pct']:.0f}%")
    print(f"   📈 Recommendation: {conf_open['recommendation']}")
    print(f"   ✓ Aligned: {', '.join(conf_open.get('aligned_indicators', [])[:3])}...")
    print()

    # ─────────────────────────────────────────────────────────────────────────────
    # MOMENT 2: 12:15 PM — After 3 hours of UP trend
    # ─────────────────────────────────────────────────────────────────────────────
    print("📊 MOMENT 2: 12:15 PM — AFTER 3 HOURS UP TREND")
    print("   NIFTY Spot: 25300 (+300 pts from open) | Strong uptrend")
    print("   Market has been consistently rising for 3 hours")
    print()

    snapshot_up_3hrs = {
        "price": {"spot": 25300.0, "futures": 25310.0, "atm_strike": 25300.0},
        "trend": {
            "supertrend_1min": {"value": 25280.0, "signal": "UP"},
            "supertrend_5min": {"value": 25200.0, "signal": "UP"},
            "supertrend_15min": {"value": 25100.0, "signal": "UP"},
            "st_consensus": "UP",
            "adx": 35.0,  # Strong trend (ADX > 25)
        },
        "momentum": {
            "rsi": 72.0,  # Overbought but in uptrend
            "ema_5": 25290.0,
            "ema_20": 25200.0,
            "ema_50": 25050.0,
            "ema_crossover": True,  # 5 > 20 > 50
        },
        "volatility": {"atr": 52.0, "india_vix": 16.5, "iv_rank": 0.35, "iv_regime": "COMPRESSED"},
        "structure": {"support": 25100.0, "resistance": 25350.0},
        "energy": {"bb_pct_b": 0.85, "vwap": 25180.0},
        "greeks": {"agg_delta": 0.65, "agg_gamma": 0.02, "agg_vega": -0.15},
    }

    conf_up_3hrs = score_confidence(snapshot_up_3hrs, direction="UP")
    print(f"   🔍 PA Confidence UP: {conf_up_3hrs['confidence_pct']:.0f}%")
    print(f"   📈 Recommendation: {conf_up_3hrs['recommendation']}")
    print(f"   ✓ Aligned: {', '.join(conf_up_3hrs.get('aligned_indicators', [])[:4])}...")
    print(f"   ⚠️  Overbought (RSI=72), but ADX=35 = strong trend continuation likely")
    print()

    # ─────────────────────────────────────────────────────────────────────────────
    # MOMENT 3: 12:45 PM — PAUSE phase (consolidation after 3hr up)
    # ─────────────────────────────────────────────────────────────────────────────
    print("📊 MOMENT 3: 12:45 PM — PAUSE PHASE (0.5 hr consolidation)")
    print("   NIFTY Spot: 25280 (-20 pts from peak) | Consolidating after strong up")
    print("   Market catching breath, forming range")
    print()

    snapshot_pause = {
        "price": {"spot": 25280.0, "futures": 25290.0, "atm_strike": 25280.0},
        "trend": {
            "supertrend_1min": {"value": 25275.0, "signal": "UP"},
            "supertrend_5min": {"value": 25250.0, "signal": "UP"},
            "supertrend_15min": {"value": 25150.0, "signal": "UP"},
            "st_consensus": "UP",
            "adx": 28.0,  # Still strong but declining
        },
        "momentum": {
            "rsi": 58.0,  # Cooling from overbought
            "ema_5": 25275.0,
            "ema_20": 25220.0,
            "ema_50": 25080.0,
            "ema_crossover": True,
        },
        "volatility": {"atr": 48.0, "india_vix": 17.2, "iv_rank": 0.40, "iv_regime": "NORMAL"},
        "structure": {"support": 25150.0, "resistance": 25300.0},  # Forming box
        "energy": {"bb_pct_b": 0.60, "vwap": 25200.0},
        "greeks": {"agg_delta": 0.55, "agg_gamma": 0.03, "agg_vega": -0.12},
    }

    conf_pause = score_confidence(snapshot_pause, direction="UP")
    print(f"   🔍 PA Confidence UP: {conf_pause['confidence_pct']:.0f}%")
    print(f"   📈 Recommendation: {conf_pause['recommendation']}")
    print(f"   ℹ️  RSI cooling (58), ADX declining → Consolidation, not reversal YET")
    print()

    # ─────────────────────────────────────────────────────────────────────────────
    # MOMENT 4: 13:45 PM — REVERSAL BEGINS (breaking support)
    # ─────────────────────────────────────────────────────────────────────────────
    print("📊 MOMENT 4: 13:45 PM — REVERSAL BEGINS (breaking down)")
    print("   NIFTY Spot: 25150 (-150 pts from pause peak) | Breaking support")
    print("   Market breaking below consolidation range")
    print()

    snapshot_reversal = {
        "price": {"spot": 25150.0, "futures": 25140.0, "atm_strike": 25150.0},
        "trend": {
            "supertrend_1min": {"value": 25160.0, "signal": "DOWN"},  # Flipped!
            "supertrend_5min": {"value": 25180.0, "signal": "DOWN"},  # Flipped!
            "supertrend_15min": {"value": 25100.0, "signal": "UP"},  # Still up, but weakening
            "st_consensus": "DOWN",
            "adx": 32.0,  # ADX jumping = strong move (down)
        },
        "momentum": {
            "rsi": 38.0,  # Dropped below 50 = momentum flipped
            "ema_5": 25140.0,
            "ema_20": 25200.0,  # EMA crossover broken!
            "ema_50": 25090.0,
            "ema_crossover": False,  # 5 < 20
        },
        "volatility": {"atr": 58.0, "india_vix": 19.5, "iv_rank": 0.52, "iv_regime": "ELEVATED"},
        "structure": {"support": 25000.0, "resistance": 25280.0},
        "energy": {"bb_pct_b": 0.25, "vwap": 25200.0},
        "greeks": {"agg_delta": -0.10, "agg_gamma": 0.04, "agg_vega": 0.05},  # Delta flipped!
    }

    conf_reversal = score_confidence(snapshot_reversal, direction="DOWN")
    print(f"   🔍 PA Confidence DOWN: {conf_reversal['confidence_pct']:.0f}%")
    print(f"   📈 Recommendation: {conf_reversal['recommendation']}")
    print(f"   ⚠️  REVERSAL CONFIRMED: ST flipped, EMA crossover broken, RSI < 50")
    print()

    # ─────────────────────────────────────────────────────────────────────────────
    # MOMENT 5: 15:30 PM — END OF DAY (back to start)
    # ─────────────────────────────────────────────────────────────────────────────
    print("📊 MOMENT 5: 15:30 PM — END OF DAY (back to open)")
    print("   NIFTY Spot: 25000 (back to open price)")
    print("   Full reversal complete in ~6 hours")
    print()

    snapshot_eod = {
        "price": {"spot": 25000.0, "futures": 24990.0, "atm_strike": 25000.0},
        "trend": {
            "supertrend_1min": {"value": 25050.0, "signal": "DOWN"},
            "supertrend_5min": {"value": 25080.0, "signal": "DOWN"},
            "supertrend_15min": {"value": 25100.0, "signal": "DOWN"},
            "st_consensus": "DOWN",
            "adx": 28.0,
        },
        "momentum": {"rsi": 32.0, "ema_5": 24990.0, "ema_20": 25080.0, "ema_50": 25100.0, "ema_crossover": False},
        "volatility": {"atr": 62.0, "india_vix": 21.0, "iv_rank": 0.58, "iv_regime": "ELEVATED"},
        "structure": {"support": 24950.0, "resistance": 25100.0},
        "energy": {"bb_pct_b": 0.15, "vwap": 25050.0},
        "greeks": {"agg_delta": -0.35, "agg_gamma": 0.05, "agg_vega": 0.12},
    }

    conf_eod = score_confidence(snapshot_eod, direction="DOWN")
    print(f"   🔍 PA Confidence DOWN: {conf_eod['confidence_pct']:.0f}%")
    print(f"   📈 Recommendation: {conf_eod['recommendation']}")
    print()

    # ─────────────────────────────────────────────────────────────────────────────
    # SUMMARY: What should a trader have done?
    # ─────────────────────────────────────────────────────────────────────────────
    print("=" * 80)
    print("📋 SUMMARY: PA RESEARCHER ANALYSIS & TRADER DECISIONS")
    print("=" * 80)
    print()

    print("🎯 ENTRY OPPORTUNITY (09:15-12:15)")
    print("   • 09:15: Weak signals (ADX=15), wait for confirmation")
    print("   • 10:00-12:15: Strong UP confirmed (ADX=35, EMA crossover, RSI>70)")
    print("   • Decision: BUY IRON FLY or CREDIT SPREAD on UP signal")
    print("   • Best Entry: 10:30-11:30 (when ADX crossed 25)")
    print()

    print("⚠️  EXIT OPPORTUNITY (12:15-13:45)")
    print("   • 12:15: RSI=72 (overbought) → Take profit or scale back")
    print("   • 12:45: RSI cooling to 58, ADX declining → First warning")
    print("   • 13:45: REVERSAL CONFIRMED → Exit position immediately")
    print("   • Cost of holding through 13:45: -300 pts unrealized loss")
    print()

    print("📊 PATTERN ANALYSIS")
    trades_history = [
        {
            "trade_id": "T1",
            "strategy": "IRON_FLY",
            "entry_price": 25100,
            "exit_price": 25300,
            "entry_time": "10:30",
            "exit_time": "12:15",
            "pnl": 1500,
            "success": True,
        },
        {
            "trade_id": "T2",
            "strategy": "IRON_FLY",
            "entry_price": 25300,
            "exit_price": 25000,
            "entry_time": "12:30",
            "exit_time": "15:30",
            "pnl": -1800,
            "success": False,
        },
    ]

    patterns = detect_patterns(trades_history)
    print(f"   Pattern Detected: {patterns}")
    print()

    # ─────────────────────────────────────────────────────────────────────────────
    # INSIGHTS FOR PM CREW
    # ─────────────────────────────────────────────────────────────────────────────
    print("=" * 80)
    print("💡 PA RECOMMENDATIONS FOR PM CREW")
    print("=" * 80)
    print()

    print("1️⃣  STRATEGY SELECTION")
    print("   ✓ For TRENDING markets (09:15-12:15): Use CREDIT SPREAD or IRON FLY")
    print("   ✗ For REVERSAL risk (13:45+): Avoid selling naked, use IRON FLY hedged")
    print()

    print("2️⃣  ENTRY WINDOW")
    entry_window = analyze_entry_window(trades_history)
    print(f"   {entry_window}")
    print()

    print("3️⃣  RISK MANAGEMENT")
    print("   ✓ Buy protection on SHORT positions when RSI > 70")
    print("   ✓ Exit when ADX declines + RSI cools (early warning)")
    print("   ✓ Do NOT hold through reversal — ST flip = exit signal")
    print()

    print("4️⃣  POSITION SIZING")
    print("   • Risk per reversal trade: ~300 pts")
    print("   • Profit per trend trade: ~200 pts")
    print("   • Recommend: 3:1 trend-to-reversal position ratio")
    print()

    print("5️⃣  LESSON FOR TOMORROW")
    print("   • Market: UP 3hrs → PAUSE 0.5hrs → REVERSAL (complete)")
    print("   • What worked: Early entry at 10:30 (+200 pts profit)")
    print("   • What failed: Holding past 12:45 (-300 pts loss)")
    print("   • Takeaway: Reversal at 13:45 was predictable from 12:45 signals")
    print()


if __name__ == "__main__":
    simulate_market_scenario()
