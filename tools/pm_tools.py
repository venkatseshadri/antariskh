"""Portfolio Manager deterministic tools.

Strategy selection, strike calculation, spec generation, CEO reporting.
"""

from typing import Dict, List, Any

# ─────────────────────────────────────────────────────────────────
# Constants from antariksh_rules.yaml (immutable — read-only reference)
# ─────────────────────────────────────────────────────────────────

DEFAULT_WING_WIDTH = 300
HIGH_VIX_WING_WIDTH = 350
VIX_HIGH_THRESHOLD = 20.0
STRIKE_GRID = 50
MAX_LOTS = 2
MAX_INDICATORS = 8
SL_SESSION_INR = 3500
TSL_POINTS = 250


# ============================================================
# Strategy Selection
# ============================================================


def select_strategy(market_state: Dict[str, Any]) -> Dict[str, Any]:
    """Select strategy type based on market conditions.

    Iron Fly: normal conditions — VIX < 20, bullish/neutral, no major events
    Credit Spread: VIX > 20, bearish, event day, gap > 0.5%

    Confirmation override: high ADX + all bullish confirmations can still select
    Iron Fly even at VIX > 20 (strong trend = direction neutral IF works).

    Returns:
        {type: "IRON_FLY"|"CREDIT_SPREAD", reason: str, indicator_scores: dict}
    """
    vix = market_state.get("vix", 15.0)
    indicators = market_state.get("indicators", {})
    event_day = market_state.get("event_day", False)
    gap_pct = market_state.get("gap_pct", 0.0)
    sentiment = market_state.get("sentiment", "NEUTRAL")
    adx = indicators.get("adx", 20.0)

    scores = {
        "vix_score": 1.0 if vix < VIX_HIGH_THRESHOLD else 0.3,
        "sentiment_score": 1.0 if sentiment in ("BULLISH", "NEUTRAL") else 0.3,
        "event_score": 0.0 if event_day else 1.0,
        "gap_score": 1.0 if gap_pct <= 0.5 else 0.3,
    }

    # High ADX + all bullish confirmations = strong trend, IB still viable
    bullish_confirmations = all(
        [
            indicators.get("supertrend_1min") == "BULLISH",
            indicators.get("ema_5_20_alignment", False),
            indicators.get("smc_bos_alignment", False),
        ]
    )
    strong_trend = adx > 25 and bullish_confirmations

    # Weighted decision
    iron_fly_score = (
        scores["vix_score"] * 0.35
        + scores["sentiment_score"] * 0.20
        + scores["event_score"] * 0.30
        + scores["gap_score"] * 0.15
        + (0.3 if strong_trend else 0.0)
    )

    if iron_fly_score >= 0.6:
        return {
            "type": "IRON_FLY",
            "reason": (
                f"IF selected: VIX={vix}, sentiment={sentiment}, "
                f"event={'YES' if event_day else 'NO'}, gap={gap_pct}%"
            ),
            "indicator_scores": scores,
        }

    return {
        "type": "CREDIT_SPREAD",
        "reason": (
            f"CS selected: VIX={vix} (>20), sentiment={sentiment}, "
            f"event={'YES' if event_day else 'NO'}, gap={gap_pct}%"
        ),
        "indicator_scores": scores,
    }


# ============================================================
# Strike Calculation
# ============================================================


def calculate_strikes(
    nifty_spot: float,
    strategy_type: str,
    wing_width: int = DEFAULT_WING_WIDTH,
    grid: int = STRIKE_GRID,
) -> List[float]:
    """Calculate option strikes for a strategy.

    Iron Butterfly:
        [spot - wing, near ATM below, near ATM above, spot + wing]

    Credit Spread:
        [spot - wing, spot + wing]

    All strikes snapped to the grid (e.g., 24513 → 24500 on 50-grid).
    """
    # Snap ATM to nearest grid
    atm = round(nifty_spot / grid) * grid

    if strategy_type == "CREDIT_SPREAD":
        lower = round((nifty_spot - wing_width) / grid) * grid
        upper = round((nifty_spot + wing_width) / grid) * grid
        return [lower, upper]

    # Iron Butterfly — 4 legs
    lower_sell = round((nifty_spot - wing_width) / grid) * grid
    lower_buy = atm - grid  # one grid below ATM
    upper_buy = atm + grid  # one grid above ATM
    upper_sell = round((nifty_spot + wing_width) / grid) * grid

    # Ensure monotonic
    strikes = sorted([lower_sell, lower_buy, upper_buy, upper_sell])

    # Deduplicate if any adjacent legs collide
    result = []
    for s in strikes:
        if not result or s != result[-1]:
            result.append(s)

    return result


# ============================================================
# Strategy Spec Builder
# ============================================================


def build_strategy_spec(
    strategy_type: str,
    market_state: Dict[str, Any],
) -> Dict[str, Any]:
    """Build a complete strategy spec dict for TA validation.

    Uses antariksh_rules.yaml parameters for SL/TSL/lots/indicators.
    """
    nifty_spot = market_state.get("nifty_spot", 24500)
    vix = market_state.get("vix", 15.0)
    indicators = market_state.get("indicators", {})

    wing = HIGH_VIX_WING_WIDTH if vix > 15 else DEFAULT_WING_WIDTH
    strikes = calculate_strikes(nifty_spot, strategy_type, wing, STRIKE_GRID)

    spec = {
        "type": strategy_type,
        "strikes": strikes,
        "wings": wing,
        "lots": 1,  # Phase 1: fixed 1 lot
        "sl": SL_SESSION_INR,
        "tsl": TSL_POINTS,
        "entry_window": {"start": "10:30", "end": "11:30"},
        "indicators": {
            "vix_max": VIX_HIGH_THRESHOLD,
            "vix_min": 10.0,
            "supertrend": indicators.get("supertrend_1min", "NEUTRAL"),
            "require_n_of_3": 2,
        },
        "broker": "shoonya",
        "nifty_spot": nifty_spot,
        "vix_at_spec_time": vix,
    }

    return spec


# ============================================================
# CEO Strategy Summary
# ============================================================


def generate_strategy_summary(
    specs: List[Dict[str, Any]],
    win_rate: float,
    profit_factor: float,
    pa_actions_taken: int = 0,
) -> Dict[str, Any]:
    """Generate CEO strategy summary from active spec + performance metrics.

    Returns:
        {strategies_active, win_rate, profit_factor, pa_actions, text}
    """
    active = len(specs)
    types = [s.get("type", "?") for s in specs]

    lines = [
        "# PM Strategy Summary for CEO",
        "",
        f"**Active Strategies:** {active} ({', '.join(types) if types else 'none'})",
        f"**Win Rate:** {win_rate:.0%}",
        f"**Profit Factor:** {profit_factor:.2f}",
        f"**PA Actions Taken:** {pa_actions_taken}",
        "",
    ]

    if active > 0:
        lines.append("## Active Specs")
        for i, spec in enumerate(specs):
            lines.append(
                f"- **{spec['type']}**: strikes={spec['strikes']}, "
                f"wing={spec['wings']}pts, lots={spec['lots']}, "
                f"SL=₹{spec['sl']}, TSL={spec['tsl']}pts"
            )

    if win_rate >= 0.60:
        lines.append("")
        lines.append("**Verdict:** ✅ WR above target — strategy performing well")
    elif win_rate >= 0.55:
        lines.append("")
        lines.append("**Verdict:** ⚠️ WR near floor — monitor closely")
    else:
        lines.append("")
        lines.append("**Verdict:** ❌ WR below floor — PA review triggered")

    return {
        "strategies_active": active,
        "win_rate": round(win_rate, 3),
        "profit_factor": round(profit_factor, 2),
        "pa_actions_taken": pa_actions_taken,
        "text": "\n".join(lines),
    }
