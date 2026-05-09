"""Trading Analyst Tests — TA-01 through TA-15.

Engine-only, deterministic, no LLM calls.
Validates trade execution against PM strategy spec.
"""

import os
import sys
from datetime import datetime, timezone, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================
# Sample PM Strategy Spec (reference)
# ============================================================

SAMPLE_SPEC = {
    "type": "IRON_FLY",
    "strikes": [24100, 24200, 24500, 24800],
    "wings": 300,
    "lots": 1,
    "sl": 3500,
    "tsl": 250,
    "entry_window": {"start": "10:30", "end": "11:30"},
    "indicators": {"vix_max": 20.0, "vix_min": 10.0},
    "broker": "shoonya",
}

SAMPLE_TRADE = {
    "trade_id": "T20260512-001",
    "type": "IRON_FLY",
    "strikes": [24100, 24200, 24500, 24800],
    "wings": 300,
    "lots": 1,
    "sl": 3500,
    "tsl": 250,
    "entry_price": 245.5,
    "entry_time": "2026-05-12T10:35:00+05:30",
    "broker": "shoonya",
    "fees": 120.0,
    "slippage": 0.5,
}


# ============================================================
# Spec Validation Tests (7 tests)
# ============================================================


def test_TA_01_validate_trade_exact_match():
    """TA-01: Trade matches PM spec exactly — no violations."""
    from tools.ta_tools import validate_trade

    result = validate_trade(SAMPLE_SPEC, SAMPLE_TRADE)
    assert result["valid"] is True, f"Exact match should be valid: {result}"
    assert result["violations"] == [], "No violations expected"


def test_TA_02_validate_trade_wrong_strikes():
    """TA-02: Trade has different strikes than spec — CRITICAL violation."""
    from tools.ta_tools import validate_trade

    bad_trade = {**SAMPLE_TRADE, "strikes": [24100, 24250, 24500, 24800]}
    result = validate_trade(SAMPLE_SPEC, bad_trade)
    assert result["valid"] is False, "Wrong strikes should invalidate"
    assert any(v["field"] == "strikes" for v in result["violations"])
    strike_v = next(v for v in result["violations"] if v["field"] == "strikes")
    assert strike_v["severity"] == "CRITICAL"


def test_TA_03_validate_trade_wrong_lots():
    """TA-03: Trade uses 2 lots, spec says 1 — CRITICAL."""
    from tools.ta_tools import validate_trade

    bad_trade = {**SAMPLE_TRADE, "lots": 2}
    result = validate_trade(SAMPLE_SPEC, bad_trade)
    assert result["valid"] is False
    lot_v = next(v for v in result["violations"] if v["field"] == "lots")
    assert lot_v["expected"] == 1
    assert lot_v["actual"] == 2


def test_TA_04_validate_trade_wrong_sl():
    """TA-04: SL = 2000 instead of 3500 — CRITICAL."""
    from tools.ta_tools import validate_trade

    bad_trade = {**SAMPLE_TRADE, "sl": 2000}
    result = validate_trade(SAMPLE_SPEC, bad_trade)
    assert result["valid"] is False
    sl_v = next(v for v in result["violations"] if v["field"] == "sl")
    assert sl_v["expected"] == 3500
    assert sl_v["actual"] == 2000


def test_TA_05_validate_trade_wrong_type():
    """TA-05: Credit Spread instead of Iron Fly — CRITICAL."""
    from tools.ta_tools import validate_trade

    bad_trade = {**SAMPLE_TRADE, "type": "CREDIT_SPREAD"}
    result = validate_trade(SAMPLE_SPEC, bad_trade)
    assert result["valid"] is False
    assert any(v["field"] == "type" for v in result["violations"])


def test_TA_06_validate_trade_missing_field():
    """TA-06: Trade missing TSL field — violation."""
    from tools.ta_tools import validate_trade

    bad_trade = {k: v for k, v in SAMPLE_TRADE.items() if k != "tsl"}
    result = validate_trade(SAMPLE_SPEC, bad_trade)
    assert result["valid"] is False
    assert any(v["field"] == "tsl" for v in result["violations"])


def test_TA_07_validate_multiple_violations():
    """TA-07: Trade with wrong strikes AND wrong lots — all violations reported."""
    from tools.ta_tools import validate_trade

    bad_trade = {**SAMPLE_TRADE, "strikes": [24000, 24100, 24400, 24800], "lots": 3}
    result = validate_trade(SAMPLE_SPEC, bad_trade)
    assert result["valid"] is False
    assert len(result["violations"]) >= 2, (
        f"Expected 2+ violations: {result['violations']}"
    )


# ============================================================
# Slippage Tests (2 tests)
# ============================================================


def test_TA_08_slippage_within_tolerance():
    """TA-08: 5 point slippage within 50 point tolerance — ok."""
    from tools.ta_tools import check_slippage

    result = check_slippage(expected_strike=24500, actual_fill=24505, tolerance=50)
    assert result["ok"] is True, f"5 pt slippage should be ok: {result}"
    assert result["slippage"] == 5


def test_TA_09_slippage_exceeds_tolerance():
    """TA-09: 75 point slippage exceeds 50 point tolerance — flagged."""
    from tools.ta_tools import check_slippage

    result = check_slippage(expected_strike=24500, actual_fill=24575, tolerance=50)
    assert result["ok"] is False, "75 pt slippage should be flagged"
    assert result["slippage"] == 75
    assert "evidence" in result


# ============================================================
# Duplicate Detection Tests (2 tests)
# ============================================================


def test_TA_10_no_duplicate_detected():
    """TA-10: Unique trade in session — no duplicates."""
    from tools.ta_tools import detect_duplicate

    session_trades = [
        {
            "trade_id": "T20260512-001",
            "strikes": [24100, 24200, 24500, 24800],
            "lots": 1,
        },
    ]
    result = detect_duplicate(SAMPLE_TRADE, session_trades)
    assert result["duplicate"] is False, f"Should not be duplicate: {result}"


def test_TA_11_duplicate_detected():
    """TA-11: Same strikes + type + lots in session — duplicate flagged."""
    from tools.ta_tools import detect_duplicate

    session_trades = [
        {
            "trade_id": "T20260512-001",
            "type": "IRON_FLY",
            "strikes": [24100, 24200, 24500, 24800],
            "lots": 1,
        },
    ]
    dup_trade = {**SAMPLE_TRADE, "trade_id": "T20260512-002"}
    result = detect_duplicate(dup_trade, session_trades)
    assert result["duplicate"] is True, f"Should detect duplicate: {result}"
    assert result["matched_with"] == "T20260512-001"


# ============================================================
# Reporting Tests (2 tests)
# ============================================================


def test_TA_12_compliance_report():
    """TA-12: Compliance report generated with violations."""
    from tools.ta_tools import generate_compliance_report

    violations = [
        {"field": "lots", "expected": 1, "actual": 2, "severity": "CRITICAL"},
        {"field": "sl", "expected": 3500, "actual": 2000, "severity": "CRITICAL"},
    ]
    report = generate_compliance_report("T20260512-001", SAMPLE_SPEC, violations)
    assert "COMPLIANCE" in report["title"].upper()
    assert len(report["violations"]) == 2
    assert "accuracy" in report
    assert report["accuracy"] == pytest.approx(0.714, 0.01)  # 5/7 fields matched
    assert "text" in report, "Must include human-readable text"


def test_TA_13_execution_ledger():
    """TA-13: Execution ledger with P&L + broker + fees for AM."""
    from tools.ta_tools import generate_execution_ledger

    trades = [
        {**SAMPLE_TRADE, "pnl": 850, "fees": 120, "slippage": 5},
    ]
    ledger = generate_execution_ledger(trades, session="2026-05-12")
    assert ledger["session"] == "2026-05-12"
    assert ledger["total_pnl"] == 850
    assert ledger["total_fees"] == 120
    assert len(ledger["trades"]) == 1


# ============================================================
# Integration Tests (2 tests)
# ============================================================


def test_TA_14_full_validation_pipeline():
    """TA-14: Full flow — validate → slippage → duplicate → report."""
    from tools.ta_tools import (
        validate_trade,
        check_slippage,
        detect_duplicate,
        generate_compliance_report,
    )

    # Validate
    result = validate_trade(SAMPLE_SPEC, SAMPLE_TRADE)
    assert result["valid"], "Clean trade should be valid"

    # Slippage check on each strike
    for strike in SAMPLE_TRADE["strikes"]:
        slip = check_slippage(strike, strike + 5, 50)
        assert slip["ok"], f"Slippage on {strike} should be ok"

    # Duplicate check
    dup = detect_duplicate(SAMPLE_TRADE, [])
    assert not dup["duplicate"]

    # Compliance (all pass, no violations)
    report = generate_compliance_report("T20260512-001", SAMPLE_SPEC, [])
    assert report["accuracy"] == 1.0


def test_TA_15_full_violation_flow():
    """TA-15: Trade with multiple violations — full reporting chain."""
    from tools.ta_tools import (
        validate_trade,
        generate_compliance_report,
        generate_execution_ledger,
    )

    bad_trade = {
        **SAMPLE_TRADE,
        "lots": 3,
        "strikes": [24100, 24300, 24500, 24800],
        "sl": 1000,
    }

    result = validate_trade(SAMPLE_SPEC, bad_trade)
    assert not result["valid"]
    assert len(result["violations"]) >= 3

    report = generate_compliance_report(
        "T20260512-002", SAMPLE_SPEC, result["violations"]
    )
    assert report["accuracy"] == pytest.approx(0.571, 0.01)  # 4/7 fields matched
    assert len(report["violations"]) == len(result["violations"])

    ledger = generate_execution_ledger([bad_trade], "2026-05-12")
    assert len(ledger["trades"]) == 1
