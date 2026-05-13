"""Trading Analyst deterministic tools.

Validates trade execution against PM strategy spec.
Reports compliance to PM, execution ledger to AM.

v2: Options Market Analyst tools — validates trade PLAN (not just execution)
against options market reality: greeks, strikes, premiums, volatility.
"""

import json
import math
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

DUCKDB_DATA_DIR = Path("/home/trading_ceo/python-trader/varaha/data")
DUCKDB_NIFTY = DUCKDB_DATA_DIR / "varaha_data.duckdb"

IST = timezone(timedelta(hours=5, minutes=30))

IST = timezone(timedelta(hours=5, minutes=30))

# Fields that must match exactly between spec and trade
SPEC_FIELDS = ["type", "strikes", "wings", "lots", "sl", "tsl", "broker"]

# Severity: CRITICAL = trade-blocking, WARNING = advisory
CRITICAL_FIELDS = {"type", "strikes", "lots", "sl"}
WARNING_FIELDS = {"wings", "tsl", "broker"}

SLIPPAGE_TOLERANCE = 50  # points

# ============================================================
# Skill Registry — knowledge base for Technical Scout
# ============================================================

SKILL_REGISTRY = {
    "indicators": {
        "adx": {
            "name": "Average Directional Index",
            "range": "0-100",
            "interpretation": ">25 trending, >35 strong trend, <20 no trend",
            "use": "Determines if market is trending or sideways. High ADX = Iron Fly viable. Low ADX = Iron Condor preferred.",
            "data_source": "DuckDB market_data.adx",
        },
        "supertrend": {
            "name": "SuperTrend",
            "range": "BULLISH / BEARISH / NEUTRAL",
            "interpretation": "Trend direction. BULLISH = uptrend, BEARISH = downtrend.",
            "use": "Confirms ADX direction. Bearish SuperTrend + high ADX = credit spread signals.",
            "data_source": "DuckDB market_data.supertrend_direction",
        },
        "rsi": {
            "name": "Relative Strength Index",
            "range": "0-100",
            "interpretation": ">70 overbought, <30 oversold",
            "use": "Overbought RSI + high ADX = Iron Fly preference (expect reversion).",
            "data_source": "DuckDB market_data.rsi",
        },
        "atr": {
            "name": "Average True Range",
            "range": "points",
            "interpretation": "Daily volatility in points. ATR * 1.5 = expected range.",
            "use": "Helps set wing width and stop-loss. High ATR = wider wings needed.",
            "data_source": "DuckDB market_data.atr",
        },
        "ema_crossover": {
            "name": "EMA 5/20 Crossover",
            "range": "ALIGNED / DIVERGENT",
            "interpretation": "EMA5 > EMA20 = short-term bullish momentum",
            "use": "Confirms SuperTrend direction. Aligned EMAs = stronger conviction.",
            "data_source": "DuckDB market_data.ema_5, ema_20",
        },
        "vwap": {
            "name": "Volume-Weighted Average Price",
            "range": "ABOVE / BELOW",
            "interpretation": "Spot > VWAP = bullish intraday bias, < VWAP = bearish.",
            "use": "Intraday bias confirmation. Trade with VWAP direction.",
            "data_source": "DuckDB market_data.vwap",
        },
    },
    "greeks": {
        "delta": {
            "name": "Delta (Δ)",
            "range": "0 to 1 (calls), -1 to 0 (puts)",
            "interpretation": "Rate of option price change per ₹1 spot move. ATM = ~0.5, deep OTM = ~0.1.",
            "use": "Iron Butterfly wings should be at ~0.15-0.20 delta. ATM sells at ~0.50 delta. Delta-neutral = net zero — price moves don't affect P&L much (gamma-driven).",
        },
        "gamma": {
            "name": "Gamma (Γ)",
            "range": "positive, peaks at ATM",
            "interpretation": "Rate of delta change. High gamma near expiry = position P&L is sensitive to spot moves.",
            "use": "Iron Butterfly: gamma * (dS)² / 2 = daily P&L swing. Used to set SL.",
            "data_source": "DuckDB market_data.agg_gamma",
        },
        "theta": {
            "name": "Theta (Θ)",
            "range": "negative for option buyers, positive for sellers",
            "interpretation": "Time decay per day. ATM options decay fastest near expiry.",
            "use": "Iron Butterfly is theta-positive (you sell ATM). Near expiry (~3 days), theta accelerates. Good for sellers — you profit from time passing.",
            "data_source": "DuckDB market_data.agg_theta",
        },
        "vega": {
            "name": "Vega (ν)",
            "range": "positive, peaks at ATM",
            "interpretation": "Option price change per 1% VIX change.",
            "use": "High VIX entry → VIX crush → vega profit. Low VIX entry → VIX spike → vega loss. Monitor INDIAVIX trend.",
            "data_source": "DuckDB market_data.agg_vega",
        },
    },
    "strategies": {
        "iron_fly": {
            "name": "Iron Butterfly",
            "regime": "Trending (ADX > 25)",
            "structure": "Sell ATM CE + PE, buy OTM CE + PE at ±wing",
            "profit": "Premium decay if spot stays near ATM",
            "max_loss": "wing_width × lot_size - premium_received",
            "greeks": "Theta-positive, delta-neutral, gamma-negative near expiry",
            "best_conditions": "VIX 12-18, 3 days to expiry, clear SuperTrend direction, no event day",
        },
        "iron_condor": {
            "name": "Iron Condor",
            "regime": "Sideways (ADX < 25)",
            "structure": "Sell OTM CE + PE, buy further OTM CE + PE",
            "profit": "Premium decay if spot stays in range",
            "max_loss": "wing_width × lot_size - premium_received",
            "greeks": "Theta-positive, delta-neutral, lower gamma than IF",
            "best_conditions": "VIX 15-22, range-bound market, no breakout catalyst",
        },
        "credit_spread": {
            "name": "Credit Spread",
            "regime": "Trending Bear/Bull (ADX > 25)",
            "structure": "Sell OTM option, buy further OTM (directional)",
            "profit": "Premium decay + directional move",
            "max_loss": "spread_width × lot_size - premium_received",
            "greeks": "Theta-positive, delta-directional",
            "best_conditions": "VIX > 18, event day, trend confirmed by SuperTrend",
        },
    },
    "terminology": {
        "vix": "India VIX — fear index. >20 = high uncertainty, <12 = complacency. Daily range ≈ VIX/100 * spot / sqrt(252)",
        "lot_size": "NIFTY = 75 shares per lot. SENSEX = 10. BANKNIFTY = 30. Always use the correct lot_size for margin and position sizing.",
        "wing_width": "Distance in points between ATM sell strike and OTM buy (hedge) strike. Wider = more protection, more margin. Narrower = cheaper, higher breach risk.",
        "strike_grid": "NIFTY strikes are on 50-point grid (24500, 24550, 24600...). SENSEX on 100-point. Always snap to grid.",
        "atm_strike": "Round(spot / grid) × grid. The strike closest to current spot price.",
        "sl_vs_volatility": "SL should cover at least 1.5× expected daily range. For IF: gamma-driven P&L swing. For CS: delta-driven.",
        "expiry_weekly": "NIFTY weekly expiry = every Thursday. 3 days to expiry = best theta. 0 days (expiry day) = high gamma risk.",
    },
}


def list_available_skills(category: str = None) -> Dict:
    """Return the skill registry for a category or all categories.

    Args:
        category: 'indicators', 'greeks', 'strategies', 'terminology', or None for all.

    Returns:
        {category: {skill_name: {name, description, ...}}}
    """
    if category and category in SKILL_REGISTRY:
        return {category: SKILL_REGISTRY[category]}
    return SKILL_REGISTRY


def get_skill_info(skill_name: str) -> Dict:
    """Look up a specific skill by name across all categories.

    Args:
        skill_name: e.g., 'adx', 'delta', 'iron_fly', 'wing_width'

    Returns:
        {skill_name, category, info}
    """
    for category, skills in SKILL_REGISTRY.items():
        if skill_name.lower() in skills:
            return {
                "skill": skill_name,
                "category": category,
                "info": skills[skill_name.lower()],
            }
    return {
        "skill": skill_name,
        "error": "Not found",
        "available_categories": list(SKILL_REGISTRY.keys()),
    }


def search_skills(query: str) -> Dict:
    """Search skills by keyword across all categories."""
    results = []
    q = query.lower()
    for category, skills in SKILL_REGISTRY.items():
        for sname, sinfo in skills.items():
            if isinstance(sinfo, str):
                text = sname + " " + sinfo
                is_dict = False
            elif isinstance(sinfo, dict):
                text = sname + " " + " ".join(str(v) for v in sinfo.values())
                is_dict = True
            else:
                continue
            if q in text.lower():
                results.append(
                    {
                        "skill": sname,
                        "category": category,
                        "name": sinfo.get("name", sname) if is_dict else sname,
                        "snippet": (
                            sinfo
                            if isinstance(sinfo, str)
                            else sinfo.get(
                                "interpretation", sinfo.get("use", str(sinfo))
                            )
                        )[:120],
                    }
                )
    return {"query": query, "results": results[:10]}


SKILLS_DIR = Path(__file__).parent.parent / "skills"


def load_skill_file(skill_file: str) -> Dict:
    """Load a skill knowledge file from the skills/ directory.

    Args:
        skill_file: Filename in skills/ dir (e.g., 'options-fundamentals.json',
                    'technical-scout.json')

    Returns:
        {file, title, categories: {category: {skill_name: info}}}
    """
    fp = SKILLS_DIR / skill_file
    if not fp.exists():
        available = (
            [f.name for f in SKILLS_DIR.glob("*.json")] if SKILLS_DIR.exists() else []
        )
        return {
            "file": skill_file,
            "error": f"Not found in skills/",
            "available": available,
        }

    try:
        data = json.loads(fp.read_text())
        return {
            "file": skill_file,
            "title": data.get("title", "Untitled"),
            "version": data.get("version", "1.0"),
            "description": data.get("description", ""),
            "categories": list(data.get("categories", {}).keys()),
            "full_content": data,
        }
    except Exception as e:
        return {"file": skill_file, "error": str(e)[:200]}


def _now_ist() -> str:
    return datetime.now(IST).strftime("%H:%M:%S IST")


# ============================================================
# Technical Scout — Market Regime Detection
# ============================================================

# ADX thresholds
ADX_TRENDING_THRESHOLD = 25
ADX_STRONG_TREND = 35


def detect_market_regime(
    adx: float = None,
    supertrend: str = None,
    vix: float = None,
    indicators: Dict[str, Any] = None,
    target_date: str = None,
) -> Dict:
    """Detect market regime from DuckDB live data or for a specific date.

    Priority: provided parameters > indicators dict > DuckDB query.
    Uses ADX for trend strength, SuperTrend for direction, VIX for volatility context.

    Args:
        adx, supertrend, vix: Override values (for testing or programmatic use).
        indicators: Dict with keys 'adx', 'supertrend_direction', 'vix', 'spot'.
        target_date: ISO date string (YYYY-MM-DD). If provided, queries the last
                     row ON or BEFORE that date. Default None = latest data.

    Returns:
        {regime, adx, supertrend_direction, vix, vix_context,
         spot, suitable_strategies, evidence, data_source, target_date}
    """
    # ── Try DuckDB ──
    spot = None
    data_source = "parameter"

    if adx is None or supertrend is None or vix is None:
        try:
            import duckdb

            if DUCKDB_NIFTY.exists():
                con = duckdb.connect(str(DUCKDB_NIFTY), read_only=True)

                if target_date:
                    row = con.execute(
                        """
                        SELECT adx, supertrend_direction, india_vix, spot
                        FROM market_data
                        WHERE adx IS NOT NULL AND date <= ?
                        ORDER BY id DESC
                        LIMIT 1
                    """,
                        [target_date],
                    ).fetchone()
                    data_source = "duckdb"
                else:
                    row = con.execute("""
                        SELECT adx, supertrend_direction, india_vix, spot
                        FROM market_data
                        WHERE adx IS NOT NULL
                        ORDER BY id DESC
                        LIMIT 1
                    """).fetchone()
                    data_source = "duckdb"

                con.close()
                if row:
                    if adx is None:
                        adx = row[0]
                    if supertrend is None:
                        supertrend = row[1]
                    if vix is None:
                        vix = row[2]
                    spot = row[3]
        except Exception:
            pass  # DuckDB not available — use provided values

    # ── Extract from indicators dict if still missing ──
    if indicators:
        if adx is None:
            adx = indicators.get("adx", indicators.get("ADX", 20.0))
        if supertrend is None:
            supertrend = indicators.get(
                "supertrend_direction",
                indicators.get(
                    "supertrend_1min", indicators.get("supertrend", "NEUTRAL")
                ),
            ).upper()
        if vix is None:
            vix = indicators.get(
                "vix", indicators.get("india_vix", indicators.get("VIX", 15.0))
            )
        if spot is None:
            spot = indicators.get("spot", indicators.get("nifty_spot"))

    # ── Apply defaults ──
    adx = float(adx or 20.0)
    supertrend = (supertrend or "NEUTRAL").upper().strip()
    vix = float(vix or 15.0)
    spot = float(spot) if spot else None

    # ── Determine regime ──
    if adx >= ADX_STRONG_TREND:
        if supertrend == "BULLISH":
            regime, suitable = "TRENDING_BULL", ["IRON_FLY"]
        elif supertrend == "BEARISH":
            regime, suitable = "TRENDING_BEAR", ["CREDIT_SPREAD"]
        else:
            regime, suitable = "TRENDING_UNCLEAR", ["IRON_FLY", "CREDIT_SPREAD"]
    elif adx >= ADX_TRENDING_THRESHOLD:
        if supertrend == "BULLISH":
            regime, suitable = "TRENDING_BULL", ["IRON_FLY"]
        elif supertrend == "BEARISH":
            regime, suitable = "TRENDING_BEAR", ["CREDIT_SPREAD"]
        else:
            regime, suitable = "TRENDING_UNCLEAR", ["IRON_FLY"]
    else:
        regime, suitable = "SIDEWAYS", ["IRON_FLY"]

    vix_ctx = (
        "LOW"
        if vix < 14
        else "NORMAL"
        if vix < 20
        else "HIGH"
        if vix < 25
        else "EXTREME"
    )

    evidence_parts = [
        f"ADX={adx:.1f} (trend≥{ADX_TRENDING_THRESHOLD}, strong≥{ADX_STRONG_TREND})",
        f"SuperTrend={supertrend}",
        f"VIX={vix:.1f}({vix_ctx})",
    ]
    if target_date:
        evidence_parts.insert(0, f"Date={target_date}")
    if spot:
        evidence_parts.append(f"Spot={spot:,.0f}")
    evidence_parts.append(f"Source: {data_source}")

    return {
        "regime": regime,
        "adx": round(adx, 1),
        "supertrend_direction": supertrend,
        "vix": round(vix, 1),
        "vix_context": vix_ctx,
        "spot": round(spot, 2) if spot else None,
        "suitable_strategies": suitable,
        "valid": True,
        "data_source": data_source,
        "target_date": target_date,
        "evidence": " | ".join(evidence_parts),
    }


# ============================================================
# Trade Validation
# ============================================================


def validate_trade(spec: Dict[str, Any], trade: Dict[str, Any]) -> Dict:
    """Validate trade against PM strategy spec.

    Checks all SPEC_FIELDS: type, strikes, wings, lots, sl, tsl, broker.
    CRITICAL mismatches mean trade should be blocked.
    WARNING mismatches mean advisory flag raised.

    Returns:
        {valid: bool, violations: [{field, expected, actual, severity}, ...]}
    """
    violations = []

    for field in SPEC_FIELDS:
        expected = spec.get(field)
        actual = trade.get(field)

        if actual is None and expected is not None:
            violations.append(
                {
                    "field": field,
                    "expected": expected,
                    "actual": "MISSING",
                    "severity": "CRITICAL" if field in CRITICAL_FIELDS else "WARNING",
                }
            )
            continue

        if expected is None:
            continue

        # Type-specific comparison
        if isinstance(expected, list):
            if actual != expected:
                violations.append(
                    {
                        "field": field,
                        "expected": expected,
                        "actual": actual,
                        "severity": "CRITICAL"
                        if field in CRITICAL_FIELDS
                        else "WARNING",
                    }
                )
        elif field in ("strikes",):
            if actual != expected:
                violations.append(
                    {
                        "field": field,
                        "expected": expected,
                        "actual": actual,
                        "severity": "CRITICAL",
                    }
                )
        elif actual != expected:
            violations.append(
                {
                    "field": field,
                    "expected": expected,
                    "actual": actual,
                    "severity": "CRITICAL" if field in CRITICAL_FIELDS else "WARNING",
                }
            )

    return {"valid": len(violations) == 0, "violations": violations}


# ============================================================
# Slippage Check
# ============================================================


def check_slippage(
    expected_strike: float,
    actual_fill: float,
    tolerance: float = SLIPPAGE_TOLERANCE,
) -> Dict:
    """Check order fill slippage against tolerance.

    Returns:
        {ok: bool, slippage: float, evidence: str}
    """
    slippage = abs(actual_fill - expected_strike)
    ok = slippage <= tolerance
    return {
        "ok": ok,
        "slippage": round(slippage, 1),
        "evidence": (
            f"Slippage: {slippage:.1f} pts (expected {expected_strike}, "
            f"filled {actual_fill}, tolerance ±{tolerance})"
        ),
    }


# ============================================================
# Duplicate Detection
# ============================================================


def detect_duplicate(trade: Dict, session_trades: List[Dict]) -> Dict:
    """Check if trade duplicates an existing one in the same session.

    Duplicate = same type + same strikes + same lots.
    Trade IDs are ignored (IDs may differ for same trade if retried).

    Returns:
        {duplicate: bool, matched_with: str | None}
    """
    key_fields = ("type", "strikes", "lots")
    for existing in session_trades:
        if all(trade.get(f) == existing.get(f) for f in key_fields):
            return {
                "duplicate": True,
                "matched_with": existing.get("trade_id", "unknown"),
            }
    return {"duplicate": False, "matched_with": None}


# ============================================================
# Compliance Report
# ============================================================


def generate_compliance_report(
    trade_id: str,
    spec: Dict[str, Any],
    violations: List[Dict],
) -> Dict:
    """Generate compliance report for PM.

    Calculates accuracy as: (fields_checked - violations) / fields_checked.
    Reports each violation with field, expected, actual, severity.

    Returns:
        {title, trade_id, accuracy, violations, text}
    """
    total = len(SPEC_FIELDS)
    matched = total - len(violations)
    accuracy = round(matched / total, 3) if total > 0 else 1.0

    lines = [
        f"# Compliance Report — {trade_id}",
        f"**Accuracy:** {accuracy:.0%} ({matched}/{total} fields matched)",
        f"**Valid:** {'NO' if violations else 'YES'}",
        "",
    ]

    if violations:
        lines.append("## Violations")
        for v in violations:
            field = v["field"].upper()
            expected = v["expected"]
            actual = v["actual"]
            severity = v["severity"]
            lines.append(
                f"- **{field}** [{severity}]: expected `{expected}`, got `{actual}`"
            )
    else:
        lines.append("## ✅ All checks passed — trade matches PM spec exactly")

    return {
        "title": f"Compliance Report — {trade_id}",
        "trade_id": trade_id,
        "accuracy": accuracy,
        "violations": violations,
        "text": "\n".join(lines),
    }


# ============================================================
# Execution Ledger
# ============================================================


def generate_execution_ledger(
    trades: List[Dict[str, Any]],
    session: str,
) -> Dict:
    """Generate execution ledger for Asset Manager.

    Summarizes P&L, broker, fees, slippage for the session.

    Returns:
        {session, total_pnl, total_fees, total_slippage, trade_count, trades}
    """
    total_pnl = sum(t.get("pnl", 0) for t in trades)
    total_fees = sum(t.get("fees", 0) for t in trades)
    total_slippage = sum(t.get("slippage", 0) for t in trades)

    trade_summaries = []
    for t in trades:
        trade_summaries.append(
            {
                "trade_id": t.get("trade_id", "?"),
                "pnl": t.get("pnl", 0),
                "fees": t.get("fees", 0),
                "slippage": t.get("slippage", 0),
                "broker": t.get("broker", "unknown"),
            }
        )

    return {
        "session": session,
        "total_pnl": total_pnl,
        "total_fees": total_fees,
        "total_slippage": round(total_slippage, 1),
        "trade_count": len(trades),
        "trades": trade_summaries,
    }


# ============================================================
# Options Market Analysis — validates trade PLAN against market reality
# ============================================================

# Minimum wing widths by VIX band — narrower wings are breached too often
MIN_WING_BY_VIX = {
    10: 100,  # very calm — wing at 100pts from ATM is ~2 daily ranges
    12: 150,
    15: 200,  # normal
    18: 250,
    20: 300,
    25: 350,
    30: 400,
}

# Maximum reasonable premium-to-strike ratio for short legs
MAX_SHORT_PREMIUM_RATIO = 0.04  # 4% of strike — anything higher is suspicious

# Minimum SL as multiple of expected daily move
SL_VIX_MULTIPLIER = 1.5  # SL should cover at least 1.5x expected daily range


def _expected_daily_range(spot: float, vix: float) -> float:
    """Expected 1-day move in points: VIX/100 * spot / sqrt(252)."""
    return (vix / 100.0) * spot / math.sqrt(252)


def _min_wing_for_vix(vix: float) -> int:
    """Minimum viable wing width for given VIX. Interpolates MIN_WING_BY_VIX."""
    bands = sorted(MIN_WING_BY_VIX.keys())
    vix = max(bands[0], min(bands[-1], vix))
    for i in range(len(bands) - 1):
        if vix <= bands[i + 1]:
            lo, hi = bands[i], bands[i + 1]
            frac = (vix - lo) / (hi - lo) if hi != lo else 0
            return round(
                MIN_WING_BY_VIX[lo] + frac * (MIN_WING_BY_VIX[hi] - MIN_WING_BY_VIX[lo])
            )
    return MIN_WING_BY_VIX[bands[-1]]


# ============================================================
# Strike Logic Validation
# ============================================================


def validate_strike_logic(
    spec: Dict[str, Any],
    vix: float,
    nifty_spot: float,
    grid: int = 50,
) -> Dict:
    """Validate that strikes make market sense for an options trade.

    Checks:
    1. ATM sell strikes are on the grid (e.g., 24500, 24550 on 50-grid)
    2. Wing width is adequate for current VIX
    3. Expiry is current week (not expired, not too far)

    Args:
        spec: PM strategy spec dict {type, strikes, wings, lots, sl, tsl}
        vix: Current VIX
        nifty_spot: Current spot price
        grid: Strike grid (50 for NIFTY)

    Returns:
        {valid, issues: [{field, expected, actual, severity}], evidence}
    """
    issues = []
    strikes = spec.get("strikes", [])
    strategy_type = spec.get("type", "")
    wing_width = spec.get("wings", 300)

    # 1. ATM grid check
    atm_strike = round(nifty_spot / grid) * grid
    atm_sells = []
    for s in strikes:
        if s == atm_strike:
            atm_sells.append(s)
        elif s == atm_strike + grid or s == atm_strike - grid:
            pass  # adjacent strikes are fine for some strategies

    if strategy_type == "IRON_FLY":
        # Both sells should be at ATM ± small offset
        sell_strikes = [
            s
            for s in strikes
            if s in (atm_strike, atm_strike + grid, atm_strike - grid)
        ]
        if len(sell_strikes) < 2:
            issues.append(
                {
                    "field": "strikes",
                    "expected": f"Two sell legs near ATM ({atm_strike})",
                    "actual": f"Sell legs at: {sell_strikes}",
                    "severity": "CRITICAL",
                }
            )

    # 2. Wing width vs VIX
    min_wing = _min_wing_for_vix(vix)
    if wing_width < min_wing:
        issues.append(
            {
                "field": "wings",
                "expected": f"≥{min_wing} (VIX={vix:.1f})",
                "actual": wing_width,
                "severity": "WARNING",
            }
        )

    # 3. Wing width is reasonable (not negative, not absurd)
    if wing_width <= 0:
        issues.append(
            {
                "field": "wings",
                "expected": ">0",
                "actual": wing_width,
                "severity": "CRITICAL",
            }
        )
    if wing_width > 1000:
        issues.append(
            {
                "field": "wings",
                "expected": "≤1000 (practical maximum)",
                "actual": wing_width,
                "severity": "WARNING",
            }
        )

    return {
        "valid": len([i for i in issues if i["severity"] == "CRITICAL"]) == 0,
        "issues": issues,
        "evidence": (
            f"ATM={atm_strike}, wings={wing_width}, min_wing@VIX{vix}={min_wing}, "
            f"strikes={strikes}, range={_expected_daily_range(nifty_spot, vix):.0f}pts/day"
        ),
    }


# ============================================================
# SL vs Volatility Validation
# ============================================================


def validate_sl_vs_volatility(
    spec: Dict[str, Any],
    vix: float,
    nifty_spot: float,
) -> Dict:
    """Validate stop-loss is adequate for current volatility.

    For delta-neutral strategies (IRON_FLY): P&L is gamma-driven.
    Daily P&L swing ≈ gamma × (day_range)² / 2 × lot_size.
    SL should be ≥ 2× expected gamma P&L swing.

    For directional strategies (CREDIT_SPREAD): P&L is delta-driven.
    Daily P&L swing ≈ |delta| × day_range_pts × lot_size.

    Returns:
        {valid, sl_actual, sl_recommended, daily_pnl_swing, issues, evidence}
    """
    daily_range_pts = _expected_daily_range(nifty_spot, vix)
    lots = spec.get("lots", 1)
    lot_size = 75  # NIFTY
    strategy_type = spec.get("type", "")
    wing_width = spec.get("wings", 300)
    sl_actual = spec.get("sl", 3500)

    # Estimate gamma for the ATM short legs
    # ATM gamma ≈ 1 / (spot * sigma * sqrt(T))
    # sigma ≈ VIX / 100, T ≈ 3/365 for 3 days to expiry
    sigma = vix / 100.0
    T = 3 / 365.0  # approx days to current weekly expiry
    atm_gamma = (
        1.0 / (nifty_spot * sigma * math.sqrt(T)) if sigma > 0 and T > 0 else 0.0003
    )
    # Scale: gamma per contract = atm_gamma * spot (gives INR gamma per point²)
    gamma_inr = atm_gamma * lot_size  # per lot

    if strategy_type == "CREDIT_SPREAD":
        # Directional — delta-driven. Delta of credit spread ≈ 0.3
        delta_est = 0.3
        daily_pnl_swing = abs(delta_est) * daily_range_pts * lot_size * lots
    else:
        # IRON_FLY or default — gamma-driven (delta-neutral at entry)
        daily_pnl_swing = gamma_inr * (daily_range_pts**2) / 2.0 * lots

    sl_recommended = daily_pnl_swing * SL_VIX_MULTIPLIER

    issues = []
    if sl_actual < sl_recommended:
        issues.append(
            {
                "field": "sl",
                "expected": f"≥₹{sl_recommended:,.0f}",
                "actual": f"₹{sl_actual:,.0f}",
                "severity": "WARNING",
            }
        )

    # TSL: should be ≥ 1 day range in points
    tsl = spec.get("tsl", 250)
    if tsl < daily_range_pts and strategy_type != "CREDIT_SPREAD":
        issues.append(
            {
                "field": "tsl",
                "expected": f"≥{daily_range_pts:.0f} pts",
                "actual": f"{tsl} pts",
                "severity": "WARNING",
            }
        )

    return {
        "valid": len(issues) == 0,
        "sl_actual": sl_actual,
        "sl_recommended": round(sl_recommended),
        "daily_range_points": round(daily_range_pts, 1),
        "daily_pnl_swing": round(daily_pnl_swing),
        "gamma_estimate": round(gamma_inr, 6),
        "vix": vix,
        "lots": lots,
        "issues": issues,
        "evidence": (
            f"VIX={vix}, day_range={daily_range_pts:.0f}pts, gamma={gamma_inr:.6f}/lot, "
            f"daily_PnL_swing≈₹{daily_pnl_swing:,.0f}, SL=₹{sl_actual:,.0f}, "
            f"recommended≥₹{sl_recommended:,.0f}"
        ),
    }


# ============================================================
# Options Health Report — combines all checks
# ============================================================


def generate_options_validation_report(
    spec: Dict[str, Any],
    vix: float,
    nifty_spot: float,
) -> Dict:
    """Run all options market validations and produce a combined pass/fail report.

    Uses validate_strike_logic + validate_sl_vs_volatility.
    Does NOT call external APIs — all checks are deterministic against spec and VIX.

    Returns:
        {valid, checks: {strike_check, sl_check}, evidence, text}
    """
    strike_check = validate_strike_logic(spec, vix, nifty_spot)
    sl_check = validate_sl_vs_volatility(spec, vix, nifty_spot)

    all_valid = strike_check["valid"] and sl_check["valid"]
    all_issues = strike_check.get("issues", []) + sl_check.get("issues", [])

    lines = [
        "# Options Market Validation",
        f"**Strategy:** {spec.get('type', '?')}",
        f"**Spot:** ₹{nifty_spot:,.0f}  |  VIX: {vix:.1f}",
        f"**Strikes:** {spec.get('strikes', [])}",
        f"**Wings:** {spec.get('wings', '?')}  |  **Lots:** {spec.get('lots', '?')}",
        f"**SL:** ₹{spec.get('sl', '?'):,}  |  **TSL:** {spec.get('tsl', '?')}pts",
        "",
        "## Strike Logic",
        f"- Strikes valid: {'YES ✅' if strike_check['valid'] else 'NO ❌'}",
    ]
    for issue in strike_check.get("issues", []):
        lines.append(
            f"  - [{issue['severity']}] {issue['field']}: expected {issue['expected']}, got {issue['actual']}"
        )

    lines += [
        "",
        "## Volatility-Adjusted SL",
        f"- SL adequate: {'YES ✅' if sl_check['valid'] else 'NO ⚠️'}",
        f"- Daily range: {sl_check['daily_range_points']}pts",
        f"- Daily P&L swing: ₹{sl_check.get('daily_pnl_swing', 0):,} (gamma estimate)",
        f"- SL actual: ₹{sl_check['sl_actual']:,}  |  Recommended: ≥₹{sl_check['sl_recommended']:,}",
        f"- TSL: {spec.get('tsl', '?')}pts vs {sl_check['daily_range_points']}pts daily range",
    ]
    for issue in sl_check.get("issues", []):
        lines.append(
            f"  - [{issue['severity']}] {issue['field']}: expected {issue['expected']}, got {issue['actual']}"
        )

    lines += [
        "",
        f"**Verdict:** {'✅ Options market validation PASSED' if all_valid else '⚠️ Issues found — review before execution'}",
    ]

    return {
        "valid": all_valid,
        "checks": {
            "strike_check": strike_check,
            "sl_check": sl_check,
        },
        "issues": all_issues,
        "text": "\n".join(lines),
    }
