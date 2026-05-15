"""Chairman Orchestrator — query routing, crew dispatch, Ralph Loop PRD verification.

Routes natural language Chairman queries, dispatches to crews via CrewAI,
runs Ralph Loop PRD verification after every crew execution, and passes
inter-crew learnings so findings from one crew reach another directly.
"""

import os, sys, re, logging
from typing import Dict, Tuple, List, Optional
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

IST = timezone(timedelta(hours=5, minutes=30))
logger = logging.getLogger(__name__)

# ============================================================
# TRADE MODE — Paper vs Live (CEO-enforced safety gate)
# ============================================================
# PAPER: All trades are simulated. No real orders. Safe default.
# LIVE:  Real money. Requires BOTH flags: TRADE_MODE=LIVE AND LIVE_KEY set.
# Only CEO can approve switching to LIVE.

TRADE_MODE = os.environ.get("TRADE_MODE", "PAPER").upper()
LIVE_KEY = os.environ.get("LIVE_KEY", "")  # must be set to switch LIVE
LIVE_KEY_REQUIRED = "antariskh-1ive-2026"  # shared secret to authorize live

if TRADE_MODE == "LIVE" and LIVE_KEY != LIVE_KEY_REQUIRED:
    TRADE_MODE = "PAPER"
    logger.warning("LIVE_KEY missing or incorrect — forcing PAPER mode")


def is_paper_mode() -> bool:
    return TRADE_MODE != "LIVE"


def get_trade_mode_banner() -> str:
    if TRADE_MODE == "LIVE":
        return "⚠️ LIVE TRADING MODE — REAL ORDERS ACTIVE ⚠️"
    return "📄 PAPER MODE — no real orders, no real money"


def switch_to_live(key: str) -> bool:
    """CEO-only: switch to LIVE trading mode with verification key."""
    if key != LIVE_KEY_REQUIRED:
        return False
    os.environ["TRADE_MODE"] = "LIVE"
    os.environ["LIVE_KEY"] = key
    global TRADE_MODE
    TRADE_MODE = "LIVE"
    logger.warning("TRADE MODE SWITCHED TO LIVE — REAL ORDERS ENABLED")
    return True


# ============================================================
# Inter-Crew Learnings — PA → PM, TA → PM, CEO → all, etc.
# ============================================================
# In-memory session cache — findings from one crew are passed
# to subsequent crew dispatches. Resets on restart (fresh each day).

_intercrew_findings: Dict[str, List[str]] = {}

# Who shares findings with whom
LEARNING_PIPELINES = {
    "pa": ["pm", "am", "ceo"],  # PA findings → PM, AM, CEO
    "ta": ["pm", "am", "pa"],  # TA findings → PM, AM, PA
    "om": ["pm", "am", "ceo"],  # OM findings → PM, AM, CEO
    "am": ["pm", "ceo"],  # AM findings → PM, CEO
    "pm": ["am", "ceo"],  # PM findings → AM, CEO
    "ceo": ["pm", "am", "om"],  # CEO directives → all crews
}

# Regex patterns to parse actionable findings from crew output
FINDING_PATTERNS = [
    # Strategy adjustments: "reduce SL", "tighten trailing", "increase lots"
    (
        r"(reduce|increase|adjust|tighten|widen|narrow)\s+(?:the\s+)?(?:SL|stop.loss|trailing|TSL|position|lot|wing|margin|risk)",
        "strategy_adjustment",
    ),
    # SL misconfiguration: "SL too wide", "stop loss way too tight"
    (
        r"(?:SL|stop[\s_-]*loss)\s+.*?(?:too|overly|way\s+too)\s+(wide|tight|loose|lax)",
        "sl_misconfigured",
    ),
    # Compliance: "violation", "non-compliant", "breach"
    (
        r"(?:violation|non.compliant|breach|out[\s_-]of[\s_-]spec|does.not.match|mismatch)",
        "compliance_violation",
    ),
    # PnL anomalies — only negative/unexpected, not "fine"
    (
        r"(?:P&L|pnl|profit|loss|drawdown|mtm).*?(?:[-]\s*[\u20B9]?\s*[\d,]+|exceeded|breach|violation|spike|crash)",
        "pnl_anomaly",
    ),
    # Broker issues
    (
        r"(?:broker|Shoonya|Flattrade).*?(?:blocked|down|error|fail|offline|latency|reject)",
        "broker_issue",
    ),
    # CEO directives: "tighten risk by 15%", "crew directive"
    (
        r"(?:directive|tighten\s+risk|reduce\s+risk|increase\s+risk|all\s+crews?\s+\w+)",
        "ceo_directive",
    ),
    # Metric breaches / PRD floor violations
    (
        r"(?:below|at|approaching)\s+(?:floor|target|threshold).*?(?:of\s+)?(\d+)",
        "metric_warning",
    ),
    # Percent adjustments anywhere
    (
        r"(?:reduce|increase|cut|raise|tighten)\s+.*?(?:by\s+)?(\d{1,3}\s*%)",
        "pct_adjustment",
    ),
    # P&L data for AM: "session P&L: ₹1,200", "broker cost: ₹55", "MTM: -₹800"
    (
        r"(?:session|daily|today).*?(?:P&L|pnl|profit|mtm)\s*[:=]?\s*[\u20B9]?\s*([-]?\s*[\d,]+)",
        "session_pnl",
    ),
    (
        r"(?:broker|execution)\s*(?:cost|fee|charge)s?\s*[:=]?\s*[\u20B9]?\s*([\d,]+)",
        "broker_cost",
    ),
    (
        r"(?:margin|capital)\s*(?:utilization|used|available)\s*[:=]?\s*[\u20B9]?\s*([\d,]+)",
        "margin_data",
    ),
]


def ingest_learnings(crew_name: str, output: str):
    """Extract actionable findings from crew output and store for other crews."""
    findings = []
    for pattern, label in FINDING_PATTERNS:
        for match in re.finditer(pattern, output, re.IGNORECASE):
            text = match.group(0).strip()[:200]
            findings.append(f"[{label}] {text}")

    if findings:
        _intercrew_findings[crew_name] = findings
        logger.info(f"Inter-crew: {crew_name} produced {len(findings)} learnings")
        for target in LEARNING_PIPELINES.get(crew_name, []):
            logger.info(f"  → will reach {target} on next dispatch")


def get_learnings_for(crew_name: str) -> List[str]:
    """Get learnings from other crews relevant to this crew."""
    relevant = []
    for source, targets in LEARNING_PIPELINES.items():
        if crew_name in targets and source in _intercrew_findings:
            findings = _intercrew_findings[source]
            relevant.extend(f"  [from {source.upper()}]: {f}" for f in findings)
    return relevant


def inject_learnings(crew_name: str, task_description: str) -> str:
    """Inject relevant inter-crew learnings into a task description."""
    learnings = get_learnings_for(crew_name)
    if not learnings:
        return task_description

    context = "\n\n## Cross-Crew Learnings (from other analysts)\n"
    context += "These findings were discovered by other crews. Consider them.\n"
    context += "If actionable, apply adjustments to your parameters.\n\n"
    context += "\n".join(learnings[:6])  # max 6 to avoid bloat

    return context + "\n\n" + task_description


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

        # Inject inter-crew learnings + trade mode banner into the task
        mode_banner = f"## {get_trade_mode_banner()}\n"
        if is_paper_mode():
            mode_banner += "Do NOT place real orders. All trades are simulated.\n"
        mode_banner += "\n"

        base_task = crew.tasks[0].description
        if query:
            base_task = f"Chairman query: {query}\n\n{base_task}"
        crew.tasks[0].description = inject_learnings(crew_name, mode_banner + base_task)

        result = crew.kickoff()
        output_str = str(result)

        # Extract learnings for other crews
        ingest_learnings(crew_name, output_str)

        return {"crew": crew_name, "result": output_str, "status": "ok", "error": None}

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
    "ta": [
        "09:18",
        "09:50",
        "10:30",
        "11:00",
        "12:00",
        "13:00",
        "14:00",
        "15:00",
        "15:35",
    ],
    "am": ["08:55", "16:00", "fr:18:00"],
    "pa": ["16:00", "fr:18:00"],
    "ceo": ["07:55", "16:00", "fr:18:00"],
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
        # Push to Chairman via notification layer
        try:
            from tools.notifications import push_ralph_escalation

            push_ralph_escalation(
                crew_name,
                ralph_result["escalation_consecutive"],
                ralph_result.get("metrics", []),
            )
        except Exception:
            pass

    return {**crew_result, "ralph": ralph_result}


# ============================================================
# PA EOD Dispatch — Post-Mortem Analysis at 15:26
# ============================================================


def dispatch_pa_crew(
    session_trades: List[Dict],
    session_pnl: float = 0,
    market_regime: str = "UNKNOWN",
    vix_at_close: float = 18.0,
) -> Dict:
    """Dispatch PA crew for end-of-day analysis.

    Called at 15:26 after market close. PA reviews all session trades,
    runs counterfactuals, detects patterns, writes reviews to ChromaDB,
    and generates recommendations.

    Args:
        session_trades: All trades executed today
        session_pnl: Day's total P&L
        market_regime: Market regime for the session
        vix_at_close: VIX level at market close

    Returns:
        PA crew analysis + recommendations
    """
    query = (
        f"EOD analysis: {len(session_trades)} trades executed, "
        f"P&L ₹{session_pnl:+,.0f}. "
        f"Market: {market_regime}, VIX={vix_at_close}. "
        f"Review all trades, generate recommendations."
    )

    logger.info(f"📊 Dispatching PA crew for EOD analysis (queries={query[:50]}...)")

    result = dispatch_with_ralph(crew_name="pa", query=query)

    # Extract top 3 recommendations for Telegram alert
    recommendations = result.get("output", {}).get("recommendations", [])[:3]
    telegram_message = f"📊 EOD PA Analysis\n"
    telegram_message += f"Trades: {len(session_trades)} | P&L: ₹{session_pnl:+,.0f}\n"
    if recommendations:
        telegram_message += "Top recommendations:\n"
        for i, rec in enumerate(recommendations, 1):
            telegram_message += f"{i}. {rec}\n"
    else:
        telegram_message += "Strategy executing well — no changes needed."

    try:
        from tools.notifications import send_telegram

        send_telegram(message=telegram_message, channel="alerts")
        logger.info(f"✓ Sent PA EOD alert to Telegram")
    except Exception as e:
        logger.warning(f"Failed to send Telegram alert: {e}")

    return result
