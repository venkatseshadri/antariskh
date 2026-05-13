"""Portfolio Manager deterministic tools.

Strategy selection, strike calculation, spec generation, CEO reporting,
wing-width margin optimization.
"""

import json
import logging
from datetime import datetime as _dt
from pathlib import Path
from typing import Dict, List, Any, Optional

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
MARGIN_LIMIT = 85.0  # max margin utilization % before scaling down

logger = logging.getLogger("PM-Tools")


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
    wing_width: Optional[int] = None,
) -> Dict[str, Any]:
    """Build a complete strategy spec dict for TA validation.

    Uses antariksh_rules.yaml parameters for SL/TSL/lots/indicators.

    Wing width is taken from:
    1. Explicit wing_width parameter, or
    2. market_state["recommended_wing"] (set by PM/recommend_optimal_wing), or
    3. Dynamic default: 350 at VIX > 20, 300 otherwise.
    """
    nifty_spot = market_state.get("nifty_spot", 24500)
    vix = market_state.get("vix", 15.0)
    indicators = market_state.get("indicators", {})

    if wing_width is None:
        wing_width = market_state.get("recommended_wing")

    if wing_width is None:
        wing_width = (
            HIGH_VIX_WING_WIDTH if vix > VIX_HIGH_THRESHOLD else DEFAULT_WING_WIDTH
        )

    strikes = calculate_strikes(nifty_spot, strategy_type, wing_width, STRIKE_GRID)

    spec = {
        "type": strategy_type,
        "strikes": strikes,
        "wings": wing_width,
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
# Wing Width Margin Optimization — calls broker SPAN calculator
# ============================================================

WING_INCREMENT = 50
WING_MIN = 50
WING_MAX = 500

# Breach risk scoring: wider wings = more room before hedge triggers
# but also more capital locked. VIX-adjusted.
BREACH_AT_100_VIX12 = 0.85  # 85% chance wing touched in 1 day at VIX 12
BREACH_AT_500_VIX12 = 0.10  # 10% at VIX 12
BREACH_AT_100_VIX25 = 0.98  # 98% at VIX 25
BREACH_AT_500_VIX25 = 0.45  # 45% at VIX 25


def _estimate_breach_risk(wing: int, vix: float) -> float:
    """Estimate probability the wing is breached intraday.

    Derived from: daily_range ≈ VIX / sqrt(252) * spot * 1.5
    At VIX=15, NIFTY daily range ~140pts → wing at 100 has ~85% touch prob.
    Linear interpolation between VIX 12 and VIX 25 baseline.
    """
    # Clamp wing to range we have data for
    wing = max(50, min(500, wing))

    # Linear interpolation of breach probability
    vix_frac = (max(12, min(25, vix)) - 12) / 13.0  # 0 at VIX=12, 1 at VIX=25

    breach_at_low_vix = (
        BREACH_AT_100_VIX12
        + (BREACH_AT_500_VIX12 - BREACH_AT_100_VIX12) * (wing - 50) / 450.0
    )
    breach_at_high_vix = (
        BREACH_AT_100_VIX25
        + (BREACH_AT_500_VIX25 - BREACH_AT_100_VIX25) * (wing - 50) / 450.0
    )

    breach = breach_at_low_vix + (breach_at_high_vix - breach_at_low_vix) * vix_frac
    return round(max(0.0, min(1.0, breach)), 4)


def _connect_shoonya_for_span():
    """Return authenticated NorenApiPy for span_calculator calls.

    Uses same cred.yml path as am_tools.query_broker_margin().
    """
    import importlib.util, yaml

    cred_path = Path("/home/trading_ceo/python-trader/Shoonya_oAuthAPI-py/cred.yml")
    if not cred_path.exists():
        raise FileNotFoundError(f"Shoonya cred.yml not found at {cred_path}")

    with open(cred_path) as f:
        cred = yaml.safe_load(f)

    spec = importlib.util.spec_from_file_location(
        "shoonya_api_helper",
        "/home/trading_ceo/python-trader/Shoonya_oAuthAPI-py/api_helper.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    NorenApiPy = mod.NorenApiPy

    api = NorenApiPy()
    api.injectOAuthHeader(
        cred.get("Access_token", ""),
        cred.get("UID", ""),
        str(cred.get("Account_ID", "")),
    )
    return api, cred


def _build_span_position(
    exch: str,
    instname: str,
    symname: str,
    expiry: str,
    optt: str,
    strike: float,
    buyqty: int,
    sellqty: int,
) -> Dict:
    """Build a single position dict for span_calculator.

    Lot size: NIFTY = 75, SENSEX = 10, BANKNIFTY = 30, stock = symbol-dependent.
    Uses OPTIDX for index options (prd='M' for intraday/MIS).
    """
    net = buyqty - sellqty
    return {
        "prd": "M",
        "exch": exch,
        "instname": instname,
        "symname": symname,
        "exd": expiry.upper(),
        "optt": optt,
        "strprc": f"{strike:.2f}",
        "buyqty": str(buyqty),
        "sellqty": str(sellqty),
        "netqty": str(net),
    }


def _get_expiry_fmt(date_str: Optional[str] = None) -> str:
    """Return expiry in DD-MON-YYYY format (e.g. '15-MAY-2026')."""
    d = _dt.now() if date_str is None else _dt.fromisoformat(date_str[:10])
    return d.strftime("%d-%b-%Y").upper()


def analyze_wing_margins(
    nifty_spot: float,
    lots: int = 1,
    expiry: Optional[str] = None,
    lot_size: int = 75,
    symbol: str = "NIFTY",
    exchange: str = "NFO",
    dry_run: bool = False,
) -> List[Dict]:
    """Call broker SPAN calculator for wing widths from WING_MIN to WING_MAX.

    Builds a 4-leg Iron Butterfly for each wing width and queries the broker
    SPAN calculator for actual margin required. The SPAN system already nets
    multi-leg positions — narrower wings consume less margin.

    Args:
        nifty_spot: Current NIFTY spot price
        lots: Number of lots (default 1)
        expiry: Expiry date string (default: auto-detect current week)
        lot_size: Lot size for the instrument (NIFTY=75)
        symbol: Trading symbol
        exchange: Exchange code (NFO)
        dry_run: If True, use heuristics instead of live API call

    Returns:
        List of dicts: [{wing, span, expo, total_margin, margin_per_lot, breach_risk, status}]
    """
    results = []
    atm = round(nifty_spot / STRIKE_GRID) * STRIKE_GRID
    expiry_fmt = _get_expiry_fmt(expiry)
    instname = "OPTIDX"

    api = None
    if not dry_run:
        try:
            api, cred = _connect_shoonya_for_span()
        except Exception as e:
            logger.warning(f"SPAN connection failed: {e}. Falling back to heuristics.")
            api = None

    vix = 15.0  # default for breach risk calc; caller should override

    for wing in range(WING_MIN, WING_MAX + 1, WING_INCREMENT):
        buy_qty = lots * lot_size
        sell_qty = lots * lot_size

        positions = [
            _build_span_position(
                exchange, instname, symbol, expiry_fmt, "PE", atm - wing, buy_qty, 0
            ),
            _build_span_position(
                exchange, instname, symbol, expiry_fmt, "PE", atm, 0, sell_qty
            ),
            _build_span_position(
                exchange, instname, symbol, expiry_fmt, "CE", atm, 0, sell_qty
            ),
            _build_span_position(
                exchange, instname, symbol, expiry_fmt, "CE", atm + wing, buy_qty, 0
            ),
        ]

        result = {
            "wing": wing,
            "lots": lots,
            "atm": atm,
            "expiry": expiry_fmt,
            "status": "OK",
        }
        breach = _estimate_breach_risk(wing, vix)
        result["breach_risk"] = breach

        if api is not None:
            try:
                actid = cred.get("user", "")
                span_resp = api.span_calculator(actid, positions)
                result["span"] = float(span_resp.get("span", 0))
                result["expo"] = float(span_resp.get("expo", 0))
                result["total_margin"] = result["span"] + result["expo"]
                result["margin_per_lot"] = result["total_margin"] / max(lots, 1)
            except Exception as e:
                result["status"] = f"API_ERROR: {str(e)[:80]}"
                result["span"] = 0
                result["expo"] = 0
                result["total_margin"] = 0
                result["margin_per_lot"] = 0
        else:
            # Heuristic fallback — SPAN charges based on max loss per lot.
            # Max loss per lot ≈ wing_width * lot_size (bought legs cap the risk).
            # SPAN ≈ max_loss * 1.8 + exposure buffer.
            # Real margins: wing=100 ~₹15k, wing=300 ~₹45k, wing=500 ~₹75k.
            margin_per_lot = (wing * lot_size * 1.8) + 5000
            result["span"] = round(margin_per_lot * 0.82, 2)
            result["expo"] = round(margin_per_lot * 0.18, 2)
            result["total_margin"] = round(margin_per_lot, 2)
            result["margin_per_lot"] = round(margin_per_lot, 2)
            result["status"] = "HEURISTIC"

        results.append(result)

    return results


def recommend_optimal_wing(
    nifty_spot: float,
    vix: float,
    free_cash: float,
    lots: int = 1,
    expiry: Optional[str] = None,
    dry_run: bool = False,
) -> Dict:
    """Recommend optimal wing width balancing margin usage and breach risk.

    Scores each wing width on:
    - Margin efficiency (40%): lower margin = higher score
    - Breach safety (40%): lower breach probability = higher score
    - Capital headroom (20%): lower % of free_cash consumed = higher score

    The winner is the wing width with the highest composite score that also
    keeps wings reasonably close to the sell leg (prefers narrower over wider
    when scores tie).

    Args:
        nifty_spot: Current spot
        vix: Current VIX
        free_cash: Free cash from AM margin query (total_available - total_used)
        lots: Number of lots
        expiry: Expiry date
        dry_run: Use heuristics instead of live API

    Returns:
        {recommended_wing, score, margin_analysis, rationale}
    """
    margin_results = analyze_wing_margins(nifty_spot, lots, expiry, dry_run=dry_run)

    # Update breach risk with actual VIX
    for r in margin_results:
        r["breach_risk"] = _estimate_breach_risk(r["wing"], vix)

    if not margin_results:
        return {
            "recommended_wing": DEFAULT_WING_WIDTH,
            "score": 0.0,
            "margin_analysis": [],
            "rationale": "No margin data available — using default.",
        }

    scored = []
    for r in margin_results:
        total = r["total_margin"]
        wing = r["wing"]
        breach = r["breach_risk"]

        # Skip wings we can't afford
        if total > free_cash:
            continue
        if free_cash <= 0:
            continue

        # Margin efficiency: lower margin → higher score
        # Normalize: cheapest wing=50 ~₹12k → 1.0, most expensive wing=500 ~₹73k → 0.0
        eff_range_min = 12000
        eff_range_max = 73000
        efficiency = 1.0 - (
            (total - eff_range_min) / max(1, eff_range_max - eff_range_min)
        )
        efficiency = max(0.0, min(1.0, efficiency))

        # Breach safety: lower breach prob → higher score
        safety = 1.0 - breach

        # Capital headroom: lower % of free cash used → higher score
        headroom = 1.0 - (total / free_cash)

        # Proximity: wings ≤ 250 are "close enough to sell leg" → full score.
        # Wings > 250 start getting penalized for being too far from ATM.
        # This captures user's "without going away TOO FAR from the sell leg".
        proximity = 1.0 if wing <= 250 else max(0.0, 1.0 - ((wing - 250) / 250))

        # Hedge effectiveness penalty: wings with >70% breach risk aren't real hedges.
        # They're too narrow to provide meaningful protection — the wing gets hit
        # almost every session, effectively making this a naked straddle.
        hedge_factor = 1.0
        if breach > 0.85:
            hedge_factor = 0.30  # nearly useless hedge → 70% penalty
        elif breach > 0.70:
            hedge_factor = 0.65  # marginal hedge → 35% penalty

        # Composite: efficiency(25%) + safety(25%) + proximity(25%) + headroom(25%)
        # All four factors weighted equally — no single dimension dominates.
        score = (
            efficiency * 0.25 + safety * 0.25 + proximity * 0.25 + headroom * 0.25
        ) * hedge_factor

        scored.append(
            {
                "wing": wing,
                "total_margin": total,
                "breach_risk": breach,
                "efficiency": round(efficiency, 4),
                "safety": round(safety, 4),
                "headroom": round(headroom, 4),
                "score": round(score, 4),
                "margin_pct_of_cash": round((total / free_cash * 100), 1)
                if free_cash > 0
                else 999,
            }
        )

    if not scored:
        # All wings exceed free cash — pick the cheapest
        cheapest = min(margin_results, key=lambda r: r["total_margin"])
        return {
            "recommended_wing": cheapest["wing"],
            "score": 0.0,
            "margin_analysis": scored,
            "rationale": (
                f"ALL wings exceed free cash (₹{free_cash:,.0f}). "
                f"Cheapest is wing={cheapest['wing']} at ₹{cheapest['total_margin']:,.0f} — "
                f"insufficient capital. HALT or reduce lots."
            ),
        }

    # Sort by score descending, then by wing ascending (prefer narrower on tie)
    scored.sort(key=lambda s: (-s["score"], s["wing"]))
    best = scored[0]

    runner_up = scored[1] if len(scored) > 1 else None
    worst_affordable = scored[-1]

    rationale_lines = [
        f"Wing width recommendation for NIFTY@{nifty_spot} VIX={vix} free_cash=₹{free_cash:,.0f}:",
        f"Winner: wing={best['wing']} (margin ₹{best['total_margin']:,.0f}, "
        f"breach_risk={best['breach_risk']:.1%}, score={best['score']:.3f})",
    ]
    if runner_up:
        rationale_lines.append(
            f"Runner-up: wing={runner_up['wing']} (margin ₹{runner_up['total_margin']:,.0f}, score={runner_up['score']:.3f})"
        )
    rationale_lines.append(
        f"Range: wing={scored[0]['wing']}→{worst_affordable['wing']} affordable "
        f"(₹{scored[0]['total_margin']:,.0f}→₹{worst_affordable['total_margin']:,.0f})"
    )

    return {
        "recommended_wing": best["wing"],
        "score": best["score"],
        "margin_analysis": scored,
        "all_results": margin_results,
        "rationale": "\n".join(rationale_lines),
    }


# ============================================================
# Position Sizing — uses AM's margin data to compute max lots
# ============================================================

LOT_MARGIN_REQUIRED = 45000  # ~₹45k per lot for NIFTY Iron Fly (wings + ATM sells)
MIN_FREE_CASH_AFTER = 25000  # must leave at least ₹25k free after position


def compute_position_size(
    total_margin_available: float,
    total_margin_used: float,
    free_cash: float,
    lot_margin: float = LOT_MARGIN_REQUIRED,
    min_free_cash: float = MIN_FREE_CASH_AFTER,
) -> Dict:
    """Compute maximum affordable lots based on actual broker margin.

    Safeguards:
    - Never exceeds MAX_LOTS from antariksh_rules.yaml (hard cap)
    - Leaves MIN_FREE_CASH_AFTER as buffer
    - Respects margin utilization target (don't use 100%)

    Returns:
        {max_lots: int, margin_per_lot, total_margin_needed, reason, evidence}
    """
    free = total_margin_available - total_margin_used
    usable = free - min_free_cash

    if usable <= 0:
        return {
            "max_lots": 0,
            "margin_per_lot": lot_margin,
            "total_margin_needed": 0,
            "reason": f"Not enough free margin: ₹{free:,.0f} available, ₹{min_free_cash:,.0f} minimum buffer",
            "evidence": f"Free: ₹{free:,.0f}, usable: ₹{usable:,.0f}, lot_margin: ₹{lot_margin:,.0f}",
        }

    affordable = int(usable / lot_margin)
    max_lots = min(affordable, MAX_LOTS)

    # Scale down if margin utilization is high
    util_pct = (
        (total_margin_used / total_margin_available * 100)
        if total_margin_available > 0
        else 100
    )
    if util_pct > MARGIN_LIMIT:
        max_lots = max(1, max_lots - 1)  # reduce by 1 if close to limit

    if max_lots == 0:
        return {
            "max_lots": 0,
            "margin_per_lot": lot_margin,
            "total_margin_needed": lot_margin,
            "reason": f"Can't afford even 1 lot: need ₹{lot_margin:,.0f}, have ₹{usable:,.0f} usable",
            "evidence": f"total_margin: ₹{total_margin_available:,.0f}, used: ₹{total_margin_used:,.0f}, free_cash: ₹{free_cash:,.0f}",
        }

    needed = max_lots * lot_margin
    return {
        "max_lots": max_lots,
        "margin_per_lot": lot_margin,
        "total_margin_needed": needed,
        "reason": f"{max_lots} lot(s) at ₹{lot_margin:,.0f}/lot = ₹{needed:,.0f} needed (₹{usable:,.0f} usable, ∀{util_pct:.0f}% util)",
        "evidence": f"Available: ₹{total_margin_available:,.0f}, Used: ₹{total_margin_used:,.0f}, Lot margin: ₹{lot_margin:,.0f}, Max: {MAX_LOTS}",
    }


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
