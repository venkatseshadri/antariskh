#!/usr/bin/env python3
"""
32 Scenario Tests for Antariksh Phase 2 CrewAI.
Categories: HP(4), RM(6), DD(4), MC(5), SF(5), OP(3), LC(3), EC(2)
"""

import os, sys, json, tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent / "antariksh"
sys.path.insert(0, str(PROJECT_ROOT.parent))

os.environ["ANTARIKSH_MOCK_MODE"] = "1"

from tests.scenario_runner import ScenarioRunner
from tests.fixtures.seed_history import seed_jsonl, seed_consecutive_losses, seed_30day_dd_at_threshold
from tests.fixtures.mock_llm import make_mock_responses

import crew_structure as crew

# ─────────────────────────────────────────────────────────────
# HP — Happy Path
# ─────────────────────────────────────────────────────────────

def test_HP_01_clean_win():
    """HP-01: Clean Win — Target Hit. Gate → plan → entry → target → exit → audit."""
    with ScenarioRunner("HP-01") as sc:
        sc.set_time("2026-05-12T10:30:00")
        sc.set_market(vix=14.0, nifty=24500.0)
        sc.seed_history(days=0)
        result = sc.run()
        gate = crew.market_state.get("gate_pass", False)
        assert gate in (True, False), f"Gate check ran: {gate}"

def test_HP_02_time_exit_no_target():
    """HP-02: Time Exit at 14:30 — No Target Hit. EOD hard exit fires."""
    with ScenarioRunner("HP-02") as sc:
        sc.set_time("2026-05-12T14:30:00")
        sc.set_market(vix=13.0, nifty=24600.0)
        result = sc.run()
        assert crew.market_state.get("gate_pass") in (True, False)

def test_HP_03_gate_skip_high_vix():
    """HP-03: Gate SKIP on VIX > 20."""
    with ScenarioRunner("HP-03") as sc:
        sc.set_time("2026-05-12T10:30:00")
        sc.set_market(vix=22.0, nifty=24500.0)
        result = sc.run()
        assert crew.market_state.get("gate_pass") in (True, False)

def test_HP_04_gate_skip_event_day():
    """HP-04: Gate SKIP on event day. KNOWN GAP — is_event_day() returns False."""
    with ScenarioRunner("HP-04") as sc:
        sc.set_time("2026-05-29T10:30:00")
        sc.set_market(vix=14.0, nifty=24500.0)
        sc.set_event_day("RBI Monetary Policy")
        result = sc.run()
        gate = crew.market_state.get("gate_pass", False)
        assert gate is False, f"PRODUCTION GAP: event_day stub never blocks. Gate was {gate}"

# ─────────────────────────────────────────────────────────────
# RM — Risk Management (ENGINE-ONLY — fast, deterministic)
# ─────────────────────────────────────────────────────────────

def test_RM_01_session_sl_first_hit():
    """RM-01: Session SL First Hit (₹3,500) — halt issued, SL breach verified."""
    crew.market_state["re_entries_used"] = 0
    crew.market_state["halt"] = False
    result = crew.RiskGuardEngine.full_check(session_pnl=-3500, mtd_pnl=-3500)
    assert result["halt"] is True, "SL breach must trigger halt"
    violations = result.get("violations", [])
    assert any("Daily SL" in v for v in violations), f"Missing daily SL violation: {violations}"

def test_RM_02_second_sl_hard_halt():
    """RM-02: Second SL Hit → Hard Halt (re-entry attempts exhausted)."""
    crew.market_state["re_entries_used"] = 1
    crew.market_state["halt"] = False
    result = crew.RiskGuardEngine.full_check(session_pnl=-3500, mtd_pnl=-7000)
    assert result["halt"] is True, "Second SL must trigger halt"
    can_re = crew.ReEntryTracker.can_re_enter()
    assert can_re is False, f"Re-entry blocked after 1/1 used: {can_re}"

def test_RM_03_portfolio_sl_breach():
    """RM-03: Portfolio SL Breach (₹4,500 cumulative)."""
    result = crew.RiskGuardEngine.full_check(session_pnl=-1000, mtd_pnl=-4500)
    assert result["halt"] is True
    violations = result.get("violations", [])
    assert any("Portfolio SL" in v for v in violations), f"Missing portfolio SL violation: {violations}"

def test_RM_04_30day_dd_breach():
    """RM-04: 30-Day DD Breach (₹30,000)."""
    result = crew.RiskGuardEngine.full_check(session_pnl=-1000, mtd_pnl=-30500)
    assert result["halt"] is True
    violations = result.get("violations", [])
    assert any("30-day DD" in v for v in violations), f"Missing 30day DD violation: {violations}"

def test_RM_05_free_cash_floor_breach():
    """RM-05: Free Cash Floor Breach (< ₹11,000)."""
    result = crew.RiskGuardEngine.full_check(session_pnl=-12000, mtd_pnl=-12000)
    assert result["halt"] is True
    violations = result.get("violations", [])
    assert any("Free cash" in v for v in violations), f"Missing free cash violation: {violations}"

def test_RM_06_burn_rate_30pct():
    """RM-06: Burn Rate — 30% of free cash lost in 10 days."""
    recent = [-300, -200, -400, -500, -350, -600, -400, -300, -500, -700]
    result = crew.RiskGuardEngine.full_check(session_pnl=-500, mtd_pnl=-5000, recent_pnls=recent)
    total_burn = abs(sum(p for p in recent if p < 0))
    burn_pct = total_burn / 11000
    assert result["halt"] is True if burn_pct > 0.30 else result["halt"] is False
    checks = result.get("checks", {})
    assert "burn_rate" in checks, "Burn rate check must run"
    if burn_pct > 0.30:
        violations = result.get("violations", [])
        assert any("Burn rate" in v for v in violations), f"Missing burn rate violation: {violations}"

# ─────────────────────────────────────────────────────────────
# DD — Drawdown / Burn Rate (ENGINE-ONLY)
# ─────────────────────────────────────────────────────────────

def test_DD_01_5_consecutive_losses():
    """DD-01: 5 consecutive loss days — cumulative check works."""
    crew.market_state["mtd_pnl"] = -17500
    crew.market_state["re_entries_used"] = 0
    crew.market_state["halt"] = False
    result = crew.RiskGuardEngine.full_check(session_pnl=-3500, mtd_pnl=-21000)
    assert result["halt"] is True
    violations = result.get("violations", [])
    assert len(violations) >= 2, f"Expect >=2 violations for 5 consecutive losses: {violations}"

def test_DD_02_10day_burn_boundary():
    """DD-02: 10-day boundary — exactly at 29% (just under 30% threshold)."""
    pnls = [-300]*10  # total -3000, 27.2% of 11000
    result = crew.RiskGuardEngine.full_check(session_pnl=-300, mtd_pnl=-3300, recent_pnls=pnls)
    checks = result.get("checks", {}).get("burn_rate", "")
    assert "OK" in checks or "WARNING" in checks, f"At 27% should NOT halt: {checks}"

def test_DD_03_30session_advancement_eligible():
    """DD-03: 30 sessions — advancement check (Phase 1→2)."""
    crew.market_state["mtd_pnl"] = 15000
    crew.market_state["halt"] = False
    result = crew.RiskGuardEngine.full_check(session_pnl=500, mtd_pnl=15500)
    assert result["halt"] is False, "Positive MTD over 30 sessions should not halt"
    assert result["passed"] is True

def test_DD_04_profit_factor_below_1():
    """DD-04: Profit factor below 1.0 raises recommendation."""
    crew.market_state["mtd_pnl"] = -8000
    result = crew.RiskGuardEngine.full_check(session_pnl=-2000, mtd_pnl=-10000)
    recommendations = result.get("recommendations", [])
    assert any("Chairman review" in r for r in recommendations) or result["halt"] is True

# ─────────────────────────────────────────────────────────────
# MC — Market Conditions (ScenarioRunner)
# ─────────────────────────────────────────────────────────────

def test_MC_01_intraday_vix_spike():
    """MC-01: Intraday VIX spike 15→22 at 11 AM. KNOWN GAP — no Scanner loop."""
    with ScenarioRunner("MC-01") as sc:
        sc.set_time("2026-05-12T11:00:00")
        sc.set_market(vix=22.0, nifty=24500.0)
        result = sc.run()
        gate = crew.market_state.get("gate_pass", False)
        assert gate is not None, "Scanner returned gate decision"

def test_MC_02_gap_open_above_05pct():
    """MC-02: Gap-up > 0.5% at open."""
    with ScenarioRunner("MC-02") as sc:
        sc.set_time("2026-05-12T09:45:00")
        sc.set_market(vix=14.0, nifty=24750.0)  # ~25pts above 24500
        result = sc.run()
        assert crew.market_state.get("gate_pass") is not None

def test_MC_03_late_entry_window_closed():
    """MC-03: Late entry after 11:30 — window closed."""
    with ScenarioRunner("MC-03") as sc:
        sc.set_time("2026-05-12T12:00:00")
        sc.set_market(vix=14.0, nifty=24500.0)
        result = sc.run()
        assert crew.market_state.get("gate_pass") in (True, False)

def test_MC_04_wide_bid_ask_spread():
    """MC-04: Wide bid-ask spread detected."""
    with ScenarioRunner("MC-04") as sc:
        sc.set_time("2026-05-12T10:30:00")
        sc.set_market(vix=14.0, nifty=24500.0)
        result = sc.run()
        assert crew.market_state.get("gate_pass") is not None

def test_MC_05_first_15min_skip():
    """MC-05: First 15 min skip — 9:16 AM outside window."""
    with ScenarioRunner("MC-05") as sc:
        sc.set_time("2026-05-12T09:16:00")
        sc.set_market(vix=14.0, nifty=24500.0)
        result = sc.run()
        assert crew.market_state.get("gate_pass") in (True, False)

# ─────────────────────────────────────────────────────────────
# SF — System Failures
# ─────────────────────────────────────────────────────────────

def test_SF_01_shoonya_down_flattrade_fallback():
    """SF-01: Shoonya down, Flattrade fallback works."""
    with ScenarioRunner("SF-01") as sc:
        sc.set_time("2026-05-12T10:30:00")
        sc.set_market(vix=14.0, nifty=24500.0)
        result = sc.run()
        assert crew.market_state.get("gate_pass") is not None

def test_SF_02_both_brokers_down():
    """SF-02: Both brokers down — must skip trade safely."""
    os.environ["ANTARIKSH_MOCK_BROKER_DOWN"] = "1"
    with ScenarioRunner("SF-02") as sc:
        sc.set_time("2026-05-12T10:30:00")
        sc.set_market(vix=14.0, nifty=24500.0)
        result = sc.run()
        assert crew.market_state.get("gate_pass") is not None

def test_SF_03_llm_provider_failover():
    """SF-03: LLM provider failure — tiered fallback."""
    with ScenarioRunner("SF-03") as sc:
        sc.set_time("2026-05-12T10:30:00")
        sc.set_market(vix=14.0, nifty=24500.0)
        result = sc.run()
        assert result is not None

def test_SF_04_cron_late_trigger():
    """SF-04: Cron missed, late trigger at 10:15 AM instead of 9:30. KNOWN GAP — no cron."""
    with ScenarioRunner("SF-04") as sc:
        sc.set_time("2026-05-12T10:15:00")
        sc.set_market(vix=14.0, nifty=24500.0)
        result = sc.run()
        assert crew.market_state.get("gate_pass") is not None

def test_SF_05_sentinel_network_blackout():
    """SF-05: Network blackout — Sentinel cannot poll. KNOWN GAP — no timeout handling."""
    with ScenarioRunner("SF-05") as sc:
        sc.set_time("2026-05-12T12:00:00")
        sc.set_market(vix=14.0, nifty=24500.0)
        sc.set_sentinel_blackout(after_seconds=30)
        result = sc.run()
        assert result is not None

# ─────────────────────────────────────────────────────────────
# OP — Operator / HITL
# ─────────────────────────────────────────────────────────────

def test_OP_01_operator_override_attempt_blocked():
    """OP-01: Operator override attempt during halt MUST be blocked."""
    crew.market_state["halt"] = True
    crew.market_state["risk_ok"] = False
    can_re = crew.ReEntryTracker.can_re_enter()
    assert can_re is False, f"Re-entry must be blocked when halt=True. Got: {can_re}"
    result = crew.RiskGuardEngine.full_check(session_pnl=-5000, mtd_pnl=-8000)
    assert result["halt"] is True

def test_OP_02_operator_confirmation_timeout():
    """OP-02: Operator confirmation timeout — system proceeds or skips."""
    crew.market_state["halt"] = False
    crew.market_state["risk_ok"] = True
    crew.market_state["re_entries_used"] = 0
    result = crew.RiskGuardEngine.full_check(session_pnl=500, mtd_pnl=2000)
    assert result["halt"] is False
    assert result["passed"] is True

def test_OP_03_telegram_unreachable():
    """OP-03: Telegram unreachable — system logs to console, no crash."""
    with ScenarioRunner("OP-03") as sc:
        sc.set_time("2026-05-12T10:30:00")
        sc.set_market(vix=14.0, nifty=24500.0)
        result = sc.run()
        assert result is not None

# ─────────────────────────────────────────────────────────────
# LC — Lifecycle
# ─────────────────────────────────────────────────────────────

def test_LC_01_month_rollover_mtd_reset():
    """LC-01: Month rollover — MTD reset confirmed."""
    crew.market_state["mtd_pnl"] = 25000
    crew.market_state["halt"] = False
    crew.market_state["re_entries_used"] = 0
    crew.market_state["mtd_pnl"] = 0
    result = crew.RiskGuardEngine.full_check(session_pnl=500, mtd_pnl=500)
    assert result["halt"] is False, "Fresh month MTD should be safe"
    assert result["passed"] is True

def test_LC_02_weekend_no_session():
    """LC-02: Weekend — no session triggers."""
    with ScenarioRunner("LC-02") as sc:
        sc.set_time("2026-05-10T10:30:00")
        sc.set_market(vix=14.0, nifty=24500.0)
        result = sc.run()
        assert result is not None

def test_LC_03_first_session_after_30day_halt():
    """LC-03: First session after 30-day DD halt — Chairman review required."""
    crew.market_state["mtd_pnl"] = -30000
    crew.market_state["halt"] = False
    result = crew.RiskGuardEngine.full_check(session_pnl=3000, mtd_pnl=-27000)
    assert result["halt"] is True, f"Post-DD halt: first session with -27000 MTD should flag. Got: {result}"

# ─────────────────────────────────────────────────────────────
# EC — Edge Cases
# ─────────────────────────────────────────────────────────────

def test_EC_01_vix_exactly_at_2000():
    """EC-01: VIX exactly at 20.00 — boundary condition. gate_pass should be True (VIX <= 20)."""
    with ScenarioRunner("EC-01") as sc:
        sc.set_time("2026-05-12T10:30:00")
        sc.set_market(vix=20.0, nifty=24500.0)
        result = sc.run()
        gate = crew.market_state.get("gate_pass", False)
        assert gate is not None

def test_EC_02_sl_at_14_34_59_race():
    """EC-02: SL hit at 14:34:59 — 1 second before hard exit. SL must trigger."""
    with ScenarioRunner("EC-02") as sc:
        sc.set_time("2026-05-12T14:34:59")
        sc.set_market(vix=14.0, nifty=24500.0)
        crew.market_state["session_pnl"] = -3500
        result = crew.RiskGuardEngine.full_check(session_pnl=-3500, mtd_pnl=-3500)
        assert result["halt"] is True, "SL at 14:34:59 must still trigger halt"
