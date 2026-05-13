"""CEO + Governance deterministic tools.

Alignment checks, crew performance aggregation, resource cap enforcement,
board reporting, escalation, authority chain, growth scouting, market research.
"""

import os
import sys
import json
import time
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone, timedelta
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30))

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


def scout_growth_opportunity(
    current_pnl_trajectory: float,
    current_margin_available: float,
    crew_skills: List[str],
    days_clean_execution: int = 0,
) -> Dict:
    """Scout new business opportunities based on crew skills and current performance.

    Phase 1 check: execution must be proven first (30 clean days, PnL on trajectory).
    Phase 2: evaluate opportunities against crew capabilities and capital.
    Phase 3: readiness for Board proposal.

    Returns:
        {phase, execution_proven, opportunities, gaps, board_ready}
    """
    phase = 1
    execution_proven = days_clean_execution >= 30 and current_pnl_trajectory >= 300000

    opportunities = []
    gaps = []

    # Always evaluate — but flag readiness
    crypto_viable = "api_integration" in crew_skills or "automation" in crew_skills
    mcx_viable = current_margin_available >= 250000  # Kurma base exists
    new_strategies_viable = "trading" in crew_skills

    if crypto_viable:
        opportunities.append(
            {
                "domain": "Crypto perpetual futures",
                "viability": "MEDIUM",
                "reason": "Crew has API skills. 24/7 market — autonomous system advantage.",
                "capital_needed": current_margin_available * 0.2,
                "skill_gap": "Crypto exchange API (Binance/Bybit), funding rate mechanics",
            }
        )
    else:
        gaps.append(
            "Crypto trading: need API integration + crypto market mechanics skills"
        )

    if mcx_viable:
        opportunities.append(
            {
                "domain": "MCX evening session (crude oil, natural gas)",
                "viability": "HIGH",
                "reason": f"Kurma codebase exists. ₹{current_margin_available:,.0f} margin available for evening session — no overlap with NIFTY day margin.",
                "capital_needed": current_margin_available * 0.3,
                "skill_gap": "MCX contract specifics, commodity fundamentals (minor gap)",
            }
        )
    else:
        gaps.append("MCX: need ₹2.5L minimum margin (currently below threshold)")

    if new_strategies_viable:
        opportunities.append(
            {
                "domain": "New strategies (Iron Condor, Ratio Spread, Calendar)",
                "viability": "HIGH",
                "reason": "Crew already runs Iron Fly. Adding condor/spread is same skill set, different risk profile.",
                "capital_needed": 0,
                "skill_gap": "None — PA can backtest any strategy with existing DuckDB data",
            }
        )

    board_ready = execution_proven and len(opportunities) > 0

    if execution_proven:
        phase = 2
        if board_ready:
            phase = 3

    return {
        "phase": phase,
        "phase_label": {1: "PROVE EXECUTION", 2: "SCOUT GROWTH", 3: "PRESENT TO BOARD"}[
            phase
        ],
        "execution_proven": execution_proven,
        "days_clean": days_clean_execution,
        "opportunities": opportunities,
        "skill_gaps": gaps,
        "board_ready": board_ready,
        "evidence": (
            f"Phase {phase}: {'BOARD READY — ' + str(len(opportunities)) + ' opportunities scouted' if board_ready else 'proving execution' if not execution_proven else 'scouting ' + str(len(opportunities)) + ' opportunities'}"
        ),
    }


# ============================================================
# Market Research — eyes on the outside world
# ============================================================

ECONOMIC_CALENDAR = {
    "RBI_MPC": {
        "next": "2026-06-05",
        "impact": "HIGH",
        "description": "RBI Monetary Policy Committee decision",
    },
    "FOMC": {
        "next": "2026-06-18",
        "impact": "HIGH",
        "description": "US Federal Reserve rate decision",
    },
    "INFLATION_CPI": {
        "next": "2026-06-12",
        "impact": "MEDIUM",
        "description": "India CPI inflation data release",
    },
    "GDP_Q1": {
        "next": "2026-05-31",
        "impact": "MEDIUM",
        "description": "India Q1 GDP growth numbers",
    },
    "EXPIRY_NIFTY": {
        "frequency": "weekly_thursday",
        "impact": "HIGH",
        "description": "NIFTY weekly options expiry",
    },
}

MARKET_HOURS = {
    "nse": {"open": "09:15", "close": "15:30", "timezone": "IST", "days": "1-5"},
    "mxc": {"open": "09:00", "close": "23:30", "timezone": "IST", "days": "1-5"},
    "crypto": {"open": "00:00", "close": "24:00", "timezone": "UTC", "days": "0-6"},
}


def market_research() -> Dict:
    """Scan external environment: VIX, events, market hours, FII/DII.

    Checks what a CEO needs to know before making strategic decisions.
    """
    now = datetime.now(IST)
    today_str = now.strftime("%Y-%m-%d")
    hour = now.hour

    # Market status
    market_open = 9 <= hour < 16 and now.weekday() < 5
    nifty_expiry_week = now.weekday() == 3  # Thursday

    # Upcoming events (next 30 days)
    upcoming = []
    for name, info in sorted(
        ECONOMIC_CALENDAR.items(), key=lambda x: x[1].get("next", "")
    ):
        next_date = info.get("next", "")
        if next_date >= today_str and (
            info.get("frequency") != "weekly_thursday" or nifty_expiry_week
        ):
            upcoming.append(
                f"{name}: {next_date} — {info.get('impact', '?')} — {info.get('description', '')}"
            )

    # Market regime assessment
    if market_open:
        regime = "TRADING HOURS — NSE open"
    elif 0 <= hour < 9:
        regime = "PRE-MARKET — pre-flight + strategy prep window"
    elif 16 <= hour < 18:
        regime = "POST-MARKET — cleanup + post-mortem window"
    else:
        regime = "CLOSED — next trading day prep / weekend reflection"

    # VIX placeholder (would come from real NSE API or data_capture)
    vix_estimate = "UNKNOWN (enable data_capture for real VIX)"

    return {
        "market_open": market_open,
        "regime": regime,
        "vix": vix_estimate,
        "expiry_week": nifty_expiry_week,
        "upcoming_events": upcoming[:5],
        "market_hours_available": [
            f"{k}: {v['open']}-{v['close']} {v['timezone']} (days {v['days']})"
            for k, v in MARKET_HOURS.items()
        ],
        "evidence": (
            f"Market: {regime}. "
            f"VIX: {vix_estimate}. "
            f"Expiry week: {'YES ⚡' if nifty_expiry_week else 'no'}. "
            f"Upcoming events: {len(upcoming)} in next 30d. "
            f"({now.strftime('%H:%M IST')})"
        ),
    }


def explore_opportunity(domain: str = "") -> Dict:
    """Deep-dive into a specific growth opportunity. Pass domain name to analyze.

    Supported domains: crypto, mcx, condor, sensex, banknifty, flattrade, dual_broker
    """
    opportunities_db = {
        "crypto": {
            "viability": "MEDIUM",
            "reason": "24/7 market — autonomous system advantage. Perpetual futures on BTC/ETH. Funding rate arbitrage possible.",
            "capital_needed": "₹50,000-₹100,000",
            "skill_gap": "Crypto exchange API (Binance/Bybit). Funding rate mechanics. Different risk profile (no circuit breakers).",
            "competition": "Retail-dominated, less institutional. Edge: 24/7 automation.",
            "timeline": "4-6 weeks to integrate + backtest",
            "risk": "Exchange insolvency risk. No SEBI protection. Higher volatility.",
        },
        "mcx": {
            "viability": "HIGH",
            "reason": "Evening session (17:00-23:30) doesn't overlap with NIFTY day margin. Crude oil + Natural gas momentum trades. Kurma codebase exists.",
            "capital_needed": "₹100,000-₹250,000",
            "skill_gap": "MCX contract specs. Commodity fundamentals (inventory data, OPEC, weather). Different margin rules.",
            "competition": "Medium institutional presence. Edge: algorithmic momentum on liquid contracts.",
            "timeline": "2-3 weeks (Kurma base exists)",
            "risk": "Overnight gap risk. Less liquid than NIFTY. Spread widening on expiry.",
        },
        "condor": {
            "viability": "HIGH",
            "reason": "Iron Condor = Iron Fly + wider wings. Same skill set. Lower delta, lower gamma — safer for larger positions.",
            "capital_needed": "₹0 (same margin, different strike layout)",
            "skill_gap": "None — PA can backtest with existing DuckDB data.",
            "competition": "Same competition as Iron Fly. Edge: better risk/reward for high VIX.",
            "timeline": "1 week (backtest + strategy spec)",
            "risk": "Lower profit per trade. Needs higher win rate to match Iron Fly PnL.",
        },
        "sensex": {
            "viability": "HIGH",
            "reason": "SENSEX has wider bid-ask but moves in sync with NIFTY. Data_capture_sensex.sh already running. Dual-index = 2x volume with same edge.",
            "capital_needed": "₹50,000 (additional margin)",
            "skill_gap": "None — same Iron Fly mechanics on different index.",
            "competition": "Same as NIFTY. Slightly less liquid options.",
            "timeline": "1-2 days (data stream exists)",
            "risk": "Correlation risk — both indices move together, not true diversification.",
        },
        "flattrade": {
            "viability": "MEDIUM",
            "reason": "₹9,615 idle. Could run 1 lot separately or consolidate to Shoonya. Broker cost arbitrage: FT may have lower brokerage.",
            "capital_needed": "₹0 (already funded)",
            "skill_gap": "FT order placement API. IP whitelist if applicable.",
            "competition": "Same trades, different broker. Edge: redundancy + cost optimization.",
            "timeline": "2-3 days",
            "risk": "Lower margin availability. Account may have restrictions.",
        },
        "dual_broker": {
            "viability": "MEDIUM",
            "reason": "Shoonya ₹601k + Flattrade ₹9.6k. Route 1 lot through each. If one broker fails, other continues. Redundancy = safety.",
            "capital_needed": "₹0",
            "skill_gap": "Orchestrator must handle dual-broker dispatch. TA must validate per-broker.",
            "competition": "Most traders single-broker. Edge: failsafe + cost comparison data.",
            "timeline": "1-2 weeks",
            "risk": "Split liquidity. PM must manage two sets of orders.",
        },
        "banknifty": {
            "viability": "HIGH",
            "reason": "BANKNIFTY has 2x NIFTY options volume. Higher premiums = higher PnL/trade. Same Iron Fly mechanics.",
            "capital_needed": "₹75,000-₹100,000 (higher lot margin)",
            "skill_gap": "None — same strategy. Different strike intervals (100pts vs 50pts).",
            "competition": "High institutional volume. Edge: systematic execution on liquid options.",
            "timeline": "1 week (add BANKNIFTY data capture + backtest)",
            "risk": "Higher volatility. Whipsaws more than NIFTY. Expiry day chaos.",
        },
    }

    if domain and domain in opportunities_db:
        info = opportunities_db[domain]
        return {
            "domain": domain,
            **info,
            "evidence": f"{domain}: {info['viability']} — {info['reason'][:120]}",
        }

    # Return all opportunities summary
    summary = []
    for key, info in sorted(
        opportunities_db.items(),
        key=lambda x: {"HIGH": 0, "MEDIUM": 1}[x[1]["viability"]],
    ):
        summary.append(f"{key}: {info['viability']} — {info['reason'][:80]}...")

    return {
        "domains_available": list(opportunities_db.keys()),
        "summary": summary,
        "top_pick": [
            k for k, v in opportunities_db.items() if v["viability"] == "HIGH"
        ][0]
        if any(v["viability"] == "HIGH" for v in opportunities_db.values())
        else "none",
        "evidence": f"{len(opportunities_db)} domains scouted. Top viability: {', '.join(k for k, v in opportunities_db.items() if v['viability'] == 'HIGH')}",
    }
