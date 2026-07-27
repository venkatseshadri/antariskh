"""Tests for orbiter_weekly.py (ORBITER v3.0 specs, multi-day-adapted) and
weekly_ic_pilot_orbiter.py (the sibling pilot that wires them in).

Style follows atom/tests/test_orbiter.py: small builder functions with
overridable kwargs, gate/TSL/TP functions tested as pure functions of
plain dicts (no sqlite/broker I/O needed for those). Only _read_enriched_row
and the pilot's entry/exit cycle need I/O mocked (tmp sqlite / monkeypatch).
"""

import sqlite3
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import orbiter_weekly as ow
import weekly_ic_pilot_orbiter as wip


def _row(
    adx=15.0,
    cpr_width_pct=0.30,
    cpr_width=None,
    bb_width=0.02,
    vwap=24000.0,
    pcr_total=1.0,
    max_pain_strike=None,
    atr=20.0,
    atr_daily=None,
    bb_upper_real=None,
    bb_lower_real=None,
):
    row = {
        "adx": adx,
        "cpr_width_pct": cpr_width_pct,
        "cpr_width": cpr_width,
        "bb_width": bb_width,
        "vwap": vwap,
        "pcr_total": pcr_total,
        "max_pain_strike": max_pain_strike,
        "atr": atr,
    }
    if atr_daily is not None:
        row["atr_daily"] = atr_daily
    if bb_upper_real is not None:
        row["bb_upper_real"] = bb_upper_real
        row["bb_lower_real"] = bb_lower_real
    return row


# ── Gate 1 ──────────────────────────────────────────────────────────────


def test_gate1_passes_low_adx_wide_cpr():
    g = ow.gate1_regime(_row(adx=15.0, cpr_width_pct=0.30))
    assert g.passed
    assert g.gate == "GATE1_REGIME"


def test_gate1_blocks_high_adx():
    g = ow.gate1_regime(_row(adx=30.0, cpr_width_pct=0.30))
    assert not g.passed
    assert "ADX" in g.reason


def test_gate1_blocks_narrow_cpr():
    g = ow.gate1_regime(_row(adx=15.0, cpr_width_pct=0.05, bb_width=0.001))
    assert not g.passed


def test_gate1_falls_back_to_bb_width_when_no_cpr():
    g = ow.gate1_regime(_row(adx=15.0, cpr_width_pct=None, cpr_width=None, bb_width=0.01))
    assert g.passed  # bb_width 0.01 >= 0.003 default threshold


def test_gate1_wide_negative_cpr_passes():
    # Inverted CPR (TC < BC, e.g. prior close in lower half of its range) is
    # a legitimate, common state, not an error — a wide-but-negative width
    # must still pass the "wide" check. Regression for the missing abs().
    g = ow.gate1_regime(_row(adx=15.0, cpr_width_pct=-0.30))
    assert g.passed


def test_gate1_narrow_negative_cpr_blocks():
    g = ow.gate1_regime(_row(adx=15.0, cpr_width_pct=-0.05, bb_width=0.001))
    assert not g.passed


# ── Gate 1: structural pre-open window (before ADX(14) warms up) ────────


def test_gate1_structural_window_passes_on_wide_cpr_despite_elevated_adx():
    row = _row(adx=35.0, cpr_width_pct=0.30)
    row["timestamp"] = "2026-07-20T09:20:00"
    g = ow.gate1_regime(row)
    assert g.passed and g.details.get("structural_window")


def test_gate1_structural_window_blocks_extreme_adx_even_pre_warmup():
    """Independent review (2026-07-19): a sustained real trend at open can
    push ADX past 60 immediately and keep it there all day — CPR-alone
    would wrongly let that through."""
    row = _row(adx=75.0, cpr_width_pct=0.30)
    row["timestamp"] = "2026-07-20T09:20:00"
    g = ow.gate1_regime(row)
    assert not g.passed and g.details.get("structural_window")
    assert "ADX" in g.reason


def test_gate1_structural_window_halts_on_narrow_cpr_regardless_of_adx():
    row = _row(adx=5.0, cpr_width_pct=0.05, bb_width=0.001)
    row["timestamp"] = "2026-07-20T09:20:00"
    g = ow.gate1_regime(row)
    assert not g.passed and "HALT" in g.reason


def test_gate1_structural_window_ends_at_configured_cutoff():
    """At/after 09:45 (2x14-bar Wilder warm-up, not the original 09:30)."""
    row = _row(adx=60.0, cpr_width_pct=0.30)
    row["timestamp"] = "2026-07-20T09:45:00"
    g = ow.gate1_regime(row)
    assert not g.passed and "structural_window" not in g.details
    assert "ADX" in g.reason


def test_gate1_missing_timestamp_does_not_enter_structural_window():
    row = _row(adx=60.0, cpr_width_pct=0.30)  # no "timestamp" key at all
    g = ow.gate1_regime(row)
    assert not g.passed and "structural_window" not in g.details


# ── Gate 3 ──────────────────────────────────────────────────────────────


def test_gate3_passes_normal_pcr():
    g = ow.gate3_entry_abort(_row(pcr_total=1.0))
    assert g.passed


def test_gate3_aborts_bull_divergence():
    g = ow.gate3_entry_abort(_row(pcr_total=0.5))
    assert not g.passed


def test_gate3_aborts_bear_divergence():
    g = ow.gate3_entry_abort(_row(pcr_total=1.5))
    assert not g.passed


def test_gate3_passes_when_no_pcr_data():
    g = ow.gate3_entry_abort(_row(pcr_total=None))
    assert g.passed
    assert "skip gate" in g.reason


# ── Gate 2 (strike anchoring) ─────────────────────────────────────────────


def test_gate2_uses_real_bb_bands_when_available():
    smap = ow.gate2_strikes(_row(bb_upper_real=24300.0, bb_lower_real=23700.0), spot=24000.0)
    assert smap.call_short >= 24300
    assert smap.put_short <= 23700
    assert smap.call_hedge > smap.call_short
    assert smap.put_hedge < smap.put_short


def test_gate2_falls_back_to_bb_width_synthesis():
    smap = ow.gate2_strikes(_row(bb_width=0.04), spot=24000.0)
    assert smap.bb_upper is not None and smap.bb_lower is not None
    assert smap.call_short > smap.atm
    assert smap.put_short < smap.atm


def test_gate2_respects_minimum_wing_width_absent_bands():
    smap = ow.gate2_strikes(_row(bb_width=None, max_pain_strike=None), spot=24000.0, wing_strikes=3)
    assert smap.call_short >= smap.atm + 3 * ow.STRIKE_GAP
    assert smap.put_short <= smap.atm - 3 * ow.STRIKE_GAP


def test_gate2_max_pain_biases_strikes_outward():
    smap = ow.gate2_strikes(
        _row(bb_width=None, max_pain_strike=24500), spot=24000.0, wing_strikes=3
    )
    assert smap.call_short >= 24500 + 3 * ow.STRIKE_GAP


# ── Legging phase machine ─────────────────────────────────────────────────


def test_direction_bear_call_above_vwap():
    assert ow.phase_machine_direction(_row(vwap=24000.0), spot=24100.0) == "bear_call_spread"


def test_direction_bull_put_below_vwap():
    assert ow.phase_machine_direction(_row(vwap=24000.0), spot=23900.0) == "bull_put_spread"


def test_direction_defaults_bull_put_near_vwap():
    assert ow.phase_machine_direction(_row(vwap=24000.0), spot=24005.0) == "bull_put_spread"


def test_consolidation_fires_when_adx_low_pcr_flat_unbreached():
    assert ow.consolidation_trigger(
        _row(adx=15.0, pcr_total=1.0), "bull_put_spread", short_strike=23700, spot=24000.0
    )


def test_consolidation_blocked_by_high_adx():
    assert not ow.consolidation_trigger(
        _row(adx=25.0, pcr_total=1.0), "bull_put_spread", short_strike=23700, spot=24000.0
    )


def test_consolidation_blocked_when_short_strike_breached():
    assert not ow.consolidation_trigger(
        _row(adx=15.0, pcr_total=1.0), "bull_put_spread", short_strike=24100, spot=24000.0
    )


def test_asymmetric_breakage_put_side():
    assert ow.asymmetric_breakage_trigger("bull_put_spread", short_strike=24100, spot=24000.0)
    assert not ow.asymmetric_breakage_trigger("bull_put_spread", short_strike=23900, spot=24000.0)


def test_asymmetric_breakage_call_side():
    assert ow.asymmetric_breakage_trigger("bear_call_spread", short_strike=23900, spot=24000.0)
    assert not ow.asymmetric_breakage_trigger("bear_call_spread", short_strike=24100, spot=24000.0)


# ── ATR TSL / ratchet / catastrophe ────────────────────────────────────────


def test_initial_tsl_uses_atr_when_available():
    sl = ow.orbiter_initial_tsl(short_entry_ltp=100.0, atr_value=20.0)
    assert sl == 100.0 + 1.5 * 20.0


def test_initial_tsl_falls_back_without_atr():
    sl = ow.orbiter_initial_tsl(short_entry_ltp=100.0, atr_value=None, sl_pct_fallback=35.0)
    assert sl == pytest.approx(135.0)


def test_ratchet_lowers_sl_after_25pct_drop():
    sl = ow.orbiter_tsl_ratchet(
        current_sl=130.0, short_entry_ltp=100.0, short_current_ltp=70.0, atr_value=20.0
    )
    assert sl == 130.0 - 0.5 * 20.0


def test_ratchet_never_moves_up_or_below_entry():
    sl = ow.orbiter_tsl_ratchet(
        current_sl=105.0, short_entry_ltp=100.0, short_current_ltp=50.0, atr_value=20.0
    )
    assert sl == 100.0  # clamped at entry, never below


def test_ratchet_holds_before_threshold():
    sl = ow.orbiter_tsl_ratchet(
        current_sl=130.0, short_entry_ltp=100.0, short_current_ltp=90.0, atr_value=20.0
    )
    assert sl == 130.0


def test_catastrophe_stop_is_50pct_above_dynamic():
    assert ow.orbiter_catastrophe_stop(100.0) == 150.0


# ── TP priority array ──────────────────────────────────────────────────────


def _times():
    entry = datetime(2026, 7, 17, 15, 20)  # Friday entry
    expiry_ts = datetime(2026, 7, 21, 15, 30)  # Tuesday expiry
    return entry, expiry_ts


def test_tp_vwap_stretch_fires_first():
    entry, expiry_ts = _times()
    now = entry + timedelta(hours=1)
    row = _row(vwap=24000.0, bb_width=0.01)  # sigma_est=60 -> upper=24150
    result = ow.orbiter_tp_check(
        "bull_put_spread",
        net_credit=100.0,
        current_pnl=10.0,
        row=row,
        spot=24500.0,
        entry_ts=entry,
        expiry_ts=expiry_ts,
        now_ts=now,
    )
    assert result.triggered
    assert result.reason == "VWAP_STRETCH"


def test_tp_iv_crush_fires_early_big_profit():
    entry, expiry_ts = _times()
    now = entry + timedelta(hours=2)  # small fraction of the ~4-day hold
    row = _row(vwap=24000.0, bb_width=0.001, pcr_total=1.0)
    result = ow.orbiter_tp_check(
        "bull_put_spread",
        net_credit=100.0,
        current_pnl=60.0,
        row=row,
        spot=24010.0,
        entry_ts=entry,
        expiry_ts=expiry_ts,
        now_ts=now,
    )
    assert result.triggered
    assert result.reason == "IV_CRUSH"


def test_tp_pcr_divergence_only_exits_winners():
    entry, expiry_ts = _times()
    now = entry + timedelta(days=2)
    row = _row(vwap=24000.0, bb_width=0.001, pcr_total=1.4)
    result = ow.orbiter_tp_check(
        "bull_put_spread",
        net_credit=100.0,
        current_pnl=5.0,
        row=row,
        spot=24010.0,
        entry_ts=entry,
        expiry_ts=expiry_ts,
        now_ts=now,
    )
    assert result.triggered
    assert result.reason == "PCR_DIVERGENCE"


def test_tp_decay_80_fires_late_in_hold():
    entry, expiry_ts = _times()
    now = entry + timedelta(days=3)
    row = _row(vwap=24000.0, bb_width=0.001, pcr_total=1.0)
    result = ow.orbiter_tp_check(
        "bull_put_spread",
        net_credit=100.0,
        current_pnl=85.0,
        row=row,
        spot=24010.0,
        entry_ts=entry,
        expiry_ts=expiry_ts,
        now_ts=now,
    )
    assert result.triggered
    assert result.reason == "DECAY_80"


def test_tp_no_trigger_when_nothing_hit():
    entry, expiry_ts = _times()
    now = entry + timedelta(hours=3)
    row = _row(vwap=24000.0, bb_width=0.001, pcr_total=1.0)
    result = ow.orbiter_tp_check(
        "bull_put_spread",
        net_credit=100.0,
        current_pnl=10.0,
        row=row,
        spot=24010.0,
        entry_ts=entry,
        expiry_ts=expiry_ts,
        now_ts=now,
    )
    assert not result.triggered


# ── _read_enriched_row (sqlite I/O) ────────────────────────────────────────


def test_read_enriched_row_returns_latest_row_for_today(tmp_path, monkeypatch):
    db_path = tmp_path / "capture_nifty.sqlite"
    con = sqlite3.connect(str(db_path))
    con.execute("""CREATE TABLE market_data_enriched (
        timestamp TEXT, instrument TEXT, adx REAL, vwap REAL, bb_width REAL,
        cpr_width REAL, cpr_width_pct REAL, pcr_total REAL, max_pain_strike INTEGER, atr REAL)""")
    con.execute("""CREATE TABLE market_data_multitf (
        timestamp TEXT, instrument TEXT, timeframe_min INTEGER,
        bb_upper REAL, bb_lower REAL, atr REAL)""")
    today = date.today().isoformat()
    con.execute(
        "INSERT INTO market_data_enriched VALUES (?,?,?,?,?,?,?,?,?,?)",
        (f"{today}T10:00:00", "NIFTY", 18.0, 24000.0, 0.02, None, 0.3, 1.0, 24050, 22.0),
    )
    con.execute(
        "INSERT INTO market_data_multitf VALUES (?,?,?,?,?,?)",
        (f"{today}T00:00:00", "NIFTY", 1440, 24300.0, 23700.0, 30.0),
    )
    con.commit()
    con.close()

    monkeypatch.setattr(ow, "get_sqlite_capture_path", lambda instrument: db_path)
    row = ow._read_enriched_row("NIFTY", date.today())
    assert row is not None
    assert row["adx"] == 18.0
    assert row["bb_width"] == 0.02
    assert row["atr_daily"] == 30.0


def test_read_enriched_row_returns_none_when_missing(tmp_path, monkeypatch):
    db_path = tmp_path / "capture_nifty.sqlite"
    con = sqlite3.connect(str(db_path))
    con.execute("""CREATE TABLE market_data_enriched (
        timestamp TEXT, instrument TEXT, adx REAL)""")
    con.execute("""CREATE TABLE market_data_multitf (
        timestamp TEXT, instrument TEXT, timeframe_min INTEGER, bb_upper REAL, bb_lower REAL, atr REAL)""")
    con.commit()
    con.close()
    monkeypatch.setattr(ow, "get_sqlite_capture_path", lambda instrument: db_path)
    assert ow._read_enriched_row("NIFTY", date.today()) is None


# ── weekly_ic_pilot_orbiter smoke test (forced dates, BS-fallback only) ────


def _synthetic_closes(today: date) -> pd.Series:
    """20+126 days of mildly-trending closes ending exactly at `today`, high
    enough realized vol on the last 20d to clear the vol-filter."""
    days = pd.date_range(end=today, periods=200, freq="B").date
    rng = np.random.default_rng(42)
    rets = rng.normal(0, 0.003, size=len(days))
    rets[-20:] = rng.normal(0, 0.02, size=20)  # spike recent vol above trailing median
    closes = 24000.0 * np.exp(np.cumsum(rets))
    return pd.Series(closes, index=days)


def test_try_enter_skips_on_low_vol_regime(tmp_path, monkeypatch):
    """_try_enter's own gating is now vol-filter + gate1/gate3 (no weekday
    check — that moved to _choose_next_instrument's expiry-alternation logic,
    outside this function). Flat synthetic closes -> RV <= its own trailing
    median -> SKIP low_vol_regime, same gate NIFTY always uses (SENSEX bypasses
    it, see the SENSEX branch above this test)."""
    monkeypatch.setattr(wip, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(wip, "LEDGER_PATH", tmp_path / "ledger.jsonl")
    monday = date(2026, 7, 20)
    flat_closes = pd.Series([24000.0] * 200, index=pd.date_range(end=monday, periods=200, freq="D").date)
    event = wip._try_enter(
        "NIFTY",
        flat_closes,
        monday,
        datetime.combine(monday, time(10, 0)),
    )
    assert event["action"] == "SKIP"
    assert event["reason"] in ("low_vol_regime", "insufficient_history")


def test_try_enter_skips_without_enriched_data(tmp_path, monkeypatch):
    monkeypatch.setattr(wip, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(wip, "LEDGER_PATH", tmp_path / "ledger.jsonl")
    monkeypatch.setattr(wip, "_read_enriched_row", lambda instrument, today: None)
    friday = date(2026, 7, 17)
    event = wip._try_enter(
        {"open_cycle": None},
        _synthetic_closes(friday),
        friday,
        datetime.combine(friday, time(15, 20)),
    )
    assert event["action"] == "SKIP"
    assert event["reason"] == "no_enriched_data"


def test_try_enter_opens_directional_spread_via_bs_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(wip, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(wip, "LEDGER_PATH", tmp_path / "ledger.jsonl")
    friday = date(2026, 7, 17)
    expiry = date(2026, 7, 21)
    monkeypatch.setattr(wip, "resolve_weekly_expiry", lambda index, now: expiry)
    monkeypatch.setattr(
        wip, "_read_enriched_row", lambda instrument, today: _row(adx=15.0, pcr_total=1.0)
    )
    monkeypatch.setattr(wip, "_resolve_two_legs", lambda *a, **k: {"short": None, "hedge": None})
    monkeypatch.setattr(wip, "_flattrade_session", lambda: None)

    now = datetime.combine(friday, time(15, 20))
    event = wip._try_enter("NIFTY", _synthetic_closes(friday), friday, now)

    assert event["action"] == "ENTER"
    cycle = event["cycle"]
    assert cycle["structure"] in ("bull_put_spread", "bear_call_spread")
    side_name = wip._SIDE_FOR_STRUCTURE[cycle["structure"]]
    side = cycle[side_name]
    assert side["pricing_source"] == "bs_fallback"
    assert side["entry_credit"] > 0


def test_mark_open_cycle_forces_expiry_exit(tmp_path, monkeypatch):
    monkeypatch.setattr(wip, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(wip, "LEDGER_PATH", tmp_path / "ledger.jsonl")
    monkeypatch.setattr(wip, "_read_enriched_row", lambda instrument, today: None)
    monkeypatch.setattr(wip, "_flattrade_session", lambda: None)

    entry_date = date(2026, 7, 17)
    expiry = date(2026, 7, 21)
    tuesday = expiry
    cycle = {
        "instrument": "NIFTY",
        "entry_date": entry_date.isoformat(),
        "entry_ts": datetime.combine(entry_date, time(15, 20)).isoformat(),
        "expiry": expiry.isoformat(),
        "structure": "bull_put_spread",
        "phase": "DIRECTIONAL_ANCHOR",
        "spot_entry": 24000.0,
        # short=23700/hedge=23550 PE, spot pinned at 23650 -> intrinsic value=50,
        # strictly between pt_level(20) and sl_level(100) so only EXPIRY can fire.
        "put": {
            "short_k": 23700,
            "hedge_k": 23550,
            "opt_type": "PE",
            "legs": {},
            "sigma": 0.15,
            "entry_credit": 50.0,
            "entry_short_ltp": 80.0,
            "dynamic_sl": 110.0,
            "pricing_source": "bs_fallback",
            "entry_leg_prices": None,
        },
        "call": None,
    }
    state = {"open_cycle": cycle}
    closes = pd.Series([23650.0], index=[tuesday])
    event = wip._mark_open_cycle(
        state, cycle, closes, tuesday, datetime.combine(tuesday, time(15, 20))
    )

    assert event["action"] == "EXIT"
    assert state["open_cycle"] is None
    assert event["exits"][0]["reason"] == "EXPIRY"
