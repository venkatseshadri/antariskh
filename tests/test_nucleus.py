#!/usr/bin/env python3
"""Test NUCLEUS capital-orchestration layer — buffer withholding, tier ceiling
split, cached-margin fail-safe fallback. Pure-function checks, no real broker calls.

Run: python3 antariksh/tests/test_nucleus.py
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import nucleus


def test_buffer_is_withheld_from_sweepable_pool():
    alloc = nucleus.compute_allocation(100000.0, "live")
    assert alloc["buffer_reserved_inr"] == 15000.0
    # every tier ceiling is computed off the post-buffer pool (85000), not the raw pool
    assert alloc["tiers"]["T1_ATOM"]["ceiling_inr"] == round(85000.0 * 0.60, 2)


def test_real_vs_simulated_tier_flags():
    alloc = nucleus.compute_allocation(100000.0, "live")
    assert alloc["tiers"]["T1_ATOM"]["real"] is True
    assert alloc["tiers"]["T3_HYDROGEN"]["real"] is True
    assert alloc["tiers"]["T2_PROTON"]["real"] is False
    assert alloc["tiers"]["T4_NEUTRON"]["real"] is False


def test_source_and_timestamp_recorded():
    alloc = nucleus.compute_allocation(50000.0, "cached")
    assert alloc["source"] == "cached"
    datetime.fromisoformat(alloc["updated_at"])  # must parse without raising


def test_cached_margin_fallback_reads_real_shape(tmp_path, monkeypatch):
    fresh_ts = (datetime.now() - timedelta(hours=1)).isoformat()
    payload = {"timestamp": fresh_ts, "free_margin": 42000.0}
    cache_file = tmp_path / "broker_limits.json"
    cache_file.write_text(json.dumps(payload))
    monkeypatch.setattr(nucleus, "CACHED_LIMITS_FILE", cache_file)
    fm, reason = nucleus._cached_free_margin()
    assert fm == 42000.0 and reason is None


def test_cached_margin_fallback_fails_safe_on_stale(tmp_path, monkeypatch):
    old_ts = (datetime.now() - timedelta(days=10)).isoformat()
    payload = {"timestamp": old_ts, "free_margin": 42000.0}
    cache_file = tmp_path / "broker_limits.json"
    cache_file.write_text(json.dumps(payload))
    monkeypatch.setattr(nucleus, "CACHED_LIMITS_FILE", cache_file)
    fm, reason = nucleus._cached_free_margin()
    assert fm is None and reason == "STALE"


def test_cached_margin_fallback_fails_safe_on_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(nucleus, "CACHED_LIMITS_FILE", tmp_path / "nonexistent.json")
    fm, reason = nucleus._cached_free_margin()
    assert fm is None and reason == "NO_FILE"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
