"""Chairman Orchestrator — query routing, crew dispatch, response aggregation.

Routes natural language Chairman queries to the correct crew,
executes them via CrewAI hierarchical process with DeepSeek,
and returns structured responses.
"""

import os, sys, re
from typing import Dict, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
