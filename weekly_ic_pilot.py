"""PROTON — weekly NIFTY iron-condor paper pilot.

Same locked strategy as NEUTRON (monthly_ic_pilot.py), backtested
2026-07-11 on 11yr real NIFTY minute data (weekly_ic_backtest.py):
  - Enter ONLY on Friday (best of 5 entry-day-of-week buckets tested;
    86.3% win, +Rs899.74/lot avg, holds up on chronological split —
    H1 +Rs89,369 H2 +Rs127,468/lot; see memory: neutron_project.md /
    atom_future_thoughts.md idea 2)
  - Enter only if trailing 20d realized vol > its own trailing ~6mo median
  - Short strikes at 1SD (entry-day trailing RV, sqrt(T)-scaled) off spot
  - 150pt wing
  - Close at 60% of credit captured (profit target)
  - Stop at 1.0x credit lost
  - Real NIFTY weekly expiry (next Tuesday) via
    config.token_resolver.resolve_weekly_expiry()

ASSUMPTION carried from the backtest: expiry-day-of-week (Tuesday) treated
as constant across history for backtest validation; live pilot uses the
REAL current broker-listed weekly expiry via resolve_weekly_expiry(), so
this assumption only affected backtest validation, not live behavior.

Isolation (same requirement as NEUTRON — must not disturb ATOM's live
weekly pipeline):
  - Paper only. No broker orders.
  - Real premiums via the same Flattrade session as NEUTRON (separate
    broker/credentials from ATOM's Shoonya session in feed.py) — on-demand
    REST quote calls only, no persistent WebSocket subscription, doesn't
    touch feed.py's subscription set or shared capture SQLite/option_prices.
  - Falls back to Black-Scholes modeling if the Flattrade session/quote
    fetch fails — logged via "pricing_source", never silent.
  - Own state/ledger files only. No writes to shared capture SQLite or any
    table ATOM reads/writes.
  - Reads market_data read-only (mode=ro).

Run once per trading day via `run_daily()`. Scheduled every 15 min,
9:15-15:30 IST weekdays, via cron/run_weekly_ic_pilot.sh (own flock, own
log — mirrors run_monthly_ic_pilot.sh).
"""

import numpy as np

from config.token_resolver import resolve_weekly_expiry, TokenResolver
from monthly_ic_pilot import (
    combined_daily_closes, trailing_rv, trailing_median_rv, _combo_value,
    _flattrade_session, _leg_ltp, _real_combo_value,
    WING, SL_MULT, PT_FRAC, STRIKE_GAP, LOT_SIZE,
)
from datetime import date, datetime
from pathlib import Path
import json

ENTRY_WEEKDAY = "Fri"

STATE_PATH = Path(__file__).resolve().parent / "data" / "weekly_ic_pilot_state.json"
LEDGER_PATH = Path(__file__).resolve().parent / "logs" / "weekly_ic_pilot.jsonl"


def _load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"open_cycle": None}


def _save_state(state: dict):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, default=str))


def _log_ledger(event: dict):
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    event = {"ts": datetime.now().isoformat(), **event}
    with open(LEDGER_PATH, "a") as f:
        f.write(json.dumps(event, default=str) + "\n")


def _resolve_legs(expiry: date, spot: float, sp: float, lp: float, sc: float, lc: float) -> dict:
    atm = round(spot / STRIKE_GAP) * STRIKE_GAP
    max_offset = max(abs(atm - lp), abs(lc - atm))
    atm_range = int(np.ceil(max_offset / STRIKE_GAP)) + 1
    tr = TokenResolver(nifty_spot=spot)
    rows = tr.resolve_weekly_nifty_for_expiry(expiry, atm_range=atm_range)
    by_key = {(row["strike"], row["opt_type"]): row for row in rows}
    return {
        "short_put": by_key.get((sp, "PE")),
        "long_put": by_key.get((lp, "PE")),
        "short_call": by_key.get((sc, "CE")),
        "long_call": by_key.get((lc, "CE")),
    }


def _mark_open_cycle(state: dict, cycle: dict, closes, today: date) -> dict:
    S = float(closes[closes.index <= today].iloc[-1])
    expiry = date.fromisoformat(cycle["expiry"])
    T = max((expiry - today).days / 365, 0)

    pricing_source = "bs_fallback"
    val = float("nan")
    leg_prices = None
    if today < expiry and cycle.get("legs"):
        api = _flattrade_session()
        if api is not None:
            real = _real_combo_value(api, cycle["legs"])
            if not np.isnan(real.value):
                val = real.value
                leg_prices = real.leg_prices
                pricing_source = "real"
    if np.isnan(val):
        val = _combo_value(S, cycle["sp"], cycle["lp"], cycle["sc"], cycle["lc"], T, cycle["sigma"])

    credit = cycle["credit"]
    pt_level = credit * (1 - PT_FRAC)
    sl_level = credit * (1 + SL_MULT)

    reason = None
    if val <= pt_level:
        reason = "PT"
    elif val >= sl_level:
        reason = "SL"
    elif today >= expiry:
        reason = "EXPIRY"

    if reason:
        pnl_per_lot = (credit - val) * LOT_SIZE
        event = {"action": "EXIT", "reason": reason, "spot": S, "combo_value": val,
                 "pricing_source": pricing_source, "leg_prices": leg_prices,
                 "pnl_per_lot": pnl_per_lot, "cycle": cycle}
        _log_ledger(event)
        state["open_cycle"] = None
        _save_state(state)
        return event

    event = {"action": "HOLD", "spot": S, "combo_value": val, "pricing_source": pricing_source,
             "leg_prices": leg_prices, "unrealized_per_lot": (credit - val) * LOT_SIZE,
             "cycle": cycle}
    _log_ledger(event)
    return event


def _try_enter(state: dict, closes, today: date, now: datetime) -> dict:
    if today.strftime("%a") != ENTRY_WEEKDAY:
        event = {"action": "SKIP", "reason": "not_entry_weekday"}
        _log_ledger(event)
        return event

    entry_rv = trailing_rv(closes, today)
    median_rv = trailing_median_rv(closes, today)

    if np.isnan(entry_rv) or np.isnan(median_rv):
        event = {"action": "SKIP", "reason": "insufficient_history"}
        _log_ledger(event)
        return event

    if entry_rv <= median_rv:
        event = {"action": "SKIP", "reason": "low_vol_regime",
                 "entry_rv": entry_rv, "median_rv": median_rv}
        _log_ledger(event)
        return event

    expiry = resolve_weekly_expiry("NIFTY", now)
    S0 = float(closes[closes.index <= today].iloc[-1])
    T0 = max((expiry - today).days / 365, 1 / 365)
    move = entry_rv * np.sqrt(T0)
    sp = round(S0 * (1 - move) / STRIKE_GAP) * STRIKE_GAP
    sc = round(S0 * (1 + move) / STRIKE_GAP) * STRIKE_GAP
    lp = sp - WING
    lc = sc + WING

    legs_raw = _resolve_legs(expiry, S0, sp, lp, sc, lc)
    legs = {k: {kk: v[kk] for kk in ("exchange", "token", "tsym", "strike", "opt_type")}
            for k, v in legs_raw.items() if v is not None}

    pricing_source = "bs_fallback"
    credit = float("nan")
    leg_prices = None
    if len(legs) == 4:
        api = _flattrade_session()
        if api is not None:
            real = _real_combo_value(api, legs_raw)
            if not np.isnan(real.value):
                credit = real.value
                leg_prices = real.leg_prices
                pricing_source = "real"
    if np.isnan(credit):
        credit = _combo_value(S0, sp, lp, sc, lc, T0, entry_rv)

    cycle = {
        "entry_date": today.isoformat(), "expiry": expiry.isoformat(),
        "spot_entry": S0, "sp": sp, "lp": lp, "sc": sc, "lc": lc,
        "sigma": entry_rv, "credit": credit, "legs": legs,
        "entry_leg_prices": leg_prices,   # persists with the cycle so every later
                                          # HOLD/EXIT event still has the entry legs
    }
    state["open_cycle"] = cycle
    _save_state(state)
    event = {"action": "ENTER", "entry_rv": entry_rv, "median_rv": median_rv,
             "pricing_source": pricing_source, "leg_prices": leg_prices, "cycle": cycle}
    _log_ledger(event)
    return event


def run_daily(now: datetime = None) -> dict:
    now = now or datetime.now()
    today = now.date()
    closes = combined_daily_closes()

    state = _load_state()
    cycle = state.get("open_cycle")
    if cycle is not None:
        return _mark_open_cycle(state, cycle, closes, today)
    return _try_enter(state, closes, today, now)


if __name__ == "__main__":
    result = run_daily()
    print(json.dumps(result, indent=2, default=str))
