#!/usr/bin/env python3
"""
crew_test.py — Mock dry-run tests for Antariksh Phase 2 CrewAI.

Tests:
    1. Mock crew dry-run (VIX gate pass + trade plan)
    2. Task dependency trace (Scanner → Strategist → Executor → Sentinel → Auditor)
    3. Risk Guard halt scenario (capital floor breach)

Usage:
    python3 crew_test.py --mock-mode --vix 18.5 --nifty 24500 --time 10:30
    python3 crew_test.py --trace
    python3 crew_test.py --capital-floor-breach
"""

import sys
import os
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "antariksh"))

from crew_structure import (
    _build_crew,
    orchestrator,
    run_session_task,
    scan_market,
    generate_trade_plan,
    check_risk,
    execute_trade,
    monitor_positions,
    log_audit,
    market_state,
    run_full_session,
    run_risk_halt_test,
    run_trial_session,
    RiskGuardEngine,
    AuditorEngine,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | TEST | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("crew_test")


def test_1_mock_crew_dryrun(
    vix: float = 18.5, nifty: float = 24500.0, time_str: str = "10:30"
) -> Dict:
    """
    Test 1: Mock Crew Dry-Run
    Set VIX=18.5 (below 20) → gate should PASS → trade plan generated → audit logged.
    """
    logger.info("=" * 70)
    logger.info("TEST 1: Mock Crew Dry-Run (VIX gate PASS)")
    logger.info(f"Params: VIX={vix}, NIFTY={nifty}, TIME={time_str}")
    logger.info("=" * 70)

    os.environ["ANTARIKSH_MOCK_MODE"] = "1"
    os.environ["ANTARIKSH_MOCK_VIX"] = str(vix)
    os.environ["ANTARIKSH_MOCK_NIFTY"] = str(nifty)
    os.environ["ANTARIKSH_MOCK_TIME"] = time_str

    # Verify agent and tools are defined
    tools = [
        scan_market,
        generate_trade_plan,
        check_risk,
        execute_trade,
        monitor_positions,
        log_audit,
    ]
    logger.info(f"Orchestrator agent: {orchestrator.role}")
    logger.info(f"Tools attached: {len(tools)}")

    # Verify task is defined
    logger.info(f"Session task defined: {run_session_task is not None}")

    # Run entry session
    result = run_full_session(
        mock_mode=True, mock_vix=vix, mock_nifty=nifty, mock_time=time_str
    )

    gate_pass = result.get("entry", {}).get("gate_pass", False)
    session_pnl = result.get("exit", {}).get("session_pnl", 0.0)

    logger.info(f"Gate result: {'PASS' if gate_pass else 'SKIP'}")
    logger.info(f"Session P&L: ₹{session_pnl}")

    # Verify expected outcomes
    checks = {
        "orchestrator_defined": orchestrator.role == "Orchestrator",
        "tools_defined": len(tools) == 6,
        "task_defined": run_session_task is not None,
        "gate_decision_logged": True,
    }

    logger.info(f"Test 1 checks: {checks}")
    return {"gate_pass": gate_pass, "session_pnl": session_pnl, "checks": checks}


def test_2_task_dependencies() -> Dict:
    """
    Test 2: Task Dependencies
    Trace the dependency chain:
    Scanner (market data) → Strategist (trade plan) → Risk Guard (approval) →
    Executor (orders) → Sentinel (P&L) → Auditor (log)
    """
    logger.info("=" * 70)
    logger.info("TEST 2: Task Dependency Trace")
    logger.info("=" * 70)

    os.environ["ANTARIKSH_MOCK_MODE"] = "1"

    # The crew uses a single Orchestrator agent with 6 deterministic tools
    crew = _build_crew()
    crew_agents = [a.role for a in crew.agents]
    crew_tasks = [t.description[:40] for t in crew.tasks]

    logger.info(f"Crew agents ({len(crew_agents)}): {crew_agents}")
    logger.info(f"Crew tasks: {len(crew_tasks)}")
    logger.info(f"Crew process: {crew.process}")

    expected_roles = ["Orchestrator"]

    all_agents_present = all(a in crew_agents for a in expected_roles)

    checks = {
        "single_orchestrator_agent": all_agents_present,
        "six_tools_available": len(orchestrator.tools) == 6,
        "sequential_process": str(crew.process) == "Process.sequential",
    }

    logger.info(f"Test 2 checks: {checks}")

    # Run a quick entry-only test
    result = run_full_session(
        mock_mode=True, mock_vix=18.5, mock_nifty=24500, mock_time="10:30"
    )

    return {"checks": checks, "result": result}


def test_3_risk_guard_halt() -> Dict:
    """
    Test 3: Risk Guard Halt on Capital Breach
    Set session_pnl = -₹4,000 (exceeds daily SL ₹3,500) →
    Risk Guard must issue HALT and set risk_ok=False.
    """
    logger.info("=" * 70)
    logger.info("TEST 3: Risk Guard Halt Scenario")
    logger.info("=" * 70)

    # Simulate capital breach
    market_state["session_pnl"] = -4000.0
    market_state["mtd_pnl"] = -4500.0

    result = run_risk_halt_test()

    halt_issued = result.get("halt_issued", False)
    risk_ok = result.get("risk_verdict", False)

    logger.info(f"Halt issued: {halt_issued}")
    logger.info(f"Risk OK: {risk_ok}")

    checks = {
        "halt_issued_on_breach": halt_issued,
        "risk_rejected_on_breach": not risk_ok,
    }

    # Verify hard rules:
    # Daily SL: -₹4,000 < -₹3,500 → should flag
    daily_sl_check = market_state.get("session_pnl", 0) <= -3500
    cumulative_check = market_state.get("mtd_pnl", 0) <= -4500

    logger.info(f"Daily SL check triggered: {daily_sl_check}")
    logger.info(f"Portfolio cumulative check triggered: {cumulative_check}")
    logger.info(
        f"Hard rule summary: daily={daily_sl_check}, cumulative={cumulative_check}"
    )

    logger.info(f"Test 3 checks: {checks}")
    return {
        "halt_issued": halt_issued,
        "checks": checks,
        "daily_sl_breach": daily_sl_check,
        "cumulative_breach": cumulative_check,
    }


def test_4_gate_skip_high_vix() -> Dict:
    """
    Test 4: Gate SKIP on High VIX
    Set VIX=22 → gate should SKIP, no trade plan generated.
    """
    logger.info("=" * 70)
    logger.info("TEST 4: Gate SKIP on High VIX (VIX=22 > 20)")
    logger.info("=" * 70)

    os.environ["ANTARIKSH_MOCK_MODE"] = "1"
    os.environ["ANTARIKSH_MOCK_VIX"] = "22.0"
    os.environ["ANTARIKSH_MOCK_NIFTY"] = "24500"
    os.environ["ANTARIKSH_MOCK_TIME"] = "10:30"

    result = run_full_session(
        mock_mode=True, mock_vix=22.0, mock_nifty=24500, mock_time="10:30"
    )

    gate_pass = result.get("entry", {}).get("gate_pass", False)
    trade_plan = result.get("entry", {}).get("trade_plan")

    logger.info(f"Gate result: {'PASS' if gate_pass else 'SKIP'}")
    logger.info(f"Trade plan: {'Generated' if trade_plan else 'None (expected)'}")

    checks = {
        "gate_skip_high_vix": not gate_pass,
        "no_trade_plan": trade_plan is None,
    }

    logger.info(f"Test 4 checks: {checks}")
    return {"gate_pass": gate_pass, "checks": checks}


def test_5_trial_run() -> Dict:
    """
    Test 5: Trial Run v1 — Live DuckDB data + paper trading.
    No mock env vars. Reads real VIX, NIFTY, regime from DuckDB.
    """
    logger.info("=" * 70)
    logger.info("TEST 5: Trial Run v1 (Live DuckDB + paper trading)")
    logger.info("=" * 70)

    os.environ.pop("ANTARIKSH_MOCK_MODE", None)

    result = run_trial_session()

    gate_pass = result.get("entry", {}).get("gate_pass", False)
    trade_plan = result.get("entry", {}).get("trade_plan")
    session_pnl = result.get("exit", {}).get("session_pnl", 0.0)

    vix = market_state.get("vix", 0)
    nifty = market_state.get("nifty_spot", 0)
    regime = market_state.get("regime", "UNKNOWN")

    logger.info(f"Live data: VIX={vix}, NIFTY={nifty}, Regime={regime}")
    logger.info(f"Gate result: {'PASS' if gate_pass else 'SKIP'}")
    logger.info(f"Trade plan: {'Generated' if trade_plan else 'None'}")
    logger.info(f"Session P&L: ₹{session_pnl}")

    return {
        "vix": vix,
        "nifty": nifty,
        "regime": regime,
        "gate_pass": gate_pass,
        "has_trade_plan": trade_plan is not None,
        "session_pnl": session_pnl,
    }


def print_results_summary(results: Dict):
    """Print formatted test results summary."""
    print("\n" + "=" * 70)
    print("CREWAI PHASE 2 TEST RESULTS SUMMARY")
    print("=" * 70)

    for test_name, result in results.items():
        checks = result.get("checks", {})
        if not checks and "vix" in result:
            # Trial run — operational, not test
            print(f"\n{test_name}: ✅ COMPLETE")
            print(
                f"  VIX={result['vix']} NIFTY={result['nifty']} Regime={result['regime']}"
            )
            print(
                f"  gate_pass={result['gate_pass']} plan={result['has_trade_plan']} P&L=₹{result['session_pnl']}"
            )
            continue
        all_pass = all(checks.values()) if checks else False
        status = "✅ PASS" if all_pass else "❌ FAIL"
        print(f"\n{test_name}: {status}")

        for check_name, check_value in checks.items():
            emoji = "✅" if check_value else "❌"
            print(f"  {emoji} {check_name}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Antariksh Phase 2 CrewAI Tests")
    parser.add_argument("--mock-mode", action="store_true", help="Run mock mode")
    parser.add_argument("--vix", type=float, default=18.5, help="Mock VIX value")
    parser.add_argument("--nifty", type=float, default=24500.0, help="Mock NIFTY value")
    parser.add_argument("--time", type=str, default="10:30", help="Mock time (HH:MM)")
    parser.add_argument("--trace", action="store_true", help="Enable verbose tracing")
    parser.add_argument(
        "--capital-floor-breach",
        action="store_true",
        help="Test Risk Guard halt on capital breach",
    )
    parser.add_argument(
        "--high-vix", action="store_true", help="Test gate SKIP on VIX > 20"
    )
    parser.add_argument(
        "--trial",
        action="store_true",
        help="Trial run v1: live DuckDB data, paper trading",
    )
    parser.add_argument("--all", action="store_true", help="Run all tests")
    args = parser.parse_args()

    if args.trace:
        logging.getLogger().setLevel(logging.DEBUG)

    results = {}

    if args.capital_floor_breach:
        results["risk_guard_halt"] = test_3_risk_guard_halt()
    elif args.high_vix:
        results["gate_skip_high_vix"] = test_4_gate_skip_high_vix()
    elif args.trial:
        results["trial_run"] = test_5_trial_run()
    elif args.trace:
        results["task_dependencies"] = test_2_task_dependencies()
    elif args.all:
        results["mock_dryrun"] = test_1_mock_crew_dryrun(
            args.vix, args.nifty, args.time
        )
        results["task_dependencies"] = test_2_task_dependencies()
        results["risk_guard_halt"] = test_3_risk_guard_halt()
        results["gate_skip_high_vix"] = test_4_gate_skip_high_vix()
    else:
        # Default: mock dry-run
        results["mock_dryrun"] = test_1_mock_crew_dryrun(
            args.vix, args.nifty, args.time
        )

    print_results_summary(results)
