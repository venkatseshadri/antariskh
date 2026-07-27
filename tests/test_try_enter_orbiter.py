"""Coverage for proton_live.py's _try_enter_orbiter — the higher-level
orchestrator that calls Gate1/Gate3, broker_confirms_flat, check_account_margin,
NUCLEUS ceiling, and (when LIVE_ENABLED) the real _orbiter_enter_legs order
placement. Flagged by DS review (2026-07-19) as the one load-bearing path
NOT covered by test_proton_live_broker_path.py's lower-level function tests.

Strategy: monkeypatch every data-layer dependency (market data, enriched
row, gates, nucleus file, strike/leg resolution, broker pricing) so the
orchestrator's OWN decision logic — which safety check blocks entry, in
what order, and whether it correctly short-circuits before reaching the
real order-placement call — is what's actually under test, not the data
sources themselves (those are separately covered: gate1_regime has its own
tests, _orbiter_enter_legs has its own 25 tests in
test_proton_live_broker_path.py).
"""
import sys
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import proton_live as pl  # noqa: E402
from test_proton_live_broker_path import FakeApi  # noqa: E402

TODAY = date(2026, 7, 20)
NOW = datetime(2026, 7, 20, 15, 25, 0)


def _passing_row():
    """A Gate1/Gate3-passing enriched row (low ADX, wide CPR, normal PCR)."""
    return {
        "adx": 15.0, "cpr_width_pct": 0.35, "cpr_width": None, "bb_width": 0.02,
        "vwap": 24000.0, "pcr_total": 1.0, "atr": 20.0, "atr_daily": 20.0,
        "timestamp": "2026-07-20T15:25:00",
    }


def _closes():
    idx = pd.date_range("2026-06-01", periods=30, freq="D").date
    return pd.Series([24000.0 + i for i in range(30)], index=idx)


class FakeStrikeMap:
    put_short, put_hedge = 24000, 23900
    call_short, call_hedge = 24450, 24550
    vwap, bb_upper, bb_lower, max_pain, atm = 24000.0, None, None, None, 24000


def _patch_common(monkeypatch, row=None, api=FakeApi(), broker_session_raises=False):
    """Wires every dependency to a passing/neutral default; individual
    tests override just the one thing they're testing."""
    monkeypatch.setattr(pl, "combined_daily_closes", lambda index: _closes())
    monkeypatch.setattr(pl, "trailing_rv", lambda closes, today: 0.15)
    monkeypatch.setattr(pl, "trailing_median_rv", lambda closes, today: 0.10)
    monkeypatch.setattr(pl.orbiter_mod, "_read_enriched_row", lambda index, today: row or _passing_row())
    monkeypatch.setattr(pl.orbiter_mod, "phase_machine_direction", lambda row, s0: "bull_put_spread")
    monkeypatch.setattr(pl.orbiter_mod, "gate2_strikes", lambda row, s0: FakeStrikeMap())
    monkeypatch.setattr(pl, "resolve_weekly_expiry", lambda index, now: date(2026, 7, 28))
    monkeypatch.setattr(
        pl, "_orbiter_resolve_two_legs",
        lambda expiry, s0, short_k, hedge_k, opt_type: {
            "short": {"exchange": "NFO", "token": "1", "tsym": "X", "strike": short_k, "opt_type": opt_type},
            "hedge": {"exchange": "NFO", "token": "2", "tsym": "Y", "strike": hedge_k, "opt_type": opt_type},
        },
    )
    monkeypatch.setattr(pl, "_leg_ltp", lambda api, exchange, token: 50.0)
    monkeypatch.setattr(pl, "_nucleus_ceiling", lambda tier="T3_HYDROGEN": (10_000_000.0, None))
    if broker_session_raises:
        def _raise():
            raise AssertionError("broker session created after a gate should have short-circuited")
        monkeypatch.setattr(pl, "_shoonya_session", _raise)
    else:
        monkeypatch.setattr(pl, "_shoonya_session", lambda: api)


def _state():
    return {"open_position": None, "orbiter_position": None}


# ── short-circuit ordering: each check must stop BEFORE the next one ────


def test_vol_filter_short_circuits_before_reading_enriched_data_or_broker():
    """rv <= median must skip before ANY broker/enriched-data call."""
    def _boom(*a, **kw):
        raise AssertionError("should not be called — vol_filter must short-circuit first")

    import pytest as _pytest
    monkeypatch = _pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(pl, "combined_daily_closes", lambda index: _closes())
        monkeypatch.setattr(pl, "trailing_rv", lambda closes, today: 0.05)
        monkeypatch.setattr(pl, "trailing_median_rv", lambda closes, today: 0.20)  # rv <= med
        monkeypatch.setattr(pl.orbiter_mod, "_read_enriched_row", _boom)
        monkeypatch.setattr(pl, "_shoonya_session", _boom)
        result = pl._try_enter_orbiter(_state(), TODAY, NOW, force_index="NIFTY")
        assert result["action"] == "SKIP_NO_EVENT" and result["reason"] == "vol_filter"
    finally:
        monkeypatch.undo()


def test_gate1_blocked_short_circuits_before_any_broker_call(monkeypatch):
    blocked_row = {**_passing_row(), "adx": 60.0, "cpr_width_pct": 0.02}  # narrow CPR, high ADX
    _patch_common(monkeypatch, row=blocked_row, broker_session_raises=True)
    result = pl._try_enter_orbiter(_state(), TODAY, NOW, force_index="NIFTY")
    assert result["action"] == "SKIP_NO_EVENT"
    assert "BLOCKED" in result["reason"] or "HALT" in result["reason"]


def test_gate3_blocked_short_circuits_before_broker_call(monkeypatch):
    row = {**_passing_row(), "pcr_total": 2.0}  # extreme PCR -> gate3 abort
    _patch_common(monkeypatch, row=row, broker_session_raises=True)
    result = pl._try_enter_orbiter(_state(), TODAY, NOW, force_index="NIFTY")
    assert result["action"] == "SKIP_NO_EVENT"


def test_no_broker_session_returns_none_not_a_dict(monkeypatch):
    """Confirmed intentional (checked the one caller, run_live_once, which
    does `result or {"action": "SKIP_NO_EVENT", ...}`) — but worth locking
    down explicitly since a None/dict mixed return type is easy to break
    accidentally in a future edit."""
    _patch_common(monkeypatch)
    monkeypatch.setattr(pl, "_shoonya_session", lambda: None)
    result = pl._try_enter_orbiter(_state(), TODAY, NOW, force_index="NIFTY")
    assert result is None


def test_broker_confirms_flat_false_refuses_entry(monkeypatch):
    api = FakeApi(positions_resp=[{"tsym": "STALE", "netqty": "75"}])
    _patch_common(monkeypatch, api=api)
    state = _state()
    state["open_position"] = {"legs": {"a": {"tsym": "STALE"}}}
    # broker_confirms_flat only checks state["open_position"]; give it one
    result = pl._try_enter_orbiter(state, TODAY, NOW, force_index="NIFTY")
    assert result["action"] == "REFUSE_ENTRY"
    assert result["reason"] == "broker_position_check_failed_or_nonzero"


def test_margin_floor_fails_refuses_entry(monkeypatch):
    # margin check only runs when LIVE_ENABLED (proton_live.py: no capital
    # check needed in paper mode) — this test targets that gated branch.
    monkeypatch.setattr(pl, "LIVE_ENABLED", True)
    api = FakeApi(limits_resp={"cash": "1000", "collat": "0", "marginavailable": "1000"})
    _patch_common(monkeypatch, api=api)
    result = pl._try_enter_orbiter(_state(), TODAY, NOW, force_index="NIFTY")
    assert result["action"] == "REFUSE_ENTRY"
    assert result["reason"] == "margin_floor_check_failed"


def test_nucleus_ceiling_exceeded_refuses_entry(monkeypatch):
    """Default fixture picks bull_put_spread (put_short=24000 > put_hedge=23900,
    wing=100) — this is exactly the side that was silently unblockable
    before the 2026-07-19 required_margin fix (see the dedicated regression
    test below). A tiny ceiling here now correctly refuses."""
    _patch_common(monkeypatch)
    monkeypatch.setattr(pl, "_nucleus_ceiling", lambda tier="T3_HYDROGEN": (1.0, None))
    result = pl._try_enter_orbiter(_state(), TODAY, NOW, force_index="NIFTY")
    assert result["action"] == "REFUSE_ENTRY"
    assert result["reason"] == "nucleus_ceiling_check_failed"


def test_required_margin_bug_regression_put_side_no_longer_always_zero(monkeypatch):
    """Locks in the 2026-07-19 fix. BEFORE: required_margin = max(hedge_k -
    short_k, 0) — via gate2_strikes, put_hedge < put_short always, so this
    was ALWAYS 0 for bull_put_spread regardless of wing width, meaning the
    NUCLEUS capital ceiling could never block a put-side entry, no matter
    how large. Found while building this exact test file. Verifies the
    fixed formula (wing - entry_credit, side-agnostic) reports a real,
    positive, ceiling-relevant number for the put side, not always 0."""
    _patch_common(monkeypatch)
    # ceiling just below the expected required_margin: wing=100
    # (put_short=24000, put_hedge=23900), entry_credit = short_ltp -
    # hedge_ltp = 50.0 - 50.0 = 0 (FakeApi always quotes 50.0)
    # -> required_margin = (100 - 0) * lot_size(75) = 7500, NOT 0.
    monkeypatch.setattr(pl, "_nucleus_ceiling", lambda tier="T3_HYDROGEN": (7499.0, None))
    blocked = pl._try_enter_orbiter(_state(), TODAY, NOW, force_index="NIFTY")
    assert blocked["action"] == "REFUSE_ENTRY"
    assert blocked["reason"] == "nucleus_ceiling_check_failed"
    assert blocked["required_margin"] == pytest.approx(7500.0)


def test_nucleus_missing_falls_back_to_broker_margin_check(monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.setattr(pl, "_nucleus_ceiling", lambda tier="T3_HYDROGEN": (None, "NO_FILE"))
    result = pl._try_enter_orbiter(_state(), TODAY, NOW, force_index="NIFTY")
    # margin is fine (FakeApi default: 100000 available) -> should proceed past the fallback
    assert result["action"] != "REFUSE_ENTRY" or result.get("reason") != "nucleus_missing_fallback_margin_check_failed"


def test_nucleus_missing_and_margin_also_fails_refuses_entry(monkeypatch):
    """The nucleus-missing fallback (LIVE_ENABLED-gated, see proton_live.py)
    re-checks margin via the SAME check_account_margin(api) call the
    top-of-function check already made — with a static mock these two calls
    always agree, so this branch is only reachable if margin genuinely
    changes between the two calls (a real, if narrow, broker-side race
    window). Scripted here via a call-counter to actually exercise the line,
    rather than skip it."""
    monkeypatch.setattr(pl, "LIVE_ENABLED", True)
    call_count = {"n": 0}

    def scripted_margin(api):
        call_count["n"] += 1
        return (True, 100000.0) if call_count["n"] == 1 else (False, 1000.0)

    _patch_common(monkeypatch)
    monkeypatch.setattr(pl, "check_account_margin", scripted_margin)
    monkeypatch.setattr(pl, "_nucleus_ceiling", lambda tier="T3_HYDROGEN": (None, "STALE"))
    result = pl._try_enter_orbiter(_state(), TODAY, NOW, force_index="NIFTY")
    assert result["action"] == "REFUSE_ENTRY"
    assert result["reason"] == "nucleus_missing_fallback_margin_check_failed"


# ── full success path ────────────────────────────────────────────────────


def test_full_success_dry_run_does_not_call_orbiter_enter_legs(monkeypatch):
    """LIVE_ENABLED=False (this process's default, no PROTON_LIVE_TRADING
    env var set) — must build and return the ENTER_TRIGGER_ORBITER event
    WITHOUT ever calling the real order-placement function."""
    assert pl.LIVE_ENABLED is False  # sanity: confirms this test's premise
    api = FakeApi()
    _patch_common(monkeypatch, api=api)
    result = pl._try_enter_orbiter(_state(), TODAY, NOW, force_index="NIFTY")
    assert result["action"] == "ENTER_TRIGGER_ORBITER"
    assert result["dry_run"] is True
    assert "would_place_side" in result
    assert "enter_result" not in result
    # api.get_quotes was called (leg pricing), but NEVER place_order
    assert not any(c[0] == "place_order" for c in api.calls)


def test_full_success_live_calls_orbiter_enter_legs_and_saves_state(monkeypatch, tmp_path):
    """With LIVE_ENABLED forced True (module attribute, not the env var —
    same effect, avoids reimporting the module mid-suite), confirms the
    orchestrator actually reaches and correctly drives the real
    order-placement call, then persists state on success."""
    monkeypatch.setattr(pl, "LIVE_ENABLED", True)
    monkeypatch.setattr(pl, "STATE_PATH", tmp_path / "state.json")
    api = FakeApi()
    _patch_common(monkeypatch, api=api)
    state = _state()
    result = pl._try_enter_orbiter(state, TODAY, NOW, force_index="NIFTY")
    assert result["action"] == "ENTER_TRIGGER_ORBITER"
    assert result["dry_run"] is False
    assert "enter_result" in result
    assert result["enter_result"]["stage"] == "complete"
    # hedge placed before short — same invariant test_proton_live_broker_path.py checks at the unit level
    place_calls = [c for c in api.calls if c[0] == "place_order"]
    assert place_calls[0][1]["buy_or_sell"] == pl.BUY
    assert place_calls[1][1]["buy_or_sell"] == pl.SELL
    assert state["orbiter_position"] is not None
