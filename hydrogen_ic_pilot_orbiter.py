"""HYDROGEN-ORBITER — ORBITER v3.0 IC targeting NEXT-WEEK expiry.

Usage:
    python3 hydrogen_ic_pilot_orbiter.py NIFTY
    python3 hydrogen_ic_pilot_orbiter.py SENSEX

One instrument per process — run as separate cron jobs. Each instrument has its
own state file and ledger. Targets the second-nearest weekly expiry (next week),
not the current/nearest. Also lives on NIFTY expiry for SENSEX vice versa.

Same ORBITER port as ATOM+/PROTON+/NEUTRON+: Multi-Gated Entry, ATR TSL,
Dynamic Take-Profit, Dynamic Legging. Enters any day vol-filter passes.
Static PT (60%) / SL (1.0x) backstop always active.
"""

import inspect
import json
import sys
import numpy as np
from datetime import date, datetime, time, timedelta
from pathlib import Path

from config.token_resolver import resolve_weekly_expiry, TokenResolver
from backtester import black_scholes_call, black_scholes_put
from monthly_ic_pilot import (
    combined_daily_closes,
    trailing_rv,
    trailing_median_rv,
    _flattrade_session,
    _leg_ltp,
    check_account_margin,
    SL_MULT,
    PT_FRAC,
    RISK_FREE_RATE,
)
from orbiter_monthly import (
    _read_enriched_row,
    _f,
    gate1_regime,
    gate1_tiger_override,
    gate3_entry_abort,
    gate2_strikes,
    phase_machine_direction,
    consolidation_trigger,
    asymmetric_breakage_trigger,
    orbiter_initial_tsl,
    orbiter_tsl_ratchet,
    orbiter_catastrophe_stop,
    orbiter_tp_check,
)

WING_STRIKES = 2

INSTRUMENT_PARAMS = {
    "NIFTY": {"step": 50, "lot": 75},
    "SENSEX": {"step": 100, "lot": 10},
}

_OPT_TYPE = {"bull_put_spread": "PE", "bear_call_spread": "CE"}
_OTHER_STRUCTURE = {"bull_put_spread": "bear_call_spread", "bear_call_spread": "bull_put_spread"}
_SIDE_FOR_STRUCTURE = {"bull_put_spread": "put", "bear_call_spread": "call"}


def resolve_next_week_expiry(instrument: str, now: datetime | None = None) -> date:
    if now is None:
        now = datetime.now()
    nearest = resolve_weekly_expiry(instrument, now)
    next_day = nearest + timedelta(days=1)
    return resolve_weekly_expiry(instrument, datetime.combine(next_day, time(0, 0)))


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


def _resolve_two_legs_weekly(
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
        rows = tr.resolve_weekly_sensex_for_expiry(expiry, atm_range=atm_range)
    by_key = {(row["strike"], row["opt_type"]): row for row in rows}
    return {"short": by_key.get((short_k, opt_type)), "hedge": by_key.get((hedge_k, opt_type))}


def _side_value_bs(
    S: float, short_k: float, hedge_k: float, opt_type: str, T: float, sigma: float
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
        api = _flattrade_session()
        if api is not None:
            short_ltp = _leg_ltp(api, legs["short"]["exchange"], legs["short"]["token"])
            hedge_ltp = _leg_ltp(api, legs["hedge"]["exchange"], legs["hedge"]["token"])
            if not (np.isnan(short_ltp) or np.isnan(hedge_ltp)):
                return short_ltp - hedge_ltp, "real", {"short": short_ltp, "hedge": hedge_ltp}
    value = _side_value_bs(S, side["short_k"], side["hedge_k"], side["opt_type"], T, side["sigma"])
    return value, "bs_fallback", None


def _open_side(
    instrument: str, structure: str, row: dict, S0: float, expiry: date, sigma: float, today: date
) -> dict:
    params = INSTRUMENT_PARAMS[instrument]
    smap = gate2_strikes(row, S0, wing_strikes=WING_STRIKES, step=params["step"])
    opt_type = _OPT_TYPE[structure]
    short_k, hedge_k = (
        (smap.put_short, smap.put_hedge) if opt_type == "PE" else (smap.call_short, smap.call_hedge)
    )
    legs_raw = _resolve_two_legs_weekly(instrument, expiry, S0, short_k, hedge_k, opt_type)
    legs = {
        k: {kk: v[kk] for kk in ("exchange", "token", "tsym", "strike", "opt_type")}
        for k, v in legs_raw.items()
        if v is not None
    }
    T0 = max((expiry - today).days / 365, 1 / 365)
    side = {
        "instrument": instrument,
        "short_k": short_k,
        "hedge_k": hedge_k,
        "opt_type": opt_type,
        "legs": legs,
        "sigma": sigma,
    }
    value, pricing_source, leg_prices = _price_side(side, S0, T0)
    atr = _f(row.get("atr_daily")) or _f(row.get("atr"))
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

    g1 = gate1_regime(row)
    g1 = gate1_tiger_override(row, g1, row.get("timestamp"))
    if not g1.passed:
        event = {"instrument": instrument, "action": "SKIP", "reason": g1.reason, "gate": g1.gate}
        LOG(event)
        return event

    g3 = gate3_entry_abort(row)
    if not g3.passed:
        event = {"instrument": instrument, "action": "SKIP", "reason": g3.reason, "gate": g3.gate}
        LOG(event)
        return event

    margin_ok, avail_margin = check_account_margin(_flattrade_session())
    if not margin_ok:
        event = {
            "instrument": instrument,
            "action": "SKIP",
            "reason": "margin_insufficient",
            "avail_margin": avail_margin,
        }
        LOG(event)
        return event

    expiry = resolve_next_week_expiry(instrument, now)
    S0 = float(closes[closes.index <= today].iloc[-1])
    structure = phase_machine_direction(row, S0)
    side = _open_side(instrument, structure, row, S0, expiry, entry_rv, today)

    params = INSTRUMENT_PARAMS[instrument]
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
        "gate1": g1.reason,
        "gate3": g3.reason,
        "cycle": cycle,
    }
    LOG(event)
    return event


def _mark_open(instrument: str, cycle: dict, closes, today: date, now: datetime) -> dict:
    S = float(closes[closes.index <= today].iloc[-1])
    expiry = date.fromisoformat(cycle["expiry"])
    entry_ts = datetime.fromisoformat(cycle["entry_ts"])
    expiry_ts = datetime.combine(expiry, time(15, 30))
    T = max((expiry - today).days / 365, 0)
    is_expiry_day = today >= expiry
    lot_size = cycle.get("lot_size", INSTRUMENT_PARAMS["NIFTY"]["lot"])

    row = _read_enriched_row(instrument, today)
    events = []
    active_sides = [s for s in ("put", "call") if cycle.get(s) is not None]

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

        current_short_ltp = leg_prices["short"] if leg_prices else None
        if reason is None and row is not None:
            atr = _f(row.get("atr_daily")) or _f(row.get("atr"))
            if current_short_ltp is not None:
                side["dynamic_sl"] = orbiter_tsl_ratchet(
                    side["dynamic_sl"], side["entry_short_ltp"], current_short_ltp, atr
                )
                catastrophe = orbiter_catastrophe_stop(side["dynamic_sl"])
                if current_short_ltp >= catastrophe:
                    reason = "CATASTROPHE_STOP"
                elif current_short_ltp >= side["dynamic_sl"]:
                    reason = "TSL_ATR"
            if reason is None:
                tp = orbiter_tp_check(
                    structure, side["entry_credit"], pnl, row, S, entry_ts, expiry_ts, now
                )
                if tp.triggered:
                    reason = tp.reason

        if reason:
            events.append(
                {
                    "side": side_name,
                    "reason": reason,
                    "value": value,
                    "pricing_source": pricing_source,
                    "pnl_per_lot": pnl,
                }
            )
            cycle[side_name] = None
            continue

        if row is not None and cycle["phase"] == "DIRECTIONAL_ANCHOR" and len(active_sides) == 1:
            if consolidation_trigger(row, structure, side["short_k"], S):
                other_structure = _OTHER_STRUCTURE[structure]
                other_side_name = _SIDE_FOR_STRUCTURE[other_structure]
                new_side = _open_side(
                    instrument, other_structure, row, S, expiry, side["sigma"], today
                )
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
    if instrument == "NIFTY":
        closes = combined_daily_closes()
    else:
        closes = combined_daily_closes_sensex()

    if cycle is not None:
        result = _mark_open(instrument, cycle, closes, today, now)
        if result["action"] == "EXIT":
            SAVE(None)
            LOG(result)
        else:
            SAVE(cycle)
            LOG(result)
    else:
        result = _try_enter(instrument, closes, today, now)
        if result.get("action") == "ENTER":
            SAVE(result["cycle"])
    return result


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in INSTRUMENT_PARAMS:
        print("Usage: python3 hydrogen_ic_pilot_orbiter.py NIFTY|SENSEX", file=sys.stderr)
        sys.exit(1)

    INSTRUMENT = sys.argv[1].upper()
    BASE = Path(__file__).resolve().parent
    STATE_FILE = BASE / "data" / "hydrogen" / f"hydrogen_ic_pilot_orbiter_{INSTRUMENT.lower()}_state.json"
    LEDGER_FILE = BASE / "logs" / "hydrogen" / f"hydrogen_ic_pilot_orbiter_{INSTRUMENT.lower()}.jsonl"
    # Paper-only by design — no broker connection exists anywhere in this file.
    # If a real-order path is ever added, this must become a flag read like
    # proton_live.py's LIVE_ENABLED, not stay a hardcoded constant.
    ORDER_MODE = "PAPER"

    def STATE() -> dict | None:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text())
        return None

    def SAVE(cycle: dict | None):
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(cycle, indent=2, default=str))

    def LOG(event: dict):
        """Auto-tags `module` (caller, via stack introspection — same
        pattern as proton_live.py's _log_ledger) and `order_mode`
        (ORDER_MODE constant above, not buried inline — see its comment)."""
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
