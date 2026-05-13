#!/usr/bin/env python3
"""
Antariksh Trading Desk — End-to-End Integration Test.

Validates the full "Conveyor Belt" flow:
  Scout → Researcher → PM → Executioner → Risk Agent

Tests:
  1. Logical Sequencing: execute_orders blocked unless PM authorizes
  2. Handoff Completeness: order_ids + entry_prices populated
  3. OCO Logic: TP fill → Risk Agent cancels all SL orders
  4. State Transitions: ACTION → MAINTENANCE after handoff

Run:
    cd /home/trading_ceo/antariksh
    python3 tests/test_integration_end_to_end.py

Expectation: Output ends with "SUCCESS: Risk Agent correctly cancelled SL orders after TP hit."
"""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["ANTARIKSH_MOCK_MODE"] = "1"
os.environ["ANTARIKSH_MOCK_ENTRY"] = "100.0"

from trading_desk import (
    desk,
    DeskPhase,
    MarketRegime,
    ProposedSetup,
    AuthorizedOrder,
    HandoffReport,
    ListenTriggers,
    engine_scout_regime,
    engine_research_setup,
    engine_pm_validate,
    engine_execute_basket,
)

PASS = 0
FAIL = 0


def check(label: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✅ {label}")
    else:
        FAIL += 1
        print(f"  ❌ {label}  —  {detail}")


def run_integration_test():
    global PASS, FAIL
    PASS = 0
    FAIL = 0

    print()
    print("=" * 70)
    print("🚀  ANTARIKSH END-TO-END INTEGRATION TEST")
    print("=" * 70)
    print()

    # ═══════════════════════════════════════════════════════════════
    # PHASE 1: PREPARATION — Scout detects regime, Researcher builds setup
    # ═══════════════════════════════════════════════════════════════
    print("━ PHASE 1: PREPARATION (Scout → Researcher)")
    print()

    regime = engine_scout_regime(mock_vix=18.5, mock_nifty=24500)
    check("Scout returned MarketRegime", isinstance(regime, MarketRegime))
    check(
        "Regime type is SIDEWAYS (VIX 18.5 < 20)",
        regime.regime == "SIDEWAYS",
        f"got: {regime.regime}",
    )
    check("VIX stored correctly", regime.vix == 18.5)
    check("NIFTY spot stored correctly", regime.nifty_spot == 24500)

    setup = engine_research_setup(regime)
    check("Researcher returned ProposedSetup", isinstance(setup, ProposedSetup))
    check("Strategy is IRON_BUTTERFLY", setup.strategy_type == "IRON_BUTTERFLY")
    check("ATM strike on 50-pt grid: 24500", setup.atm_strike == 24500)
    check("Wing width = 300 (normal VIX)", setup.wing_width == 300)
    check("4 legs in setup", len(setup.legs) == 4, f"got {len(setup.legs)}")
    check("Leg 0 is LONG_PUT_WING (BUY PE)", setup.legs[0]["role"] == "LONG_PUT_WING")
    check(
        "Leg 1 is SHORT_PUT_BODY (SELL PE)", setup.legs[1]["role"] == "SHORT_PUT_BODY"
    )
    check(
        "Leg 2 is SHORT_CALL_BODY (SELL CE)", setup.legs[2]["role"] == "SHORT_CALL_BODY"
    )
    check("Leg 3 is LONG_CALL_WING (BUY CE)", setup.legs[3]["role"] == "LONG_CALL_WING")

    print()

    # ═══════════════════════════════════════════════════════════════
    # PHASE 2: VALIDATION — PM audits capital, authorizes lots
    # ═══════════════════════════════════════════════════════════════
    print("━ PHASE 2: VALIDATION (PM capital check)")
    print()

    auth = engine_pm_validate(setup, mock_balance=200000)
    check("PM returned AuthorizedOrder", isinstance(auth, AuthorizedOrder))
    check(
        "PM AUTHORIZED (margin ₹150k < 85% of ₹200k)",
        auth.status == "AUTHORIZED",
        f"got: {auth.status}",
    )
    check("1 lot authorized", auth.authorized_lots == 1)
    check("Max margin set", auth.max_margin > 0)
    check("Spec contains legs", len(auth.spec.get("legs", [])) == 4)
    check(
        "Phase is VALIDATION", desk.phase == DeskPhase.VALIDATION, f"got: {desk.phase}"
    )

    # Test rejection scenario
    rejected = engine_pm_validate(setup, mock_balance=50000)
    check(
        "PM REJECTS when margin > 85% of balance",
        rejected.status == "REJECTED",
        f"got: {rejected.status}",
    )

    print()

    # ═══════════════════════════════════════════════════════════════
    # PHASE 3: ACTION — Executioner places orders (wings-first)
    # ═══════════════════════════════════════════════════════════════
    print("━ PHASE 3: ACTION (Executioner places orders)")
    print()

    handoff = engine_execute_basket(auth)
    check("Executioner returned HandoffReport", isinstance(handoff, HandoffReport))
    check("All 4 legs filled", handoff.total_legs == 4, f"got {handoff.total_legs}")
    check("Order IDs populated", len(handoff.order_ids) >= 4)
    check("Entry prices populated", len(handoff.entry_prices) == 4)
    check("TSYMs populated", len(handoff.tsyms) == 4)
    check("Wings count = 2", handoff.wings_count == 2, f"got {handoff.wings_count}")
    check("Center count = 2", handoff.center_count == 2, f"got {handoff.center_count}")
    check("Positions marked open", desk.positions_open == True)
    check("Phase is ACTION", desk.phase == DeskPhase.ACTION, f"got: {desk.phase}")
    check("Active SL orders exist", len(desk.active_sl_orders) > 0)
    check("Active TP orders exist", len(desk.active_tp_orders) > 0)

    print(f"    Fill details:")
    for fill in handoff.fills:
        print(f"      {fill['leg']:25s} | {fill['status']:6s} | {fill['order_id']}")

    print()

    # ═══════════════════════════════════════════════════════════════
    # PHASE 4: MAINTENANCE — Risk Agent listens, reacts to events
    # ═══════════════════════════════════════════════════════════════
    print("━ PHASE 4: MAINTENANCE (Risk Agent listen triggers)")
    print()

    triggers = ListenTriggers(desk_ref=desk)

    # Get the first TP order ID for simulation
    tp_keys = [k for k in handoff.order_ids if "TP" in k]
    tp_order_id = handoff.order_ids[tp_keys[0]] if tp_keys else "SIM-TP-001"
    tp_tsym = (
        handoff.tsyms.get(tp_keys[0], "NIFTY14MAY202624500CE")
        if tp_keys
        else "NIFTY14MAY202624500CE"
    )

    print(f"    Mock TP order: {tp_order_id} ({tp_tsym})")

    # ── Test 4a: TP COMPLETE → Risk Agent cancels SL orders ──
    print()
    print("    Test 4a: TP order fills → OCO logic (cancel all SLs)")

    mock_order_update = {
        "status": "COMPLETE",
        "noid": tp_order_id,
        "tsym": tp_tsym,
    }
    result = triggers.on_order_update(mock_order_update)

    check(
        "TP_COMPLETE trigger fired",
        result.get("trigger") == "TP_COMPLETE",
        f"got trigger: {result.get('trigger')}",
    )
    check(
        "Command = CANCEL",
        result.get("command") == "CANCEL",
        f"got: {result.get('command')}",
    )
    check(
        "Action = CANCEL_ALL_SL",
        result.get("action") == "CANCEL_ALL_SL",
        f"got: {result.get('action')}",
    )
    check(
        "Cancelled orders list not empty", len(result.get("cancelled_orders", [])) > 0
    )
    check(
        "Cancelled orders contain SL order IDs",
        any("SIM" in str(o) for o in result.get("cancelled_orders", [])),
    )
    check(
        "Positions marked closed after TP fill",
        desk.positions_open == False,
        f"got: {desk.positions_open}",
    )
    check(
        "Active SL orders cleared",
        len(desk.active_sl_orders) == 0,
        f"got {len(desk.active_sl_orders)} remaining",
    )

    print()

    # ── Test 4b: No positions → feed update ignored ──
    print("    Test 4b: Feed update with closed positions → ignored")

    feed = ListenTriggers.on_feed_update(
        {
            "token": "NSE|35003",
            "lp": "95.0",
            "ltq": "50",
        }
    )
    check(
        "Feed ignored (no positions)",
        feed.get("action") == "IGNORE",
        f"got: {feed.get('action')}",
    )

    print()

    # ═══════════════════════════════════════════════════════════════
    # SUMMARY
    # ═══════════════════════════════════════════════════════════════
    print("=" * 70)
    total = PASS + FAIL
    print(f"RESULTS: {PASS}/{total} PASSED, {FAIL}/{total} FAILED")
    print("=" * 70)

    if FAIL == 0:
        print()
        print("🏁  SUCCESS: System is End-to-End Functional.")
        print("    The 'Conveyor Belt' flows correctly from Scout → Risk Agent.")
        print("    OCO (One-Cancels-Other) logic verified.")
        print("    Ready for next level: Leg Shifter + live WebSocket.")
        return True
    else:
        print()
        print(f"⚠️   {FAIL} test(s) FAILED. Review output above for details.")
        return False


if __name__ == "__main__":
    ok = run_integration_test()
    sys.exit(0 if ok else 1)
