"""PROTON — live real-money order placement, dual-index alternation
(Board-gated, DRY_RUN by default).

Schedule (explicit user direction, 2026-07-15 — flagged with backtest
evidence before building; SENSEX-Tuesday tests negative under every strike
method checked, see sensex_weekly_ic_backtest.py / strike_selection_compare.py
history — proceeding anyway per Board decision):
  - Entry trigger is the OTHER index's REAL RESOLVED expiry date (holiday-aware,
    via config.token_resolver.resolve_weekly_expiry), not a hardcoded weekday
    string — a holiday shifts an index's actual expiry off its normal day
    (see latest_changes_deepseek.md), and a fixed "Thu"/"Tue" check would
    silently miss that shift.
  - SENSEX enters when NIFTY's resolved expiry == today, near EOD (~15:20+)
  - NIFTY enters when SENSEX's resolved expiry == today, near EOD (~15:20+)
  - Only one position open at a time (same FSM-gate pattern as ATOM/paper PROTON)
  - Strikes are delta-selected (0.25 NIFTY, 0.20 SENSEX — both back-tested to
    beat the original 1SD method after honest costs), not the 1SD method the
    paper pilots (monthly_ic_pilot.py / weekly_ic_pilot.py) still use.

Broker (2026-07-15 revision): Shoonya, NOT Flattrade. Original build used
Flattrade to preserve capital/risk isolation from ATOM. Reconsidered — the
strongest argument for Flattrade (avoiding WS/session contention with
Penguin) doesn't actually hold, since ATOM's own broker_session.py already
proves stateless REST calls against the SAME token don't interfere with
Penguin's WS session. Flattrade's real weakness: order placement through it
has NEVER been tested in this codebase (SCENARIO_COVERAGE_AND_GAPS_ANALYSIS.md
marks the Shoonya->Flattrade order-fallback test "NOTEST"; NEUTRON/PROTON only
ever called get_quotes() on it). Shoonya's order placement IS proven — ATOM's
2026-07-13 live canary test placed real orders through it. User's explicit
call: switch to Shoonya, accept the shared-account risk, mitigate via a real
margin check (see check_account_margin()) rather than a separate untested
broker. The actual remaining risk isn't API contention, it's ATOM and
HYDROGEN drawing on the same margin pool with neither aware of the other's
open positions — check_account_margin() queries real broker-reported free
margin before every entry, which reflects whatever ATOM has already deployed
(account-level, not position-level — doesn't require parsing ATOM's specific
state, just refuses to enter if the account itself is margin-tight).

Replicates ATOM's live order architecture otherwise unchanged: NRML product
type (no EOD close), hedge-first sequential entry, shorts-first exit, no
auto-unwind on partial fill, local JSON state PLUS a real api.get_positions()
cross-check before any entry, DRY_RUN unless PROTON_LIVE_TRADING=YES_REAL_MONEY,
MAX_LOTS=1 hard cap.
"""

from __future__ import annotations

import inspect
import json
import math
import os
import sqlite3
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

sys.path.insert(0, "/home/trading_ceo/atom/src")
from atom.broker_session import load_live_api

from config.sqlite_schema import get_sqlite_capture_path
from config.token_resolver import resolve_weekly_expiry, TokenResolver
from monthly_ic_pilot import (
    _leg_ltp,
    _real_combo_value,
    trailing_rv,
    trailing_median_rv,
    RISK_FREE_RATE,
)
from backtester import black_scholes_call, black_scholes_put
import orbiter_weekly as orbiter_mod

_N = NormalDist()

BUY, SELL = "B", "S"
LIMIT = "LMT"
NRML = "M"
MARKETABLE_BUFFER_PCT = 0.02

MAX_LOTS = 1
LIVE_ENABLED = os.environ.get("PROTON_LIVE_TRADING") == "YES_REAL_MONEY"
# Distinguishes PROTON+ (paper, ORBITER v3 tier) from base PROTON's own dry-run
# state/ledger when both run LIVE_ENABLED=False — same script, same 15-min cron
# schedule, different lock files, so without this they'd race on one file.
# Default "" keeps PROTON base's existing paths untouched.
_INSTANCE_SUFFIX = os.environ.get("PROTON_INSTANCE_SUFFIX", "")

STATE_PATH = (
    Path(__file__).resolve().parent / "data" / "proton" / "proton_live_state.json"
    if LIVE_ENABLED
    else Path(__file__).resolve().parent / "data" / "proton" / f"proton_live_dry_state{_INSTANCE_SUFFIX}.json"
)
LEDGER_PATH = (
    Path(__file__).resolve().parent / "logs" / "proton" / "proton_live.jsonl"
    if LIVE_ENABLED
    else Path(__file__).resolve().parent / "logs" / "proton" / f"proton_live_dry{_INSTANCE_SUFFIX}.jsonl"
)

SENSEX_HIST_CSV = Path(__file__).resolve().parent / "data" / "sensex_candlestick_data.csv"
# Copied here 2026-07-23 from /root/.cache/kagglehub/... — that path lives
# under root's home directory (0700), which algo_prod (the now-live-money-
# adjacent cron user) can never traverse regardless of the file's own
# permissions. Surfaced when PROTON+ actually ran a SENSEX cycle as algo_prod
# for the first time and hit a PermissionError. Original kaggle download
# untouched; this is a one-time copy, not a symlink (root's cache directory
# itself isn't reachable to link against anyway).

INDEX_CONFIG = {
    "NIFTY": {
        "gap": 50,
        "lot_size": 75,
        "target_delta": 0.25,
        "triggered_by_expiry_of": "SENSEX",
        "resolver_kwarg": "nifty_spot",
        "resolver_method": "resolve_weekly_nifty_for_expiry",
    },
    "SENSEX": {
        "gap": 100,
        "lot_size": 10,
        "target_delta": 0.20,
        "triggered_by_expiry_of": "NIFTY",
        "resolver_kwarg": "sensex_spot",
        "resolver_method": "resolve_weekly_sensex_for_expiry",
    },
}
WING_PCT = 0.0075  # same ratio for both, per sensex_weekly_ic_backtest.py's calibration note
PT_FRAC, SL_MULT = 0.6, 1.0
ENTRY_EOD_TIME = "15:20"  # entries only fire near close, not all day


def marketable_limit(action: str, ltp: float) -> float:
    mult = 1 + MARKETABLE_BUFFER_PCT if action == BUY else 1 - MARKETABLE_BUFFER_PCT
    return round(ltp * mult, 1)


@dataclass(frozen=True)
class LiveOrderResult:
    ok: bool
    norenordno: str | None
    raw: dict


def _ok(resp) -> bool:
    return isinstance(resp, dict) and resp.get("stat") == "Ok"


def _norenordno(resp):
    return resp.get("norenordno") if isinstance(resp, dict) else None


def place_leg(
    api, action: str, exchange: str, tradingsymbol: str, qty: int, ltp: float, remarks: str
) -> LiveOrderResult:
    price = marketable_limit(action, ltp)
    resp = api.place_order(
        buy_or_sell=action,
        product_type=NRML,
        exchange=exchange,
        tradingsymbol=tradingsymbol,
        quantity=qty,
        discloseqty=0,
        price_type=LIMIT,
        price=price,
        retention="DAY",
        remarks=remarks,
    )
    return LiveOrderResult(_ok(resp), _norenordno(resp), resp)


SL_LIMIT = "SL-LMT"
BASE_SL_MULT = 1.0
ATR_SL_MULTIPLIER = 1.25  # backtested: NIFTY plateaus 1.25-1.75x, SENSEX best
# in that range too — see hydrogen_sl_atr_sweep.py.
# NIFTY costed total 243,266 (flat) -> 265,081 (this),
# SENSEX 12,367 -> 17,933. Combo-level in backtest;
# translated to per-leg resting orders below.
SL_TRIGGER_BUFFER_PCT = 0.01  # limit price past trigger, so it fills like a stop


def place_resting_sl(
    api,
    action: str,
    exchange: str,
    tradingsymbol: str,
    qty: int,
    trigger_price: float,
    remarks: str,
) -> LiveOrderResult:
    """Resting SL-LMT — the broker-side backstop the software combo-check
    doesn't have. action=BUY (closing a short leg on a stop-up)."""
    limit_price = round(trigger_price * (1 + SL_TRIGGER_BUFFER_PCT), 1)
    resp = api.place_order(
        buy_or_sell=action,
        product_type=NRML,
        exchange=exchange,
        tradingsymbol=tradingsymbol,
        quantity=qty,
        discloseqty=0,
        price_type=SL_LIMIT,
        price=limit_price,
        trigger_price=round(trigger_price, 1),
        retention="DAY",
        remarks=remarks,
    )
    return LiveOrderResult(_ok(resp), _norenordno(resp), resp)


def cancel_order(api, orderno: str) -> LiveOrderResult:
    resp = api.cancel_order(orderno=orderno)
    return LiveOrderResult(_ok(resp), _norenordno(resp), resp)


def atr_sl_multiplier(rv: float, median_rv: float) -> float:
    ratio = min(max(rv / median_rv, 0.5), 2.0) if median_rv else 1.0
    return BASE_SL_MULT * ratio * ATR_SL_MULTIPLIER


def delta_strike(
    S: float, T: float, sigma: float, target_delta: float, option_type: str, gap: int
) -> int:
    if T <= 1e-6 or sigma <= 0:
        return round(S / gap) * gap
    d1 = _N.inv_cdf(target_delta if option_type == "call" else 1 - target_delta)
    k = S * math.exp((RISK_FREE_RATE + 0.5 * sigma**2) * T - d1 * sigma * math.sqrt(T))
    return round(k / gap) * gap


def sensex_historical_daily_closes() -> pd.Series:
    df = pd.read_csv(SENSEX_HIST_CSV, usecols=["Date", "Time", "Close"])
    df["ts"] = pd.to_datetime(df["Date"] + " " + df["Time"], format="%d-%m-%Y %H:%M:%S")
    df = df.set_index("ts").sort_index()
    df["day"] = df.index.date
    return df.groupby("day")["Close"].last()


def _live_daily_closes(index: str) -> pd.Series:
    path = get_sqlite_capture_path(index)
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT timestamp, close FROM market_data "
            "WHERE instrument=? AND close > 0 ORDER BY timestamp",
            (index,),
        ).fetchall()
    finally:
        con.close()
    if not rows:
        return pd.Series(dtype=float)
    df = pd.DataFrame(rows, columns=["timestamp", "close"])
    df["day"] = pd.to_datetime(df["timestamp"]).dt.date
    return df.groupby("day")["close"].last()


def combined_daily_closes(index: str) -> pd.Series:
    if index == "NIFTY":
        from monthly_ic_pilot import _historical_daily_closes

        hist = _historical_daily_closes()
    else:
        hist = sensex_historical_daily_closes()
    live = _live_daily_closes(index)
    if live.empty:
        return hist
    return pd.concat([hist, live[~live.index.isin(hist.index)]]).sort_index()


def _load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"open_position": None}


def _save_state(state: dict):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, default=str))


def _log_ledger(event: dict):
    """Appends one JSON line per cycle decision. Auto-tags `module` (the
    calling function, via stack introspection — avoids touching every one
    of this file's ~20 _log_ledger call sites individually) and
    `order_mode` (PAPER/REAL, from the same LIVE_ENABLED flag that gates
    real order placement, so the tag can never drift from actual behavior).
    System keys are applied AFTER **event (not before) so a caller's dict
    can never accidentally shadow ts/module/order_mode — caught in review
    (DeepSeek, 2026-07-19) before it shipped."""
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    caller = inspect.stack()[1].function
    event = {
        **event,
        "ts": datetime.now().isoformat(),
        "module": caller,
        "order_mode": "REAL" if LIVE_ENABLED else "PAPER",
    }
    with open(LEDGER_PATH, "a") as f:
        f.write(json.dumps(event, default=str) + "\n")


def _shoonya_session():
    """Same cred file / token ATOM and Penguin already use (atom/broker_session.py
    load_live_api — proven order placement, ATOM's 2026-07-13 canary test). Wraps
    its raise-on-failure contract into the None-on-failure contract the rest of
    this module expects (a broker outage must never crash a cron tick)."""
    try:
        return load_live_api()
    except Exception:
        return None


MARGIN_FLOOR_INR = 50_000.0  # same floor ATOM's risk.py uses (BROKER_MARGIN_LOW)


def check_account_margin(api) -> tuple[bool, float | None]:
    """Real broker-reported free margin, account-level — reflects whatever ATOM
    has already deployed on this SHARED account without needing to parse ATOM's
    specific positions. Fails closed: any error/missing field refuses entry
    rather than assuming margin is fine."""
    try:
        limits = api.get_limits()
        if not isinstance(limits, dict):
            return False, None
        cash = float(limits.get("cash", 0) or 0)
        col = float(limits.get("collat", limits.get("col", 0)) or 0)
        avail = float(limits.get("marginavailable", limits.get("marginallowed", cash + col)))
        return avail >= MARGIN_FLOOR_INR, avail
    except Exception:
        return False, None


NUCLEUS_ALLOCATION_FILE = Path(__file__).resolve().parent / "data" / "nucleus_allocation.json"
NUCLEUS_MAX_AGE_MIN = 1080  # 18h — covers overnight gap (15:00→09:00); intraday freshness is
# guaranteed by the 15-min refresh cadence below


def _nucleus_ceiling(tier: str = "T3_HYDROGEN") -> tuple[float | None, str | None]:
    """T3 capital ceiling from NUCLEUS (antariksh/nucleus.py), dynamically swept
    across all 4 tiers off real broker margin. Fail-closed: any read/parse/
    staleness failure returns (None, reason) — caller must refuse entry rather
    than assume unlimited capital."""
    try:
        raw = json.loads(NUCLEUS_ALLOCATION_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None, "NO_FILE"
    try:
        ts = datetime.fromisoformat(raw["updated_at"])
        ceiling = float(raw["tiers"][tier]["ceiling_inr"])
    except (KeyError, TypeError, ValueError):
        return None, "MALFORMED"
    age_min = (datetime.now() - ts).total_seconds() / 60
    if age_min < 0:
        return None, "FUTURE_TIMESTAMP"
    if age_min > NUCLEUS_MAX_AGE_MIN:
        return None, "STALE"
    return ceiling, None


def broker_position_qty(api, tsym: str) -> int | None:
    try:
        positions = api.get_positions() or []
        by_tsym = {p["tsym"]: int(float(p["netqty"])) for p in positions}
        return by_tsym.get(tsym, 0)
    except Exception:
        return None


def broker_confirms_flat(api, state: dict) -> bool:
    pos = state.get("open_position")
    if not pos:
        return True
    for leg in pos["legs"].values():
        qty = broker_position_qty(api, leg["tsym"])
        if qty is None or qty != 0:
            return False
    return True


def _resolve_legs(
    index: str, expiry: date, spot: float, sp: float, lp: float, sc: float, lc: float
) -> dict:
    cfg = INDEX_CONFIG[index]
    kwargs = {cfg["resolver_kwarg"]: spot}
    tr = TokenResolver(**kwargs)
    gap = cfg["gap"]
    atm = round(spot / gap) * gap
    max_offset = max(abs(atm - lp), abs(lc - atm))
    atm_range = int(np.ceil(max_offset / gap)) + 1
    rows = getattr(tr, cfg["resolver_method"])(expiry, atm_range=atm_range)
    by_key = {(row["strike"], row["opt_type"]): row for row in rows}
    return {
        "short_put": by_key.get((sp, "PE")),
        "long_put": by_key.get((lp, "PE")),
        "short_call": by_key.get((sc, "CE")),
        "long_call": by_key.get((lc, "CE")),
    }


def _enter_leg_sequence(api, legs_raw: dict, leg_prices: dict, qty: int, sl_mult: float) -> dict:
    result = {"stage": None, "orders": {}, "sl_orders": {}}
    for leg_name, action in (("long_put", BUY), ("long_call", BUY)):
        leg = legs_raw[leg_name]
        r = place_leg(
            api,
            action,
            leg["exchange"],
            leg["tsym"],
            qty,
            leg_prices[leg_name],
            remarks=f"PROTON_LIVE_{leg_name}",
        )
        result["orders"][leg_name] = {"ok": r.ok, "norenordno": r.norenordno, "raw": r.raw}
        if not r.ok:
            result["stage"] = f"failed_{leg_name}"
            return result
    for leg_name, action in (("short_put", SELL), ("short_call", SELL)):
        leg = legs_raw[leg_name]
        r = place_leg(
            api,
            action,
            leg["exchange"],
            leg["tsym"],
            qty,
            leg_prices[leg_name],
            remarks=f"PROTON_LIVE_{leg_name}",
        )
        result["orders"][leg_name] = {"ok": r.ok, "norenordno": r.norenordno, "raw": r.raw}
        if not r.ok:
            result["stage"] = f"failed_{leg_name}_hedges_live"
            return result
    # resting SL-LMT per short leg — the broker-side backstop the software
    # combo-check doesn't have. Trigger = that leg's own entry fill * (1+sl_mult).
    # A failure here does NOT unwind the (already-live, correctly hedged) position —
    # it means "protected only by the software poll until fixed," logged loudly.
    for leg_name in ("short_put", "short_call"):
        leg = legs_raw[leg_name]
        trigger = leg_prices[leg_name] * (1 + sl_mult)
        r = place_resting_sl(
            api,
            BUY,
            leg["exchange"],
            leg["tsym"],
            qty,
            trigger,
            remarks=f"PROTON_LIVE_SL_{leg_name}",
        )
        result["sl_orders"][leg_name] = {"ok": r.ok, "norenordno": r.norenordno, "raw": r.raw}
        if not r.ok:
            result["stage"] = f"complete_but_sl_failed_{leg_name}"
    if result["stage"] is None:
        result["stage"] = "complete"
    return result


def _cancel_resting_sl(api, sl_order_ids: dict) -> dict:
    canceled = {}
    for leg_name, ordno in (sl_order_ids or {}).items():
        if not ordno:
            continue
        r = cancel_order(api, ordno)
        canceled[leg_name] = {"ok": r.ok, "raw": r.raw}
    return canceled


def _exit_leg_sequence(
    api, legs: dict, leg_prices: dict, qty: int, sl_order_ids: dict = None
) -> dict:
    result = {"stage": None, "orders": {}, "sl_cancel": {}}
    # cancel resting SL orders first — about to close these legs via market
    # exit, a stale resting stop must not also fire and double-close
    result["sl_cancel"] = _cancel_resting_sl(api, sl_order_ids)
    for leg_name, action in (
        ("short_put", BUY),
        ("short_call", BUY),
        ("long_put", SELL),
        ("long_call", SELL),
    ):
        leg = legs[leg_name]
        r = place_leg(
            api,
            action,
            leg["exchange"],
            leg["tsym"],
            qty,
            leg_prices[leg_name],
            remarks=f"PROTON_LIVE_CLOSE_{leg_name}",
        )
        result["orders"][leg_name] = {"ok": r.ok, "norenordno": r.norenordno, "raw": r.raw}
        if not r.ok:
            result["stage"] = f"failed_close_{leg_name}"
            return result
    result["stage"] = "complete"
    return result


def _check_exit(state: dict, today: date) -> dict | None:
    pos = state["open_position"]
    index = pos["index"]
    closes = combined_daily_closes(index)
    S = float(closes[closes.index <= today].iloc[-1])
    expiry = date.fromisoformat(pos["expiry"])

    api = _shoonya_session()
    if api is None:
        _log_ledger({"action": "SKIP_TICK", "reason": "no_broker_session", "index": index})
        return None

    legs = pos["legs"]
    sl_order_ids = pos.get("sl_order_ids", {})

    # reconciliation: did a resting SL already fire at the broker since the
    # last tick (e.g. cron was down, or it fired between polls)? If a short
    # leg is already flat at the broker while state still says open, don't
    # run the normal combo-value check against stale legs — halt for a human
    # rather than guess at what already happened.
    if LIVE_ENABLED:
        for leg_name in ("short_put", "short_call"):
            qty = broker_position_qty(api, legs[leg_name]["tsym"])
            if qty is not None and qty == 0:
                event = {
                    "action": "HALT_RESTING_SL_FIRED_UNRECONCILED",
                    "index": index,
                    "leg": leg_name,
                    "note": "broker shows this short leg flat but "
                    "state still has the position open — resting SL likely fired "
                    "between ticks; needs human reconciliation before this module "
                    "touches the position again",
                }
                state["stranded_legs"] = {"cycle": pos, "reason": "resting_sl_fired_unreconciled"}
                _save_state(state)
                _log_ledger(event)
                return event

    real = _real_combo_value(api, legs)
    if np.isnan(real.value):
        _log_ledger({"action": "SKIP_TICK", "reason": "unpriceable", "index": index, "spot": S})
        return None
    val, leg_prices = real.value, real.leg_prices
    credit = pos["credit"]
    sl_mult = pos.get("sl_mult", BASE_SL_MULT)
    pt_level, sl_level = credit * (1 - PT_FRAC), credit * (1 + sl_mult)

    reason = None
    if val <= pt_level:
        reason = "PT"
    elif val >= sl_level:
        reason = "SL"
    elif today >= expiry:
        reason = "EXPIRY"

    if reason is None:
        _log_ledger(
            {
                "action": "HOLD",
                "index": index,
                "spot": S,
                "combo_value": val,
                "unrealized_per_lot": (credit - val) * (INDEX_CONFIG[index]["lot_size"]),
            }
        )
        return None

    event = {
        "action": "EXIT_TRIGGER",
        "index": index,
        "reason": reason,
        "spot": S,
        "combo_value": val,
        "dry_run": not LIVE_ENABLED,
    }
    if not LIVE_ENABLED:
        event["would_close_legs"] = {k: v["tsym"] for k, v in legs.items()}
        _log_ledger(event)
        return event

    close_result = _exit_leg_sequence(api, legs, leg_prices, pos["qty"], sl_order_ids)
    event["close_result"] = close_result
    if close_result["stage"] == "complete":
        event["pnl_per_lot"] = (credit - val) * INDEX_CONFIG[index]["lot_size"]
        state["open_position"] = None
        _save_state(state)
    else:
        event["partial_close_needs_human"] = True
    _log_ledger(event)
    return event


def _try_enter(index: str, state: dict, today: date, now: datetime) -> dict | None:
    cfg = INDEX_CONFIG[index]
    api = _shoonya_session()
    if api is None:
        _log_ledger({"action": "SKIP", "index": index, "reason": "no_broker_session"})
        return None
    if not broker_confirms_flat(api, state):
        event = {
            "action": "REFUSE_ENTRY",
            "index": index,
            "reason": "broker_position_check_failed_or_nonzero",
        }
        _log_ledger(event)
        return event

    if LIVE_ENABLED:
        margin_ok, avail_margin = check_account_margin(api)
        if not margin_ok:
            event = {
                "action": "REFUSE_ENTRY",
                "index": index,
                "reason": "margin_floor_check_failed",
                "available_margin": avail_margin,
                "floor": MARGIN_FLOOR_INR,
            }
            _log_ledger(event)
            return event

    closes = combined_daily_closes(index)
    rv = trailing_rv(closes, today)
    med = trailing_median_rv(closes, today)
    if np.isnan(rv) or np.isnan(med) or rv <= med:
        _log_ledger(
            {"action": "SKIP", "index": index, "reason": "vol_filter", "rv": rv, "median_rv": med}
        )
        return None

    expiry = resolve_weekly_expiry(index, now)
    S0 = float(closes[closes.index <= today].iloc[-1])
    T0 = max((expiry - today).days / 365, 1 / 365)
    gap = cfg["gap"]
    sp = delta_strike(S0, T0, rv, cfg["target_delta"], "put", gap)
    sc = delta_strike(S0, T0, rv, cfg["target_delta"], "call", gap)
    wing = round(S0 * WING_PCT / gap) * gap
    lp, lc = sp - wing, sc + wing

    legs_raw = _resolve_legs(index, expiry, S0, sp, lp, sc, lc)
    if any(v is None for v in legs_raw.values()):
        _log_ledger({"action": "SKIP", "index": index, "reason": "leg_resolution_incomplete"})
        return None
    legs = {
        k: {kk: v[kk] for kk in ("exchange", "token", "tsym", "strike", "opt_type")}
        for k, v in legs_raw.items()
    }

    real = _real_combo_value(api, legs_raw)
    if np.isnan(real.value):
        _log_ledger({"action": "SKIP", "index": index, "reason": "unpriceable_at_entry"})
        return None
    credit, leg_prices = real.value, real.leg_prices
    sl_mult = atr_sl_multiplier(rv, med)

    required_margin = max(wing - credit, 0.0) * cfg["lot_size"] * MAX_LOTS
    nucleus_ceiling, nucleus_reason = _nucleus_ceiling("T3_HYDROGEN")
    if nucleus_ceiling is None or required_margin > nucleus_ceiling:
        event = {
            "action": "REFUSE_ENTRY",
            "index": index,
            "reason": "nucleus_ceiling_check_failed",
            "required_margin": required_margin,
            "nucleus_ceiling": nucleus_ceiling,
            "nucleus_fail_reason": nucleus_reason,
        }
        _log_ledger(event)
        return event

    cycle = {
        "index": index,
        "entry_date": today.isoformat(),
        "expiry": expiry.isoformat(),
        "spot_entry": S0,
        "sp": sp,
        "lp": lp,
        "sc": sc,
        "lc": lc,
        "sigma": rv,
        "credit": credit,
        "legs": legs,
        "qty": MAX_LOTS * cfg["lot_size"],
        "sl_mult": sl_mult,
    }

    event = {
        "action": "ENTER_TRIGGER",
        "index": index,
        "rv": rv,
        "median_rv": med,
        "sl_mult": sl_mult,
        "cycle": cycle,
        "dry_run": not LIVE_ENABLED,
    }
    if not LIVE_ENABLED:
        event["would_place_legs"] = {k: v["tsym"] for k, v in legs.items()}
        event["would_place_resting_sl_at"] = {
            leg_name: round(leg_prices[leg_name] * (1 + sl_mult), 2)
            for leg_name in ("short_put", "short_call")
        }
        _log_ledger(event)
        return event

    enter_result = _enter_leg_sequence(api, legs_raw, leg_prices, cycle["qty"], sl_mult)
    event["enter_result"] = enter_result
    if enter_result["stage"].startswith("complete"):
        cycle["sl_order_ids"] = {
            leg_name: v.get("norenordno")
            for leg_name, v in enter_result.get("sl_orders", {}).items()
        }
        state["open_position"] = cycle
        _save_state(state)
    else:
        state["stranded_legs"] = {
            "cycle": cycle,
            "orders": enter_result["orders"],
            "stage": enter_result["stage"],
        }
        _save_state(state)
    _log_ledger(event)
    return event


def run_live_once(now: datetime = None, use_orbiter: bool = False) -> dict:
    """Main entry point. When `use_orbiter=True` (ORBITER v3.0 Tier 2, Project
    Square 2026-07-15), dispatches to the ORBITER-specific entry/exit/morph
    codepath — Friday-only NIFTY entry, directional 2-leg spread via
    3-Gate sequential entry, 5-point TP priority array, ATR-vol TSL, and
    dynamic legging Phase 1→2 consolidation state machine. Same pattern
    as ATOM's runner.py `use_orbiter` flag."""
    now = now or datetime.now()
    today = now.date()
    state = _load_state()

    if state.get("stranded_legs"):
        event = {"action": "HALT_STRANDED_LEGS", "stranded_legs": state["stranded_legs"]}
        _log_ledger(event)
        return event

    if state.get("orbiter_position"):
        result = _check_exit_orbiter(state, today, now)
        if result:
            if (
                use_orbiter
                and result.get("action") in ("EXIT_ORBITER", "EXIT_TRIGGER_ORBITER")
                and result.get("fully_closed")
            ):
                opposite = "SENSEX" if result["index"] == "NIFTY" else "NIFTY"
                re_entry = _try_enter_orbiter(state, today, now, force_index=opposite)
                if re_entry and re_entry.get("action", "").startswith("ENTER"):
                    return {
                        "action": "ROLL_FORWARD",
                        "exit": result,
                        "re_entry": re_entry,
                    }
            return result
        morph_result = _morph_check_orbiter(state, today, now)
        if morph_result:
            return morph_result
        return {"action": "HOLD_NO_EVENT", "index": state["orbiter_position"]["index"]}

    if state.get("open_position"):
        result = _check_exit(state, today)
        return result or {"action": "HOLD_NO_EVENT", "index": state["open_position"]["index"]}

    if use_orbiter:
        result = _try_enter_orbiter(state, today, now)
        return result or {"action": "SKIP_NO_EVENT", "index": "NIFTY"}

    if now.strftime("%H:%M") < ENTRY_EOD_TIME:
        return {"action": "SKIP_NO_EVENT", "reason": "before_eod_entry_window"}

    due_index = None
    midnight_today = datetime.combine(today, datetime.min.time())
    for idx, cfg in INDEX_CONFIG.items():
        trigger_index = cfg["triggered_by_expiry_of"]
        trigger_expiry = resolve_weekly_expiry(trigger_index, midnight_today)
        if trigger_expiry == today:
            due_index = idx
            break
    if due_index is None:
        return {"action": "SKIP_NO_EVENT", "reason": "today_is_not_the_other_indexs_expiry"}

    result = _try_enter(due_index, state, today, now)
    return result or {"action": "SKIP_NO_EVENT", "index": due_index}


# ── ORBITER v3.0 Tier 2 (PROTON+) — real-order entry/exit/morph ────────────
# Ports the same 5 module specs from atom/src/atom/orbiter.py into
# proton_live.py's live-order architecture, following the same `use_orbiter`
# boolean-flag retrofit pattern as ATOM's runner.py. NIFTY-only, Friday entry,
# directional 2-leg → morph → condor. Static PT/SL remain as backstop.


def _orbiter_resolve_two_legs(
    expiry: date, spot: float, short_k: int, hedge_k: int, opt_type: str
) -> dict:
    cfg = INDEX_CONFIG["NIFTY"]
    kwargs = {cfg["resolver_kwarg"]: spot}
    tr = TokenResolver(**kwargs)
    atm = round(spot / cfg["gap"]) * cfg["gap"]
    max_offset = max(abs(atm - short_k), abs(atm - hedge_k))
    atm_range = int(np.ceil(max_offset / cfg["gap"])) + 1
    rows = getattr(tr, cfg["resolver_method"])(expiry, atm_range=atm_range)
    by_key = {(row["strike"], row["opt_type"]): row for row in rows}
    return {"short": by_key.get((short_k, opt_type)), "hedge": by_key.get((hedge_k, opt_type))}


def _orbiter_enter_legs(api, legs_raw: dict, leg_prices: dict, qty: int, sl_mult: float) -> dict:
    """Place directional 2-leg spread (hedge buy first, short sell second) +
    resting SL-LMT on the short leg. Returns result dict with stage/orders/sl_orders."""
    result = {"stage": None, "orders": {}, "sl_orders": {}}
    leg_name, action = ("hedge", BUY)
    leg = legs_raw[leg_name]
    r = place_leg(
        api,
        action,
        leg["exchange"],
        leg["tsym"],
        qty,
        leg_prices[leg_name],
        remarks=f"PROTON_ORBITER_{leg_name}",
    )
    result["orders"][leg_name] = {"ok": r.ok, "norenordno": r.norenordno, "raw": r.raw}
    if not r.ok:
        result["stage"] = f"failed_{leg_name}"
        return result
    leg_name, action = ("short", SELL)
    leg = legs_raw[leg_name]
    r = place_leg(
        api,
        action,
        leg["exchange"],
        leg["tsym"],
        qty,
        leg_prices[leg_name],
        remarks=f"PROTON_ORBITER_{leg_name}",
    )
    result["orders"][leg_name] = {"ok": r.ok, "norenordno": r.norenordno, "raw": r.raw}
    if not r.ok:
        result["stage"] = f"failed_{leg_name}_hedge_live"
        return result
    leg = legs_raw["short"]
    trigger = leg_prices["short"] * (1 + sl_mult)
    r = place_resting_sl(
        api, BUY, leg["exchange"], leg["tsym"], qty, trigger, remarks=f"PROTON_ORBITER_SL_short"
    )
    result["sl_orders"]["short"] = {"ok": r.ok, "norenordno": r.norenordno, "raw": r.raw}
    if not r.ok:
        result["stage"] = "complete_but_sl_failed"
    if result["stage"] is None:
        result["stage"] = "complete"
    return result


def _orbiter_exit_side(api, side: dict, qty: int, sl_order_ids: dict) -> dict:
    """Exit a single side (2 legs: short buyback + hedge sell). Cancels resting
    SL first. Returns result dict with stage/orders/sl_cancel.

    Closes short then hedge sequentially with an early return on failure —
    so a retry after a short-succeeds/hedge-fails partial close must not
    re-place the short order a second time. Tracks completed legs in
    side["legs_closed"] (mutated in place — `side` is the same dict object
    the caller holds in pos[...], so this persists across retries without
    extra wiring) and skips any leg already recorded there."""
    result = {"stage": None, "orders": {}, "sl_cancel": {}}
    result["sl_cancel"] = _cancel_resting_sl(api, sl_order_ids)
    already_closed = side.setdefault("legs_closed", {})
    for leg_name, action in (("short", BUY), ("hedge", SELL)):
        if leg_name in already_closed:
            result["orders"][leg_name] = {
                "ok": True,
                "norenordno": already_closed[leg_name],
                "skipped_already_closed": True,
            }
            continue
        leg = side["legs"][leg_name]
        r = place_leg(
            api,
            action,
            leg["exchange"],
            leg["tsym"],
            qty,
            side.get("exit_leg_prices", {}).get(leg_name) or 0.0,
            remarks=f"PROTON_ORBITER_CLOSE_{leg_name}",
        )
        result["orders"][leg_name] = {"ok": r.ok, "norenordno": r.norenordno, "raw": r.raw}
        if not r.ok:
            result["stage"] = f"failed_close_{leg_name}"
            return result
        already_closed[leg_name] = r.norenordno or True
    result["stage"] = "complete"
    return result


def _orbiter_price_side_broker(api, side: dict) -> dict | None:
    """Price a single side's 2 legs via real broker quotes. Returns {leg: ltp}
    or None on failure."""
    try:
        result = {}
        for leg_name, leg in side["legs"].items():
            ltp = _leg_ltp(api, leg["exchange"], leg["token"])
            if np.isnan(ltp):
                return None
            result[leg_name] = ltp
        return result
    except Exception:
        return None


def _check_exit_orbiter(state: dict, today: date, now: datetime) -> dict | None:
    pos = state["orbiter_position"]
    index = pos["index"]
    closes = combined_daily_closes(index)
    S = float(closes[closes.index <= today].iloc[-1])
    expiry = date.fromisoformat(pos["expiry"])
    entry_ts = datetime.fromisoformat(pos["entry_ts"])
    expiry_ts = datetime.combine(expiry, datetime.strptime("15:30", "%H:%M").time())
    is_expiry_day = today >= expiry

    api = _shoonya_session()
    if api is None:
        _log_ledger(
            {"action": "SKIP_TICK", "reason": "no_broker_session", "index": index, "orbiter": True}
        )
        return None

    row = orbiter_mod._read_enriched_row(index, today)
    atr = orbiter_mod._f(row.get("atr_daily")) if row else None
    exited, active_sides, side_pnls = [], [], {}
    for side_name in ("put", "call"):
        side = pos.get(side_name)
        if side is None:
            continue
        structure = "bull_put_spread" if side["opt_type"] == "PE" else "bear_call_spread"
        entry_credit = side["entry_credit"]
        entry_short_ltp = side["entry_short_ltp"]

        leg_prices = _orbiter_price_side_broker(api, side) if LIVE_ENABLED else None
        if (
            leg_prices
            and leg_prices.get("short") is not None
            and leg_prices.get("hedge") is not None
        ):
            value = leg_prices["short"] - leg_prices["hedge"]
            current_short_ltp = leg_prices["short"]
            pricing_source = "real"
        else:
            T = max((expiry - today).days / 365, 0)
            bs = black_scholes_put if side["opt_type"] == "PE" else black_scholes_call
            value = bs(S, side["short_k"], T, RISK_FREE_RATE, pos["sigma"]) - bs(
                S, side["hedge_k"], T, RISK_FREE_RATE, pos["sigma"]
            )
            current_short_ltp = None
            pricing_source = "bs_fallback"

        pnl = (entry_credit - value) * INDEX_CONFIG[index]["lot_size"]
        side_pnls[side_name] = pnl
        static_pt = entry_credit * (1 - PT_FRAC)
        static_sl = entry_credit * (1 + SL_MULT)

        reason = None
        if value <= static_pt:
            reason = "PT"
        elif value >= static_sl:
            reason = "SL"

        dynamic_sl = side["dynamic_sl"]
        if reason is None and current_short_ltp is not None:
            if atr:
                dynamic_sl = orbiter_mod.orbiter_tsl_ratchet(
                    dynamic_sl, entry_short_ltp, current_short_ltp, atr
                )
                side["dynamic_sl"] = dynamic_sl
            catastrophe = orbiter_mod.orbiter_catastrophe_stop(dynamic_sl)
            if current_short_ltp >= catastrophe:
                reason = "CATASTROPHE_STOP"
            elif current_short_ltp >= dynamic_sl:
                reason = "TSL_ATR"

        if reason is None and row is not None and not is_expiry_day:
            tp = orbiter_mod.orbiter_tp_check(
                structure, entry_credit, pnl, row, S, entry_ts, expiry_ts, now
            )
            if tp.triggered:
                reason = tp.reason
                pnl = tp.pnl if tp.pnl is not None else pnl

        if is_expiry_day and reason is None:
            reason = "EXPIRY"

        if reason:
            exited.append(
                {
                    "side": side_name,
                    "reason": reason,
                    "pnl": pnl,
                    "value": value,
                    "pricing_source": pricing_source,
                }
            )
        else:
            active_sides.append(side_name)

    if not exited and active_sides:
        total_credit = sum(pos[s]["entry_credit"] for s in active_sides if pos.get(s))
        total_pnl = sum(side_pnls[s] for s in active_sides if s in side_pnls)
        total_max_profit = total_credit * INDEX_CONFIG[index]["lot_size"]
        if total_max_profit > 0 and total_pnl >= total_max_profit * 0.5:
            for s in active_sides:
                exited.append(
                    {
                        "side": s,
                        "reason": "HARVEST_50",
                        "pnl": side_pnls.get(s),
                        "value": None,
                        "pricing_source": "harvest_aggregate",
                    }
                )

    if not exited:
        if active_sides:
            _save_state(state)
        return None

    if not LIVE_ENABLED:
        for ex in exited:
            pos[ex["side"]] = None
        # Only clear the whole position when NO side is still active. A
        # consolidated iron condor where only one leg (e.g. put) hit its own
        # exit condition must keep the surviving leg (call) tracked, not get
        # silently dropped — that was the pre-existing bug: this branch used
        # to null state["orbiter_position"] unconditionally whenever ANY
        # side exited, orphaning any leg that hadn't. Reverting phase to
        # DIRECTIONAL_ANCHOR lets _morph_check_orbiter re-engage for the
        # survivor on a later tick, same as a fresh single-side entry.
        fully_closed = len(active_sides) == 0
        if fully_closed:
            state["orbiter_position"] = None
        else:
            pos["phase"] = "DIRECTIONAL_ANCHOR"
            state["orbiter_position"] = pos
        event = {
            "action": "EXIT_TRIGGER_ORBITER",
            "index": index,
            "spot": S,
            "exits": exited,
            "dry_run": True,
            "would_close_sides": list(e["side"] for e in exited),
            # Gates the ROLL_FORWARD-to-opposite-exchange path in
            # run_live_once() — must only be True on a genuine full close,
            # never while a leg survives (DS review 2026-07-22).
            "fully_closed": fully_closed,
        }
        _save_state(state)
        _log_ledger(event)
        return event

    close_results = []
    for ex in exited:
        side = pos[ex["side"]]
        sl_ids = side.get("sl_order_ids", {})
        side["exit_leg_prices"] = _orbiter_price_side_broker(api, side)
        close_result = _orbiter_exit_side(api, side, pos["qty"], sl_ids)
        close_results.append({"side": ex["side"], "close_result": close_result})
        # Only drop the leg from tracking if the broker close actually
        # completed. A failed close (network blip, rejection) must stay
        # tracked — nulling it unconditionally here orphans a REAL open
        # position with no further SL/TP/TSL monitoring (DS review
        # 2026-07-22: pre-existing, found while fixing the related
        # partial-exit bug below).
        if close_result["stage"] == "complete":
            pos[ex["side"]] = None

    all_ok = all(cr["close_result"]["stage"] == "complete" for cr in close_results)
    # Same fix as the paper branch: a successful close of the exited leg(s)
    # does not mean the WHOLE position is closed if another leg is still
    # active and untouched — only clear state when nothing remains open.
    fully_closed = all_ok and len(active_sides) == 0
    if fully_closed:
        state["orbiter_position"] = None
    else:
        pos["phase"] = "DIRECTIONAL_ANCHOR"
        state["orbiter_position"] = pos
    _save_state(state)

    event = {
        "action": "EXIT_ORBITER",
        "index": index,
        "spot": S,
        "exits": exited,
        "close_results": close_results,
        "fully_closed": fully_closed,
    }
    _log_ledger(event)
    return event


_MORPH_SIDE = {"put": "call", "call": "put"}
_MORPH_STRUCT = {"bull_put_spread": "bear_call_spread", "bear_call_spread": "bull_put_spread"}


def _morph_check_orbiter(state: dict, today: date, now: datetime) -> dict | None:
    pos = state["orbiter_position"]
    if pos["phase"] != "DIRECTIONAL_ANCHOR":
        return None
    active_sides = [s for s in ("put", "call") if pos.get(s) is not None]
    if len(active_sides) != 1:
        return None
    side_name = active_sides[0]
    side = pos[side_name]

    row = orbiter_mod._read_enriched_row(pos["index"], today)
    if row is None:
        return None
    S = float(combined_daily_closes(pos["index"])[lambda s: s[s.index <= today]].iloc[-1])
    structure = "bull_put_spread" if side["opt_type"] == "PE" else "bear_call_spread"
    if not orbiter_mod.consolidation_trigger(row, structure, side["short_k"], S):
        return None

    other_structure = _MORPH_STRUCT[structure]
    other_side_name = _MORPH_SIDE[side_name]
    opt_type = "PE" if other_structure == "bull_put_spread" else "CE"
    smap = orbiter_mod.gate2_strikes(row, S)
    short_k = smap.put_short if opt_type == "PE" else smap.call_short
    hedge_k = smap.put_hedge if opt_type == "PE" else smap.call_hedge
    expiry = date.fromisoformat(pos["expiry"])
    legs_raw = _orbiter_resolve_two_legs(expiry, S, short_k, hedge_k, opt_type)
    if legs_raw.get("short") is None or legs_raw.get("hedge") is None:
        return None
    api = _shoonya_session()
    leg_prices = {}
    if api is not None:
        for ln in ("short", "hedge"):
            ltp = _leg_ltp(api, legs_raw[ln]["exchange"], legs_raw[ln]["token"])
            if not np.isnan(ltp):
                leg_prices[ln] = ltp
    if len(leg_prices) < 2:
        T = max((expiry - today).days / 365, 1 / 365)
        bs = black_scholes_put if opt_type == "PE" else black_scholes_call
        short_ltp = bs(S, short_k, T, RISK_FREE_RATE, pos["sigma"])
        hedge_ltp = bs(S, hedge_k, T, RISK_FREE_RATE, pos["sigma"])
        leg_prices = {"short": short_ltp, "hedge": hedge_ltp}
    entry_credit = leg_prices["short"] - leg_prices["hedge"]
    entry_short_ltp = leg_prices["short"]
    atr = orbiter_mod._f(row.get("atr_daily")) or orbiter_mod._f(row.get("atr"))
    dynamic_sl = orbiter_mod.orbiter_initial_tsl(entry_short_ltp, atr)
    legs = {
        "short": {
            k: v
            for k, v in legs_raw["short"].items()
            if k in ("exchange", "token", "tsym", "strike", "opt_type")
        },
        "hedge": {
            k: v
            for k, v in legs_raw["hedge"].items()
            if k in ("exchange", "token", "tsym", "strike", "opt_type")
        },
    }
    new_side = {
        "short_k": short_k,
        "hedge_k": hedge_k,
        "opt_type": opt_type,
        "entry_credit": entry_credit,
        "entry_short_ltp": entry_short_ltp,
        "dynamic_sl": dynamic_sl,
        "legs": legs,
    }
    if LIVE_ENABLED and api is not None:
        enter_result = _orbiter_enter_legs(
            api, legs_raw, leg_prices, pos["qty"], BASE_SL_MULT * ATR_SL_MULTIPLIER
        )
        if enter_result["stage"].startswith("complete"):
            new_side["sl_order_ids"] = {
                "short": enter_result.get("sl_orders", {}).get("short", {}).get("norenordno")
            }
        else:
            return {
                "action": "MORPH_ADD_FAILED",
                "index": pos["index"],
                "structure": other_structure,
                "enter_result": enter_result,
            }
    pos[other_side_name] = new_side
    pos["phase"] = "CONSOLIDATION"
    _save_state(state)
    event = {
        "action": "MORPH_ADD",
        "index": pos["index"],
        "spot": S,
        "phase": "CONSOLIDATION",
        "added_side": other_side_name,
        "structure": other_structure,
        "live": LIVE_ENABLED,
    }
    _log_ledger(event)
    return event


def _try_enter_orbiter(
    state: dict, today: date, now: datetime, force_index: str | None = None
) -> dict | None:
    """Entry via ORBITER Gates 1/2/3 onto the nearest-expiry index. When
    `force_index` is given (e.g. "SENSEX" after HARVEST_50 on NIFTY), enters
    that index regardless of nearest-expiry computation — roll-forward path."""
    if force_index:
        index = force_index
    else:
        index = _nearest_expiry_index(now)
    if index is None:
        return {"action": "SKIP_NO_EVENT", "reason": "no_resolvable_expiry"}

    closes = combined_daily_closes(index)
    rv = trailing_rv(closes, today)
    med = trailing_median_rv(closes, today)
    if np.isnan(rv) or np.isnan(med) or rv <= med:
        return {"action": "SKIP_NO_EVENT", "reason": "vol_filter", "rv": rv, "median_rv": med}

    row = orbiter_mod._read_enriched_row(index, today)
    if row is None:
        return {"action": "SKIP_NO_EVENT", "reason": "no_enriched_data"}
    if row.get("_stale_fallback"):
        _log_ledger(
            {
                "action": "STALE_ENRICHED_DATA",
                "index": index,
                "note": "using yesterday's enriched row — today's not yet available",
            }
        )

    g1 = orbiter_mod.gate1_regime(row)
    g1 = orbiter_mod.gate1_tiger_override(row, g1, row.get("timestamp"))
    if not g1.passed:
        _log_ledger(
            {"action": "GATE_BLOCKED", "gate": g1.gate, "reason": g1.reason, "details": g1.details}
        )
        return {"action": "SKIP_NO_EVENT", "reason": g1.reason}

    g3 = orbiter_mod.gate3_entry_abort(row)
    if not g3.passed:
        _log_ledger({"action": "GATE_BLOCKED", "gate": g3.gate, "reason": g3.reason})
        return {"action": "SKIP_NO_EVENT", "reason": g3.reason}

    api = _shoonya_session()
    if api is None:
        _log_ledger({"action": "SKIP", "index": index, "reason": "no_broker_session"})
        return None
    if not broker_confirms_flat(api, state):
        return {
            "action": "REFUSE_ENTRY",
            "index": index,
            "reason": "broker_position_check_failed_or_nonzero",
        }

    if LIVE_ENABLED:
        margin_ok, avail_margin = check_account_margin(api)
        if not margin_ok:
            return {
                "action": "REFUSE_ENTRY",
                "index": index,
                "reason": "margin_floor_check_failed",
                "available_margin": avail_margin,
                "floor": MARGIN_FLOOR_INR,
            }

    S0 = float(closes[closes.index <= today].iloc[-1])
    structure = orbiter_mod.phase_machine_direction(row, S0)
    smap = orbiter_mod.gate2_strikes(row, S0)
    opt_type = "PE" if structure == "bull_put_spread" else "CE"
    side_name = _SIDE_FOR_STRUCTURE_MAP[structure]
    short_k, hedge_k = (
        (smap.put_short, smap.put_hedge) if opt_type == "PE" else (smap.call_short, smap.call_hedge)
    )
    expiry = resolve_weekly_expiry(index, now)
    legs_raw = _orbiter_resolve_two_legs(expiry, S0, short_k, hedge_k, opt_type)
    if legs_raw.get("short") is None or legs_raw.get("hedge") is None:
        return {"action": "SKIP_NO_EVENT", "reason": "leg_resolution_incomplete"}

    leg_prices = {}
    if api is not None:
        for ln in ("short", "hedge"):
            ltp = _leg_ltp(api, legs_raw[ln]["exchange"], legs_raw[ln]["token"])
            if not np.isnan(ltp):
                leg_prices[ln] = ltp
    if len(leg_prices) < 2:
        T0 = max((expiry - today).days / 365, 1 / 365)
        bs = black_scholes_put if opt_type == "PE" else black_scholes_call
        leg_prices["short"] = bs(S0, short_k, T0, RISK_FREE_RATE, rv)
        leg_prices["hedge"] = bs(S0, hedge_k, T0, RISK_FREE_RATE, rv)
    entry_credit = leg_prices["short"] - leg_prices["hedge"]
    entry_short_ltp = leg_prices["short"]

    cfg = INDEX_CONFIG[index]
    sl_mult = atr_sl_multiplier(rv, med)
    # BUG FIX (2026-07-19, found while building orchestrator tests): was
    # `max(hedge_k - short_k, 0)` — via gate2_strikes, hedge is ALWAYS
    # below short for puts (put_hedge = put_short - wing*step) and ALWAYS
    # above short for calls (call_hedge = call_short + wing*step), so this
    # was silently 0 for every bull_put_spread regardless of wing width —
    # the NUCLEUS capital ceiling could never block a put-side entry, only
    # ever a call-side one. Matches the legacy (non-orbiter) _try_enter's
    # already-correct, side-agnostic pattern: max(width - credit, 0), DS
    # confirmed as the right fix over a bare abs() (which would ignore
    # premium collected and needlessly over-block valid entries).
    wing = abs(hedge_k - short_k)
    required_margin = max(wing - entry_credit, 0.0) * cfg["lot_size"] * MAX_LOTS
    nucleus_ceiling, nucleus_reason = _nucleus_ceiling("T3_HYDROGEN")
    if nucleus_ceiling is not None and required_margin > nucleus_ceiling:
        return {
            "action": "REFUSE_ENTRY",
            "index": index,
            "reason": "nucleus_ceiling_check_failed",
            "required_margin": required_margin,
            "nucleus_ceiling": nucleus_ceiling,
            "nucleus_fail_reason": nucleus_reason,
        }
    if LIVE_ENABLED and nucleus_ceiling is None and nucleus_reason in ("NO_FILE", "STALE"):
        # NUCLEUS file missing or stale — fall back to broker-reported free
        # margin as a floor check rather than refuse entry (prevents a
        # missing allocation file from blocking a Monday open)
        margin_ok, avail = check_account_margin(api) if api is not None else (False, None)
        if not margin_ok:
            return {
                "action": "REFUSE_ENTRY",
                "index": index,
                "reason": "nucleus_missing_fallback_margin_check_failed",
                "nucleus_fail_reason": nucleus_reason,
                "available_margin": avail,
            }
        _log_ledger(
            {
                "action": "NUCLEUS_FALLBACK",
                "index": index,
                "nucleus_reason": nucleus_reason,
                "note": "using broker margin floor check while NUCLEUS unavailable",
            }
        )

    atr = orbiter_mod._f(row.get("atr_daily")) or orbiter_mod._f(row.get("atr"))
    dynamic_sl = orbiter_mod.orbiter_initial_tsl(entry_short_ltp, atr)
    legs = {
        "short": {
            k: v
            for k, v in legs_raw["short"].items()
            if k in ("exchange", "token", "tsym", "strike", "opt_type")
        },
        "hedge": {
            k: v
            for k, v in legs_raw["hedge"].items()
            if k in ("exchange", "token", "tsym", "strike", "opt_type")
        },
    }
    side = {
        "short_k": short_k,
        "hedge_k": hedge_k,
        "opt_type": opt_type,
        "entry_credit": entry_credit,
        "entry_short_ltp": entry_short_ltp,
        "dynamic_sl": dynamic_sl,
        "legs": legs,
    }
    opposite = _MORPH_SIDE[side_name]
    cycle = {
        "index": index,
        "entry_date": today.isoformat(),
        "entry_ts": now.isoformat(),
        "expiry": expiry.isoformat(),
        "structure": structure,
        "phase": "DIRECTIONAL_ANCHOR",
        "spot_entry": S0,
        "sigma": rv,
        "qty": MAX_LOTS * cfg["lot_size"],
        side_name: side,
        opposite: None,
    }
    event = {
        "action": "ENTER_TRIGGER_ORBITER",
        "index": index,
        "rv": rv,
        "median_rv": med,
        "structure": structure,
        "gate1": g1.reason,
        "gate3": g3.reason,
        "cycle": cycle,
        "dry_run": not LIVE_ENABLED,
    }
    if not LIVE_ENABLED:
        event["would_place_side"] = side_name
        event["would_place_resting_sl_at"] = round(leg_prices["short"] * (1 + sl_mult), 2)
        # Paper mode must still persist the cycle — _check_exit_orbiter/
        # _morph_check_orbiter already manage state["orbiter_position"]
        # correctly regardless of LIVE_ENABLED (BS-fallback pricing, no real
        # order calls). Without this the entry was logged every tick and
        # immediately forgotten — never actually tracked to SL/TP/exit.
        state["orbiter_position"] = cycle
        _save_state(state)
        _log_ledger(event)
        return event
    enter_result = _orbiter_enter_legs(api, legs_raw, leg_prices, cycle["qty"], sl_mult)
    event["enter_result"] = enter_result
    if enter_result["stage"].startswith("complete"):
        side["sl_order_ids"] = {
            "short": enter_result.get("sl_orders", {}).get("short", {}).get("norenordno")
        }
        cycle[side_name] = side
        state["orbiter_position"] = cycle
        _save_state(state)
    else:
        state["stranded_legs"] = {
            "cycle": cycle,
            "orders": enter_result["orders"],
            "stage": enter_result["stage"],
        }
        _save_state(state)
    _log_ledger(event)
    return event


_SIDE_FOR_STRUCTURE_MAP = {"bull_put_spread": "put", "bear_call_spread": "call"}


def _nearest_expiry_index(now: datetime) -> str | None:
    """Return the index (NIFTY/SENSEX) whose weekly expiry is closest to today,
    breaking ties in favour of NIFTY. Returns None if neither is resolvable."""
    nifty_expiry = resolve_weekly_expiry("NIFTY", now)
    sensex_expiry = resolve_weekly_expiry("SENSEX", now)
    nifty_days = (nifty_expiry - now.date()).days
    sensex_days = (sensex_expiry - now.date()).days
    if nifty_days < 0 and sensex_days < 0:
        return None
    if nifty_days < 0:
        return "SENSEX"
    if sensex_days < 0:
        return "NIFTY"
    return "NIFTY" if nifty_days <= sensex_days else "SENSEX"


if __name__ == "__main__":
    result = run_live_once(use_orbiter=True)
    print(json.dumps(result, indent=2, default=str))
    if not LIVE_ENABLED:
        print(
            "\n[DRY_RUN] set PROTON_LIVE_TRADING=YES_REAL_MONEY to place real orders.",
            file=sys.stderr,
        )
