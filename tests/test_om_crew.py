"""Operations Manager Crew Tests — OM-01 through OM-17.

Engine-only, deterministic, env-var mocking. No LLM calls.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def _clear_mock_env(monkeypatch):
    """Clear mock env vars between tests."""
    for k in (
        "ANTARIKSH_MOCK_MODE",
        "ANTARIKSH_MOCK_SHOONYA_DOWN",
        "ANTARIKSH_MOCK_BROKER_DOWN",
        "ANTARIKSH_MOCK_CODE_CHANGED",
        "ANTARIKSH_MOCK_DATA_STOPPED",
        "ANTARIKSH_MOCK_DISK_FULL",
        "ANTARIKSH_MOCK_CRON_DEAD",
        "ANTARIKSH_MOCK_NETWORK_DOWN",
        "ANTARIKSH_MOCK_DISK_PCT",
    ):
        monkeypatch.delenv(k, raising=False)


def _enable_mock(monkeypatch):
    monkeypatch.setenv("ANTARIKSH_MOCK_MODE", "1")


# ============================================================
# PreFlightAgent Tools (12 tests)
# ============================================================


@pytest.mark.engine
@pytest.mark.om
def test_OM_01_token_refresh_both_ok(monkeypatch):
    """OM-01: Both Shoonya + Flattrade tokens valid."""
    from tools.om_tools import token_refresh_status

    _enable_mock(monkeypatch)
    result = token_refresh_status()
    assert result["shoonya"] is True, f"Shoonya should be OK: {result}"
    assert result["flattrade"] is True, f"Flattrade should be OK: {result}"
    assert result["ok"] is True, "Both tokens valid → ok=True"


@pytest.mark.engine
@pytest.mark.om
def test_OM_02_token_refresh_shoonya_fail_flattrade_ok(monkeypatch):
    """OM-02: Shoonya token fails, Flattrade valid."""
    from tools.om_tools import token_refresh_status

    _enable_mock(monkeypatch)
    monkeypatch.setenv("ANTARIKSH_MOCK_SHOONYA_DOWN", "1")
    result = token_refresh_status()
    assert result["shoonya"] is False, f"Shoonya should be down: {result}"
    assert result["flattrade"] is True, "Flattrade should be OK"
    assert result["ok"] is True, "One broker up → ok=True"


@pytest.mark.engine
@pytest.mark.om
def test_OM_03_token_refresh_both_fail(monkeypatch):
    """OM-03: Both broker tokens fail."""
    from tools.om_tools import token_refresh_status

    _enable_mock(monkeypatch)
    monkeypatch.setenv("ANTARIKSH_MOCK_SHOONYA_DOWN", "1")
    monkeypatch.setenv("ANTARIKSH_MOCK_BROKER_DOWN", "1")
    result = token_refresh_status()
    assert result["shoonya"] is False, f"Shoonya should be down: {result}"
    assert result["flattrade"] is False, f"Flattrade should be down: {result}"
    assert result["ok"] is False, "Both brokers down → ok=False"


@pytest.mark.engine
@pytest.mark.om
def test_OM_04_code_verification_unchanged(monkeypatch):
    """OM-04: Code hash matches — no unauthorized changes."""
    from tools.om_tools import verify_code_hash

    _enable_mock(monkeypatch)
    result = verify_code_hash()
    assert result["unchanged"] is True, f"Code should be unchanged: {result}"
    assert result["ok"] is True, "Unchanged code → ok=True"


@pytest.mark.engine
@pytest.mark.om
def test_OM_05_code_verification_changed(monkeypatch):
    """OM-05: Unauthorized code change detected."""
    from tools.om_tools import verify_code_hash

    _enable_mock(monkeypatch)
    monkeypatch.setenv("ANTARIKSH_MOCK_CODE_CHANGED", "1")
    result = verify_code_hash()
    assert result["unchanged"] is False, "Code change should be detected"
    assert result["ok"] is False, "Changed code → ok=False"
    assert "evidence" in result, "Must include evidence of change"


@pytest.mark.engine
@pytest.mark.om
def test_OM_06_data_capture_running(monkeypatch):
    """OM-06: DuckDB market data stream alive."""
    from tools.om_tools import data_capture_health

    _enable_mock(monkeypatch)
    result = data_capture_health()
    assert result["running"] is True, f"Data should be running: {result}"
    assert result["ok"] is True, "Running data → ok=True"


@pytest.mark.engine
@pytest.mark.om
def test_OM_07_data_capture_stopped(monkeypatch):
    """OM-07: DuckDB stream dead."""
    from tools.om_tools import data_capture_health

    _enable_mock(monkeypatch)
    monkeypatch.setenv("ANTARIKSH_MOCK_DATA_STOPPED", "1")
    result = data_capture_health()
    assert result["running"] is False, "Data should be stopped"
    assert result["ok"] is False, "Stopped data → ok=False"


@pytest.mark.engine
@pytest.mark.om
def test_OM_08_disk_usage_normal(monkeypatch):
    """OM-08: Disk at 45% — healthy."""
    from tools.om_tools import disk_usage_check

    _enable_mock(monkeypatch)
    result = disk_usage_check()
    assert result["pct_used"] < 90, f"Disk should be healthy: {result}"
    assert result["ok"] is True, "Normal disk → ok=True"


@pytest.mark.engine
@pytest.mark.om
def test_OM_09_disk_usage_critical(monkeypatch):
    """OM-09: Disk 98% full — halt condition."""
    from tools.om_tools import disk_usage_check

    _enable_mock(monkeypatch)
    monkeypatch.setenv("ANTARIKSH_MOCK_DISK_FULL", "1")
    result = disk_usage_check()
    assert result["pct_used"] >= 95, f"Disk should be critical: {result}"
    assert result["ok"] is False, "Full disk → ok=False"


@pytest.mark.engine
@pytest.mark.om
def test_OM_10_network_broker_reachable(monkeypatch):
    """OM-10: Both Shoonya and Flattrade APIs reachable."""
    from tools.om_tools import network_connectivity_check

    _enable_mock(monkeypatch)
    result = network_connectivity_check()
    assert result["ok"] is True, f"Network should be OK: {result}"
    assert "broker" in result
    assert result["broker"]["shoonya"] > 0, "Shoonya latency > 0"


@pytest.mark.engine
@pytest.mark.om
def test_OM_11_network_broker_unreachable(monkeypatch):
    """OM-11: Broker APIs unreachable."""
    from tools.om_tools import network_connectivity_check

    _enable_mock(monkeypatch)
    monkeypatch.setenv("ANTARIKSH_MOCK_BROKER_DOWN", "1")
    result = network_connectivity_check()
    assert result["ok"] is False, "No brokers → ok=False"
    assert result["broker"]["shoonya"] < 0, "Unreachable → negative latency code"


@pytest.mark.engine
@pytest.mark.om
def test_OM_12_network_telegram_reachable(monkeypatch):
    """OM-12: Telegram via picoclaw is reachable."""
    from tools.om_tools import network_connectivity_check

    _enable_mock(monkeypatch)
    result = network_connectivity_check()
    assert "evidence" in result, "Network check must have evidence"
    assert isinstance(result["evidence"], str)
    assert len(result["evidence"]) > 0


# ============================================================
# CronWatchdog Tests (2 tests)
# ============================================================


@pytest.mark.engine
@pytest.mark.om
def test_OM_13_crons_all_active(monkeypatch):
    """OM-13: All expected crons running."""
    from tools.om_tools import cron_health_check

    _enable_mock(monkeypatch)
    result = cron_health_check()
    assert result["ok"] is True, f"Crons should be active: {result}"
    assert len(result.get("active", [])) >= 2, "At least 2 crons expected"
    assert len(result.get("missing", [])) == 0, "No missing crons"


@pytest.mark.engine
@pytest.mark.om
def test_OM_14_crons_missing_entry(monkeypatch):
    """OM-14: Expected crons missing from crontab."""
    from tools.om_tools import cron_health_check

    _enable_mock(monkeypatch)
    monkeypatch.setenv("ANTARIKSH_MOCK_CRON_DEAD", "1")
    result = cron_health_check()
    assert result["ok"] is False, "Dead crons → ok=False"
    assert len(result.get("missing", [])) > 0, "Should list missing crons"


# ============================================================
# Reporter Tests (2 tests)
# ============================================================


@pytest.mark.engine
@pytest.mark.om
def test_OM_15_health_report_all_pass():
    """OM-15: All checks pass → GO decision with evidence."""
    from tools.om_tools import aggregate_health_report

    checks = [
        {
            "name": "tokens",
            "ok": True,
            "evidence": "Both tokens refreshed at 07:02 IST",
        },
        {"name": "code", "ok": True, "evidence": "Code hash matches: a1b2c3d4"},
        {"name": "data", "ok": True, "evidence": "DuckDB last write: 07:55 IST"},
        {"name": "disk", "ok": True, "evidence": "45% used, 234GB free"},
        {"name": "network", "ok": True, "evidence": "Shoonya: 120ms, Flattrade: 85ms"},
        {"name": "cron", "ok": True, "evidence": "4/4 crons active"},
    ]
    result = aggregate_health_report(checks)
    assert result["overall"] == "GO", f"All pass → GO: {result}"
    assert "telegram_md" in result, "Must include Telegram markdown"
    assert "GO" in result["telegram_md"], "Report must show GO decision"
    for check in checks:
        assert check["evidence"] in result["telegram_md"], (
            f"Evidence for {check['name']} must be in report"
        )


@pytest.mark.engine
@pytest.mark.om
def test_OM_16_health_report_critical_fail():
    """OM-16: CRITICAL failure → NOGO with halt reason."""
    from tools.om_tools import aggregate_health_report

    checks = [
        {
            "name": "tokens",
            "ok": False,
            "evidence": "Shoonya: FAILED, Flattrade: FAILED",
        },
        {"name": "code", "ok": True, "evidence": "Code unchanged"},
        {"name": "data", "ok": True, "evidence": "DuckDB running"},
        {"name": "disk", "ok": True, "evidence": "45% used"},
        {"name": "network", "ok": False, "evidence": "Both brokers unreachable"},
        {"name": "cron", "ok": True, "evidence": "4/4 crons active"},
    ]
    result = aggregate_health_report(checks)
    assert result["overall"] == "NOGO", "CRITICAL fails → NOGO"
    assert "NOGO" in result["telegram_md"], "Report must show NOGO"
    assert "Shoonya: FAILED" in result["telegram_md"], "Evidence in NOGO report"
    assert "Both brokers unreachable" in result["telegram_md"]


# ============================================================
# Integration Test (1 test)
# ============================================================


@pytest.mark.engine
@pytest.mark.om
def test_OM_17_full_pre_flight_pipeline(monkeypatch):
    """OM-17: Full pipeline — all 7 checks run, report assembled."""
    from tools.om_tools import (
        token_refresh_status,
        verify_code_hash,
        data_capture_health,
        disk_usage_check,
        network_connectivity_check,
        cron_health_check,
        aggregate_health_report,
    )

    _enable_mock(monkeypatch)

    token_result = token_refresh_status()
    code_result = verify_code_hash()
    data_result = data_capture_health()
    disk_result = disk_usage_check()
    network_result = network_connectivity_check()
    cron_result = cron_health_check()

    checks = [
        {"name": "tokens", **token_result},
        {"name": "code", **code_result},
        {"name": "data", **data_result},
        {"name": "disk", **disk_result},
        {"name": "network", **network_result},
        {"name": "cron", **cron_result},
    ]
    report = aggregate_health_report(checks)

    assert token_result["ok"], "Tokens should be OK in mock mode"
    assert code_result["ok"], "Code should be unchanged"
    assert data_result["ok"], "Data should be running"
    assert disk_result["ok"], "Disk should be healthy"
    assert network_result["ok"], "Network should be OK"
    assert cron_result["ok"], "Crons should be active"
    assert report["overall"] == "GO", "Mock mode all-pass → GO"
    assert "telegram_md" in report
    assert len(report["telegram_md"]) > 200, "Report should be substantial"
    assert "IST" in report["telegram_md"], "Report should include timestamps"


# ============================================================
# Edge Case / Real Path Tests (3 tests)
# ============================================================


@pytest.mark.engine
@pytest.mark.om
def test_OM_18_network_telegram_unreachable(monkeypatch):
    """OM-18: ANTARIKSH_MOCK_NETWORK_DOWN simulates Telegram down."""
    from tools.om_tools import network_connectivity_check

    _enable_mock(monkeypatch)
    monkeypatch.setenv("ANTARIKSH_MOCK_NETWORK_DOWN", "1")
    result = network_connectivity_check()
    assert result["ok"] is False, f"Telegram down → ok=False: {result}"
    assert "UNREACHABLE" in result["evidence"], (
        f"Telegram should be unreachable: {result['evidence']}"
    )
    assert result["broker"]["shoonya"] > 0, "Brokers still reachable"


@pytest.mark.engine
@pytest.mark.om
def test_OM_19_disk_exactly_at_threshold(monkeypatch):
    """OM-19: Disk at exactly 90% → ok=False (boundary)."""
    from tools.om_tools import disk_usage_check

    _enable_mock(monkeypatch)
    monkeypatch.setenv("ANTARIKSH_MOCK_DISK_PCT", "90.0")
    result = disk_usage_check()
    assert result["pct_used"] == 90.0, f"Disk should be exactly 90%: {result}"
    assert result["ok"] is False, "Exactly 90% should be NOT ok"


@pytest.mark.engine
@pytest.mark.om
def test_OM_20_code_hash_real_calculation():
    """OM-20: verify_code_hash produces a non-empty hash string (real path)."""
    from tools.om_tools import verify_code_hash

    result = verify_code_hash()
    assert "evidence" in result
    assert "Code hash:" in result["evidence"], (
        f"Must contain hash: {result['evidence']}"
    )
    import re

    match = re.search(r"Code hash: (\S+)", result["evidence"])
    assert match, f"No hash found: {result['evidence']}"
    assert len(match.group(1)) > 0, "Hash must not be empty"
