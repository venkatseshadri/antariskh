"""Asset Manager deterministic tools.

P&L tracking, margin monitoring, capital limit enforcement, CEO/PM reporting.
"""

from typing import Dict, List, Any

# From antariksh_rules.yaml (immutable — read-only reference)
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
