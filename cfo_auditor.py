#!/usr/bin/env python3
"""
CFO Auditor — logs trade governance, capital preservation, L1 invariant checks.
Every session logged: gate decision, trade plan, backtest result, CFO verdict.
"""

import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional

logger = logging.getLogger("CFOAuditor")

class CFOAuditor:
    """
    CFO agent (Phase 1: audit logger only, not autonomous).
    Logs every session decision for later review.
    """

    # L1 INVARIANTS (from STRATEGY_DESIGN_QUESTIONS.md)
    MAX_DAILY_SL = 3500  # ₹3,500 per session
    MAX_PORTFOLIO_SL = 4500  # ₹4,500 cumulative
    MAX_30_DAY_DD = 30000  # ₹30,000 max drawdown
    DAILY_TARGET = 1000  # ₹1,000 target profit
    MIN_FREE_CASH = 11000  # ₹11,000 floor
    MAX_DD_PERCENTAGE = 0.30  # 30% of free cash

    def __init__(self):
        self.log_dir = Path(__file__).parent / "logs"
        self.log_dir.mkdir(exist_ok=True)
        self.mtd_pnl = 0.0
        self.session_count = 0
        self.cumulative_dd = 0.0

    def log_session(self, gate_pass: bool, trade_plan: Optional[Dict],
                   backtest_result: Optional[Dict]) -> Dict:
        """
        Log session: gate decision + trade plan + P&L + CFO audit.
        Returns audit verdict.
        """
        timestamp = datetime.now().isoformat()
        session_date = datetime.now().strftime("%Y-%m-%d")
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Build audit log entry
        entry = {
            "timestamp": timestamp,
            "session_id": session_id,
            "gate_pass": gate_pass,
            "trade_plan": trade_plan,
            "backtest_result": backtest_result,
            "cfo_verdict": self._audit_session(trade_plan, backtest_result),
        }

        # Append to JSONL log file (immutable audit trail)
        log_file = self.log_dir / f"cfo_audit_{session_date}.jsonl"
        with open(log_file, 'a') as f:
            f.write(json.dumps(entry) + "\n")

        logger.info(f"Session logged: {session_id}, verdict={entry['cfo_verdict'].get('passed')}")
        return entry['cfo_verdict']

    def _audit_session(self, trade_plan: Optional[Dict],
                      backtest_result: Optional[Dict]) -> Dict:
        """
        Audit one session against L1 invariants.
        Returns verdict: passed/failed, reason, recommendations.
        """
        verdict = {
            "passed": True,
            "checks": {},
            "violations": [],
            "recommendations": [],
        }

        if not backtest_result:
            verdict["passed"] = True  # No trade, no violations
            verdict["checks"]["no_trade"] = "PASS"
            return verdict

        pnl = backtest_result.get("pnl_inr", 0.0)
        max_loss = backtest_result.get("max_loss", self.MAX_DAILY_SL)

        # Check 1: Daily SL not breached
        if pnl <= -max_loss:
            verdict["violations"].append(f"Daily SL breached: P&L {pnl} <= -{max_loss}")
            verdict["checks"]["daily_sl"] = "FAIL"
            verdict["passed"] = False
        else:
            verdict["checks"]["daily_sl"] = f"PASS ({pnl} > -{max_loss})"

        # Check 2: Portfolio cumulative SL
        self.cumulative_dd += abs(min(pnl, 0))  # Only count losses
        if self.cumulative_dd > self.MAX_PORTFOLIO_SL:
            verdict["violations"].append(f"Portfolio SL breached: cumulative {self.cumulative_dd} > {self.MAX_PORTFOLIO_SL}")
            verdict["checks"]["portfolio_sl"] = "FAIL"
            verdict["passed"] = False
        else:
            verdict["checks"]["portfolio_sl"] = f"PASS (cumulative: {self.cumulative_dd})"

        # Check 3: Capital preservation (30% of free cash)
        free_cash = 100000  # Mock: ₹1L free cash in Phase 1
        dd_ceiling = free_cash * self.MAX_DD_PERCENTAGE  # ₹30K
        if self.cumulative_dd > dd_ceiling:
            verdict["violations"].append(f"Capital preservation breached: {self.cumulative_dd} > {dd_ceiling}")
            verdict["checks"]["capital_preservation"] = "FAIL"
            verdict["passed"] = False
        else:
            verdict["checks"]["capital_preservation"] = f"PASS ({self.cumulative_dd:.0f} < {dd_ceiling:.0f})"

        # Check 4: Target tracking
        self.mtd_pnl += pnl
        self.session_count += 1
        avg_daily = self.mtd_pnl / self.session_count if self.session_count > 0 else 0
        verdict["mtd_pnl"] = self.mtd_pnl
        verdict["avg_daily"] = avg_daily
        verdict["checks"]["target_tracking"] = f"MTD {self.mtd_pnl:.0f}, avg {avg_daily:.0f}/day"

        if avg_daily < self.DAILY_TARGET * 0.5:
            verdict["recommendations"].append(f"Average P&L below 50% of target ({avg_daily:.0f} < {self.DAILY_TARGET * 0.5:.0f})")

        # Verdict summary
        if verdict["violations"]:
            verdict["summary"] = f"❌ FAIL: {len(verdict['violations'])} violation(s)"
        else:
            verdict["summary"] = "✅ PASS: All L1 checks clear"

        logger.info(f"Audit verdict: {verdict['summary']}")
        return verdict

    def get_mtd_summary(self) -> Dict:
        """Get MTD (month-to-date) summary"""
        return {
            "sessions": self.session_count,
            "mtd_pnl": self.mtd_pnl,
            "avg_daily": self.mtd_pnl / self.session_count if self.session_count > 0 else 0,
            "cumulative_dd": self.cumulative_dd,
            "capital_remaining": 100000 - self.cumulative_dd,  # Mock free cash
        }

# ============================================================
# SINGLETON INSTANCE
# ============================================================

_cfo_auditor = None

def get_cfo_auditor() -> CFOAuditor:
    """Get or create singleton CFO auditor"""
    global _cfo_auditor
    if _cfo_auditor is None:
        _cfo_auditor = CFOAuditor()
    return _cfo_auditor

def log_session(gate_pass: bool, trade_plan: Optional[Dict],
               backtest_result: Optional[Dict]) -> Dict:
    """Log session verdict"""
    return get_cfo_auditor().log_session(gate_pass, trade_plan, backtest_result)
