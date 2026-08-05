"""NEUTRON-ORBITER — ORBITER v3.0 specs on NEUTRON's monthly iron condor.

Usage:
    python3 monthly_ic_pilot_orbiter.py NIFTY
    python3 monthly_ic_pilot_orbiter.py SENSEX

One instrument per process — run as separate cron jobs. Each instrument has its
own state file and ledger, zero overlap with the other or with vanilla NEUTRON.

Same design as ATOM+/PROTON+: Multi-Gated Entry, ATR Trailing Stop, Dynamic
Take-Profit, Dynamic Legging. Enters any trading day vol-filter passes. Static
PT (60% credit) / SL (1.0x credit) backstop always active.

Real-order path (2026-07-27, Board-gated, DRY by default): LIVE_ENABLED gates
actual Flattrade order placement, same on/off pattern as proton_live.py's
PROTON_LIVE_TRADING. Deliberately NOT parallel to PROTON's dual-index
alternation — NIFTY and SENSEX are fully independent processes here (own
cron, own state, own ledger), matching this file's existing paper design;
neither instrument's entry depends on the other's expiry. Broker is Flattrade,
not Shoonya — proton_live.py's own docstring flags Flattrade order placement
as never tested in this codebase (that's WHY PROTON switched to Shoonya);
this file is the first real test of that path, so treat LIVE_ENABLED=True
here as materially higher-risk than PROTON's proven Shoonya path until it has
a verified live fill.
"""

import inspect
import json
import os
import sys
import numpy as np
from datetime import date, datetime, time
from pathlib import Path

from config.lot_size import get_lot_size
from config.token_resolver import resolve_monthly_expiry, TokenResolver
from backtester import black_scholes_call, black_scholes_put
from monthly_ic_pilot import (
    combined_daily_closes,
    trailing_rv,
    trailing_median_rv,
    fo_market_is_open,
    _leg_ltp,
    check_account_margin,
    get_broker_session,
    place_leg,
    place_resting_sl,
    cancel_order,
    cancel_resting_sl,
    broker_confirms_flat,
    resting_sl_fired_unreconciled,
    confirm_shoonya_fill,
    fill_rejected,
    nucleus_ceiling,
    shoonya_order_status,
    FILL_FAILURE_STATUSES,
    BUY,
    SELL,
    MAX_LOTS,
    SL_MULT,
    PT_FRAC,
    RISK_FREE_RATE,
)
from orbiter_monthly import (
    ORBITER_CFG,
    _read_enriched_row,
    _f,
    gate3_entry_abort,
    gate2_strikes,
    phase_machine_direction,
    consolidation_trigger,
    asymmetric_breakage_trigger,
    orbiter_initial_tsl,
    orbiter_catastrophe_stop,
    orbiter_tp_check,
)

# Gate1 (ADX+CPR regime filter, shared with PROTON+/HYDROGEN+ via
# orbiter_monthly.gate1_regime / atom.orbiter._gate1_regime_core) removed
# for NEUTRON+ entirely, 2026-07-29 (Board override). Both its inputs are
# intraday-scoped and don't map to a 30-day hold: CPR is a single day's
# H/L/C pivot snapshot ("breakout day likely"), and ADX(14) here is
# computed over 1-MINUTE bars (confirmed in enrichers/lib/buffer.py — a
# ~14-minute lookback), not the 5-min ADX atom.orbiter's docstring
# describes for ATOM's original intraday use case. Neither says anything
# meaningful about the coming month. NEUTRON+'s own vol-filter
# (trailing_rv 20d vs trailing_median_rv 126d, checked earlier in
# _try_enter) is the genuinely monthly-scale regime signal; gate3 (PCR)
# remains as the entry-day sanity check.

WING_STRIKES = 2
LIVE_ENABLED = os.environ.get("NEUTRON_LIVE_TRADING") == "YES_REAL_MONEY"
BROKER = os.environ.get("NEUTRON_BROKER", "FLATTRADE").upper()
NUCLEUS_TIER = "T4_NEUTRON"

# Roll-in: once a leg's OWN premium has decayed this much from its own entry
# price, close it and open its replacement one step closer to ATM (PE: strike
# +step; CE: strike -step). Independent per leg — short and hedge can roll at
# different times, wing width is allowed to float rather than being kept in
# sync (Board decision 2026-08-01). No cap on rolls per cycle.
SHORT_LEG_ROLL_DECAY_PCT = 0.60
HEDGE_LEG_ROLL_DECAY_PCT = 0.50

INSTRUMENT_PARAMS = {
    # Lot sizes now sourced live from scrip_master (config/lot_size.py),
    # not hardcoded — see that module's docstring for why (2026-07-30, the
    # 75/10-vs-65/20 staleness that hit this file 2026-07-29 recurred
    # independently in 3 sibling files before this fix).
    "NIFTY": {"step": 50, "lot": get_lot_size("NIFTY")},
    "SENSEX": {"step": 100, "lot": get_lot_size("SENSEX")},
}

_OPT_TYPE = {"bull_put_spread": "PE", "bear_call_spread": "CE"}
_OTHER_STRUCTURE = {"bull_put_spread": "bear_call_spread", "bear_call_spread": "bull_put_spread"}
_SIDE_FOR_STRUCTURE = {"bull_put_spread": "put", "bear_call_spread": "call"}


def combined_daily_closes_sensex() -> "pd.Series":  # noqa: F821
    import pandas as pd
    import sqlite3
    from config.sqlite_schema import get_sqlite_capture_path

    path = get_sqlite_capture_path("SENSEX")
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT timestamp, close FROM market_data "
            "WHERE instrument='SENSEX' AND close > 0 ORDER BY timestamp"
        ).fetchall()
    finally:
        con.close()
    if not rows:
        return pd.Series(dtype=float)
    df = pd.DataFrame(rows, columns=["timestamp", "close"])
    df["day"] = pd.to_datetime(df["timestamp"]).dt.date
    return df.groupby("day")["close"].last()


def _resolve_two_legs_monthly(
    instrument: str, expiry: date, spot: float, short_k: int, hedge_k: int, opt_type: str
) -> dict:
    params = INSTRUMENT_PARAMS[instrument]
    step = params["step"]
    atm = round(spot / step) * step
    atm_range = int(np.ceil(max(abs(atm - short_k), abs(atm - hedge_k)) / step)) + 1
    tr = TokenResolver(
        nifty_spot=spot if instrument == "NIFTY" else None,
        sensex_spot=spot if instrument == "SENSEX" else None,
    )
    if instrument == "NIFTY":
        rows = tr.resolve_weekly_nifty_for_expiry(expiry, atm_range=atm_range)
    else:
        rows = tr.resolve_monthly_sensex_for_expiry(expiry, atm_range=atm_range)
    by_key = {(row["strike"], row["opt_type"]): row for row in rows}
    return {"short": by_key.get((short_k, opt_type)), "hedge": by_key.get((hedge_k, opt_type))}


def _resolve_one_leg_monthly(instrument: str, expiry: date, spot: float, strike: int, opt_type: str) -> dict | None:
    params = INSTRUMENT_PARAMS[instrument]
    step = params["step"]
    atm = round(spot / step) * step
    atm_range = int(np.ceil(abs(atm - strike) / step)) + 1
    tr = TokenResolver(
        nifty_spot=spot if instrument == "NIFTY" else None,
        sensex_spot=spot if instrument == "SENSEX" else None,
    )
    if instrument == "NIFTY":
        rows = tr.resolve_weekly_nifty_for_expiry(expiry, atm_range=atm_range)
    else:
        rows = tr.resolve_monthly_sensex_for_expiry(expiry, atm_range=atm_range)
    for row in rows:
        if row["strike"] == strike and row["opt_type"] == opt_type:
            return {kk: row[kk] for kk in ("exchange", "token", "tsym", "strike", "opt_type")}
    return None


def _leg_decay_pct(entry_price: float, current_price: float) -> float:
    if entry_price <= 0:
        return 0.0
    return (entry_price - current_price) / entry_price


def _hedge_cash_shortfall(hedge_price: float | None, qty: int, cash_avail: float | None) -> dict | None:
    """None if the hedge (option-BUY) leg's cost is covered by real cash
    alone, else a dict with hedge_cost/cash_avail for the caller to log.
    Buying an option requires cash, not collateral — real Shoonya rejection
    hit live 2026-07-29 (RED:RULE:{Allow CAC credit but disallow collateral
    and daylong cash for option buy}); see check_account_margin's docstring
    for why cash_avail must come from its cash-only return, not avail.
    2026-08-02."""
    if hedge_price is None:
        return None
    hedge_cost = hedge_price * qty
    if cash_avail is None or hedge_cost > cash_avail:
        return {"hedge_cost": hedge_cost, "cash_avail": cash_avail}
    return None


def _roll_leg_live(
    api, side: dict, leg_name: str, instrument: str, expiry: date, S: float,
    qty: int, atr: float | None, remarks_prefix: str,
) -> dict:
    """Close one leg (short or hedge) and open its replacement one step
    closer to ATM (PE: strike+step; CE: strike-step) — independent of the
    other leg, wing width allowed to float. Rebases
    side['entry_leg_prices'][leg_name] and side['entry_credit'] to the fresh
    pair so PT/STATIC_SL/DECAY_80/IV_CRUSH measure from the new baseline
    going forward. If the SHORT leg rolled, also rebases entry_short_ltp and
    restarts the ATR trailing stop (fresh dynamic_sl, fresh resting SL-LMT
    at the broker) off the new strike — same real-order sequencing
    discipline as _enter_side_live/_exit_side_live (close before open, never
    leave a naked short mid-sequence)."""
    result = {"stage": None, "close": {}, "open": {}}
    old_leg = side["legs"][leg_name]
    step = INSTRUMENT_PARAMS[instrument]["step"]
    opt_type = old_leg["opt_type"]
    new_strike = old_leg["strike"] + step if opt_type == "PE" else old_leg["strike"] - step

    new_leg = _resolve_one_leg_monthly(instrument, expiry, S, new_strike, opt_type)
    if new_leg is None:
        result["stage"] = "failed_no_new_strike_token"
        return result

    close_action = BUY if leg_name == "short" else SELL
    open_action = SELL if leg_name == "short" else BUY

    if leg_name == "short" and side.get("sl_order_ids", {}).get("short"):
        c = cancel_order(api, side["sl_order_ids"]["short"])
        result["sl_cancel"] = {"ok": c.ok, "raw": c.raw}

    close_price = _leg_ltp(api, old_leg["exchange"], old_leg["token"])
    r = place_leg(
        api, close_action, old_leg["exchange"], old_leg["tsym"], qty, close_price,
        remarks=f"{remarks_prefix}_ROLL_CLOSE_{leg_name}",
    )
    fc = confirm_shoonya_fill(r.norenordno, BROKER)
    result["close"] = {"ok": r.ok, "norenordno": r.norenordno, "fill_confirmation": fc}
    if not r.ok or fill_rejected(fc):
        result["stage"] = f"failed_close_{leg_name}"
        return result

    open_price = _leg_ltp(api, new_leg["exchange"], new_leg["token"])
    if open_action == BUY:
        # Rolling the hedge closes the old hedge (SELL, no cash needed) then
        # opens a new one (BUY, needs actual cash — same Shoonya rule as
        # entry/MORPH_ADD, see _hedge_cash_shortfall's docstring). The old
        # hedge is already closed at this point, so skipping here leaves the
        # short leg naked — same real stranding as a failed open, hence the
        # matching stage name so the caller's existing HALT_STRANDED_LEGS
        # check (stage.startswith("failed_open_")) catches it. 2026-08-03.
        _, _, roll_cash_avail = check_account_margin(api, BROKER)
        shortfall = _hedge_cash_shortfall(open_price, qty, roll_cash_avail)
        if shortfall is not None:
            result["stage"] = f"failed_open_{leg_name}_cash_insufficient"
            result["cash_shortfall"] = shortfall
            return result
    r = place_leg(
        api, open_action, new_leg["exchange"], new_leg["tsym"], qty, open_price,
        remarks=f"{remarks_prefix}_ROLL_OPEN_{leg_name}",
    )
    fc = confirm_shoonya_fill(r.norenordno, BROKER)
    result["open"] = {"ok": r.ok, "norenordno": r.norenordno, "fill_confirmation": fc}
    if not r.ok or fill_rejected(fc):
        result["stage"] = f"failed_open_{leg_name}_stranded_leg"
        return result

    side["legs"][leg_name] = new_leg
    if side.get("entry_leg_prices") is None:
        side["entry_leg_prices"] = {}
    side["entry_leg_prices"][leg_name] = open_price
    other_name = "hedge" if leg_name == "short" else "short"
    other_price = side["entry_leg_prices"].get(other_name)
    if other_price is not None:
        side["entry_credit"] = side["entry_leg_prices"]["short"] - side["entry_leg_prices"]["hedge"]

    if leg_name == "short":
        side["entry_short_ltp"] = open_price
        side["dynamic_sl"] = orbiter_initial_tsl(open_price, atr)
        sl_r = place_resting_sl(
            api, BUY, new_leg["exchange"], new_leg["tsym"], qty, side["dynamic_sl"],
            remarks=f"{remarks_prefix}_ROLL_SL",
        )
        result["new_sl"] = {"ok": sl_r.ok, "norenordno": sl_r.norenordno}
        side["sl_order_ids"] = {"short": sl_r.norenordno if sl_r.ok else None}

    result["stage"] = "complete"
    return result


def _side_value_bs(
    instrument: str, S: float, short_k: float, hedge_k: float, opt_type: str, T: float, sigma: float
) -> float:
    if T <= 0:
        if opt_type == "PE":
            return max(short_k - S, 0) - max(hedge_k - S, 0)
        return max(S - short_k, 0) - max(S - hedge_k, 0)
    bs = black_scholes_put if opt_type == "PE" else black_scholes_call
    return bs(S, short_k, T, RISK_FREE_RATE, sigma) - bs(S, hedge_k, T, RISK_FREE_RATE, sigma)


def _price_side(side: dict, S: float, T: float) -> tuple[float, str, dict | None]:
    legs = side.get("legs") or {}
    if legs.get("short") and legs.get("hedge"):
        api = get_broker_session(BROKER)
        if api is not None:
            short_ltp = _leg_ltp(api, legs["short"]["exchange"], legs["short"]["token"])
            hedge_ltp = _leg_ltp(api, legs["hedge"]["exchange"], legs["hedge"]["token"])
            if not (np.isnan(short_ltp) or np.isnan(hedge_ltp)):
                return short_ltp - hedge_ltp, "real", {"short": short_ltp, "hedge": hedge_ltp}
    value = _side_value_bs(
        side.get("instrument", "NIFTY"),
        S,
        side["short_k"],
        side["hedge_k"],
        side["opt_type"],
        T,
        side["sigma"],
    )
    return value, "bs_fallback", None


def _open_side(
    instrument: str, structure: str, row: dict, S0: float, expiry: date, sigma: float, today: date
) -> dict:
    params = INSTRUMENT_PARAMS[instrument]
    T0 = max((expiry - today).days / 365, 1 / 365)
    smap = gate2_strikes(row, S0, wing_strikes=WING_STRIKES, step=params["step"], sigma=sigma, T=T0)
    opt_type = _OPT_TYPE[structure]
    short_k, hedge_k = (
        (smap.put_short, smap.put_hedge) if opt_type == "PE" else (smap.call_short, smap.call_hedge)
    )
    legs_raw = _resolve_two_legs_monthly(instrument, expiry, S0, short_k, hedge_k, opt_type)
    legs = {
        k: {kk: v[kk] for kk in ("exchange", "token", "tsym", "strike", "opt_type")}
        for k, v in legs_raw.items()
        if v is not None
    }
    side = {
        "instrument": instrument,
        "short_k": short_k,
        "hedge_k": hedge_k,
        "opt_type": opt_type,
        "legs": legs,
        "sigma": sigma,
    }
    value, pricing_source, leg_prices = _price_side(side, S0, T0)
    # atr_daily/atr are the UNDERLYING index's point-ATR (e.g. ~233 for NIFTY
    # at ~24000 spot), not the option premium's own ATR — orbiter_initial_tsl
    # adds it straight onto the rupee premium, off by ~2.6x, dimensionally
    # meaningless (no per-leg premium ATR or live delta is tracked anywhere
    # in this pipeline to convert index points -> premium rupees correctly).
    # Same wrong-timeframe/wrong-unit class as Gate1 ADX/CPR and Phase2 ADX
    # above — forced None here so orbiter_initial_tsl/orbiter_tsl_ratchet
    # fall back to their own dimensionally-correct pct-of-premium path
    # instead of a guessed conversion factor on live-money SL math. Real fix
    # needs per-leg premium-candle history or live delta, neither built yet
    # — see neutron_plus_open_issues_20260729 memory. 2026-08-02.
    atr = None
    entry_short_ltp = (
        leg_prices["short"]
        if leg_prices
        else (black_scholes_put if opt_type == "PE" else black_scholes_call)(
            S0, short_k, T0, RISK_FREE_RATE, sigma
        )
    )
    side.update(
        {
            "entry_credit": value,
            "entry_short_ltp": entry_short_ltp,
            "dynamic_sl": orbiter_initial_tsl(entry_short_ltp, atr),
            "pricing_source": pricing_source,
            "entry_leg_prices": leg_prices,
        }
    )
    return side


def _verify_real_entry(api, legs: dict, qty: int, margin_before: float | None) -> dict:
    """Cross-checks the account's actual position + available margin after
    placing entry orders — added 2026-08-05 after a real incident: Shoonya
    returned REST "stat: Ok" + real-looking order numbers for orders placed
    at 09:00 (before F&O market open at 09:15 — no pre-open session exists
    for derivatives), but broker order history later showed
    'Error Occurred : 5 "no data"' for every one of them. fill_confirmation
    was null too (the WS-based check), but fill_rejected(None) trusts the
    REST accept by design (reasonable for WS lag, wrong for a genuine silent
    drop) — nothing caught it. get_positions() is the account's actual
    current state; it can't be phantom the way a REST accept or a specific
    order's history lookup can still (per Shoonya's own docs, neither
    get_orderbook/get_tradebook/single_order_history take a date — they're
    today/session-scoped, so this check has to happen NOW, immediately
    after placement, not reconstructed later). Position match is the hard
    gate; margin consumption is a softer corroborating signal only (margin
    moves for other reasons too), logged but not blocking on its own."""
    try:
        positions = api.get_positions() or []
        position_readable = True
    except Exception:
        positions = []
        position_readable = False
    by_tsym = {p.get("tsym"): p for p in positions}
    hedge_qty = int(float(by_tsym.get(legs["hedge"]["tsym"], {}).get("netqty", 0) or 0))
    short_qty = int(float(by_tsym.get(legs["short"]["tsym"], {}).get("netqty", 0) or 0))
    position_ok = position_readable and hedge_qty == qty and short_qty == -qty

    try:
        _, avail_margin, _ = check_account_margin(api, BROKER)
    except Exception:
        avail_margin = None
    margin_consumed = (
        margin_before is not None and avail_margin is not None and avail_margin < margin_before
    )
    return {
        "position_ok": position_ok,
        "hedge_qty": hedge_qty,
        "short_qty": short_qty,
        "expected_qty": qty,
        "margin_before": margin_before,
        "margin_after": avail_margin,
        "margin_consumed": margin_consumed,
    }


def _enter_side_live(api, side: dict, qty: int, remarks_prefix: str) -> dict:
    """Place one side's directional 2-leg spread for real (hedge BUY first,
    then short SELL, then a resting SL-LMT on the short) — same sequencing
    as proton_live.py's _orbiter_enter_legs so a mid-sequence failure never
    leaves a naked short. Resting SL trigger = side['dynamic_sl'], the same
    ATR-trailing level the software poll already tracks (this file has no
    separate atr_sl_multiplier() concept; reusing dynamic_sl keeps the
    broker-side backstop consistent with whatever the software would exit
    at anyway)."""
    result = {"stage": None, "orders": {}, "sl_orders": {}}
    legs = side["legs"]
    entry_prices = side.get("entry_leg_prices") or {}
    _, margin_before, _ = check_account_margin(api, BROKER)

    leg = legs["hedge"]
    r = place_leg(
        api, BUY, leg["exchange"], leg["tsym"], qty,
        entry_prices.get("hedge", side["entry_credit"]), remarks=f"{remarks_prefix}_hedge",
    )
    fc = confirm_shoonya_fill(r.norenordno, BROKER)
    result["orders"]["hedge"] = {"ok": r.ok, "norenordno": r.norenordno, "raw": r.raw, "fill_confirmation": fc}
    if not r.ok or fill_rejected(fc):
        result["stage"] = "failed_hedge"
        return result

    leg = legs["short"]
    r = place_leg(
        api, SELL, leg["exchange"], leg["tsym"], qty,
        entry_prices.get("short", side["entry_short_ltp"]), remarks=f"{remarks_prefix}_short",
    )
    fc_short = confirm_shoonya_fill(r.norenordno, BROKER)
    result["orders"]["short"] = {"ok": r.ok, "norenordno": r.norenordno, "raw": r.raw, "fill_confirmation": fc_short}
    if not r.ok or fill_rejected(fc_short):
        result["stage"] = "failed_short_hedge_live"
        return result

    # Verification order (2026-08-05): WS first (already-flowing data,
    # zero extra API cost, checked once — see confirm_shoonya_fill's
    # docstring), REST position/margin check only as a fallback when the WS
    # didn't positively confirm both legs. reporttype=="Fill" is Shoonya's
    # own documented signal for a genuine execution (ShoonyaApi-py README,
    # get_singleorderhistory section) — stronger than `status` alone.
    fc_hedge = result["orders"]["hedge"]["fill_confirmation"]
    ws_confirmed = (
        bool(fc_hedge) and fc_hedge.get("reporttype") == "Fill"
        and bool(fc_short) and fc_short.get("reporttype") == "Fill"
    )
    if not ws_confirmed:
        verify = _verify_real_entry(api, legs, qty, margin_before)
        result["position_verify"] = verify
        if not verify["position_ok"]:
            hedge_real = verify["hedge_qty"] == qty
            short_real = verify["short_qty"] == -qty
            if hedge_real != short_real:
                # One real, one not — a genuine naked leg sitting at the
                # broker, same stranding class as a mid-sequence order
                # failure. Needs a human, not a retry.
                result["stage"] = "failed_naked_leg_position_mismatch"
            else:
                # Neither leg real (both phantom, or the position check
                # itself was unreadable) — nothing actually happened at the
                # broker, safe to just retry next tick like any other
                # failed entry.
                result["stage"] = "failed_phantom_fill_no_real_position"
            return result

    r = place_resting_sl(
        api, BUY, leg["exchange"], leg["tsym"], qty, side["dynamic_sl"], remarks=f"{remarks_prefix}_SL_short",
    )
    result["sl_orders"]["short"] = {"ok": r.ok, "norenordno": r.norenordno, "raw": r.raw}
    if not r.ok:
        result["stage"] = "complete_but_sl_failed"
    if result["stage"] is None:
        result["stage"] = "complete"
    return result


def _exit_side_live(api, side: dict, qty: int, exit_prices: dict | None, remarks_prefix: str) -> dict:
    """Close one side's 2 legs for real (short buyback first, then hedge
    sell). Cancels the resting SL first. Tracks legs already closed in
    side['legs_closed'] (mutated in place, persists across retries) so a
    retry after a short-succeeds/hedge-fails partial close never re-places
    the short a second time — same pattern as proton_live.py's
    _orbiter_exit_side."""
    result = {"stage": None, "orders": {}, "sl_cancel": {}}
    result["sl_cancel"] = cancel_resting_sl(api, side.get("sl_order_ids", {}))
    already_closed = side.setdefault("legs_closed", {})
    legs = side["legs"]
    for leg_name, action in (("short", BUY), ("hedge", SELL)):
        if leg_name in already_closed:
            result["orders"][leg_name] = {
                "ok": True, "norenordno": already_closed[leg_name], "skipped_already_closed": True,
            }
            continue
        leg = legs[leg_name]
        price = (exit_prices or {}).get(leg_name)
        if price is None:
            result["stage"] = f"failed_close_{leg_name}_no_price"
            return result
        r = place_leg(api, action, leg["exchange"], leg["tsym"], qty, price, remarks=f"{remarks_prefix}_CLOSE_{leg_name}")
        fc = confirm_shoonya_fill(r.norenordno, BROKER)
        result["orders"][leg_name] = {"ok": r.ok, "norenordno": r.norenordno, "raw": r.raw, "fill_confirmation": fc}
        if not r.ok or fill_rejected(fc):
            result["stage"] = f"failed_close_{leg_name}"
            return result
        already_closed[leg_name] = r.norenordno or True
    result["stage"] = "complete"
    return result


def _replace_resting_sl_live(api, side: dict, qty: int, new_trigger: float, remarks_prefix: str) -> dict:
    """Cancel the existing resting SL and place a new one at the ratcheted
    trigger. orbiter_tsl_ratchet() updates side['dynamic_sl'] in memory every
    tick, but the broker-side resting SL-LMT order placed at entry never
    moved to match — without this, the real backstop stays pinned at its
    original (looser) trigger forever while the software's own trailing
    stop tightens, so the two drift apart exactly when it matters most.
    Best-effort: if the replace leg fails, the OLD resting SL (if the cancel
    also failed) or nothing (if cancel succeeded but replace didn't) is left
    — logged either way, never silently dropped, but not blocking the tick."""
    result = {"cancel": None, "replace": None}
    old_ordno = side.get("sl_order_ids", {}).get("short")
    if old_ordno:
        c = cancel_order(api, old_ordno)
        result["cancel"] = {"ok": c.ok, "raw": c.raw}
    leg = side["legs"]["short"]
    r = place_resting_sl(
        api, BUY, leg["exchange"], leg["tsym"], qty, new_trigger, remarks=f"{remarks_prefix}_SL_replace",
    )
    result["replace"] = {"ok": r.ok, "norenordno": r.norenordno, "raw": r.raw}
    if r.ok:
        side.setdefault("sl_order_ids", {})["short"] = r.norenordno
    return result


def _monthly_bb(closes, today: date, period: int = 20) -> tuple[float | None, float | None, float | None]:
    """Real 20-*day* Bollinger Band + SMA anchor off daily closes (~1-month
    lookback, matching NEUTRON+'s ~27-day hold) — gate2_strikes' own bb_width,
    and phase_machine_direction/orbiter_tp_check's own vwap, both fall back to
    a ~20-*minute*/~3-hour rolling value from the enrichers/lib/buffer.py
    intraday IndicatorBuffer (bb_width~0.001 at real entry, 07-29), the same
    wrong-timeframe class of gap already documented and removed for Gate1's
    ADX/CPR above. BB found live 2026-07-31 checking why the call strike
    landed almost ATM; VWAP found 2026-08-02 (no daily-volume data exists in
    this pipeline, so the same 20d-close mid-band SMA doubles as the VWAP
    substitute — not volume-weighted, but timeframe-correct, which the old
    ~3hr rolling vwap wasn't). Feeds gate2_strikes / phase_machine_direction /
    orbiter_tp_check via row['bb_upper_real']/['bb_lower_real']/['vwap_real']
    (their first-priority branch), overriding the intraday value for
    NEUTRON+ only — orbiter_weekly.py/PROTON+/HYDROGEN+ untouched."""
    hist = closes[closes.index <= today]
    if len(hist) < period:
        return None, None, None
    window = hist.iloc[-period:]
    mid, std = float(window.mean()), float(window.std())
    return mid + 2 * std, mid - 2 * std, mid


def _with_monthly_bb(row: dict, closes, today: date) -> dict:
    bb_upper, bb_lower, vwap_real = _monthly_bb(closes, today)
    if bb_upper is None:
        return row
    return {**row, "bb_upper_real": bb_upper, "bb_lower_real": bb_lower, "vwap_real": vwap_real}


def _try_enter(instrument: str, closes, today: date, now: datetime) -> dict:
    entry_rv = trailing_rv(closes, today)
    median_rv = trailing_median_rv(closes, today)
    vol_pass = bool(not np.isnan(entry_rv) and not np.isnan(median_rv) and entry_rv > median_rv)

    if instrument == "SENSEX" and not vol_pass:
        # Paper-only: skip vol-filter for SENSEX (not enough history yet),
        # let ORBITER gates alone decide. Real-money would gate here.
        if np.isnan(entry_rv):
            entry_rv = 0.15
    elif not vol_pass:
        reason = (
            "insufficient_history"
            if (np.isnan(entry_rv) or np.isnan(median_rv))
            else "low_vol_regime"
        )
        event = {
            "instrument": instrument,
            "action": "SKIP",
            "reason": reason,
            "entry_rv": entry_rv,
            "median_rv": median_rv,
        }
        LOG(event)
        return event
    if entry_rv <= median_rv:
        event = {
            "instrument": instrument,
            "action": "SKIP",
            "reason": "low_vol_regime",
            "entry_rv": entry_rv,
            "median_rv": median_rv,
        }
        LOG(event)
        return event

    row = _read_enriched_row(instrument, today)
    if row is None:
        event = {"instrument": instrument, "action": "SKIP", "reason": "no_enriched_data"}
        LOG(event)
        return event
    if row.get("_stale_fallback"):
        LOG(
            {
                "instrument": instrument,
                "action": "STALE_ENRICHED_DATA",
                "note": "using yesterday's enriched row — today's not yet available",
            }
        )

    g3 = gate3_entry_abort(row)
    if not g3.passed:
        event = {"instrument": instrument, "action": "SKIP", "reason": g3.reason, "gate": g3.gate}
        LOG(event)
        return event

    row = _with_monthly_bb(row, closes, today)

    if LIVE_ENABLED and not fo_market_is_open(now):
        event = {"instrument": instrument, "action": "SKIP", "reason": "fo_market_not_open", "broker": BROKER}
        LOG(event)
        return event

    api = get_broker_session(BROKER) if LIVE_ENABLED else None
    if LIVE_ENABLED:
        if api is None:
            event = {"instrument": instrument, "action": "SKIP", "reason": "no_broker_session", "broker": BROKER}
            LOG(event)
            return event
        margin_ok, avail_margin, cash_avail = check_account_margin(api, BROKER)
        if not margin_ok:
            event = {
                "instrument": instrument,
                "action": "SKIP",
                "reason": "margin_insufficient",
                "avail_margin": avail_margin,
                "broker": BROKER,
            }
            LOG(event)
            return event

    expiry = resolve_monthly_expiry(instrument, now)
    S0 = float(closes[closes.index <= today].iloc[-1])
    structure = phase_machine_direction(row, S0)
    side = _open_side(instrument, structure, row, S0, expiry, entry_rv, today)

    params = INSTRUMENT_PARAMS[instrument]

    if LIVE_ENABLED:
        legs = side["legs"]
        if not broker_confirms_flat(api, [legs["short"]["tsym"], legs["hedge"]["tsym"]]):
            event = {
                "instrument": instrument,
                "action": "REFUSE_ENTRY",
                "reason": "broker_position_check_failed_or_nonzero",
                "broker": BROKER,
            }
            LOG(event)
            return event
        if side.get("entry_leg_prices") is None:
            event = {
                "instrument": instrument,
                "action": "REFUSE_ENTRY",
                "reason": "no_real_quotes_for_live_order",
                "broker": BROKER,
            }
            LOG(event)
            return event
        # Buying the hedge leg (an option BUY) requires actual cash per
        # Shoonya's margin rule — real rejection hit live 2026-07-29:
        # RED:RULE:{Allow CAC credit but disallow collateral and daylong
        # cash for option buy}. check_account_margin()'s avail_margin above
        # (cash+collateral) can't catch this — cash_avail (fetched at the
        # margin_ok check above) is the officially documented cash-only
        # field, checked against the hedge leg's own cost specifically. See
        # check_account_margin's docstring. 2026-08-02.
        shortfall = _hedge_cash_shortfall(
            side["entry_leg_prices"].get("hedge"), params["lot"] * MAX_LOTS, cash_avail
        )
        if shortfall is not None:
            event = {
                "instrument": instrument,
                "action": "REFUSE_ENTRY",
                "reason": "cash_insufficient_for_option_buy",
                "broker": BROKER,
                **shortfall,
            }
            LOG(event)
            return event
        wing = abs(side["hedge_k"] - side["short_k"])
        required_margin = max(wing - side["entry_credit"], 0.0) * params["lot"] * MAX_LOTS
        ceiling, ceiling_reason = nucleus_ceiling(NUCLEUS_TIER)
        if ceiling is None or required_margin > ceiling:
            event = {
                "instrument": instrument,
                "action": "REFUSE_ENTRY",
                "reason": "nucleus_ceiling_check_failed",
                "required_margin": required_margin,
                "nucleus_ceiling": ceiling,
                "nucleus_fail_reason": ceiling_reason,
                "broker": BROKER,
            }
            LOG(event)
            return event

    cycle = {
        "instrument": instrument,
        "entry_date": today.isoformat(),
        "entry_ts": now.isoformat(),
        "expiry": expiry.isoformat(),
        "structure": structure,
        "phase": "DIRECTIONAL_ANCHOR",
        "spot_entry": S0,
        "lot_size": params["lot"],
        _SIDE_FOR_STRUCTURE[structure]: side,
        _SIDE_FOR_STRUCTURE[_OTHER_STRUCTURE[structure]]: None,
    }
    event = {
        "instrument": instrument,
        "action": "ENTER",
        "entry_rv": entry_rv,
        "median_rv": median_rv,
        "structure": structure,
        "gate3": g3.reason,
        "cycle": cycle,
        "dry_run": not LIVE_ENABLED,
    }
    if not LIVE_ENABLED:
        LOG(event)
        return event

    qty = params["lot"] * MAX_LOTS
    enter_result = _enter_side_live(api, side, qty, remarks_prefix=f"NEUTRON_{instrument}")
    event["enter_result"] = enter_result
    event["broker"] = BROKER
    if enter_result["stage"].startswith("complete"):
        side["sl_order_ids"] = {"short": enter_result.get("sl_orders", {}).get("short", {}).get("norenordno")}
        cycle[_SIDE_FOR_STRUCTURE[structure]] = side
        LOG(event)
        return event

    LOG({**event, "stranded": True})
    return {
        "instrument": instrument,
        "action": "HALT_STRANDED_LEGS",
        "stranded_legs": {"cycle": cycle, "enter_result": enter_result},
    }


def _mark_open(instrument: str, cycle: dict, closes, today: date, now: datetime) -> dict:
    S = float(closes[closes.index <= today].iloc[-1])
    expiry = date.fromisoformat(cycle["expiry"])
    entry_ts = datetime.fromisoformat(cycle["entry_ts"])
    expiry_ts = datetime.combine(expiry, time(15, 30))
    T = max((expiry - today).days / 365, 0)
    is_expiry_day = today >= expiry
    lot_size = cycle.get("lot_size", INSTRUMENT_PARAMS["NIFTY"]["lot"])

    if LIVE_ENABLED and not fo_market_is_open(now):
        # Same fo_market_is_open() gate as _try_enter — this tick's exit/
        # roll/MORPH_ADD paths all place real orders too, same phantom-order
        # risk as a fresh entry if attempted before 09:15. See
        # fo_market_is_open's docstring. 2026-08-05.
        return {"action": "SKIP_TICK", "instrument": instrument, "reason": "fo_market_not_open", "broker": BROKER}

    api = get_broker_session(BROKER) if LIVE_ENABLED else None
    if LIVE_ENABLED and api is None:
        return {"action": "SKIP_TICK", "instrument": instrument, "reason": "no_broker_session", "broker": BROKER}

    row = _read_enriched_row(instrument, today)
    if row is not None:
        row = _with_monthly_bb(row, closes, today)
    events = []
    active_sides = [s for s in ("put", "call") if cycle.get(s) is not None]

    # Reconciliation: did a resting SL already fire at the broker since the
    # last tick (cron down, or it fired between 15-min polls)? If so, a side
    # we think is still open is actually already closed at the broker — halt
    # for a human rather than keep computing PT/SL/TSL off a dead leg, or
    # worse, try to close it a second time. Same discipline as proton_live.py's
    # _check_exit reconciliation.
    if LIVE_ENABLED:
        for side_name in active_sides:
            side = cycle[side_name]
            if not side.get("sl_order_ids"):
                continue
            short_tsym = side["legs"]["short"]["tsym"]
            if resting_sl_fired_unreconciled(api, short_tsym):
                stranded = {
                    "cycle": cycle,
                    "reason": "resting_sl_fired_unreconciled",
                    "side": side_name,
                    "broker": BROKER,
                }
                return {
                    "instrument": instrument,
                    "action": "HALT_STRANDED_LEGS",
                    "stranded_legs": stranded,
                }

    for side_name in active_sides:
        side = cycle[side_name]
        structure = "bull_put_spread" if side["opt_type"] == "PE" else "bear_call_spread"
        value, pricing_source, leg_prices = _price_side(side, S, T)
        pnl = (side["entry_credit"] - value) * lot_size
        pt_level = side["entry_credit"] * (1 - PT_FRAC)
        sl_level = side["entry_credit"] * (1 + SL_MULT)

        reason = None
        if value <= pt_level:
            reason = "PT"
        elif value >= sl_level:
            reason = "SL"
        elif is_expiry_day:
            reason = "EXPIRY"

        # Resting SL-LMT is placed with retention="DAY" (exchange auto-cancels
        # it EOD) and previously only got re-placed when orbiter_tsl_ratchet
        # actually moved the trigger. In a quiet market the ratchet never
        # fires, so the day-1 order silently expires at the broker and never
        # gets re-armed on later days — found live 2026-07-31: both NEUTRON+
        # NIFTY legs' resting SLs showed CANCELED at ~day-1 EOD (2026-07-29)
        # and stayed unarmed through 2026-07-31 with the position still open.
        # resting_sl_fired_unreconciled() can't catch this (position qty is
        # still nonzero — the SL expired, it didn't fire), so nothing else
        # in this file would have noticed. Re-arm at the same dynamic_sl
        # trigger whenever the recorded order is confirmed dead.
        if reason is None and LIVE_ENABLED:
            old_ordno = side.get("sl_order_ids", {}).get("short")
            if old_ordno:
                status = shoonya_order_status(old_ordno)
                if status is not None and status.get("status") in FILL_FAILURE_STATUSES:
                    replace_result = _replace_resting_sl_live(
                        api, side, cycle.get("lot_size", lot_size), side["dynamic_sl"],
                        remarks_prefix=f"NEUTRON_{instrument}",
                    )
                    events.append(
                        {
                            "side": side_name,
                            "reason": "SL_REARMED_EXPIRED",
                            "old_status": status.get("status"),
                            "new_trigger": side["dynamic_sl"],
                            "replace_result": replace_result,
                            "broker": BROKER,
                        }
                    )

        current_short_ltp = leg_prices["short"] if leg_prices else None
        if reason is None and row is not None:
            if current_short_ltp is not None:
                old_sl = side["dynamic_sl"]
                # orbiter_tsl_ratchet's atr-scaled step is unusable here (see
                # _open_side's atr comment — wrong-unit index points, no
                # per-leg premium ATR/delta tracked). The dominant real-world
                # effect of that formula was snapping dynamic_sl down to
                # breakeven (entry_short_ltp) almost immediately once premium
                # decayed past the 25% threshold — its own
                # max(new_sl, short_entry_ltp) floor dominated given atr's
                # ~233pt magnitude vs a ~216 rupee premium. Reimplemented
                # directly here, dimensionally clean, no atr: ratchet to
                # breakeven once premium has decayed >= the same threshold,
                # never up. 2026-08-02.
                entry_ltp = side["entry_short_ltp"]
                if entry_ltp > 0:
                    drop_pct = (entry_ltp - current_short_ltp) / entry_ltp
                    threshold = ORBITER_CFG["tsl.ratchet.premium_drop_pct"] / 100.0
                    if drop_pct >= threshold:
                        side["dynamic_sl"] = min(side["dynamic_sl"], entry_ltp)
                if LIVE_ENABLED and side["dynamic_sl"] != old_sl and side.get("sl_order_ids", {}).get("short"):
                    replace_result = _replace_resting_sl_live(
                        api, side, cycle.get("lot_size", lot_size), side["dynamic_sl"],
                        remarks_prefix=f"NEUTRON_{instrument}",
                    )
                    events.append(
                        {
                            "side": side_name,
                            "reason": "SL_RATCHET_REPLACED",
                            "old_trigger": old_sl,
                            "new_trigger": side["dynamic_sl"],
                            "replace_result": replace_result,
                            "broker": BROKER,
                        }
                    )
                catastrophe = orbiter_catastrophe_stop(side["dynamic_sl"])
                if current_short_ltp >= catastrophe:
                    reason = "CATASTROPHE_STOP"
                elif current_short_ltp >= side["dynamic_sl"]:
                    reason = "TSL_ATR"
            if reason is None:
                # net_credit must be lot-multiplied to match pnl's units (pnl =
                # (entry_credit - value) * lot_size) — passing the bare
                # per-point entry_credit here inflated profit_pct/decay_pct by
                # exactly lot_size inside orbiter_tp_check (profit_pct =
                # current_pnl / net_credit * 100), causing IV_CRUSH/DECAY_80
                # to fire on ~2% real profit as if it were >100%. Found live,
                # 2026-07-29 — real entries were exiting within ~10-15 minutes
                # of opening, not a genuine fast decay.
                tp = orbiter_tp_check(
                    structure, side["entry_credit"] * lot_size, pnl, row, S, entry_ts, expiry_ts, now
                )
                if tp.triggered:
                    reason = tp.reason

            # Roll-in: each leg's OWN premium decay vs its own entry price,
            # independent of the other leg (wing width can float — Board
            # decision 2026-08-01). Requires real per-leg prices; skipped on
            # a BS-fallback tick. Only one leg rolls per tick (throttle real
            # order flow) — the other is re-checked next tick.
            if reason is None and leg_prices is not None:
                for leg_name, decay_thr in (
                    ("short", SHORT_LEG_ROLL_DECAY_PCT), ("hedge", HEDGE_LEG_ROLL_DECAY_PCT)
                ):
                    entry_price = (side.get("entry_leg_prices") or {}).get(leg_name)
                    current_price = leg_prices.get(leg_name)
                    if entry_price is None or current_price is None:
                        continue
                    if _leg_decay_pct(entry_price, current_price) < decay_thr:
                        continue
                    old_leg = side["legs"][leg_name]
                    step = INSTRUMENT_PARAMS[instrument]["step"]
                    new_strike = (
                        old_leg["strike"] + step if old_leg["opt_type"] == "PE" else old_leg["strike"] - step
                    )
                    if not LIVE_ENABLED:
                        events.append(
                            {
                                "side": side_name, "reason": "ROLL_IN_WOULD_TRIGGER", "leg": leg_name,
                                "old_strike": old_leg["strike"], "new_strike": new_strike,
                                "decay_pct": round(_leg_decay_pct(entry_price, current_price) * 100, 1),
                            }
                        )
                        break
                    other_name = "hedge" if leg_name == "short" else "short"
                    other_strike = side["legs"][other_name]["strike"]
                    projected_short_k = new_strike if leg_name == "short" else other_strike
                    projected_hedge_k = new_strike if leg_name == "hedge" else other_strike
                    projected_wing = abs(projected_hedge_k - projected_short_k)
                    ceiling, ceiling_reason = nucleus_ceiling(NUCLEUS_TIER)
                    required_margin = max(projected_wing - value, 0.0) * lot_size * MAX_LOTS
                    if ceiling is None or required_margin > ceiling:
                        events.append(
                            {
                                "side": side_name, "reason": "ROLL_SKIPPED_MARGIN_CEILING", "leg": leg_name,
                                "required_margin": required_margin, "nucleus_ceiling": ceiling,
                                "nucleus_fail_reason": ceiling_reason, "broker": BROKER,
                            }
                        )
                        break
                    roll_result = _roll_leg_live(
                        api, side, leg_name, instrument, expiry, S,
                        # atr forced None — see _open_side's comment, same
                        # wrong-unit index-point ATR, unusable for the rolled
                        # leg's initial SL either. 2026-08-02.
                        cycle.get("lot_size", lot_size), None, remarks_prefix=f"NEUTRON_{instrument}",
                    )
                    stage = roll_result.get("stage") or ""
                    if stage.startswith("failed_open_"):
                        # Old leg already closed at the broker, new leg's
                        # open failed — a real naked position, not a safe
                        # no-op like failed_close (old leg untouched there).
                        # Was previously logged as "ROLLED_IN" regardless of
                        # outcome, with no halt — same HALT_STRANDED_LEGS
                        # discipline _try_enter/the resting-SL reconciliation
                        # check above already use for this exact class of
                        # broker/state mismatch. DS review, 2026-08-02. Caller
                        # (the tick loop below) LOGs every HALT_STRANDED_LEGS
                        # return already — no separate log call needed here,
                        # same as the resting-SL reconciliation halt above.
                        return {
                            "instrument": instrument,
                            "action": "HALT_STRANDED_LEGS",
                            "stranded_legs": {
                                "cycle": cycle, "reason": "roll_open_failed", "side": side_name,
                                "leg": leg_name, "old_strike": old_leg["strike"], "new_strike": new_strike,
                                "roll_result": roll_result, "broker": BROKER,
                            },
                        }
                    events.append(
                        {
                            "side": side_name,
                            "reason": "ROLLED_IN" if stage == "complete" else "ROLL_FAILED_CLOSE",
                            "leg": leg_name,
                            "old_strike": old_leg["strike"], "new_strike": new_strike,
                            "roll_result": roll_result, "broker": BROKER,
                        }
                    )
                    break

        if reason:
            event = {
                "side": side_name,
                "reason": reason,
                "value": value,
                "pricing_source": pricing_source,
                "pnl_per_lot": pnl,
            }
            if LIVE_ENABLED:
                qty = cycle.get("lot_size", lot_size)
                close_result = _exit_side_live(api, side, qty, leg_prices, remarks_prefix=f"NEUTRON_{instrument}")
                event["close_result"] = close_result
                event["broker"] = BROKER
                if close_result["stage"] == "complete":
                    cycle[side_name] = None
                else:
                    # partial/failed close — keep the side tracked (with
                    # legs_closed progress from _exit_side_live) so the next
                    # tick retries only the remaining leg(s); nulling it here
                    # would orphan a real open position with no further
                    # SL/TP/TSL monitoring.
                    event["partial_close_needs_human"] = True
                    cycle[side_name] = side
            else:
                cycle[side_name] = None
            events.append(event)
            continue

        # Gated on phase == "DIRECTIONAL_ANCHOR" only, until 2026-08-03: once
        # MORPH_ADD succeeded once (phase -> "CONSOLIDATION"), that phase
        # never reverts, so if the other side later exits on its own (e.g.
        # a profitable PCR_DIVERGENCE close, as happened live 2026-07-31)
        # this block could never re-evaluate — permanently stuck one-sided
        # regardless of market conditions, even in a trend that's exactly
        # when a fresh spread on the closed side would help. Found live
        # 2026-08-03 (NIFTY gapped up, put side had already closed 07-31,
        # call side left naked with no re-add path). consolidation_trigger's
        # own PCR-flat + active-side-unbreached check already provides the
        # real safety gate (won't fire mid-trend/mid-breach) — the phase
        # restriction was redundant and wrong. Now re-evaluates every tick
        # whenever exactly one side is active, regardless of phase history.
        if row is not None and len(active_sides) == 1:
            if consolidation_trigger(row, structure, side["short_k"], S):
                other_structure = _OTHER_STRUCTURE[structure]
                other_side_name = _SIDE_FOR_STRUCTURE[other_structure]
                new_side = _open_side(
                    instrument, other_structure, _with_monthly_bb(row, closes, today), S, expiry, side["sigma"], today
                )
                if LIVE_ENABLED:
                    cash_shortfall = None
                    if new_side.get("entry_leg_prices") is not None:
                        _, _, morph_cash_avail = check_account_margin(api, BROKER)
                        cash_shortfall = _hedge_cash_shortfall(
                            new_side["entry_leg_prices"].get("hedge"),
                            cycle.get("lot_size", lot_size),
                            morph_cash_avail,
                        )
                    if new_side.get("entry_leg_prices") is None:
                        events.append(
                            {
                                "side": other_side_name,
                                "reason": "MORPH_ADD_SKIPPED_NO_QUOTES",
                                "structure": other_structure,
                            }
                        )
                    elif cash_shortfall is not None:
                        events.append(
                            {
                                "side": other_side_name,
                                "reason": "MORPH_ADD_SKIPPED_CASH_INSUFFICIENT",
                                "structure": other_structure,
                                **cash_shortfall,
                            }
                        )
                    else:
                        qty = cycle.get("lot_size", lot_size)
                        enter_result = _enter_side_live(
                            api, new_side, qty, remarks_prefix=f"NEUTRON_{instrument}_MORPH"
                        )
                        if enter_result["stage"].startswith("complete"):
                            new_side["sl_order_ids"] = {
                                "short": enter_result.get("sl_orders", {}).get("short", {}).get("norenordno")
                            }
                            cycle[other_side_name] = new_side
                            cycle["phase"] = "CONSOLIDATION"
                            events.append(
                                {
                                    "side": other_side_name,
                                    "reason": "MORPH_ADD",
                                    "structure": other_structure,
                                    "enter_result": enter_result,
                                    "broker": BROKER,
                                }
                            )
                        else:
                            # entry failed — don't set cycle[other_side_name],
                            # don't touch phase; consolidation_trigger gets
                            # re-checked next tick regardless of phase now.
                            events.append(
                                {
                                    "side": other_side_name,
                                    "reason": "MORPH_ADD_FAILED",
                                    "structure": other_structure,
                                    "enter_result": enter_result,
                                    "broker": BROKER,
                                }
                            )
                else:
                    cycle[other_side_name] = new_side
                    cycle["phase"] = "CONSOLIDATION"
                    events.append(
                        {"side": other_side_name, "reason": "MORPH_ADD", "structure": other_structure}
                    )
            elif asymmetric_breakage_trigger(structure, side["short_k"], S):
                cycle["phase"] = "ASYMMETRIC_BREAKAGE"

    if not any(cycle.get(s) is not None for s in ("put", "call")):
        return {
            "action": "EXIT",
            "instrument": instrument,
            "spot": S,
            "exits": events,
            "cycle": cycle,
        }
    return {
        "action": "MORPH" if any(e.get("reason") == "MORPH_ADD" for e in events) else "HOLD",
        "instrument": instrument,
        "spot": S,
        "events": events,
        "cycle": cycle,
    }


def run_daily(instrument: str, now: datetime = None) -> dict:
    now = now or datetime.now()
    today = now.date()

    cycle = STATE()
    if isinstance(cycle, dict) and cycle.get("stranded_legs"):
        result = {
            "instrument": instrument,
            "action": "HALT_STRANDED_LEGS",
            "stranded_legs": cycle["stranded_legs"],
        }
        LOG(result)
        return result

    if instrument == "NIFTY":
        closes = combined_daily_closes()
    else:
        closes = combined_daily_closes_sensex()

    if cycle is not None:
        result = _mark_open(instrument, cycle, closes, today, now)
        if result["action"] == "EXIT":
            SAVE(None)
            LOG(result)
        elif result["action"] in ("SKIP_TICK", "HALT_STRANDED_LEGS"):
            if result["action"] == "HALT_STRANDED_LEGS":
                SAVE({"stranded_legs": result["stranded_legs"]})
            LOG(result)
        else:
            SAVE(cycle)
            LOG(result)
    else:
        result = _try_enter(instrument, closes, today, now)
        if result.get("action") == "ENTER":
            SAVE(result["cycle"])
        elif result.get("action") == "HALT_STRANDED_LEGS":
            SAVE({"stranded_legs": result["stranded_legs"]})
    return result


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in INSTRUMENT_PARAMS:
        print("Usage: python3 monthly_ic_pilot_orbiter.py NIFTY|SENSEX", file=sys.stderr)
        sys.exit(1)

    INSTRUMENT = sys.argv[1].upper()
    BASE = Path(__file__).resolve().parent
    # Existing plain-name files already carry real paper-trading history
    # (running since before this real-order path existed) — LIVE gets its
    # own distinctly-named path instead, so flipping NEUTRON_LIVE_TRADING=YES
    # on can never be misread as "continue this paper cycle with real orders."
    # Inverse of proton_live.py's convention (which never had pre-existing
    # paper history under the plain name) for exactly that reason.
    _fname = f"monthly_ic_pilot_orbiter_{INSTRUMENT.lower()}"
    STATE_FILE = BASE / "data" / "neutron" / (f"{_fname}_live_state.json" if LIVE_ENABLED else f"{_fname}_state.json")
    LEDGER_FILE = BASE / "logs" / "neutron" / (f"{_fname}_live.jsonl" if LIVE_ENABLED else f"{_fname}.jsonl")
    ORDER_MODE = "REAL" if LIVE_ENABLED else "PAPER"

    def STATE() -> dict | None:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text())
        return None

    def SAVE(cycle: dict | None):
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(cycle, indent=2, default=str))

    def LOG(event: dict):
        """Auto-tags `module` (caller, via stack introspection) and
        `order_mode` (ORDER_MODE constant above, not buried inline)."""
        LEDGER_FILE.parent.mkdir(parents=True, exist_ok=True)
        caller = inspect.stack()[1].function
        event = {
            **event,
            "ts": datetime.now().isoformat(),
            "module": caller,
            "order_mode": ORDER_MODE,
        }
        with open(LEDGER_FILE, "a") as f:
            f.write(json.dumps(event, default=str) + "\n")

    result = run_daily(INSTRUMENT)
    print(json.dumps(result, indent=2, default=str))
