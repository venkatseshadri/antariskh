"""ORBITER v3.0 specs, multi-day-adapted for NEUTRON's monthly NIFTY+SENSEX iron condor.

Ports the same 5 module specs retrofitted into ATOM (Tier 1, intraday) and
PROTON+ (Tier 2, weekly) — Multi-Gated Entry, ATR Trailing Stop, Dynamic
Take-Profit, Dynamic Legging (see atom/src/atom/orbiter.py) — into a monthly
hold with parallel NIFTY and SENSEX streams. No dynamic DTE selection or
index-switching; each stream enters and manages independently off its own
enriched market data against its own monthly expiry.

Key difference from orbiter_weekly.py: instrument-aware STRIKE_GAP (50 for
NIFTY, 100 for SENSEX) and SENSEX data reads from capture_sensex.sqlite
instead of capture_nifty.sqlite. Enricher tables (market_data_enriched /
market_data_multitf) are identical in schema across instruments.

Data source (read-only, mode=ro): same shared capture SQLite ATOM's Penguin
pipeline writes to — gates fail CLOSED on missing rows, TP/TSL fail OPEN.

No physical ORBITER doc01-05 file exists anywhere in the repo — "spec" is
atom/src/atom/orbiter.py's actual implementation.
"""

from __future__ import annotations

import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

sys.path.insert(0, "/home/trading_ceo/atom/src")
from atom.orbiter import (  # noqa: E402
    _gate1_regime_core,
    _gate1_tiger_override_core,
)

from config.sqlite_schema import get_sqlite_capture_path

ORBITER_CFG = {
    "gate1.adx.max": 25,
    "gate1.cpr_wide_pct_min": 0.25,  # reverted 07-18 recalibration attempt — see orbiter_weekly.py's gate1_regime for rationale.
    "gate1.cpr_wide_min": 0.008,
    "gate1.bb_width_wide_min": 0.003,
    "gate1.structural_window_end": "09:45",  # ADX(14) warm-up (2x14 bars): before this, Gate1 leans on CPR (07-18, revised 07-19)
    "gate1.structural_window_adx_ceiling": 60.0,  # even pre-warmup, block an obvious sustained trend (07-19)
    "gate1.tiger.time_gate": "10:00",
    "gate1.tiger.adx_ceiling": 40.0,
    "gate3.pcr.bull_div_thr": 0.75,
    "gate3.pcr.bear_div_thr": 1.25,
    "phase2.adx.max": 20,
    "phase2.pcr.flat.low": 0.85,
    "phase2.pcr.flat.high": 1.15,
    "tp.vwap_stddev": 2.5,
    "tp.iv_crush.profit_pct": 55,
    "tp.iv_crush.time_pct": 25,
    "tp.decay_target_pct": 80,
    "tsl.atr_multiplier": 1.5,
    "tsl.ratchet.premium_drop_pct": 25,
    "tsl.ratchet.atr_fraction": 0.5,
    "tsl.catastrophe.above_pct": 50,
}


def _f(x) -> float | None:
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _read_enriched_row(instrument: str = "NIFTY", today: date | None = None) -> dict | None:
    """Latest market_data_enriched + daily market_data_multitf row for `today`.

    Read-only (mode=ro) against the shared capture SQLite — same isolation
    pattern as monthly_ic_pilot.py's _live_daily_closes(). Returns None if
    no enriched row exists for `today` (enricher down/not yet run today) —
    callers must fail closed on entry gates, fail open on TP/TSL extras.

    Fallback: if today's enriched data is not yet available, falls back to
    yesterday's latest enriched row with `_stale_fallback=True`."""
    today = today or date.today()
    day_prefix = today.isoformat()
    path = get_sqlite_capture_path(instrument)
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        row = con.execute(
            "SELECT * FROM market_data_enriched WHERE instrument=? "
            "AND timestamp LIKE ? ORDER BY timestamp DESC LIMIT 1",
            (instrument, f"{day_prefix}%"),
        ).fetchone()
        if row is not None:
            out = dict(row)
            daily = con.execute(
                "SELECT bb_upper, bb_lower, atr FROM market_data_multitf "
                "WHERE instrument=? AND timeframe_min=1440 AND timestamp LIKE ? "
                "ORDER BY timestamp DESC LIMIT 1",
                (instrument, f"{day_prefix}%"),
            ).fetchone()
            if daily is not None and daily["atr"] is not None:
                out["atr_daily"] = daily["atr"]
            out["_stale_fallback"] = False
            return out

        yesterday = today - timedelta(days=1)
        yday_prefix = yesterday.isoformat()
        row = con.execute(
            "SELECT * FROM market_data_enriched WHERE instrument=? "
            "AND timestamp LIKE ? ORDER BY timestamp DESC LIMIT 1",
            (instrument, f"{yday_prefix}%"),
        ).fetchone()
        if row is None:
            return None
        out = dict(row)
        y_daily = con.execute(
            "SELECT bb_upper, bb_lower, atr FROM market_data_multitf "
            "WHERE instrument=? AND timeframe_min=1440 AND timestamp LIKE ? "
            "ORDER BY timestamp DESC LIMIT 1",
            (instrument, f"{yday_prefix}%"),
        ).fetchone()
        if y_daily is not None and y_daily["atr"] is not None:
            out["atr_daily"] = y_daily["atr"]
        out["_stale_fallback"] = True
        return out
    finally:
        con.close()


# ── 3-Gate Entry ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GateResult:
    passed: bool
    gate: str
    reason: str
    details: dict = field(default_factory=dict)


def gate1_regime(row: dict) -> GateResult:
    """Gate 1: Regime Filter — thin adapter over the shared core in
    atom/src/atom/orbiter.py (centralized 2026-07-19; see
    _gate1_regime_core's docstring there for the full history)."""
    return _gate1_regime_core(row, row.get("timestamp") or "", ORBITER_CFG)


def gate1_tiger_override(row: dict, g1: GateResult, bar_ts: str | None = None) -> GateResult:
    """Monday-gap tiger fencing — thin adapter over the shared core in
    atom/src/atom/orbiter.py (centralized 2026-07-19)."""
    return _gate1_tiger_override_core(row, g1, bar_ts or "", ORBITER_CFG, structure_label="IRON_CONDOR")


def gate3_entry_abort(row: dict) -> GateResult:
    """Gate 3: PCR-divergence entry-abort check."""
    pcr = _f(row.get("pcr_total"))
    if pcr is None:
        return GateResult(True, "GATE3_ENGINE", "PASSED: no PCR data (skip gate)", {})
    bull_div = pcr < ORBITER_CFG["gate3.pcr.bull_div_thr"]
    bear_div = pcr > ORBITER_CFG["gate3.pcr.bear_div_thr"]
    if bull_div:
        return GateResult(False, "GATE3_ENGINE", f"PCR={pcr:.2f} < bull_div — ABORT", {"pcr": pcr})
    if bear_div:
        return GateResult(False, "GATE3_ENGINE", f"PCR={pcr:.2f} > bear_div — ABORT", {"pcr": pcr})
    return GateResult(True, "GATE3_ENGINE", f"PASSED: PCR={pcr:.2f} within range", {"pcr": pcr})


@dataclass(frozen=True)
class StrikeMap:
    put_short: int
    put_hedge: int
    call_short: int
    call_hedge: int
    vwap: float
    bb_upper: float | None
    bb_lower: float | None
    max_pain: int | None
    atm: int


def gate2_strikes(row: dict, spot: float, wing_strikes: int = 3, step: int = 50) -> StrikeMap:
    """Gate 2: anchor condor boundaries off real BB (multitf daily) if present,
    plus VWAP/MaxPain. `step` must be 50 for NIFTY, 100 for SENSEX."""
    atm = round(spot / step) * step
    vwap = _f(row.get("vwap")) or spot
    bb_width = _f(row.get("bb_width"))

    if row.get("bb_upper_real") is not None:
        bb_upper, bb_lower = _f(row["bb_upper_real"]), _f(row["bb_lower_real"])
    elif bb_width and bb_width > 0:
        bb_upper, bb_lower = spot * (1 + bb_width / 2), spot * (1 - bb_width / 2)
    else:
        bb_upper, bb_lower = None, None

    max_pain_raw = _f(row.get("max_pain_strike"))
    max_pain = int(max_pain_raw) if max_pain_raw else None

    def _nearest(target: float) -> int:
        return round(target / step) * step

    if bb_upper and bb_lower:
        call_short = _nearest(bb_upper) + step
        put_short = _nearest(bb_lower) - step
    else:
        call_short = atm + wing_strikes * step
        put_short = atm - wing_strikes * step

    call_short = max(call_short, atm + wing_strikes * step)
    put_short = min(put_short, atm - wing_strikes * step)
    call_hedge = call_short + wing_strikes * step
    put_hedge = put_short - wing_strikes * step

    if max_pain is not None and max_pain != atm:
        if max_pain > atm:
            call_short = max(call_short, max_pain + wing_strikes * step)
            call_hedge = call_short + wing_strikes * step
        else:
            put_short = min(put_short, max_pain - wing_strikes * step)
            put_hedge = put_short - wing_strikes * step

    return StrikeMap(
        put_short, put_hedge, call_short, call_hedge, vwap, bb_upper, bb_lower, max_pain, atm
    )


# ── Dynamic Legging Phase Machine ──────────────────────────────────────────


def phase_machine_direction(row: dict, spot: float) -> str:
    """Phase 1: directional anchor via VWAP vs spot."""
    vwap = _f(row.get("vwap"))
    if vwap and spot > vwap * 1.002:
        return "bear_call_spread"
    if vwap and spot < vwap * 0.998:
        return "bull_put_spread"
    return "bull_put_spread"


def consolidation_trigger(row: dict, structure: str, short_strike: float, spot: float) -> bool:
    """Phase 2: fire MORPH_ADD when ADX<20, PCR flat, short strike unbreached."""
    adx = _f(row.get("adx"))
    if adx is None or adx >= ORBITER_CFG["phase2.adx.max"]:
        return False
    pcr = _f(row.get("pcr_total"))
    pcr_ok = True
    if pcr is not None:
        pcr_ok = ORBITER_CFG["phase2.pcr.flat.low"] <= pcr <= ORBITER_CFG["phase2.pcr.flat.high"]
    breached = spot <= short_strike if structure == "bull_put_spread" else spot >= short_strike
    return pcr_ok and not breached


def asymmetric_breakage_trigger(structure: str, short_strike: float, spot: float) -> bool:
    """Phase 3: has the short strike been breached by spot."""
    return spot <= short_strike if structure == "bull_put_spread" else spot >= short_strike


# ── ORBITER TSL (ATR-based, ratchets down only) ────────────────────────────


def orbiter_initial_tsl(
    short_entry_ltp: float, atr_value: float | None, sl_pct_fallback: float = 35.0
) -> float:
    m = ORBITER_CFG["tsl.atr_multiplier"]
    if atr_value and atr_value > 0:
        return round(short_entry_ltp + m * atr_value, 2)
    return round(short_entry_ltp * (1 + sl_pct_fallback / 100.0), 2)


def orbiter_tsl_ratchet(
    current_sl: float, short_entry_ltp: float, short_current_ltp: float, atr_value: float | None
) -> float:
    if short_entry_ltp <= 0:
        return current_sl
    drop_pct = (short_entry_ltp - short_current_ltp) / short_entry_ltp
    threshold = ORBITER_CFG["tsl.ratchet.premium_drop_pct"] / 100.0
    atr = atr_value or 0.0
    if drop_pct >= threshold and atr > 0:
        new_sl = round(current_sl - ORBITER_CFG["tsl.ratchet.atr_fraction"] * atr, 2)
        return max(new_sl, short_entry_ltp)
    return current_sl


def orbiter_catastrophe_stop(dynamic_sl: float) -> float:
    return round(dynamic_sl * (1 + ORBITER_CFG["tsl.catastrophe.above_pct"] / 100.0), 2)


# ── 5-Point Take-Profit Priority Array (multi-day elapsed time) ────────────


@dataclass(frozen=True)
class OrbiterExit:
    triggered: bool
    reason: str | None
    pnl: float | None
    detail: str = ""


def orbiter_tp_check(
    structure: str,
    net_credit: float,
    current_pnl: float | None,
    row: dict,
    spot: float,
    entry_ts: datetime,
    expiry_ts: datetime,
    now_ts: datetime,
) -> OrbiterExit:
    """Same 5-point priority order as ATOM/PROTON+, EOD_HARD dropped (monthly
    expiry is the hard stop, caller runs EXPIRY check before this each tick).
    `elapsed`/`total_duration` span the multi-week hold window."""
    # P1: Statistical Stretch (VWAP +/- 2.5 sigma)
    vwap = _f(row.get("vwap"))
    if vwap:
        bb_width = _f(row.get("bb_width")) or 0.0
        sigma_est = vwap * bb_width / 4 if bb_width else vwap * 0.01
        thr = ORBITER_CFG["tp.vwap_stddev"]
        upper, lower = vwap + thr * sigma_est, vwap - thr * sigma_est
        if spot >= upper or spot <= lower:
            return OrbiterExit(
                True,
                "VWAP_STRETCH",
                current_pnl,
                f"spot {spot} >= {upper:.0f} or <= {lower:.0f} ({thr}sigma)",
            )

    # P3: IV Crush (>=55% profit in <25% of the hold elapsed)
    if current_pnl is not None and net_credit > 0:
        profit_pct = current_pnl / net_credit * 100
        total_duration = max((expiry_ts - entry_ts).total_seconds(), 1)
        elapsed = (now_ts - entry_ts).total_seconds()
        time_pct = elapsed / total_duration * 100
        if (
            profit_pct >= ORBITER_CFG["tp.iv_crush.profit_pct"]
            and time_pct < ORBITER_CFG["tp.iv_crush.time_pct"]
        ):
            return OrbiterExit(
                True,
                "IV_CRUSH",
                current_pnl,
                f"{profit_pct:.0f}% profit in {time_pct:.0f}% of hold",
            )

    # P4: PCR Divergence (smart-money reversal, only exits winners)
    pcr = _f(row.get("pcr_total"))
    if pcr is not None and current_pnl is not None and current_pnl > 0:
        bull_div = pcr < ORBITER_CFG["gate3.pcr.bull_div_thr"]
        bear_div = pcr > ORBITER_CFG["gate3.pcr.bear_div_thr"]
        if structure == "bull_put_spread" and bear_div:
            return OrbiterExit(
                True, "PCR_DIVERGENCE", current_pnl, f"PCR={pcr:.2f} bear_div, bull put profitable"
            )
        if structure == "bear_call_spread" and bull_div:
            return OrbiterExit(
                True, "PCR_DIVERGENCE", current_pnl, f"PCR={pcr:.2f} bull_div, bear call profitable"
            )

    # P5: 80% decay
    if current_pnl is not None and net_credit > 0:
        decay_pct = current_pnl / net_credit * 100
        if decay_pct >= ORBITER_CFG["tp.decay_target_pct"]:
            return OrbiterExit(
                True, "DECAY_80", current_pnl, f"{decay_pct:.0f}% of net credit captured"
            )

    return OrbiterExit(False, None, current_pnl)
