"""Trading Analyst deterministic tools.

Validates trade execution against PM strategy spec.
Reports compliance to PM, execution ledger to AM.
"""

from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any

IST = timezone(timedelta(hours=5, minutes=30))

# Fields that must match exactly between spec and trade
SPEC_FIELDS = ["type", "strikes", "wings", "lots", "sl", "tsl", "broker"]

# Severity: CRITICAL = trade-blocking, WARNING = advisory
CRITICAL_FIELDS = {"type", "strikes", "lots", "sl"}
WARNING_FIELDS = {"wings", "tsl", "broker"}

SLIPPAGE_TOLERANCE = 50  # points


def _now_ist() -> str:
    return datetime.now(IST).strftime("%H:%M:%S IST")


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
