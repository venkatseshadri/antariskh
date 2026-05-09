"""CEO Tests — CEO-01 through CEO-20 (+ GA-01 to GA-15 governance)."""

import os, sys, pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

GOALS = [
    "Don't burn capital",
    "₹36L/year passive income",
    "Systematic intraday options",
]
STRATEGY_OK = {"action": "select IRON_FLY", "reason": "VIX=15, bullish, no event"}
STRATEGY_BAD = {"action": "double lots to 4", "reason": "greed"}


# Alignment (3)
@pytest.mark.engine
@pytest.mark.ceo
def test_CEO_01_alignment_check_pass():
    from tools.ceo_tools import alignment_check

    r = alignment_check(STRATEGY_OK, GOALS)
    assert r["aligned"] is True, f"Should align: {r}"


@pytest.mark.engine
@pytest.mark.ceo
def test_CEO_02_alignment_check_violation():
    from tools.ceo_tools import alignment_check

    r = alignment_check(STRATEGY_BAD, GOALS)
    assert r["aligned"] is False, "Doubling lots violates capital preservation"
    assert len(r["violations"]) > 0


@pytest.mark.engine
@pytest.mark.ceo
def test_CEO_03_alignment_check_empty():
    from tools.ceo_tools import alignment_check

    r = alignment_check({}, GOALS)
    assert r["aligned"] is False


# Aggregation (3)
@pytest.mark.engine
@pytest.mark.ceo
def test_CEO_04_aggregate_performance():
    from tools.ceo_tools import aggregate_crew_performance

    crews = [
        {"role": "OM", "uptime": 1.0, "checks_passed": 7},
        {"role": "TA", "compliance": 0.95, "trades_validated": 10},
        {"role": "PM", "win_rate": 0.62, "profit_factor": 1.6},
        {"role": "AM", "margin_ok": True, "capital_ok": True},
    ]
    r = aggregate_crew_performance(crews)
    assert r["overall_healthy"] is True


@pytest.mark.engine
@pytest.mark.ceo
def test_CEO_05_aggregate_with_failure():
    from tools.ceo_tools import aggregate_crew_performance

    r = aggregate_crew_performance([{"role": "OM", "uptime": 0.0, "checks_passed": 0}])
    assert r["overall_healthy"] is False


@pytest.mark.engine
@pytest.mark.ceo
def test_CEO_06_aggregate_empty():
    from tools.ceo_tools import aggregate_crew_performance

    r = aggregate_crew_performance([])
    assert r["crews_active"] == 0


# Resource caps (3)
@pytest.mark.engine
@pytest.mark.ceo
def test_CEO_07_resource_caps_within_limits():
    from tools.ceo_tools import enforce_resource_caps

    r = enforce_resource_caps(positions=2, capital_inr=250000, strategies=2)
    assert r["ok"] is True


@pytest.mark.engine
@pytest.mark.ceo
def test_CEO_08_resource_caps_exceeded():
    from tools.ceo_tools import enforce_resource_caps

    r = enforce_resource_caps(positions=5, capital_inr=600000, strategies=4)
    assert r["ok"] is False
    assert len(r["violations"]) >= 2


@pytest.mark.engine
@pytest.mark.ceo
def test_CEO_09_resource_caps_positions_only():
    from tools.ceo_tools import enforce_resource_caps

    r = enforce_resource_caps(positions=5, capital_inr=200000, strategies=1)
    assert r["ok"] is False


# Board report (3)
@pytest.mark.engine
@pytest.mark.ceo
def test_CEO_10_board_report():
    from tools.ceo_tools import generate_board_report

    summaries = {
        "OM": "All checks passed",
        "PM": "WR 62%, PF 1.6",
        "TA": "100% compliance",
        "AM": "Margin 51%",
    }
    report = generate_board_report(summaries)
    assert "Board" in report["title"] or "board" in report["title"].lower()
    assert "OM" in report["text"]


@pytest.mark.engine
@pytest.mark.ceo
def test_CEO_11_board_report_with_violations():
    from tools.ceo_tools import generate_board_report

    report = generate_board_report(
        {"OM": "CRITICAL: broker down", "alignments": ["doubling lots violation"]}
    )
    assert "ALERT" in report["text"].upper() or "violation" in report["text"].lower()


@pytest.mark.engine
@pytest.mark.ceo
def test_CEO_12_board_report_clean():
    from tools.ceo_tools import generate_board_report

    report = generate_board_report({})
    assert report["flags"] == 0


# Escalation (3)
@pytest.mark.engine
@pytest.mark.ceo
def test_CEO_13_escalate_after_consecutive_failures():
    from tools.ceo_tools import should_escalate

    assert should_escalate([False, False, False], threshold=3) is True


@pytest.mark.engine
@pytest.mark.ceo
def test_CEO_14_no_escalate_below_threshold():
    from tools.ceo_tools import should_escalate

    assert should_escalate([False, False], threshold=3) is False


@pytest.mark.engine
@pytest.mark.ceo
def test_CEO_15_escalate_with_mixed():
    from tools.ceo_tools import should_escalate

    assert should_escalate([False, True, False], threshold=3) is False, (
        "Mixed = no consecutive streak"
    )


# Authority chain (2)
@pytest.mark.engine
@pytest.mark.ceo
def test_CEO_16_authority_can():
    from tools.ceo_tools import check_authority

    assert check_authority("crew_dispatch") is True


@pytest.mark.engine
@pytest.mark.ceo
def test_CEO_17_authority_cannot():
    from tools.ceo_tools import check_authority

    assert check_authority("trade_directly") is False


# CEO does NOT override risk guard (1)
@pytest.mark.engine
@pytest.mark.ceo
def test_CEO_18_ceo_no_risk_override():
    from tools.ceo_tools import check_authority

    assert check_authority("override_risk_guard_halt") is False


# Governance boundary tests (GA-01 to GA-15 condensed to 2 tests)
@pytest.mark.engine
@pytest.mark.ceo
def test_CEO_19_governance_veto_chain():
    from tools.ceo_tools import governance_veto

    r = governance_veto("PM", "strategy_switch", "CREDIT_SPREAD")
    assert r["needs_approval"] is True
    assert "CEO" in r.get("approvers", [])


@pytest.mark.engine
@pytest.mark.ceo
def test_CEO_20_governance_self_approval_blocked():
    from tools.ceo_tools import governance_veto

    r = governance_veto("CEO", "modify_constitution", "change SL from 3500 to 2000")
    assert r["needs_approval"] is True
    assert "Board" in r.get("approvers", [])
