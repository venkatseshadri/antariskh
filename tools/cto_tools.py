"""CTO deterministic tools — technical strategy, architecture, gatekeeping.

The CTO owns the technical vision:
- Scouts new tools/frameworks to reduce cost and maintenance
- Evaluates architecture, spots technical debt
- Designs POCs for CEO's new visions (Crypto, MCX expansion, multi-asset)
- Gatekeeps ALL source code changes (Dev→QA→Deploy pipeline)
- Continuously monitors tech landscape for opportunities
- Works WITH the CEO, not just executes for them
"""

import json
import subprocess
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime as _dt

PROJECT_ROOT = Path(__file__).parent.parent

# Files considered CRITICAL — blast radius is high for any change here
CRITICAL_FILES = {
    "tools/pm_tools.py": "Portfolio Manager strategy tools. Wing/margin/lot sizing decisions.",
    "tools/am_tools.py": "Asset Manager broker margin queries. Live broker API calls.",
    "tools/pa_tools.py": "Post-mortem analysis. Pattern detection, SL optimization.",
    "tools/ceo_tools.py": "CEO governance. Resource caps, alignment, escalation.",
    "antariksh_rules.yaml": "Immutable trading rules. L3 parameters gate.",
}

# Dependency graph — which files import which (changes propagate downstream)
DEPENDENCY_GRAPH: Dict[str, List[str]] = {
    "tools/pm_tools.py": ["crews/pm_crew.py"],
    "tools/am_tools.py": ["crews/am_crew.py"],
    "tools/pa_tools.py": ["crews/pa_crew.py"],
    "tools/cto_tools.py": ["crews/cto_crew.py"],
    "tools/dev_tools.py": ["crews/dev_crew.py"],
    "tools/qa_tools.py": ["crews/qa_crew.py"],
    "crew_structure.py": [
        "tests/scenario_runner.py",
        "tests/test_scenarios.py",
        "crew_test.py",
    ],
}


def assess_change_risk(change_spec: Dict) -> Dict:
    """Evaluate blast radius and technical risk of a proposed change.

    Args:
        change_spec: Dict with keys:
            - change_id, title, description, requester
            - files_to_modify: list of file paths (relative to project root)
            - specific_edit: human-readable description of the change
            - rollback_plan: how to revert if needed
            - test_plan: how to verify

    Returns:
        {risk_level: "LOW"|"MEDIUM"|"HIGH"|"CRITICAL",
         blast_radius: list of affected files (transitive),
         critical_files_touched: list,
         dependency_impact: {file: list of downstream files},
         rollback_feasibility: "SIMPLE"|"MODERATE"|"COMPLEX",
         concerns: list of str warnings,
         score: 0-100 (higher = more risky)}
    """
    files = change_spec.get("files_to_modify", [])
    blast = set()
    critical_touched = []
    dependency_impact = {}
    concerns = []
    risk_score = 0

    for f in files:
        base = Path(f).name

        # Transitive blast radius
        blast.add(f)
        downstream = DEPENDENCY_GRAPH.get(f, DEPENDENCY_GRAPH.get(base, []))
        for d in downstream:
            blast.add(d)
            # Second-order: check if downstream files have their own dependents
            d2 = DEPENDENCY_GRAPH.get(d, [])
            for dd in d2:
                blast.add(dd)

        dependency_impact[f] = downstream

        # Criticality
        if base in CRITICAL_FILES:
            critical_touched.append(base)
            risk_score += 30

        # crew_structure.py is the HIGHEST blast radius — affects ALL sessions
        if "crew_structure.py" in base:
            critical_touched.append("crew_structure.py")
            risk_score += 50
        elif base.startswith("crew") or base.endswith("_crew.py"):
            risk_score += 15
        elif base.startswith("test"):
            risk_score += 5
        else:
            risk_score += 10

    # Rollback assessment
    rollback = change_spec.get("rollback_plan", "").lower()
    if "git revert" in rollback or "git reset" in rollback:
        rollback_feasibility = "SIMPLE"
    elif "manual" in rollback:
        rollback_feasibility = "COMPLEX"
        risk_score += 10
    else:
        rollback_feasibility = "MODERATE"
        risk_score += 5

    if len(blast) > 10:
        concerns.append(f"Large blast radius: {len(blast)} files affected transitively")
        risk_score += 15
    if critical_touched:
        concerns.append(f"Critical files modified: {', '.join(critical_touched)}")
    if not change_spec.get("test_plan"):
        concerns.append("NO TEST PLAN provided — change untestable")
        risk_score += 20

    if risk_score <= 20:
        risk_level = "LOW"
    elif risk_score <= 40:
        risk_level = "MEDIUM"
    elif risk_score <= 65:
        risk_level = "HIGH"
    else:
        risk_level = "CRITICAL"

    return {
        "change_id": change_spec.get("change_id", "UNKNOWN"),
        "risk_level": risk_level,
        "risk_score": risk_score,
        "blast_radius": sorted(blast),
        "critical_files_touched": critical_touched,
        "dependency_impact": dependency_impact,
        "rollback_feasibility": rollback_feasibility,
        "concerns": concerns,
        "recommendation": (
            "APPROVE"
            if risk_level in ("LOW", "MEDIUM")
            else "REVIEW_REQUIRED"
            if risk_level == "HIGH"
            else "REJECT — CRITICAL risk, needs redesign"
        ),
    }


def preview_diff(change_spec: Dict) -> Dict:
    """Generate a preview of what the diff WOULD look like.

    Returns:
        {change_id, files: {filepath: {diff_preview, line_count_added, line_count_removed}}}
    """
    files_preview = {}
    total_added = 0
    total_removed = 0

    for f in change_spec.get("files_to_modify", []):
        full_path = PROJECT_ROOT / f
        preview = {
            "exists": full_path.exists(),
            "size_bytes": full_path.stat().st_size if full_path.exists() else 0,
            "diff_preview": change_spec.get(
                "specific_edit", "NO EDIT DESCRIPTION PROVIDED"
            )[:300],
            "line_count_added": 0,
            "line_count_removed": 0,
        }
        files_preview[f] = preview

    return {
        "change_id": change_spec.get("change_id", "UNKNOWN"),
        "files": files_preview,
        "total_files_affected": len(files_preview),
    }


def cto_signoff(
    change_spec: Dict,
    risk_assessment: Dict,
    override: Optional[str] = None,
) -> Dict:
    """CTO final decision on a change. Returns YES, NO, or NEEDS_CLARIFICATION.

    If override is provided, it bypasses risk assessment (for emergencies).
    """
    decision_id = f"CTO-{_dt.now().strftime('%Y%m%d_%H%M%S')}"

    if override:
        return {
            "decision_id": decision_id,
            "decision": override.upper(),
            "reason": f"CTO override: {override}",
            "risk_level": risk_assessment.get("risk_level"),
            "blast_radius": risk_assessment.get("blast_radius", []),
            "conditions": [],
            "delegates_to": "dev" if override.upper() == "YES" else None,
        }

    risk_level = risk_assessment.get("risk_level", "UNKNOWN")
    concerns = risk_assessment.get("concerns", [])
    blast = risk_assessment.get("blast_radius", [])

    if risk_level == "CRITICAL":
        return {
            "decision_id": decision_id,
            "decision": "NO",
            "reason": f"CRITICAL risk (score={risk_assessment.get('risk_score')}). Concerns: {'; '.join(concerns)}",
            "risk_level": risk_level,
            "blast_radius": blast,
            "conditions": [],
            "delegates_to": None,
        }

    if risk_level == "HIGH":
        return {
            "decision_id": decision_id,
            "decision": "NEEDS_CLARIFICATION",
            "reason": f"HIGH risk (score={risk_assessment.get('risk_score')}). Requires: detailed test plan, rollback runbook, blast radius mitigation.",
            "risk_level": risk_level,
            "blast_radius": blast,
            "conditions": [
                "Detailed test plan required",
                "Rollback runbook documented",
                f"Blast radius limits: {', '.join(blast[:5])}",
            ],
            "delegates_to": None,
        }

    if not change_spec.get("test_plan"):
        return {
            "decision_id": decision_id,
            "decision": "NEEDS_CLARIFICATION",
            "reason": "Missing test plan — cannot approve untestable change",
            "risk_level": risk_level,
            "blast_radius": blast,
            "conditions": ["Test plan required"],
            "delegates_to": None,
        }

    # LOW or MEDIUM risk with test plan → approve
    return {
        "decision_id": decision_id,
        "decision": "YES",
        "reason": f"{risk_level} risk (score={risk_assessment.get('risk_score')}), test plan provided, rollback feasible.",
        "risk_level": risk_level,
        "blast_radius": blast,
        "conditions": [
            "QA must validate before deployment",
            f"Rollback via: {change_spec.get('rollback_plan', 'manual revert')}",
        ],
        "delegates_to": "dev",
    }


def generate_cto_brief(
    change_spec: Dict,
    risk_assessment: Dict,
    signoff: Dict,
) -> str:
    """Generate a structured CTO decision brief for CEO/PM/Board review."""
    lines = [
        "# CTO Change Decision Brief",
        f"**Change:** {change_spec.get('change_id', '?')} — {change_spec.get('title', 'Untitled')}",
        f"**Requester:** {change_spec.get('requester', 'Unknown')}",
        f"**Decision ID:** {signoff.get('decision_id', '?')}",
        f"**Decision:** {signoff.get('decision', 'UNKNOWN')}",
        "",
        "## Risk Assessment",
        f"- **Level:** {risk_assessment.get('risk_level', '?')} (score: {risk_assessment.get('risk_score', '?')}/100)",
        f"- **Blast Radius:** {len(risk_assessment.get('blast_radius', []))} files",
        f"- **Critical Files:** {', '.join(risk_assessment.get('critical_files_touched', [])) or 'none'}",
        f"- **Rollback:** {risk_assessment.get('rollback_feasibility', '?')}",
        "",
        "## Concerns",
    ]
    for c in risk_assessment.get("concerns", []):
        lines.append(f"- ⚠️ {c}")
    if not risk_assessment.get("concerns"):
        lines.append("- None identified")

    lines += [
        "",
        "## Conditions",
    ]
    for c in signoff.get("conditions", []):
        lines.append(f"- {c}")
    if not signoff.get("conditions"):
        lines.append("- None")

    lines += [
        "",
        f"**Reason:** {signoff.get('reason', 'No reason provided')}",
        "",
        f"_{_dt.now().isoformat()}_ — CTO automated signature",
    ]
    return "\n".join(lines)


def validate_change_spec(change_spec: Dict) -> Dict:
    """Validate a change request has all required fields before processing."""
    required = ["change_id", "title", "requester", "files_to_modify", "specific_edit"]
    missing = [f for f in required if not change_spec.get(f)]

    if missing:
        return {
            "valid": False,
            "reason": f"Missing required fields: {', '.join(missing)}",
            "required_fields": required,
        }

    for f in change_spec.get("files_to_modify", []):
        full = PROJECT_ROOT / f
        if not full.exists() and not f.startswith("new:"):
            return {
                "valid": False,
                "reason": f"File does not exist: {f}",
                "hint": f"Prefix new files with 'new:filename'",
            }

    return {"valid": True, "reason": "All required fields present"}


# ============================================================
# Strategic CTO Functions — Technology Radar, POC Design, Architecture
# ============================================================

KNOWN_TECHNOLOGIES = {
    "broker_apis": {
        "current": "Shoonya NorenApi (OAuth) + Flattrade NorenApi (session token)",
        "alternatives": [
            {
                "name": "Zerodha Kite Connect",
                "cost": "₹2000/mo",
                "benefit": "Better WebSocket, streaming quotes, 20+ instruments",
            },
            {
                "name": "Dhan API",
                "cost": "Free (beta)",
                "benefit": "Modern REST API, no legacy Noren overhead",
            },
            {
                "name": "Angel One SmartAPI",
                "cost": "Free",
                "benefit": "Python SDK, historical data, good for MCX",
            },
        ],
    },
    "llm_providers": {
        "current": "DeepSeek V3 (deepseek-chat) @ ₹0.14/1M tokens",
        "alternatives": [
            {
                "name": "DeepSeek V4-Pro",
                "cost": "~₹0.20/1M tokens",
                "benefit": "Better reasoning, longer context, tool-use SOTA",
            },
            {
                "name": "Qwen 3 Max",
                "cost": "~₹0.15/1M tokens",
                "benefit": "Multilingual, strong code gen, 1M context window",
            },
            {
                "name": "Llama 4 (local)",
                "cost": "₹0 (self-host)",
                "benefit": "Zero API cost, no rate limits, air-gapped",
            },
            {
                "name": "Gemma 3 (local)",
                "cost": "₹0 (self-host)",
                "benefit": "Google quality, 128K context, runs on 16GB VRAM",
            },
        ],
    },
    "agent_frameworks": {
        "current": "CrewAI (hierarchical, 7 crews, ~₹40/day LLM cost)",
        "alternatives": [
            {
                "name": "LangGraph",
                "cost": "Same LLM cost",
                "benefit": "DAG-based flows, better checkpointing, state machines",
            },
            {
                "name": "OpenAI Agents SDK",
                "cost": "Requires OpenAI billing",
                "benefit": "Native tool-use, guardrails, tracing built-in",
            },
            {
                "name": "Agno",
                "cost": "Same LLM cost",
                "benefit": "Lightweight, multi-modal, faster cold-start than CrewAI",
            },
        ],
    },
    "monitoring": {
        "current": "JSONL logs + crew verbose output + /tmp files",
        "alternatives": [
            {
                "name": "AgentOps",
                "cost": "Free (self-host) or SaaS",
                "benefit": "Session waterfall, cost tracking, CrewAI-native",
            },
            {
                "name": "Langfuse",
                "cost": "Free (self-host)",
                "benefit": "Open-source LLM observability, prompt versioning",
            },
            {
                "name": "Prometheus + Grafana",
                "cost": "₹0 (self-host)",
                "benefit": "System metrics, margin alerts, cron heartbeat",
            },
        ],
    },
    "deployment": {
        "current": "VPS (cron + tmux + manual restart)",
        "alternatives": [
            {
                "name": "systemd services",
                "cost": "₹0",
                "benefit": "Auto-restart on crash, journald logging, dependency ordering",
            },
            {
                "name": "Docker Compose",
                "cost": "₹0",
                "benefit": "Reproducible env, healthchecks, zero-downtime restart",
            },
            {
                "name": "GitHub Actions CI/CD",
                "cost": "Free (2000 min/mo)",
                "benefit": "Auto-test on push, deploy on merge, PR gating",
            },
        ],
    },
}

ARCHITECTURE_PATTERNS = {
    "event_driven": "Decouple crews with event bus. PM emits 'strategy_ready', OM subscribes. Reduces coupling.",
    "state_machine": "Replace market_state dict with formal state machine. Prevents invalid state transitions.",
    "plugin_broker": "Abstract broker interface. Swap Shoonya/Flattrade without touching trading logic.",
    "circuit_breaker": "Auto-halt all trading if 3 consecutive losses. Hardware-level safety, not agent-level.",
    "shadow_mode": "Run new strategy in parallel with paper money for 30 days before real capital.",
}


def scout_technology(category: str, constraints: Dict = None) -> Dict:
    """Research and recommend better/cheaper technologies for a given category.

    Args:
        category: One of 'broker_apis', 'llm_providers', 'agent_frameworks',
                  'monitoring', 'deployment' — or 'all' for full scan.
        constraints: Dict of constraints like max_cost, must_be_self_hosted, etc.

    Returns:
        {category, current, recommendations: [{name, cost, benefit, migration_effort}]}
    """
    if constraints is None:
        constraints = {}

    if category == "all":
        results = {}
        for cat in KNOWN_TECHNOLOGIES:
            results[cat] = scout_technology(cat, constraints)
        return {"scan_type": "full", "categories": results}

    current = KNOWN_TECHNOLOGIES.get(category, {})
    if not current:
        return {
            "category": category,
            "error": "Unknown category",
            "available": list(KNOWN_TECHNOLOGIES.keys()),
        }

    alternatives = current.get("alternatives", [])
    filtered = []
    for alt in alternatives:
        cost_str = alt["cost"]
        if "₹0" in cost_str or "free" in cost_str.lower():
            migration = "LOW"
        elif "self-host" in cost_str:
            migration = "MEDIUM"
        else:
            migration = "MEDIUM-HIGH"

        filtered.append(
            {
                "name": alt["name"],
                "cost": alt["cost"],
                "benefit": alt["benefit"],
                "migration_effort": migration,
                "roi_estimate": f"Current {current['current'].split('(')[0].strip()} → {alt['name']}",
            }
        )

    return {
        "category": category,
        "current": current["current"],
        "recommendations": filtered,
        "top_pick": filtered[0]["name"] if filtered else None,
    }


def evaluate_architecture(component: str = "all") -> Dict:
    """Evaluate current architecture and suggest improvements.

    Args:
        component: Specific component or 'all' for full system review.

    Returns:
        {component, current_state, pain_points, recommended_pattern, migration_plan}
    """
    patterns = {
        "market_state": {
            "current": "Shared mutable dict accessed by all tools. No type safety, no transition validation.",
            "pain": "State corruption possible. Tool A writes 'gate_pass': True while Tool B reads stale value.",
            "recommendation": ARCHITECTURE_PATTERNS["state_machine"],
            "effort": "MEDIUM — ~200 line refactor, changes affect 6 tools",
        },
        "crew_orchestration": {
            "current": "Single Orchestrator agent with 6 tools. Sequential. No parallelism.",
            "pain": "Blocking. Scanner → Strategist → RiskGuard is serial. Could run Scanner + AM margin query in parallel.",
            "recommendation": ARCHITECTURE_PATTERNS["event_driven"],
            "effort": "HIGH — redesigns crew communication model",
        },
        "broker_integration": {
            "current": "Two separate import blocks in am_tools.py. Shoonya and Flattrade hardcoded.",
            "pain": "Adding Dhan/Kite requires code changes in multiple places. No abstraction.",
            "recommendation": ARCHITECTURE_PATTERNS["plugin_broker"],
            "effort": "MEDIUM — ~150 line refactor, broker interface + 2 adapters",
        },
        "safety_systems": {
            "current": "RiskGuardEngine + AuditorEngine. Hardcoded limits. No hardware-level halt.",
            "pain": "If DeepSeek API is down, agent can't call tools. No circuit breaker. Agent could theoretically skip risk check.",
            "recommendation": ARCHITECTURE_PATTERNS["circuit_breaker"],
            "effort": "LOW — systemd-level health check + 50 line Python wrapper",
        },
        "deployment": {
            "current": "tmux sessions on VPS. Manual restart. No auto-recovery.",
            "pain": "If VPS reboots, Varaha + Kurma + Antariksh all die. No startup sequencing.",
            "recommendation": f"{ARCHITECTURE_PATTERNS['event_driven']} + systemd services + healthcheck endpoints",
            "effort": "LOW — 3 systemd unit files + 1 healthcheck script",
        },
    }

    if component == "all":
        return {
            "review_type": "full_architecture",
            "components": patterns,
            "summary": (
                "Priority order: 1) Circuit breaker (LOW effort, CRITICAL safety), "
                "2) systemd deployment (LOW effort, operational stability), "
                "3) Broker plugin (MEDIUM, enables multi-broker), "
                "4) State machine (MEDIUM, prevents corruption), "
                "5) Event-driven (HIGH, complex but unlocks parallelism)"
            ),
        }

    info = patterns.get(component)
    if not info:
        return {
            "component": component,
            "error": "Unknown component",
            "available": list(patterns.keys()),
        }

    return {"component": component, **info}


def design_poc_plan(vision: str, scope: str = "minimal") -> Dict:
    """Design a proof-of-concept plan for a new CEO vision.

    Args:
        vision: Description of the vision (e.g., 'Crypto trading', 'MCX expansion')
        scope: 'minimal' (smoke test), 'functional' (working demo), 'production' (full)

    Returns:
        {vision, scope, phases: [{phase, tasks, duration_est, risk}]}
    """
    vision_lower = vision.lower()

    if "crypto" in vision_lower:
        return {
            "vision": vision,
            "scope": scope,
            "architecture_note": "No SEBI jurisdiction. Binance/Bybit APIs. 24x7. USDT-margined.",
            "phases": [
                {
                    "phase": 1,
                    "name": "API Smoke Test",
                    "tasks": [
                        "Open Binance testnet account (5 min)",
                        "Install python-binance (pip)",
                        "Fetch BTCUSDT ticker, 24h volume, order book depth",
                        "Place 1 test order (0.001 BTC, market buy)",
                        "Verify fills, commission, PnL in USDT",
                    ],
                    "duration_est": "2 hours",
                    "risk": "LOW — testnet, no real money",
                    "deliverable": "Working API connection + 1 trade confirmation",
                },
                {
                    "phase": 2,
                    "name": "Strategy Port — BTC Iron Condor",
                    "tasks": [
                        "Port pm_tools.calculate_strikes() to BTC (grid=500, wing=2000)",
                        "Adapt span_calculator → Binance margin tier API",
                        "Build BTC weekly options crew (reuse PM+TA+OM pattern)",
                        "Paper trade 5 sessions, track PnL in CSV",
                    ],
                    "duration_est": "1 weekend",
                    "risk": "MEDIUM — new exchange, different option mechanics",
                    "deliverable": "Paper-traded BTC Iron Condor with PnL journal",
                },
                {
                    "phase": 3,
                    "name": "Live with ₹50k",
                    "tasks": [
                        "Deposit ₹50k → USDT → Binance",
                        "Set max position = 0.001 BTC (₹5k risk per trade)",
                        "Run Antariksh Crypto Crew for 5 sessions (Mon-Fri)",
                        "Daily CFO audit of crypto PnL segment",
                    ],
                    "duration_est": "1 week",
                    "risk": "HIGH — real money, 24x7 market, no circuit breaker",
                    "deliverable": "5-day live trading journal + PnL report",
                },
            ],
        }

    if "mcx" in vision_lower or "kurma" in vision_lower:
        return {
            "vision": vision,
            "scope": scope,
            "architecture_note": "Evening session (17:00-23:20). Kurma codebase exists. No index options overlap.",
            "phases": [
                {
                    "phase": 1,
                    "name": "MCX API Integration",
                    "tasks": [
                        "Verify Shoonya supports MCX segment (it does)",
                        "Fetch Crude Oil, Natural Gas, Gold futures quotes",
                        "Test margin query for MCX segment (different SPAN rules)",
                        "Verify after-hours trading permissions",
                    ],
                    "duration_est": "4 hours",
                    "risk": "LOW — same broker, different segment",
                    "deliverable": "MCX quote stream + margin data",
                },
                {
                    "phase": 2,
                    "name": "Strategy Adaptation",
                    "tasks": [
                        "Port Iron Condor to Crude Oil (strike grid=50, wing=200)",
                        "Add commodity-specific gates: inventory data, OPEC calendar, weather",
                        "Build MCX Scanner tool (different indicators than NIFTY)",
                        "Paper trade 10 sessions",
                    ],
                    "duration_est": "1 weekend",
                    "risk": "MEDIUM — commodity fundamentals differ from index",
                    "deliverable": "Paper-traded Crude Oil strategy spec",
                },
            ],
        }

    # Generic POC plan
    return {
        "vision": vision,
        "scope": scope,
        "phases": [
            {
                "phase": 1,
                "name": "Research & Feasibility",
                "tasks": [
                    f"Research existing solutions for: {vision}",
                    "Identify API/SDK availability",
                    "Estimate cost, latency, regulatory constraints",
                    "Write 1-page feasibility memo",
                ],
                "duration_est": "4 hours",
                "risk": "LOW — research only",
                "deliverable": "Feasibility memo",
            },
            {
                "phase": 2,
                "name": "Minimal POC",
                "tasks": [
                    "Build hello-world integration",
                    "Verify data flows end-to-end",
                    "Identify integration pain points",
                    "Estimate full build effort",
                ],
                "duration_est": "1 day",
                "risk": "MEDIUM — may discover blocking constraints",
                "deliverable": "Working POC + build estimate",
            },
            {
                "phase": 3,
                "name": "Paper Trading / Shadow Mode",
                "tasks": [
                    "Run strategy in shadow mode for N sessions",
                    "Compare against existing strategies",
                    "Collect PnL, win rate, max DD data",
                ],
                "duration_est": "1-2 weeks",
                "risk": "HIGH — strategy may underperform",
                "deliverable": "Shadow mode performance report",
            },
        ],
    }
