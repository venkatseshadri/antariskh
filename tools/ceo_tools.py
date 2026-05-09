"""CEO + Governance deterministic tools.

Alignment checks, crew performance aggregation, resource cap enforcement,
board reporting, escalation, authority chain.
"""

from typing import Dict, List, Any

MAX_POSITIONS = 4
MAX_CAPITAL = 500000
MAX_STRATEGIES = 2

AUTHORITY_CAN = [
    "crew_dispatch",
    "halt_all",
    "approve_strategy_switch",
    "resource_audit",
    "escalate_to_board",
    "present_board_report",
]
AUTHORITY_CANNOT = [
    "override_risk_guard_halt",
    "modify_constitution",
    "trade_directly",
    "execute_trades",
]
VETO_CHAIN = {"PM": ["CEO"], "CEO": ["Board"], "Board": ["Chairman"]}


def alignment_check(decision: Dict, goals: List[str]) -> Dict:
    """Check if a crew decision aligns with company goals."""
    violations = []
    action = str(decision.get("action", "")).lower()
    reason = str(decision.get("reason", "")).lower()

    if "lot" in action and ("4" in action or "double" in action or "greed" in reason):
        violations.append("VIOLATES: Don't burn capital — doubling lots increases risk")
    if not any(
        kw in action
        for kw in ("option", "strategy", "iron", "spread", "fly", "trade", "strike")
    ):
        violations.append("UNKNOWN: Action doesn't match any known trading strategy")
    if "greed" in reason or "fomo" in reason:
        violations.append("VIOLATES: Emotional decision-making")

    return {
        "aligned": len(violations) == 0 and len(action) > 0,
        "violations": violations,
        "goals_checked": goals,
    }


def aggregate_crew_performance(crews: List[Dict]) -> Dict:
    """Aggregate performance metrics from all crews."""
    if not crews:
        return {"overall_healthy": False, "crews_active": 0, "details": {}}

    details = {}
    all_healthy = True
    for c in crews:
        role = c.get("role", "?")
        healthy = (
            c.get("uptime", c.get("compliance", c.get("margin_ok", True)))
            and c.get("checks_passed", c.get("trades_validated", 1)) > 0
        )
        details[role] = {"healthy": bool(healthy), **c}
        if not healthy:
            all_healthy = False

    return {
        "overall_healthy": all_healthy,
        "crews_active": len(crews),
        "details": details,
    }


def enforce_resource_caps(positions: int, capital_inr: float, strategies: int) -> Dict:
    """Enforce resource limits."""
    violations = []
    if positions > MAX_POSITIONS:
        violations.append(f"Positions: {positions} > max {MAX_POSITIONS}")
    if capital_inr > MAX_CAPITAL:
        violations.append(f"Capital: ₹{capital_inr:,} > max ₹{MAX_CAPITAL:,}")
    if strategies > MAX_STRATEGIES:
        violations.append(f"Strategies: {strategies} > max {MAX_STRATEGIES}")
    return {
        "ok": len(violations) == 0,
        "violations": violations,
        "limits": {
            "max_positions": MAX_POSITIONS,
            "max_capital": MAX_CAPITAL,
            "max_strategies": MAX_STRATEGIES,
        },
    }


def generate_board_report(summaries: Dict) -> Dict:
    """Generate board report from crew summaries."""
    flags = (
        len(summaries.get("alignments", []))
        if isinstance(summaries.get("alignments"), list)
        else 0
    )
    has_alert = any(
        "CRITICAL" in str(v).upper() or "violation" in str(v).lower()
        for v in summaries.values()
    )
    lines = ["# CEO Board Report", ""]
    for crew, summary in summaries.items():
        if isinstance(summary, str):
            lines.append(f"**{crew}:** {summary}")
    if flags:
        lines.append(f"\n⚠️ **{flags} alignment violations** flagged this session")
    if has_alert:
        lines.append(f"\n## ALERT: CRITICAL issues detected — see details above")
    return {
        "title": "CEO Board Report",
        "flags": flags,
        "alerts": has_alert,
        "text": "\n".join(lines),
    }


def should_escalate(failure_history: List[bool], threshold: int = 3) -> bool:
    """Check if consecutive failures warrant escalation."""
    streak = 0
    for f in failure_history:
        if not f:
            streak += 1
        else:
            streak = 0
        if streak >= threshold:
            return True
    return False


def check_authority(action: str) -> bool:
    """Check if CEO can perform an action."""
    if action in AUTHORITY_CANNOT:
        return False
    if action in AUTHORITY_CAN:
        return True
    return False  # Unknown actions denied by default


def governance_veto(actor: str, action: str, detail: str) -> Dict:
    """Check governance veto chain for cross-crew decisions."""
    needs = action in (
        "strategy_switch",
        "modify_constitution",
        "halt_all",
        "crew_dispatch",
    )
    approvers = VETO_CHAIN.get(actor, ["CEO"])
    return {
        "needs_approval": needs,
        "approvers": approvers,
        "action": action,
        "detail": detail,
    }
