"""Ralph Loop Infrastructure Tests — RL-01 through RL-04.

Engine-only, deterministic, no LLM or CrewAI integration.
"""

import os
import sys
import tempfile
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ralph.ralph_loop import (
    VerificationResult,
    RolePRD,
    PRDRalphLoop,
    RalphScheduler,
    load_prd_yaml,
    _parse_metric_value,
)


# ============================================================
# RL-01: Scheduled PRD Check — scheduler picks correct crew
# ============================================================


def test_RL_01_scheduler_picks_correct_crew():
    """RL-01: RalphScheduler.run_due_roles() runs the correct crew at the
    configured time and skips roles that are not due."""
    prd = RolePRD(
        name="OM",
        mission="Infrastructure health",
        metrics=[{"name": "uptime", "target": 100.0, "floor": 99.0, "min_samples": 1}],
    )

    def agent_fn(prompt):
        return {"uptime": 99.5}

    def metric_eval(output):
        return output

    loop = PRDRalphLoop(agent_fn, prd, metric_eval)

    # 8:00 AM — OM should be due
    with patch("ralph.ralph_loop.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 5, 12, 8, 0)
        scheduler = RalphScheduler([(loop, "08:00")])
        results = scheduler.run_due_roles()
        assert len(results) >= 1, "OM should be due at 08:00"
        assert results[0].get("role") == "OM"

    # 9:05 AM — OM already ran today, should NOT be due
    # With time window of ±2 min, 9:05 > 8:02 so won't match
    result = RalphScheduler._simple_time_match(
        "08:00", datetime(2026, 5, 12, 9, 5), window_minutes=2
    )
    assert result is False, "9:05 AM should not match 8:00 schedule"

    # 7:59 AM — within window
    result = RalphScheduler._simple_time_match(
        "08:00", datetime(2026, 5, 12, 7, 59), window_minutes=2
    )
    assert result is True, "7:59 AM should match 8:00 schedule (±2 min window)"

    # 8:02 AM — within window
    result = RalphScheduler._simple_time_match(
        "08:00", datetime(2026, 5, 12, 8, 2), window_minutes=2
    )
    assert result is True, "8:02 AM should match 8:00 schedule (±2 min window)"


# ============================================================
# RL-02: YAML Loading — edge cases
# ============================================================


def test_RL_02_yaml_loading_happy_path():
    """RL-02: load_prd_yaml() loads all 6 PRDs with correct value types."""
    for role in ["om", "pm", "ta", "am", "pa", "ceo"]:
        prd = load_prd_yaml(f"ralph/prds/{role}_prd.yaml")
        assert prd.name is not None, f"{role} PRD should have a name"
        assert prd.mission != "", f"{role} PRD should have a mission"
        assert len(prd.metrics) > 0, f"{role} PRD should have metrics"
        for m in prd.metrics:
            assert "name" in m, f"{role} metric must have name"
            assert "target" in m, f"{role} metric must have target"
            assert "floor" in m, f"{role} metric must have floor"
            assert "min_samples" in m, f"{role} metric must have min_samples"
            assert isinstance(m["min_samples"], int), f"{role} min_samples must be int"
            # Value types can be bool, float, or str (qualitative targets)
            assert type(m["target"]) in (bool, float, str), (
                f"{role}.{m['name']} target type={type(m['target']).__name__}"
            )


def test_RL_02_yaml_loading_missing_file():
    """RL-02: load_prd_yaml() raises FileNotFoundError for nonexistent PRD."""
    with pytest.raises(FileNotFoundError, match="PRD file not found"):
        load_prd_yaml("ralph/prds/nonexistent_prd.yaml")


def test_RL_02_yaml_loading_malformed_yaml():
    """RL-02: load_prd_yaml() handles malformed YAML."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tmp:
        tmp.write("role: Broken\nmetrics:\n  - !!python/tuple [bad, yaml]\n")
        tmp_path = tmp.name
    try:
        with pytest.raises((Exception,)):
            load_prd_yaml(tmp_path)
    finally:
        os.unlink(tmp_path)


def test_RL_02_yaml_loading_missing_fields():
    """RL-02: load_prd_yaml() returns defaults for missing optional fields."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tmp:
        tmp.write("role: Minimal\nmission: Just testing")
        tmp_path = tmp.name
    try:
        prd = load_prd_yaml(tmp_path)
        assert prd.name == "Minimal"
        assert prd.mission == "Just testing"
        assert prd.metrics == [], "No metrics → empty list"
        assert prd.authority_can == [], "No authority → empty lists"
        assert prd.authority_cannot == []
    finally:
        os.unlink(tmp_path)


# ============================================================
# RL-03: Auto-Escalation — counter after consecutive failures
# ============================================================


def test_RL_03_escalation_counter_increments():
    """RL-03: PRDRalphLoop escalation counter tracks consecutive PRD failures.

    A crew that consistently fails its PRD should accumulate failures
    and mark escalation_triggered after exceeding max_iterations.
    """
    prd = RolePRD(
        name="Test Crew",
        mission="Always fail",
        metrics=[{"name": "win_rate", "target": 0.60, "floor": 0.50, "min_samples": 1}],
    )

    # Agent always returns terrible results (below floor)
    def always_fail_agent(prompt):
        return {"win_rate": 0.10}

    def metric_eval(output):
        return output

    loop = PRDRalphLoop(
        agent_fn=always_fail_agent,
        prd=prd,
        metric_evaluator=metric_eval,
        max_iterations=3,
    )

    result = loop.run("Test escalation")
    # After 3 iterations, all failing — completion_reason should show max_iterations
    assert result["iterations"] == 3, (
        f"Should exhaust all 3 iterations: got {result['iterations']}"
    )
    assert result["completion_reason"] == "max_iterations", (
        f"Should exhaust all iterations: {result['completion_reason']}"
    )
    assert "failed to verify" in result.get("reason", "").lower(), (
        f"Reason should explain failure: {result.get('reason')}"
    )


def test_RL_03_no_escalation_when_eventually_pass():
    """RL-03: PRD passes on retry — no escalation triggered."""
    prd = RolePRD(
        name="Test Crew",
        mission="Improve",
        metrics=[{"name": "accuracy", "target": 0.90, "floor": 0.80, "min_samples": 1}],
    )

    call_count = [0]

    def improving_agent(prompt):
        val = 0.70 if call_count[0] == 0 else 0.95
        call_count[0] += 1
        return {"accuracy": val}

    def metric_eval(output):
        return output

    loop = PRDRalphLoop(
        agent_fn=improving_agent,
        prd=prd,
        metric_evaluator=metric_eval,
        max_iterations=3,
    )

    result = loop.run("Test improvement")
    assert result["completion_reason"] == "verified", (
        f"Should verify after value improves: {result['completion_reason']}"
    )
    assert result["iterations"] == 2, "Should converge in 2 iterations"


# ============================================================
# RL-04: PRD Evolution — metric history tracking
# ============================================================


def test_RL_04_data_immature_status():
    """RL-04: check_metric() returns DATA_IMMATURE when samples < min_samples."""
    prd = RolePRD(
        name="New Role",
        mission="Learning",
        metrics=[
            {
                "name": "win_rate",
                "target": 0.60,
                "floor": 0.50,
                "min_samples": 20,
                "before_min": "TRACKING",
            }
        ],
    )

    # 5 samples — way below 20 min_samples
    status, reason = prd.check_metric("win_rate", 0.70, 5)
    assert status == "DATA_IMMATURE", f"Expected DATA_IMMATURE, got {status}"
    assert reason == "TRACKING"

    # 19 samples — still below
    status, reason = prd.check_metric("win_rate", 0.70, 19)
    assert status == "DATA_IMMATURE"

    # 20 samples — over threshold, should evaluate
    status, reason = prd.check_metric("win_rate", 0.70, 20)
    assert status != "DATA_IMMATURE", "Should evaluate when samples >= min_samples"
    assert status == "PASS", "0.70 >= target 0.60 should PASS"


def test_RL_04_pass_warning_fail_with_samples():
    """RL-04: check_metric reports correct status based on actual vs target/floor."""
    prd = RolePRD(
        name="Test",
        mission="Testing thresholds",
        metrics=[
            {
                "name": "accuracy",
                "target": 0.90,
                "floor": 0.70,
                "min_samples": 5,
            }
        ],
    )

    # Above target → PASS
    status, _ = prd.check_metric("accuracy", 0.95, 10)
    assert status == "PASS"

    # At target → PASS
    status, _ = prd.check_metric("accuracy", 0.90, 10)
    assert status == "PASS", "0.90 = target 0.90 should be PASS"

    # Below target but above floor → WARNING
    status, _ = prd.check_metric("accuracy", 0.85, 10)
    assert status == "WARNING"

    # At floor → WARNING
    status, _ = prd.check_metric("accuracy", 0.70, 10)
    assert status == "WARNING", "0.70 = floor 0.70 should be WARNING"

    # Below floor → FAIL
    status, _ = prd.check_metric("accuracy", 0.50, 10)
    assert status == "FAIL"


def test_RL_04_boolean_metric_check():
    """RL-04: check_metric() handles boolean targets."""
    prd = RolePRD(
        name="OM",
        mission="Infra",
        metrics=[
            {
                "name": "pre_flight_pass",
                "target": True,
                "floor": True,
                "min_samples": 1,
            }
        ],
    )

    status, _ = prd.check_metric("pre_flight_pass", True, 1)
    assert status == "PASS", "True >= True should be PASS"

    status, _ = prd.check_metric("pre_flight_pass", False, 1)
    assert status == "FAIL", "False < True should be FAIL"


def test_RL_04_unknown_metric_graceful():
    """RL-04: check_metric() returns PASS for unknown metric (not an error)."""
    prd = RolePRD(
        name="Test",
        mission="Testing",
        metrics=[
            {"name": "only_metric", "target": 0.5, "floor": 0.3, "min_samples": 1}
        ],
    )

    status, reason = prd.check_metric("nonexistent", 1.0, 10)
    assert status == "PASS", "Unknown metrics should pass gracefully"
    assert "Unknown" in reason


# ============================================================
# _parse_metric_value regression
# ============================================================


def test_parse_metric_value_all_types():
    """Verify _parse_metric_value handles all PRD value types."""
    assert _parse_metric_value("True") is True
    assert _parse_metric_value("False") is False
    assert _parse_metric_value("100%") == 100.0
    assert _parse_metric_value("99%") == 99.0
    assert _parse_metric_value("≤80%") == 80.0
    assert _parse_metric_value("≥1.5") == 1.5
    assert _parse_metric_value("≤₹15,000") == 15000.0
    assert _parse_metric_value(0.60) == 0.60
    assert _parse_metric_value(3500) == 3500.0
    assert _parse_metric_value(True) is True
    assert _parse_metric_value(False) is False
    assert _parse_metric_value("≥₹2 profit per ₹100 deployed") == 2.0
    assert _parse_metric_value("TRENDING DOWN") == "TRENDING DOWN"
