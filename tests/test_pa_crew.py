"""Post-Mortem Analyst Tests — PA-01 through PA-14.

Engine-only, deterministic. Reviews trades, runs counterfactuals, recommends PM adjustments.
"""

import os, sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TRADE = {
    "id": "T001",
    "type": "IRON_FLY",
    "lots": 1,
    "strikes": [24100, 24200, 24500, 24800],
    "pnl": 850,
    "entry": 24550,
    "exit": 24800,
    "sl_hit": False,
    "tp_hit": True,
    "entry_time": "10:35",
    "exit_time": "13:20",
}
SPEC_TRADE = TRADE  # same as spec for "matched" test


# Review tests (4)
@pytest.mark.engine
@pytest.mark.pa
def test_PA_01_review_matched_trade():
    from tools.pa_tools import review_trade

    r = review_trade(TRADE, SPEC_TRADE)
    assert r["quality"] == "EXCELLENT", f"Matched trade should be EXCELLENT: {r}"
    assert r["issues"] == []


@pytest.mark.engine
@pytest.mark.pa
def test_PA_02_review_sl_hit_trade():
    from tools.pa_tools import review_trade

    r = review_trade(
        {**TRADE, "pnl": -3500, "sl_hit": True, "tp_hit": False}, SPEC_TRADE
    )
    assert r["quality"] != "EXCELLENT"
    assert any("SL" in i or "sl" in i for i in r["issues"])


@pytest.mark.engine
@pytest.mark.pa
def test_PA_03_review_early_exit():
    from tools.pa_tools import review_trade

    r = review_trade(
        {**TRADE, "pnl": 90, "tp_hit": False, "exit_time": "10:50"}, SPEC_TRADE
    )
    assert any("early" in i.lower() for i in r["issues"]), (
        f"Early exit should be flagged: {r}"
    )


@pytest.mark.engine
@pytest.mark.pa
def test_PA_04_review_overrides():
    """PA-04: Lot override — significant quality drop."""
    from tools.pa_tools import review_trade

    r = review_trade({**TRADE, "lots": 2}, SPEC_TRADE)
    assert "WRONG LOTS" in str(r["issues"]), f"Lot override should be flagged: {r}"
    assert r["score"] < 50, "Lot override should be severely scored"


# Counterfactuals (3)
@pytest.mark.engine
@pytest.mark.pa
def test_PA_05_counterfactual_better_exit():
    from tools.pa_tools import run_counterfactuals

    cf = run_counterfactuals(TRADE, peak_pnl=1200, better_exit=24850)
    assert cf["missed_profit"] >= 0, "Should calculate missed profit"
    assert cf["better_exit"]["price"] == 24850


@pytest.mark.engine
@pytest.mark.pa
def test_PA_06_counterfactual_what_if_pnl():
    from tools.pa_tools import run_counterfactuals

    cf = run_counterfactuals(
        {**TRADE, "sl": 3500, "sl_hit": True, "pnl": -3500},
        peak_pnl=600,
        hypothetical_entry=24500,
    )
    assert cf["scenario"] == "sl_hit"
    assert cf["hypothetical"]["entry"] is not None


@pytest.mark.engine
@pytest.mark.pa
def test_PA_07_counterfactual_no_peaks():
    from tools.pa_tools import run_counterfactuals

    cf = run_counterfactuals(TRADE, peak_pnl=850)
    assert cf["missed_profit"] == 0, "No missed profit if no higher peak"


# Pattern detection (2)
@pytest.mark.engine
@pytest.mark.pa
def test_PA_08_detect_recurring_issues():
    from tools.pa_tools import detect_patterns

    trades = [
        {**TRADE, "sl_hit": True},
        {**TRADE, "sl_hit": True, "id": "T002"},
        {**TRADE, "id": "T003"},
    ]
    patterns = detect_patterns(trades)
    assert patterns["sl_hit_rate"] == pytest.approx(2 / 3, 0.01), "2/3 trades hit SL"


@pytest.mark.engine
@pytest.mark.pa
def test_PA_09_detect_empty():
    from tools.pa_tools import detect_patterns

    patterns = detect_patterns([])
    assert patterns["total_trades"] == 0


# Reporting (2)
@pytest.mark.engine
@pytest.mark.pa
def test_PA_10_post_mortem_report():
    """PA-10: Post-mortem report with quality distribution + recommendations."""
    from tools.pa_tools import (
        review_trade,
        run_counterfactuals,
        detect_patterns,
        generate_post_mortem_report,
    )

    reviews = [review_trade(TRADE, SPEC_TRADE)]
    cfs = [run_counterfactuals(TRADE, peak_pnl=1200, better_exit=24850)]
    patterns = detect_patterns([TRADE])
    report = generate_post_mortem_report(reviews, cfs, patterns, "2026-05-12")
    assert (
        "EXCELLENT" in report["text"].upper() or "excellent" in report["text"].lower()
    )
    assert report["recommendations"] != []


@pytest.mark.engine
@pytest.mark.pa
def test_PA_11_post_mortem_recommendations():
    from tools.pa_tools import (
        review_trade,
        run_counterfactuals,
        detect_patterns,
        generate_post_mortem_report,
    )

    r = review_trade({**TRADE, "sl_hit": True, "pnl": -3500}, SPEC_TRADE)
    cf = run_counterfactuals(
        {**TRADE, "sl_hit": True, "pnl": -3500}, peak_pnl=500, hypothetical_entry=24500
    )
    report = generate_post_mortem_report(
        [r], [cf], detect_patterns([TRADE]), "2026-05-12"
    )
    assert len(report["recommendations"]) >= 1, "SL hit should produce recommendations"


# Integration (3)
@pytest.mark.engine
@pytest.mark.pa
def test_PA_12_full_analysis_flow():
    from tools.pa_tools import (
        review_trade,
        run_counterfactuals,
        detect_patterns,
        generate_post_mortem_report,
    )

    trades = [
        TRADE,
        {**TRADE, "id": "T002", "pnl": -1500, "sl_hit": True, "tp_hit": False},
    ]
    reviews = [review_trade(t, SPEC_TRADE) for t in trades]
    cfs = [
        run_counterfactuals(
            t, peak_pnl=max(0, t["pnl"] + 200), better_exit=t["strikes"][-1] + 50
        )
        for t in trades
    ]
    patterns = detect_patterns(trades)
    report = generate_post_mortem_report(reviews, cfs, patterns, "2026-05-12")
    assert report["trades_reviewed"] == 2
    assert len(report["recommendations"]) > 0


@pytest.mark.engine
@pytest.mark.pa
def test_PA_13_counterfactual_better_sl():
    from tools.pa_tools import run_counterfactuals

    cf = run_counterfactuals(
        {**TRADE, "sl": 3500, "sl_hit": True, "pnl": -3500}, peak_pnl=0, better_sl=2500
    )
    assert cf["better_sl"]["value"] == 2500
    assert cf["hypothetical_sl_pnl"] >= -2500


@pytest.mark.engine
@pytest.mark.pa
def test_PA_14_counterfactual_better_tp():
    from tools.pa_tools import run_counterfactuals

    cf = run_counterfactuals(TRADE, peak_pnl=1200, better_tp=1000)
    assert cf["better_tp"]["value"] == 1000


# ============================================================
# Edge Case / Coverage Tests (3 tests)
# ============================================================


@pytest.mark.engine
@pytest.mark.pa
def test_PA_15_counterfactual_all_params():
    """PA-15: Pass all 5 params (peak, exit, sl, tp, entry) → all returned."""
    from tools.pa_tools import run_counterfactuals

    cf = run_counterfactuals(
        {**TRADE, "sl": 3500, "sl_hit": True, "pnl": -3500},
        peak_pnl=800,
        better_exit=24900,
        better_sl=2500,
        better_tp=1100,
        hypothetical_entry=24500,
    )
    assert cf["peak_pnl"] == 800
    assert cf["better_exit"] is not None
    assert cf["better_exit"]["price"] == 24900
    assert cf["better_sl"] is not None
    assert cf["better_sl"]["value"] == 2500
    assert cf["better_tp"] is not None
    assert cf["better_tp"]["value"] == 1100
    assert cf["hypothetical"]["entry"] is not None
    assert cf["hypothetical"]["entry"]["entry"] == 24500


@pytest.mark.engine
@pytest.mark.pa
def test_PA_16_large_session_pattern_detection():
    """PA-16: 10 trade session — patterns detected."""
    from tools.pa_tools import detect_patterns

    trades = []
    for i in range(10):
        t = {**TRADE, "id": f"T{i + 1:03d}"}
        if i < 4:
            t.update({"sl_hit": True, "pnl": -3500})
        else:
            t.update({"sl_hit": False, "pnl": 850})
        trades.append(t)

    patterns = detect_patterns(trades)
    assert patterns["total_trades"] == 10
    assert patterns["sl_hit_rate"] == pytest.approx(0.4, 0.01)
    assert patterns["average_pnl"] == pytest.approx(-890.0, 0.1)
    assert len(patterns["patterns"]) > 0, "Should detect patterns"


@pytest.mark.engine
@pytest.mark.pa
def test_PA_17_quality_distribution():
    """PA-17: Verify quality_distribution dict in report output."""
    from tools.pa_tools import (
        review_trade,
        run_counterfactuals,
        detect_patterns,
        generate_post_mortem_report,
    )

    reviews = [
        review_trade(TRADE, SPEC_TRADE),
        review_trade({**TRADE, "id": "T002", "sl_hit": True, "pnl": -3500}, SPEC_TRADE),
    ]
    cfs = [run_counterfactuals(TRADE, peak_pnl=1200)]
    patterns = detect_patterns([TRADE])
    report = generate_post_mortem_report(reviews, cfs, patterns, "2026-05-12")
    assert "quality_distribution" in report
    qd = report["quality_distribution"]
    assert isinstance(qd, dict)
    assert sum(qd.values()) == 2, f"Should sum to 2 trades: {qd}"
