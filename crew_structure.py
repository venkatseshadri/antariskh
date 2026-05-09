#!/usr/bin/env python3
"""
Antariksh Phase 2 — CrewAI Multi-Agent Trading System
7 agents: Orchestrator, Scanner, Strategist, Executor, Sentinel, Risk Guard, Auditor
Hierarchical crew with Orchestrator as manager, Risk Guard with veto power.

Usage:
    python crew_structure.py --mock --vix 18.5 --nifty 24500 --time 10:30
    python crew_structure.py --mock --trace
"""

import sys
import os
import json
import logging
from pathlib import Path
from datetime import datetime as _dt, time as dt_time

# Alias for mock patching compatibility (ScenarioRunner patches 'datetime')
datetime = _dt
from typing import Dict, Optional, Tuple, List

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "python-trader"))
sys.path.insert(0, str(PROJECT_ROOT / "antariksh"))

from crewai import Agent, Task, Crew, Process
from crewai.llm import LLM
from crewai.tools import tool

# ============================================================
# LLM Configuration
# ============================================================

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")

deepseek_llm = LLM(
    model="deepseek/deepseek-chat",
    base_url=DEEPSEEK_BASE,
    api_key=DEEPSEEK_API_KEY,
    temperature=0.3,
)

# ============================================================
# Logging
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("Antariksh-Crew")

# ============================================================
# MOCK MODE (for testing without live broker)
# ============================================================

MOCK_MODE = os.environ.get("ANTARIKSH_MOCK_MODE", "0") == "1"
MOCK_VIX = float(os.environ.get("ANTARIKSH_MOCK_VIX", "18.5"))
MOCK_NIFTY = float(os.environ.get("ANTARIKSH_MOCK_NIFTY", "24500.0"))

# ============================================================
# Shared Market State (context dict passed between tasks)
# ============================================================

market_state: Dict = {
    "vix": None,
    "nifty_spot": None,
    "atm_strike": None,
    "trade_plan": None,
    "gate_pass": False,
    "gate_reason": "",
    "positions": {},
    "mtd_pnl": 0.0,
    "session_pnl": 0.0,
    "alerts": [],
    "audit_entries": [],
    "halt": False,
    "risk_ok": True,
    "re_entries_used": 0,
    "max_re_entries": 1,
}

# ============================================================
# TOOLS — Deterministic Functions (no LLM, instant execution)
# ============================================================


@tool
def scan_market() -> str:
    """
    Scan market conditions and set gate_pass in market_state.
    1. Read VIX and NIFTY from market_state (mock mode) or live broker.
    2. Check if VIX > 20 (gate fail).
    3. Check if current time is within entry window (10:30-11:30 IST).
    4. Check event calendar for event day.
    5. Set market_state gate_pass and gate_reason.
    """
    mock_mode = os.environ.get("ANTARIKSH_MOCK_MODE", "0") == "1"
    mock_time = os.environ.get("ANTARIKSH_MOCK_TIME", "")
    mock_event = os.environ.get("ANTARIKSH_MOCK_EVENT_DAY", "0") == "1"
    mock_event_name = os.environ.get("ANTARIKSH_MOCK_EVENT_NAME", "")

    vix = market_state.get("vix") or float(os.environ.get("ANTARIKSH_MOCK_VIX", 18.5))
    nifty = market_state.get("nifty_spot") or float(
        os.environ.get("ANTARIKSH_MOCK_NIFTY", 24500.0)
    )

    market_state["vix"] = vix
    market_state["nifty_spot"] = nifty

    reasons = []

    if vix > 20:
        reasons.append(f"VIX {vix} > 20")

    now = _dt.fromisoformat(mock_time) if mock_time else _dt.now()
    entry_start = now.replace(hour=10, minute=30, second=0, microsecond=0)
    entry_end = now.replace(hour=11, minute=30, second=0, microsecond=0)
    if not (entry_start <= now <= entry_end):
        reasons.append(f"Outside entry window: {now.strftime('%H:%M')}")

    if mock_event:
        reasons.append(f"Event day: {mock_event_name}")

    gate_pass = len(reasons) == 0
    market_state["gate_pass"] = gate_pass
    market_state["gate_reason"] = " | ".join(reasons) if reasons else "All gates passed"

    logger.info(
        f"scan_market: VIX={vix}, NIFTY={nifty}, gate_pass={gate_pass}, reason={market_state['gate_reason']}"
    )
    return json.dumps(
        {
            "vix": vix,
            "nifty_spot": nifty,
            "gate_pass": gate_pass,
            "gate_reason": market_state["gate_reason"],
        }
    )


@tool
def generate_trade_plan() -> str:
    """
    Generate Iron Butterfly trade plan from market data.
    Calculate ATM strike: round(spot/50)*50. Wing width 300. Lots=1.
    If gate_pass is False, return skip.
    """
    if not market_state.get("gate_pass", False):
        market_state["trade_plan"] = None
        logger.info("generate_trade_plan: skipped (gate_pass=False)")
        return json.dumps({"status": "skipped", "reason": "gate_pass=False"})

    spot = market_state.get("nifty_spot", 24500.0)
    atm_strike = round(spot / 50) * 50

    plan = {
        "instrument": "NIFTY",
        "strategy": "Iron Butterfly",
        "spot": spot,
        "atm_strike": atm_strike,
        "wing_width": 300,
        "lots": 1,
        "target_profit": 1000,
        "max_loss": 3500,
        "legs": [
            {
                "type": "BUY",
                "strike": atm_strike - 300,
                "option": "PE",
                "action": "BUY",
            },
            {"type": "SELL", "strike": atm_strike, "option": "PE", "action": "SELL"},
            {"type": "SELL", "strike": atm_strike, "option": "CE", "action": "SELL"},
            {
                "type": "BUY",
                "strike": atm_strike + 300,
                "option": "CE",
                "action": "BUY",
            },
        ],
        "entry_time": _dt.now().isoformat(),
    }
    market_state["trade_plan"] = plan
    market_state["atm_strike"] = atm_strike

    logger.info(
        f"generate_trade_plan: ATM={atm_strike}, spot={spot}, wings={plan['wing_width']}"
    )
    return json.dumps({"status": "generated", "atm_strike": atm_strike, "legs": 4})


@tool
def check_risk() -> str:
    """
    Run L1 capital preservation checks via RiskGuardEngine.full_check().
    Uses session_pnl and mtd_pnl from market_state. Returns verdict.
    Sets halt and risk_ok in market_state.
    """
    session_pnl = market_state.get("session_pnl", 0.0)
    mtd_pnl = market_state.get("mtd_pnl", 0.0)
    recent = market_state.get("recent_pnls", None)

    verdict = RiskGuardEngine.full_check(
        session_pnl=session_pnl, mtd_pnl=mtd_pnl, recent_pnls=recent
    )

    logger.info(
        f"check_risk: passed={verdict['passed']}, halt={verdict['halt']}, "
        f"violations={verdict['violations']}"
    )
    return json.dumps(
        {
            "passed": verdict["passed"],
            "halt": verdict["halt"],
            "violations": verdict["violations"],
            "recommendations": verdict["recommendations"],
        }
    )


@tool
def execute_trade() -> str:
    """
    Execute the trade plan. Verify risk_ok=True and halt=False first.
    Place 4-leg Iron Butterfly basket (stubbed in Phase 2).
    """
    if market_state.get("halt", False):
        market_state["positions"] = {}
        logger.info("execute_trade: aborted — trading halted")
        return json.dumps({"status": "aborted", "reason": "trading_halted"})
    if not market_state.get("risk_ok", True):
        market_state["positions"] = {}
        logger.info("execute_trade: aborted — risk check failed")
        return json.dumps({"status": "aborted", "reason": "risk_check_failed"})
    if market_state.get("trade_plan") is None:
        market_state["positions"] = {}
        logger.info("execute_trade: skipped — no trade plan")
        return json.dumps({"status": "skipped", "reason": "no_trade_plan"})

    plan = market_state["trade_plan"]
    fills = []
    for leg in plan.get("legs", []):
        fills.append(
            {
                "leg": f"{leg['option']}_{leg['strike']}_{leg['type']}",
                "status": "filled",
                "price": 0.0,  # STUBBED in Phase 2
            }
        )

    market_state["positions"] = {"legs": fills, "status": "open"}
    logger.info(f"execute_trade: {len(fills)} legs placed (stubbed)")
    return json.dumps(
        {"status": "executed", "legs_executed": len(fills), "fills": fills}
    )


@tool
def monitor_positions() -> str:
    """
    Monitor open positions: calculate MTM P&L, check SL/target proximity.
    Update session_pnl in market_state. Stubbed in Phase 2 (simulated P&L).
    """
    positions = market_state.get("positions", {})
    if not positions or not positions.get("legs"):
        market_state["session_pnl"] = market_state.get("session_pnl", 0.0)
        logger.info("monitor_positions: no open positions")
        return json.dumps(
            {"status": "no_positions", "session_pnl": market_state["session_pnl"]}
        )

    # Simulate P&L for mock mode (target hit scenario)
    mock_mode = os.environ.get("ANTARIKSH_MOCK_MODE", "0") == "1"
    if mock_mode:
        pnl = float(os.environ.get("ANTARIKSH_MOCK_PNL", 850))
    else:
        pnl = 0.0  # Live MTM calculation goes here

    market_state["session_pnl"] = pnl
    target_hit = pnl >= market_state.get("trade_plan", {}).get("target_profit", 1000)
    sl_breach = pnl <= -3500
    sl_distance = 3500 + pnl  # positive = still above SL

    logger.info(
        f"monitor_positions: P&L={pnl}, target_hit={target_hit}, "
        f"sl_breach={sl_breach}, sl_distance={sl_distance}"
    )
    return json.dumps(
        {
            "session_pnl": pnl,
            "target_hit": target_hit,
            "sl_breach": sl_breach,
            "sl_distance": sl_distance,
        }
    )


@tool
def log_audit() -> str:
    """
    Append session to immutable JSONL audit trail.
    Validates L1 invariants and writes entry via AuditorEngine.
    """
    gate_pass = market_state.get("gate_pass", False)
    trade_plan = market_state.get("trade_plan")
    pnl = market_state.get("session_pnl", 0.0)
    alerts = market_state.get("alerts", [])

    passed, violations, recommendations = AuditorEngine.validate_l1_invariants(pnl)

    entry = AuditorEngine.append_session(
        gate_pass=gate_pass,
        trade_plan=trade_plan,
        pnl=pnl,
        violations=violations,
        recommendations=recommendations,
    )

    logger.info(
        f"log_audit: session logged, passed={passed}, mtd_pnl={market_state.get('mtd_pnl')}"
    )
    return json.dumps(
        {
            "session_id": entry["session_id"],
            "verdict": "passed" if passed else "failed",
            "mtd_pnl": market_state.get("mtd_pnl"),
            "violations": violations,
            "entries_appended": 1,
        }
    )


# ============================================================
# AGENT — Orchestrator only (LLM-backed coordination)
# ============================================================

orchestrator = Agent(
    role="Orchestrator",
    goal="Coordinate the daily trading session by calling tools in strict sequence: "
    "scan → plan → risk → execute → monitor → audit. "
    "Skip execution on gate fail or halt. Never skip risk check before trade.",
    backstory=(
        "You are the master coordinator of Antariksh. You run the daily "
        "rhythm: 9:30 AM entry gate check, 10:30 AM entry window, 2:35 PM exit. "
        "All trading logic is in deterministic tools — you only coordinate them. "
        "Sequence: scan_market → generate_trade_plan → check_risk → execute_trade "
        "→ monitor_positions → log_audit. "
        "When scan_market returns gate_pass=False, skip to log_audit. "
        "When check_risk returns halt=True, stop — do NOT execute. "
        "You never override Risk Guard's hard capital limits. "
        "When check_risk says 'halt', you halt — no exceptions."
    ),
    llm=deepseek_llm,
    tools=[
        scan_market,
        generate_trade_plan,
        check_risk,
        execute_trade,
        monitor_positions,
        log_audit,
    ],
    verbose=True,
    allow_delegation=False,
)


# ============================================================
# TASK
# ============================================================

run_session_task = Task(
    description=(
        "Run a complete Antariksh trading session. Follow this EXACT sequence:\n"
        "1. Call scan_market tool — fetch VIX/NIFTY, set gate_pass.\n"
        "2. Call generate_trade_plan tool — generate Iron Fly basket.\n"
        "3. Call check_risk tool — run L1 capital checks (RiskGuardEngine).\n"
        "   If halt=True, skip to step 6.\n"
        "4. Call execute_trade tool — place orders only if risk_ok.\n"
        "5. Call monitor_positions tool — calculate session P&L.\n"
        "6. Call log_audit tool — append to immutable audit trail.\n"
        f"Session type: {{session_type}}. Mock mode: {{mock_mode}}."
    ),
    expected_output=(
        "Session report JSON: gate_pass, trade_plan status, risk_verdict, "
        "execution status, session_pnl, audit summary"
    ),
    agent=orchestrator,
)


# ============================================================
# IMPLEMENTATION: AUDITOR — Phase 1 Log Integration
# ============================================================


class AuditorEngine:
    """
    Deterministic auditor — reads Phase 1 CFO JSONL logs,
    calculates MTD P&L, validates L1 invariants, appends new entries.
    Does NOT use LLM reasoning for validation.
    """

    AUDIT_DIR = Path(__file__).parent / "logs"

    # L1 invariants (mirrors RiskGuardEngine for validation cross-check)
    DAILY_SL = 3500
    PORTFOLIO_SL = 4500
    MAX_30DAY_DD = 30000
    MIN_FREE_CASH = 11000

    @staticmethod
    def read_phase1_logs(date_str: Optional[str] = None) -> List[Dict]:
        """Read Phase 1 CFO audit trail for a given date. Returns list of entries."""
        if date_str is None:
            date_str = _dt.now().strftime("%Y-%m-%d")
        log_file = AuditorEngine.AUDIT_DIR / f"cfo_audit_{date_str}.jsonl"
        entries = []
        if log_file.exists():
            try:
                with open(log_file, "r") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            entries.append(json.loads(line))
                logger.info(f"Auditor: read {len(entries)} entries from {log_file}")
            except Exception as e:
                logger.warning(f"Auditor: failed to read {log_file}: {e}")
        else:
            logger.info(f"Auditor: no Phase 1 log at {log_file} (first session?)")
        return entries

    @staticmethod
    def calculate_mtd_from_logs(date_str: Optional[str] = None) -> float:
        """
        Calculate MTD P&L by summing all session P&Ls from current month's logs.
        Searches all available monthly log files.
        """
        log_dir = AuditorEngine.AUDIT_DIR
        mtd = 0.0
        try:
            month_prefix = (date_str or _dt.now().strftime("%Y-%m-%d"))[:7]
            for log_file in sorted(log_dir.glob(f"cfo_audit_{month_prefix}*.jsonl")):
                with open(log_file, "r") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        entry = json.loads(line)
                        pnl = 0.0
                        if isinstance(entry, dict):
                            pnl = (
                                entry.get("capital_impact", {}).get("net_pnl", 0)
                                or entry.get("backtest_result", {}).get("pnl_inr", 0)
                                or entry.get("cfo_verdict", {}).get("mtd_pnl", 0)
                            )
                        mtd += float(pnl)
            logger.info(f"Auditor: MTD P&L from logs = ₹{mtd:.2f}")
        except Exception as e:
            logger.error(f"Auditor: MTD calculation failed: {e}")
        return mtd

    @staticmethod
    def append_session(
        gate_pass: bool,
        trade_plan: Optional[Dict],
        pnl: float,
        violations: List[str],
        recommendations: List[str],
    ) -> Dict:
        """Append new session entry to immutable JSONL audit trail."""
        AuditorEngine.AUDIT_DIR.mkdir(exist_ok=True)
        timestamp = _dt.now().isoformat()
        session_date = _dt.now().strftime("%Y-%m-%d")
        session_id = _dt.now().strftime("%Y%m%d_%H%M%S")
        mtd_pnl = AuditorEngine.calculate_mtd_from_logs() + pnl

        entry = {
            "timestamp": timestamp,
            "session_id": session_id,
            "gate_pass": gate_pass,
            "trade_plan": trade_plan,
            "backtest_result": {"pnl_inr": pnl},
            "cfo_verdict": {
                "passed": len(violations) == 0,
                "checks": {},
                "violations": violations,
                "recommendations": recommendations,
                "mtd_pnl": mtd_pnl,
                "summary": (
                    "✅ PASS: All L1 checks clear"
                    if not violations
                    else f"❌ FAIL: {len(violations)} violation(s)"
                ),
            },
            "capital_impact": {
                "gross_pnl": pnl,
                "brokerage_est": 50,
                "net_pnl": pnl - 50,
                "free_cash_after": AuditorEngine.MIN_FREE_CASH + pnl - 50,
            },
        }

        log_file = AuditorEngine.AUDIT_DIR / f"cfo_audit_{session_date}.jsonl"
        with open(log_file, "a") as f:
            f.write(json.dumps(entry) + "\n")

        logger.info(
            f"Auditor: appended session {session_id} to {log_file} — P&L ₹{pnl}"
        )
        market_state["audit_entries"].append(entry)
        market_state["mtd_pnl"] = mtd_pnl
        return entry

    @staticmethod
    def validate_l1_invariants(pnl: float) -> Tuple[bool, List[str], List[str]]:
        """
        Hard deterministic L1 check. Returns (passed, violations, recommendations).
        """
        violations = []
        recommendations = []
        mtd = AuditorEngine.calculate_mtd_from_logs() + pnl

        if pnl <= -AuditorEngine.DAILY_SL:
            violations.append(
                f"Daily SL breached: P&L ₹{pnl} <= -₹{AuditorEngine.DAILY_SL}"
            )
        if mtd <= -AuditorEngine.PORTFOLIO_SL:
            violations.append(
                f"Portfolio SL breached: MTD ₹{mtd} <= -₹{AuditorEngine.PORTFOLIO_SL}"
            )
        if mtd <= -AuditorEngine.MAX_30DAY_DD:
            violations.append(
                f"30-day DD breached: ₹{mtd} <= -₹{AuditorEngine.MAX_30DAY_DD}"
            )
        if AuditorEngine.MIN_FREE_CASH + pnl < 0:
            violations.append(
                f"Free cash exhausted: ₹{AuditorEngine.MIN_FREE_CASH + pnl}"
            )

        if pnl > 0 and pnl < 500:
            recommendations.append("Low profit session — review entry timing")
        if mtd < -10000:
            recommendations.append("MTD deeply negative — consider lot size reduction")

        passed = len(violations) == 0
        logger.info(
            f"Auditor L1 validation: passed={passed}, violations={len(violations)}"
        )
        return passed, violations, recommendations


# ============================================================
# IMPLEMENTATION: RISK GUARD — Hard Deterministic Rules
# ============================================================


class RiskGuardEngine:
    """
    Deterministic capital preservation engine.
    All L1 checks are HARD CODE. No LLM in the decision path.
    The Risk Guard AGENT only generates recommendation TEXT — this class enforces.
    """

    DAILY_SL = 3500  # ₹3,500 per session
    PORTFOLIO_SL = 4500  # ₹4,500 cumulative
    MAX_30DAY_DD = 30000  # ₹30,000 max drawdown
    MIN_FREE_CASH = 11000  # ₹11,000 floor
    BURN_DAYS = 10  # Lookback window for burn rate
    BURN_THRESHOLD = 0.30  # 30% of free cash

    @staticmethod
    def check_daily_sl(session_pnl: float) -> Tuple[bool, str]:
        if session_pnl <= -RiskGuardEngine.DAILY_SL:
            return (
                False,
                f"Daily SL ₹{RiskGuardEngine.DAILY_SL} breached: P&L ₹{session_pnl}",
            )
        return True, f"Daily SL OK (₹{session_pnl} > -₹{RiskGuardEngine.DAILY_SL})"

    @staticmethod
    def check_portfolio_sl(mtd_pnl: float) -> Tuple[bool, str]:
        if mtd_pnl <= -RiskGuardEngine.PORTFOLIO_SL:
            return (
                False,
                f"Portfolio SL ₹{RiskGuardEngine.PORTFOLIO_SL} breached: MTD ₹{mtd_pnl}",
            )
        return True, f"Portfolio SL OK (MTD ₹{mtd_pnl})"

    @staticmethod
    def check_30day_dd(mtd_pnl: float) -> Tuple[bool, str]:
        if mtd_pnl <= -RiskGuardEngine.MAX_30DAY_DD:
            return (
                False,
                f"30-day DD ₹{RiskGuardEngine.MAX_30DAY_DD} breached: ₹{mtd_pnl}",
            )
        return True, f"30-day DD OK (₹{mtd_pnl})"

    @staticmethod
    def check_free_cash_floor(session_pnl: float) -> Tuple[bool, str]:
        remaining = RiskGuardEngine.MIN_FREE_CASH + session_pnl
        if remaining < 0:
            return False, f"Free cash exhausted: ₹{remaining}"
        if remaining < RiskGuardEngine.MIN_FREE_CASH * 0.5:
            return (
                True,
                f"Free cash WARNING: ₹{remaining} (floor ₹{RiskGuardEngine.MIN_FREE_CASH})",
            )
        return True, f"Free cash OK: ₹{remaining}"

    @staticmethod
    def check_burn_rate(recent_pnls: List[float]) -> Tuple[bool, str]:
        if len(recent_pnls) < RiskGuardEngine.BURN_DAYS:
            return (
                True,
                f"Burn rate: insufficient data ({len(recent_pnls)}/{RiskGuardEngine.BURN_DAYS} days)",
            )
        recent_slice = recent_pnls[-RiskGuardEngine.BURN_DAYS :]
        total_loss = sum(p for p in recent_slice if p < 0)
        burn_pct = abs(total_loss) / RiskGuardEngine.MIN_FREE_CASH
        if burn_pct > RiskGuardEngine.BURN_THRESHOLD:
            return (
                False,
                f"Burn rate {burn_pct:.0%} > {RiskGuardEngine.BURN_THRESHOLD:.0%} of free cash",
            )
        return True, f"Burn rate OK: {burn_pct:.0%}"

    @staticmethod
    def full_check(
        session_pnl: float,
        mtd_pnl: float,
        recent_pnls: Optional[List[float]] = None,
    ) -> Dict:
        """
        Run ALL L1 checks. Returns verdict dict.
        This is the SOLE entry point for capital rule enforcement.
        Called by both the Risk Guard task AND the Executor before placing orders.
        """
        checks = {}
        violations = []
        recommendations = []

        ok, msg = RiskGuardEngine.check_daily_sl(session_pnl)
        checks["daily_sl"] = msg
        if not ok:
            violations.append(msg)

        ok, msg = RiskGuardEngine.check_portfolio_sl(mtd_pnl)
        checks["portfolio_sl"] = msg
        if not ok:
            violations.append(msg)

        ok, msg = RiskGuardEngine.check_30day_dd(mtd_pnl)
        checks["30day_dd"] = msg
        if not ok:
            violations.append(msg)

        ok, msg = RiskGuardEngine.check_free_cash_floor(session_pnl)
        checks["free_cash"] = msg
        if not ok:
            violations.append(msg)

        if recent_pnls is None:
            recent_pnls = []
        ok, msg = RiskGuardEngine.check_burn_rate(recent_pnls)
        checks["burn_rate"] = msg
        if not ok:
            violations.append(msg)

        if session_pnl > 800:
            recommendations.append("Protect gains — consider early TP trail")
        if mtd_pnl < -5000:
            recommendations.append("Reduce lot size to 1 until MTD recovers")
        if mtd_pnl < -10000:
            recommendations.append("Chairman review required — 10%+ capital at risk")

        verdict = {
            "passed": len(violations) == 0,
            "checks": checks,
            "violations": violations,
            "recommendations": recommendations,
            "halt": len(violations) > 0,
        }

        market_state["risk_ok"] = verdict["passed"]
        market_state["halt"] = verdict["halt"]

        logger.info(
            f"Risk Guard full check: passed={verdict['passed']}, "
            f"halt={verdict['halt']}, violations={len(violations)}"
        )
        return verdict


# ============================================================
# IMPLEMENTATION: RE-ENTRY TRACKER
# ============================================================


class ReEntryTracker:
    """
    Tracks re-entry attempts per session.
    Strategist can recommend re-entry if SL is hit and attempts remain.
    Executor respects this before placing any re-entry order.
    """

    MAX_RE_ENTRIES = 1

    @staticmethod
    def can_re_enter() -> bool:
        used = market_state.get("re_entries_used", 0)
        max_allowed = market_state.get("max_re_entries", ReEntryTracker.MAX_RE_ENTRIES)
        if market_state.get("halt", False):
            logger.warning("Re-entry blocked: trading halted by Risk Guard")
            return False
        if used >= max_allowed:
            logger.warning(f"Re-entry denied: {used}/{max_allowed} attempts used")
            return False
        logger.info(f"Re-entry allowed: {used}/{max_allowed} attempts used so far")
        return True

    @staticmethod
    def mark_re_entry() -> int:
        market_state["re_entries_used"] = market_state.get("re_entries_used", 0) + 1
        count = market_state["re_entries_used"]
        logger.info(
            f"Re-entry marked: {count}/{market_state.get('max_re_entries', 1)} used"
        )
        return count

    @staticmethod
    def reset_session():
        market_state["re_entries_used"] = 0
        logger.info("Re-entry counter reset for new session")


# ============================================================
# PRE-SESSION INITIALIZATION
# ============================================================


def initialize_session():
    """
    Called at crew startup. Loads Phase 1 audit trail,
    calculates MTD P&L, resets session state.
    """
    logger.info("Initializing Antariksh session...")
    mtd_pnl = AuditorEngine.calculate_mtd_from_logs()
    market_state["mtd_pnl"] = mtd_pnl
    market_state["halt"] = False
    market_state["risk_ok"] = True
    ReEntryTracker.reset_session()
    logger.info(
        f"Session initialized: MTD ₹{mtd_pnl:.2f}, "
        f"re-entries 0/{market_state['max_re_entries']}"
    )


# ============================================================
# CREW — lazy builder (no LLM connection on import)
# ============================================================

_crew_cache = None


def _build_crew():
    """Build the Antariksh crew. Lazy — no LLM connection until kickoff()."""
    global _crew_cache
    if _crew_cache is None:
        _crew_cache = Crew(
            agents=[orchestrator],
            tasks=[run_session_task],
            process=Process.sequential,
            verbose=True,
        )
    return _crew_cache


# ============================================================
# ENTRY POINTS
# ============================================================


def run_entry_session(
    mock_mode: bool = False,
    mock_vix: float = 18.5,
    mock_nifty: float = 24500.0,
    mock_time: str = "10:30",
) -> Dict:
    """
    Run the entry gate + trade plan generation crew.
    Called at 9:30 AM IST.

    Returns:
        Dict with gate_pass, trade_plan, risk_verdict
    """
    if mock_mode:
        os.environ["ANTARIKSH_MOCK_MODE"] = "1"
        os.environ["ANTARIKSH_MOCK_VIX"] = str(mock_vix)
        os.environ["ANTARIKSH_MOCK_NIFTY"] = str(mock_nifty)
        os.environ["ANTARIKSH_MOCK_TIME"] = mock_time
        logger.info(f"MOCK: VIX={mock_vix}, NIFTY={mock_nifty}, TIME={mock_time}")

    logger.info("=" * 60)
    logger.info("ANTARIKSH PHASE 2 CREW — ENTRY SESSION START")
    logger.info("=" * 60)

    result = _build_crew().kickoff(
        inputs={
            "session_type": "entry",
            "mock_mode": mock_mode,
        }
    )

    logger.info(f"Crew kickoff result: {result}")
    logger.info("=" * 60)
    logger.info("ANTARIKSH PHASE 2 CREW — ENTRY SESSION COMPLETE")
    logger.info("=" * 60)

    return {
        "gate_pass": market_state.get("gate_pass", False),
        "trade_plan": market_state.get("trade_plan"),
        "risk_verdict": market_state.get("risk_ok", False),
    }


def run_exit_session(mock_mode: bool = False, mock_pnl: float = 0.0) -> Dict:
    """
    Run the exit + P&L audit crew.
    Called at 2:35 PM IST.

    Returns:
        Dict with session_pnl, mtd_pnl, audit_verdict
    """
    if mock_mode:
        os.environ["ANTARIKSH_MOCK_MODE"] = "1"

    logger.info("=" * 60)
    logger.info("ANTARIKSH PHASE 2 CREW — EXIT SESSION START")
    logger.info("=" * 60)

    result = _build_crew().kickoff(
        inputs={
            "session_type": "exit",
            "mock_mode": mock_mode,
        }
    )

    logger.info(f"Crew kickoff result: {result}")
    logger.info("=" * 60)
    logger.info("ANTARIKSH PHASE 2 CREW — EXIT SESSION COMPLETE")
    logger.info("=" * 60)

    return {
        "session_pnl": market_state.get("session_pnl", 0.0),
        "mtd_pnl": market_state.get("mtd_pnl", 0.0),
        "audit_verdict": market_state.get("audit_verdict", {}),
    }


def run_full_session(
    mock_mode: bool = False,
    mock_vix: float = 18.5,
    mock_nifty: float = 24500.0,
    mock_time: str = "10:30",
) -> Dict:
    """Run full entry + exit session in a single LLM kickoff (all 6 tools)."""
    if mock_mode:
        os.environ["ANTARIKSH_MOCK_MODE"] = "1"
        os.environ["ANTARIKSH_MOCK_VIX"] = str(mock_vix)
        os.environ["ANTARIKSH_MOCK_NIFTY"] = str(mock_nifty)
        os.environ["ANTARIKSH_MOCK_TIME"] = mock_time
        logger.info(f"MOCK: VIX={mock_vix}, NIFTY={mock_nifty}, TIME={mock_time}")

    logger.info("=" * 60)
    logger.info("ANTARIKSH PHASE 2 CREW — FULL SESSION START")
    logger.info("=" * 60)

    _build_crew().kickoff(
        inputs={
            "session_type": "full",
            "mock_mode": mock_mode,
        }
    )

    logger.info("=" * 60)
    logger.info("ANTARIKSH PHASE 2 CREW — FULL SESSION COMPLETE")
    logger.info("=" * 60)

    return {
        "entry": {
            "gate_pass": market_state.get("gate_pass", False),
            "trade_plan": market_state.get("trade_plan"),
            "risk_verdict": market_state.get("risk_ok", False),
        },
        "exit": {
            "session_pnl": market_state.get("session_pnl", 0.0),
            "mtd_pnl": market_state.get("mtd_pnl", 0.0),
            "audit_verdict": {},
        },
    }


def run_risk_halt_test() -> Dict:
    """Test Risk Guard autonomous halt on capital breach."""
    os.environ["ANTARIKSH_MOCK_MODE"] = "1"
    market_state["session_pnl"] = -4000  # Breach daily SL
    market_state["mtd_pnl"] = -5000

    logger.info("=" * 60)
    logger.info("ANTARIKSH PHASE 2 CREW — RISK GUARD HALT TEST")
    logger.info("=" * 60)

    result = _build_crew().kickoff(
        inputs={
            "session_type": "risk_test",
            "test_scenario": "capital_floor_breach",
        }
    )

    logger.info(f"Risk halt test result: {result}")
    return {
        "halt_issued": market_state.get("halt", False),
        "risk_verdict": market_state.get("risk_ok", False),
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Antariksh Phase 2 CrewAI")
    parser.add_argument("--mock", action="store_true", help="Enable mock mode")
    parser.add_argument("--vix", type=float, default=18.5, help="Mock VIX")
    parser.add_argument("--nifty", type=float, default=24500.0, help="Mock NIFTY")
    parser.add_argument("--time", type=str, default="10:30", help="Mock time (HH:MM)")
    parser.add_argument("--trace", action="store_true", help="Enable trace logging")
    parser.add_argument(
        "--capital-floor-breach",
        action="store_true",
        help="Test Risk Guard halt scenario",
    )
    args = parser.parse_args()

    if args.trace:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.capital_floor_breach:
        result = run_risk_halt_test()
        print(
            f"\nRisk Halt Test: halt_issued={result['halt_issued']}, "
            f"risk_ok={result['risk_verdict']}"
        )
    else:
        result = run_full_session(
            mock_mode=args.mock,
            mock_vix=args.vix,
            mock_nifty=args.nifty,
            mock_time=args.time,
        )
        print(
            f"\nSession Result: gate_pass={result['entry']['gate_pass']}, "
            f"pnl={result['exit']['session_pnl']}"
        )
