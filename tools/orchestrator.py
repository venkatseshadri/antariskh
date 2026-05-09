"""Chairman Orchestrator — query routing, crew dispatch, Ralph Loop PRD verification.

Routes natural language Chairman queries, dispatches to crews via CrewAI,
and runs Ralph Loop PRD verification after every crew execution.
"""

import os, sys, re, logging
from typing import Dict, Tuple, List
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

IST = timezone(timedelta(hours=5, minutes=30))
logger = logging.getLogger(__name__)

# Keyword-to-crew routing table
ROUTING_TABLE = {
    "am": {
        "keywords": [
            "margin",
            "capital",
            "free cash",
            "pnl",
            "profit",
            "loss",
            "₹",
            "rupee",
            "fund",
            "balance",
            "burn rate",
            "drawdown",
            "daily sl",
            "portfolio sl",
            "cash floor",
            "fees",
            "broker cost",
            "financial",
            "allocation",
            "available",
        ],
        "crew_import": "crews.am_crew",
        "crew_builder": "build_am_crew",
    },
    "pm": {
        "keywords": [
            "strategy",
            "iron fly",
            "credit spread",
            "strike",
            "indicator",
            "vix",
            "nifty",
            "entry",
            "wing",
            "lot size",
            "position",
            "select",
            "which trade",
            "market condition",
            "signal",
            "supertrend",
        ],
        "crew_import": "crews.pm_crew",
        "crew_builder": "build_pm_crew",
    },
    "ta": {
        "keywords": [
            "validate",
            "compliance",
            "violation",
            "slippage",
            "check trade",
            "verify execution",
            "match spec",
            "duplicate",
            "report trade",
            "execution accuracy",
        ],
        "crew_import": "crews.ta_crew",
        "crew_builder": "build_ta_crew",
    },
    "om": {
        "keywords": [
            "health",
            "check",
            "status",
            "pre-flight",
            "token",
            "disk",
            "network",
            "cron",
            "uptime",
            "infrastructure",
            "broker status",
            "system",
            "ready",
            "go/nogo",
            "available",
        ],
        "crew_import": "crews.om_crew",
        "crew_builder": "build_om_crew",
    },
    "pa": {
        "keywords": [
            "review",
            "post-mortem",
            "what went wrong",
            "why loss",
            "counterfactual",
            "recommend",
            "improve",
            "pattern",
            "missed",
            "alternative",
            "feedback",
        ],
        "crew_import": "crews.pa_crew",
        "crew_builder": "build_pa_crew",
    },
    "ceo": {
        "keywords": [
            "halt",
            "emergency",
            "constitution",
            "override",
            "board",
            "escalate",
            "all crews",
            "company",
            "resource",
            "dispatch",
            "authorize",
            "approve",
            "governance",
        ],
        "crew_import": "crews.ceo_crew",
        "crew_builder": "build_ceo_crew",
    },
}

# Actions requiring CEO authorization
RESTRICTED_ACTIONS = [
    "halt_all",
    "approve_strategy_switch",
    "crew_dispatch",
    "escalate_to_board",
    "override_risk_guard_halt",
    "modify_constitution",
]

CEO_AUTHORITY = {
    "can": [
        "crew_dispatch",
        "halt_all",
        "approve_strategy_switch",
        "resource_audit",
        "escalate_to_board",
        "present_board_report",
    ],
    "cannot": ["override_risk_guard_halt", "modify_constitution", "trade_directly"],
}


def route_query(query: str) -> Tuple[str, float]:
    """Route a Chairman natural language query to the right crew.

    Returns:
        (crew_name, confidence) — crew_name is "am", "pm", etc.
        Falls back to "ceo" for ambiguous/unknown queries.
    """
    query_lower = query.lower()
    scores = {}

    for crew_name, config in ROUTING_TABLE.items():
        score = 0
        for kw in config["keywords"]:
            if kw.lower() in query_lower:
                score += 1
        if score > 0:
            scores[crew_name] = score

    if not scores:
        return ("ceo", 0.0)

    best = max(scores, key=scores.get)
    max_score = scores[best]
    total = sum(scores.values())
    confidence = max_score / total if total > 0 else 0.0

    return (best, round(confidence, 2))


def dispatch_to_crew(crew_name: str, query: str = "") -> Dict:
    """Dispatch a query to a specific crew and get the structured result.

    Runs the crew via CrewAI kickoff() with DeepSeek LLM.

    Args:
        crew_name: "om", "ta", "pm", "am", "pa", or "ceo"
        query: Optional natural language task for the crew

    Returns:
        {crew: str, result: any, status: "ok"|"error", error: str|None}
    """
    if crew_name not in ROUTING_TABLE:
        return {
            "crew": crew_name,
            "result": None,
            "status": "error",
            "error": f"Unknown crew: {crew_name}",
        }

    config = ROUTING_TABLE[crew_name]
    try:
        mod = __import__(config["crew_import"], fromlist=[config["crew_builder"]])
        builder = getattr(mod, config["crew_builder"])
        crew = builder()

        # If query provided, inject it into the first task description
        if query:
            crew.tasks[
                0
            ].description = f"Chairman query: {query}\n\n{crew.tasks[0].description}"

        result = crew.kickoff()
        return {"crew": crew_name, "result": str(result), "status": "ok", "error": None}

    except Exception as e:
        return {"crew": crew_name, "result": None, "status": "error", "error": str(e)}


def is_authorized(crew_name: str, action: str) -> bool:
    """Check if an action is within crew authority boundaries.

    CEO can dispatch/approve/halt but cannot override risk guard or modify constitution.
    Other crews have limited authority.
    """
    if action in RESTRICTED_ACTIONS:
        if crew_name != "ceo":
            return False
        if action in CEO_AUTHORITY["cannot"]:
            return False
        return action in CEO_AUTHORITY["can"]

    # Non-restricted actions: allowed if crew has tools for it
    return True


def aggregate_responses(responses: list) -> Dict:
    """Aggregate multiple crew responses into a single summary.

    Args:
        responses: List of {crew, result, status} dicts

    Returns:
        {total: int, ok: int, errors: int, summaries: dict}
    """
    summary = {
        "total": len(responses),
        "ok": sum(1 for r in responses if r.get("status") == "ok"),
        "errors": sum(1 for r in responses if r.get("status") != "ok"),
        "crews": {},
    }
    for r in responses:
        crew = r.get("crew", "unknown")
        status = r.get("status", "error")
        summary["crews"][crew] = {
            "status": status,
            "result_preview": str(r.get("result", ""))[:200]
            if r.get("result")
            else None,
            "error": r.get("error"),
        }
    return summary


def handle_query(query: str) -> Dict:
    """Full Chairman query pipeline: route → dispatch → aggregate.

    Example:
        >>> handle_query("how much margin is available for monday trading?")
        {"routed_to": "am", "confidence": 0.8, "response": {...}, "status": "ok"}
    """
    crew_name, confidence = route_query(query)
    result = dispatch_to_crew(crew_name, query)
    return {
        "query": query,
        "routed_to": crew_name,
        "confidence": confidence,
        "status": result["status"],
        "response": result["result"],
        "error": result.get("error"),
    }


# ============================================================
# Ralph Loop PRD Verification Integration
# ============================================================

# Ralph PRD check schedule (from PRD frequency fields)
RALPH_SCHEDULE = {
    "om": ["08:00", "08:55"],
    "pm": ["08:55", "16:00"],
    "ta": ["09:18", "15:35"],
    "am": ["08:55", "16:00", "fr:18:00"],
    "pa": ["16:00", "fr:18:00"],
    "ceo": ["08:55", "16:00", "fr:18:00"],
}

_ralph_escalation_counters: Dict[str, int] = {}
_ralph_metric_history: Dict[str, List[Dict]] = {}


def run_ralph_check(crew_name: str, crew_output: any) -> Dict:
    """Run Ralph Loop PRD verification on crew output.

    Called after every crew kickoff to verify output against PRD metrics.
    Tracks metric history and escalation counters across sessions.

    Returns:
        {status: "PASS"|"FAIL"|"WARNING"|"DATA_IMMATURE", metrics: [...], escalation: bool}
    """
    try:
        from ralph.ralph_loop import load_prd_yaml

        prd_path = f"ralph/prds/{crew_name}_prd.yaml"
        prd = load_prd_yaml(prd_path)

        # Extract metrics from crew output (handle both str and dict results)
        output_str = str(crew_output) if not isinstance(crew_output, dict) else ""
        metrics_result = []

        for metric_def in prd.metrics:
            name = metric_def.get("name", "")
            target = metric_def.get("target", 0)
            floor = metric_def.get("floor", 0)
            min_samples = metric_def.get("min_samples", 1)

            # Count samples from history
            history_key = f"{crew_name}:{name}"
            samples = _ralph_metric_history.get(history_key, [])
            sample_count = len(samples)

            # Determine status based on min_samples
            if sample_count < min_samples:
                status = "DATA_IMMATURE"
                reason = metric_def.get("before_min", "TRACKING")
            else:
                # Check against PRD thresholds
                actual = _extract_metric_value(output_str, name)
                if isinstance(target, bool):
                    status = "PASS" if actual == target else "FAIL"
                elif isinstance(target, (int, float)):
                    if actual >= target:
                        status = "PASS"
                    elif actual >= floor:
                        status = "WARNING"
                    else:
                        status = "FAIL"
                else:
                    status = "DATA_IMMATURE"  # qualitative metric

                if status == "PASS":
                    reason = f"{name}: {actual} ≥ target {target}"
                elif status == "WARNING":
                    reason = f"{name}: {actual} ≥ floor {floor} but < target {target}"
                else:
                    reason = f"{name}: {actual} < floor {floor}"

            metrics_result.append(
                {
                    "name": name,
                    "status": status,
                    "reason": reason,
                    "samples": sample_count,
                    "min_samples": min_samples,
                }
            )

            # Track history
            samples.append(
                {
                    "status": status,
                    "reason": reason,
                    "timestamp": datetime.now(IST).isoformat(),
                }
            )
            _ralph_metric_history[history_key] = samples[-50:]  # Keep last 50

        # Escalation tracking
        failures = [m for m in metrics_result if m["status"] == "FAIL"]
        counter_key = f"{crew_name}:escalation"
        if failures:
            _ralph_escalation_counters[counter_key] = (
                _ralph_escalation_counters.get(counter_key, 0) + 1
            )
        else:
            _ralph_escalation_counters[counter_key] = 0

        escalation_needed = _ralph_escalation_counters.get(counter_key, 0) >= 3

        return {
            "crew": crew_name,
            "status": "FAIL" if failures else "PASS",
            "metrics": metrics_result,
            "failures": len(failures),
            "escalation_consecutive": _ralph_escalation_counters.get(counter_key, 0),
            "escalation_needed": escalation_needed,
            "ran_at": datetime.now(IST).isoformat(),
        }

    except Exception as e:
        logger.error(f"Ralph check failed for {crew_name}: {e}")
        return {"crew": crew_name, "status": "ERROR", "error": str(e)}


def _extract_metric_value(output_str: str, metric_name: str) -> float:
    """Extract a numeric metric value from crew output text.

    Handles boolean values (True/False) and numeric values.
    """
    output_lower = output_str.lower()
    metric_lower = metric_name.lower()

    # Try boolean extraction first
    for val, num in [
        (": true", 1.0),
        (": false", 0.0),
        ("= true", 1.0),
        ("= false", 0.0),
        (": yes", 1.0),
        (": no", 0.0),
    ]:
        if f"{metric_lower}{val}" in output_lower:
            return num

    # Try numeric: "metric_name: 0.65" or "metric: 65%"
    pat = rf"{re.escape(metric_name)}[:\s=]*([0-9.]+)"
    m = re.search(pat, output_str, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass

    # Check shorter prefix (first 3 chars of metric name)
    short = metric_name[:3]
    if short != metric_name:
        pat2 = rf"{re.escape(short)}[:\s=]*([0-9.]+)"
        m2 = re.search(pat2, output_str, re.IGNORECASE)
        if m2:
            try:
                return float(m2.group(1))
            except ValueError:
                pass

    # If metric name appears, it's at least present
    if metric_lower in output_lower:
        return 1.0

    return 0.0


def ralph_check_is_due(crew_name: str, at_time: datetime = None) -> bool:
    """Check if Ralph PRD verification is due for a crew at the given time.

    Uses PRD frequency schedules. Returns True if within ±2 min window.
    """
    if at_time is None:
        at_time = datetime.now(IST)

    schedules = RALPH_SCHEDULE.get(crew_name, [])
    if not schedules:
        return False

    time_str = at_time.strftime("%H:%M")
    weekday = at_time.strftime("%a").lower()

    for sched in schedules:
        if sched.startswith("fr:"):
            check_time = sched[3:]
            if weekday == "fri" and _time_in_window(check_time, at_time):
                return True
        elif _time_in_window(sched, at_time):
            return True

    return False


def _time_in_window(scheduled: str, now: datetime, window: int = 2) -> bool:
    """Check if now is within ±window minutes of scheduled HH:MM time."""
    try:
        h, m = map(int, scheduled.split(":"))
        scheduled_minutes = h * 60 + m
        now_minutes = now.hour * 60 + now.minute
        diff = abs(now_minutes - scheduled_minutes)
        return diff <= window or diff >= (1440 - window)  # midnight wrap
    except (ValueError, AttributeError):
        return False


def dispatch_with_ralph(crew_name: str, query: str = "") -> Dict:
    """Dispatch crew AND run Ralph Loop PRD verification afterward.

    Full pipeline: crew kickoff → Ralph PRD check → escallation check.
    Use this instead of dispatch_to_crew() for production.
    """
    crew_result = dispatch_to_crew(crew_name, query)
    if crew_result["status"] != "ok":
        return crew_result

    ralph_result = run_ralph_check(crew_name, crew_result["result"])

    if ralph_result.get("escalation_needed"):
        logger.warning(
            f"RALPH ESCALATION: {crew_name} has {ralph_result['escalation_consecutive']} "
            f"consecutive PRD failures — notifying Chairman"
        )

    return {**crew_result, "ralph": ralph_result}
