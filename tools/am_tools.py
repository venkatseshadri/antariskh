"""Asset Manager deterministic tools.

P&L tracking, margin monitoring, capital limit enforcement, CEO/PM reporting.
"""

import json
import os
import subprocess
from typing import Dict, List, Any, Optional
from pathlib import Path


# ============================================================
# Broker Margin Query — connects to actual broker APIs
# ============================================================


def query_broker_margin() -> Dict:
    """Query actual margin/funds from Flattrade and Shoonya via live APIs.

    Uses the same NorenApi that production Varaha/Kurma use.

    Returns:
        {
            shoonya: {margin_available, margin_used, status, error?},
            flattrade: {margin_available, margin_used, status, error?},
            total_available, total_used, evidence
        }
    """
    result = {
        "shoonya": {"margin_available": 0, "margin_used": 0, "status": "UNKNOWN"},
        "flattrade": {"margin_available": 0, "margin_used": 0, "status": "UNKNOWN"},
        "total_available": 0,
        "total_used": 0,
    }

    # ── Shoonya (OAuth) ──
    try:
        import importlib.util
        import yaml

        cred_path = Path("/home/trading_ceo/python-trader/Shoonya_oAuthAPI-py/cred.yml")
        if cred_path.exists():
            with open(cred_path) as f:
                cred = yaml.safe_load(f)

            # Dynamically import api_helper from Shoonya dir
            spec = importlib.util.spec_from_file_location(
                "shoonya_api_helper",
                "/home/trading_ceo/python-trader/Shoonya_oAuthAPI-py/api_helper.py",
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            NorenApiPy = mod.NorenApiPy

            api_s = NorenApiPy()
            api_s.injectOAuthHeader(
                cred.get("Access_token", ""),
                cred.get("UID", ""),
                str(cred.get("Account_ID", "")),
            )
            limits = api_s.get_limits()
            if limits.get("stat") == "Ok":
                result["shoonya"]["margin_available"] = float(
                    limits.get("cash", 0)
                ) + float(limits.get("collateral", 0))
                result["shoonya"]["margin_used"] = (
                    float(limits.get("marginused", 0))
                    if "marginused" in limits
                    else 0.0
                )
                result["shoonya"]["status"] = "OK"
        else:
            result["shoonya"]["status"] = "NO_CRED_FILE"
    except Exception as e:
        result["shoonya"]["error"] = str(e)[:100]
        result["shoonya"]["status"] = "ERROR"

    # ── Flattrade (session token) ──
    try:
        import importlib.util
        import json as _json

        token_path = Path("/home/trading_ceo/python-trader/tokens.json")
        if token_path.exists():
            with open(token_path) as f:
                tok = _json.load(f)
            access_token = tok.get("access_token", "")
            if access_token:
                spec = importlib.util.spec_from_file_location(
                    "flattrade_api_helper",
                    "/home/trading_ceo/python-trader/FlattradeApi-py/api_helper.py",
                )
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                NorenApiPyFT = mod.NorenApiPy

                api_f = NorenApiPyFT()
                api_f.set_session(userid="FT055702", accesstoken=access_token)
                limits = api_f.get_limits()
                if limits.get("stat") == "Ok":
                    result["flattrade"]["margin_available"] = float(
                        limits.get("cash", 0)
                    ) + float(limits.get("collateral", 0))
                    result["flattrade"]["margin_used"] = (
                        float(limits.get("marginused", 0))
                        if "marginused" in limits
                        else 0.0
                    )
                    result["flattrade"]["status"] = "OK"
                else:
                    result["flattrade"]["status"] = (
                        f"API_FAIL: {limits.get('emsg', 'unknown')}"
                    )
        else:
            result["flattrade"]["status"] = "NO_TOKEN_FILE"
    except Exception as e:
        result["flattrade"]["error"] = str(e)[:100]
        result["flattrade"]["status"] = "ERROR"

    result["total_available"] = (
        result["shoonya"]["margin_available"] + result["flattrade"]["margin_available"]
    )
    result["total_used"] = (
        result["shoonya"]["margin_used"] + result["flattrade"]["margin_used"]
    )

    # Also run check_margin and check_capital_limits inline (one call does all)
    margin_check = check_margin(result["total_used"], result["total_available"])
    capital_check = check_capital_limits(
        0, 0, result["total_available"] - result["total_used"]
    )

    result.update(
        {
            "margin_pct": margin_check["pct_used"],
            "margin_ok": margin_check["ok"],
            "capital_ok": capital_check["overall_ok"],
            "free_cash": result["total_available"] - result["total_used"],
        }
    )

    result["evidence"] = (
        f"Shoonya: {result['shoonya']['status']} (₹{result['shoonya']['margin_available']:,.0f} avail, "
        f"₹{result['shoonya']['margin_used']:,.0f} used), "
        f"Flattrade: {result['flattrade']['status']} (₹{result['flattrade']['margin_available']:,.0f} avail, "
        f"₹{result['flattrade']['margin_used']:,.0f} used) → "
        f"Total: ₹{result['total_available']:,.0f} | "
        f"Margin: {result['margin_pct']}% used | "
        f"Free: ₹{result['free_cash']:,.0f}"
    )

    return result


# ============================================================
# Constants from antariksh_rules.yaml (immutable)
# ============================================================
DAILY_SL = 3500
PORTFOLIO_SL = 4500
FREE_CASH_FLOOR = 11000
MARGIN_TARGET = 70.0  # max utilization %
MARGIN_LIMIT = 85.0
TOTAL_MARGIN_DEFAULT = 250000


# ============================================================
# P&L Tracking
# ============================================================


def track_cumulative_pnl(trades: List[Dict[str, Any]], session: str) -> Dict:
    """Track cumulative P&L across all trades in a session.

    Returns:
        {session, day_pnl, day_fees, net_pnl, trade_count}
    """
    day_pnl = sum(t.get("pnl", 0) for t in trades)
    day_fees = sum(t.get("fees", 0) for t in trades)
    net_pnl = day_pnl - day_fees

    return {
        "session": session,
        "day_pnl": day_pnl,
        "day_fees": day_fees,
        "net_pnl": net_pnl,
        "trade_count": len(trades),
    }


# ============================================================
# Margin Check
# ============================================================


def check_margin(
    used_margin: float,
    total_margin: float = TOTAL_MARGIN_DEFAULT,
    target_pct: float = MARGIN_TARGET,
    limit_pct: float = MARGIN_LIMIT,
) -> Dict:
    """Check margin utilization against targets.

    Returns:
        {ok, pct_used, target_pct, limit_pct, evidence}
    """
    pct_used = round((used_margin / total_margin) * 100, 1) if total_margin > 0 else 0.0
    ok = pct_used <= target_pct

    return {
        "ok": ok,
        "pct_used": pct_used,
        "target_pct": target_pct,
        "limit_pct": limit_pct,
        "used_inr": used_margin,
        "total_inr": total_margin,
        "evidence": (
            f"Margin: {pct_used}% used (₹{used_margin:,.0f} / ₹{total_margin:,.0f}), "
            f"target ≤{target_pct}%, limit ≤{limit_pct}%"
        ),
    }


# ============================================================
# Capital Limits Enforcement
# ============================================================


def check_capital_limits(
    day_pnl: float,
    portfolio_pnl: float,
    free_cash: float,
    daily_sl: int = DAILY_SL,
    portfolio_sl: int = PORTFOLIO_SL,
    free_cash_floor: int = FREE_CASH_FLOOR,
) -> Dict:
    """Enforce hard capital preservation limits.

    Returns:
        {overall_ok, daily_ok, portfolio_ok, free_cash_ok, evidence}
    """
    daily_ok = day_pnl > -daily_sl
    portfolio_ok = portfolio_pnl > -portfolio_sl
    free_cash_ok = free_cash >= free_cash_floor
    overall_ok = daily_ok and portfolio_ok and free_cash_ok

    return {
        "overall_ok": overall_ok,
        "daily_ok": daily_ok,
        "portfolio_ok": portfolio_ok,
        "free_cash_ok": free_cash_ok,
        "daily_sl": daily_sl,
        "portfolio_sl": portfolio_sl,
        "free_cash_floor": free_cash_floor,
        "day_pnl": day_pnl,
        "free_cash": free_cash,
        "evidence": (
            f"Daily P&L: ₹{day_pnl:+,} (SL: ₹{daily_sl}), "
            f"Free cash: ₹{free_cash:,} (floor: ₹{free_cash_floor:,}), "
            f"Portfolio P&L: ₹{portfolio_pnl:+,} (SL: ₹{portfolio_sl})"
        ),
    }


# ============================================================
# CEO Financial Report
# ============================================================


def generate_financial_report(
    pnl_data: Dict,
    margin: Dict,
    limits: Dict,
    session: str = None,
) -> Dict:
    """Generate daily financial health report for CEO.

    Returns:
        {overall_healthy, session, pnl, margin, limits, text}
    """
    healthy = limits.get("overall_ok", False) and margin.get("ok", False)

    status = "🟢 HEALTHY" if healthy else "🔴 ATTENTION"
    lines = [
        f"# AM Financial Report — {session or 'today'}",
        f"**Status:** {status}",
        "",
        "## P&L",
        f"- Day P&L: ₹{pnl_data.get('day_pnl', 0):+,}",
        f"- Fees: ₹{pnl_data.get('day_fees', 0):,}",
        f"- Net P&L: ₹{pnl_data.get('net_pnl', 0):+,}",
        f"- Trades: {pnl_data.get('trade_count', 0)}",
        "",
        "## Margin",
        f"- Utilization: {margin.get('pct_used', 0)}% (target ≤{margin.get('target_pct', 70)}%)",
        "",
        "## Capital Limits",
        f"- Daily SL: {'✅' if limits.get('daily_ok') else '❌'}",
        f"- Portfolio SL: {'✅' if limits.get('portfolio_ok') else '❌'}",
        f"- Free Cash Floor: {'✅' if limits.get('free_cash_ok') else '❌'}",
    ]

    if not limits.get("daily_ok", True):
        lines.append("")
        lines.append(
            f"⚠️ **DAILY SL BREACHED**: ₹{limits.get('day_pnl', 0):+,} > ₹{limits.get('daily_sl', DAILY_SL)}"
        )

    if not limits.get("free_cash_ok", True):
        lines.append("")
        lines.append(
            f"⚠️ **FREE CASH BELOW FLOOR**: ₹{limits.get('free_cash', 0):,} < ₹{limits.get('free_cash_floor', FREE_CASH_FLOOR):,}"
        )

    return {
        "overall_healthy": healthy,
        "session": session,
        "text": "\n".join(lines),
    }


# ============================================================
# PM Capital Report
# ============================================================


def generate_capital_report(
    available_margin: float,
    used_margin: float,
    free_cash: float,
    burn_rate_daily: float,
) -> Dict:
    """Generate capital allocation report for Portfolio Manager.

    Returns:
        {margin_pct, free_cash, burn_rate_daily, text}
    """
    total = available_margin + used_margin
    margin_pct = round((used_margin / total) * 100, 1) if total > 0 else 0.0

    lines = [
        "# AM Capital Report for PM",
        "",
        f"**Available Margin:** ₹{available_margin:,}",
        f"**Used Margin:** ₹{used_margin:,}",
        f"**Margin Utilization:** {margin_pct}%",
        f"**Free Cash:** ₹{free_cash:,}",
        f"**Burn Rate:** ₹{burn_rate_daily}/session",
        "",
    ]

    if margin_pct > 70:
        lines.append("⚠️ **Margin approaching limit** — consider reducing lot size")
    if free_cash < 20000:
        lines.append("⚠️ **Free cash low** — avoid new position additions")

    return {
        "margin_pct": margin_pct,
        "free_cash": free_cash,
        "burn_rate_daily": burn_rate_daily,
        "text": "\n".join(lines),
    }
