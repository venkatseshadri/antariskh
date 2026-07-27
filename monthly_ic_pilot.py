"""NEUTRON — monthly NIFTY iron-condor paper pilot.

Locked strategy (backtested 2026-07-09 on 11yr real NIFTY data, 71.7% win rate,
+Rs17,377/lot/11yr, holds up on chronological split — see memory:
atom_future_thoughts.md idea 2 / mcx_entry_redesign_pending.md):
  - Enter only if trailing 20d realized vol > its own trailing ~6mo median
  - Short strikes at 1SD (entry-day trailing RV) off spot
  - 150pt wing
  - Close at 60% of credit captured (profit target)
  - Stop at 1.0x credit lost
  - Real NIFTY monthly expiry via config.token_resolver.resolve_monthly_expiry()

Isolation (explicit requirement — must not disturb ATOM's live weekly pipeline):
  - Paper only. No broker orders.
  - Real premiums via a Flattrade session — separate broker, separate
    credentials/token from ATOM's Shoonya session (feed.py), zero shared
    session/rate-limit contention. Own on-demand REST quote calls (once/day,
    4 legs), not a persistent WebSocket subscription — does NOT touch
    feed.py's subscription set or the shared capture SQLite/option_prices
    table in any way.
  - Falls back to Black-Scholes modeling (backtester.black_scholes_call/put)
    if the Flattrade session/quote fetch fails for any reason — logged via
    "pricing_source" so a degraded day is visible in the ledger, not silent.
  - Own state/ledger files only. No writes to the shared capture SQLite or
    any table ATOM reads/writes (trade_outcomes, market_data, option_prices).
  - Reads market_data read-only (mode=ro) — same pattern as tools/entry_tools.py.

Run once per trading day via `run_daily()`. Scheduled every 15 min, 9:15-15:30
IST weekdays, via cron/run_monthly_ic_pilot.sh (own flock, own log — mirrors
run_atom_paper.sh). Entry-day strike sizing uses last daily close (not live
intraday spot) — more frequent runs mainly buy faster PT/SL reaction, not
fresher entries; acceptable given ~5 entries/year and the backtest itself
was daily-granularity.
"""

import json
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from datetime import date, datetime

import numpy as np
import pandas as pd

from config.token_resolver import resolve_monthly_expiry, TokenResolver
from config.sqlite_schema import get_sqlite_capture_path
from backtester import black_scholes_call, black_scholes_put

FLATTRADE_ROOT = Path("/home/trading_ceo/python-trader/FlattradeApi")
FLATTRADE_TOKENS_PATH = FLATTRADE_ROOT / "tokens.json"
FLATTRADE_HOST = "https://piconnect.flattrade.in/PiConnectAPI/"
FLATTRADE_WS = "wss://piconnect.flattrade.in/PiConnectWSAPI/"

WING = 150
SL_MULT = 1.0
PT_FRAC = 0.6
RISK_FREE_RATE = 0.06
RV_WINDOW = 20
RV_MEDIAN_LOOKBACK = 126
STRIKE_GAP = 50
LOT_SIZE = 75

HIST_CSV = Path("/home/trading_ceo/trading-knowledge-base/nifty_minute_2015_2026.csv")
STATE_PATH = Path(__file__).resolve().parent / "data" / "neutron" / "monthly_ic_pilot_state.json"
LEDGER_PATH = Path(__file__).resolve().parent / "logs" / "neutron" / "monthly_ic_pilot.jsonl"


def _historical_daily_closes() -> pd.Series:
    df = pd.read_csv(HIST_CSV, usecols=["date", "close"], parse_dates=["date"])
    df["day"] = df["date"].dt.date
    return df.groupby("day")["close"].last()


def _live_daily_closes() -> pd.Series:
    """Read-only against the shared capture SQLite. No writes, no lock contention risk."""
    path = get_sqlite_capture_path("NIFTY")
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        # close>0: known feed bug class writes 0.0 on lp-less ticks (see memory
        # sensex_option_capture_zero_ltp) — drop bad ticks, keep last valid close/day.
        rows = con.execute(
            "SELECT timestamp, close FROM market_data "
            "WHERE instrument='NIFTY' AND close > 0 ORDER BY timestamp"
        ).fetchall()
    finally:
        con.close()
    if not rows:
        return pd.Series(dtype=float)
    df = pd.DataFrame(rows, columns=["timestamp", "close"])
    df["day"] = pd.to_datetime(df["timestamp"]).dt.date
    return df.groupby("day")["close"].last()


def combined_daily_closes() -> pd.Series:
    """Historical CSV (through 2026-01-23) + live capture (2026-05-29 onward).
    Known gap Jan24-May28 2026 (capture wasn't running yet) — doesn't
    materially affect a 20d/126d trailing window."""
    hist = _historical_daily_closes()
    live = _live_daily_closes()
    if live.empty:
        return hist
    return pd.concat([hist, live[~live.index.isin(hist.index)]]).sort_index()


def _log_returns(closes: pd.Series, asof: date) -> pd.Series:
    s = closes[closes.index <= asof]
    return np.log(s / s.shift(1)).dropna()


def trailing_rv(closes: pd.Series, asof: date, window: int = RV_WINDOW) -> float:
    logret = _log_returns(closes, asof)
    if len(logret) < window:
        return float("nan")
    return float(logret.tail(window).std() * np.sqrt(252))


def trailing_median_rv(closes: pd.Series, asof: date) -> float:
    logret = _log_returns(closes, asof)
    rv = logret.rolling(RV_WINDOW).std() * np.sqrt(252)
    rv = rv.tail(RV_MEDIAN_LOOKBACK).dropna()
    if rv.empty:
        return float("nan")
    return float(rv.median())


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


def _flattrade_session():
    """Own Flattrade session — separate broker/credentials from ATOM's Shoonya
    session in feed.py. Returns None (triggers BS fallback) on any failure;
    a broken/expired token here must never raise into the daily cycle."""
    try:
        creds = json.loads(FLATTRADE_TOKENS_PATH.read_text())
        if not creds.get("exchange_ok"):
            return None
        if str(FLATTRADE_ROOT) not in sys.path:
            sys.path.insert(0, str(FLATTRADE_ROOT))
        from NorenRestApiPy.NorenApi import NorenApi
        api = NorenApi(host=FLATTRADE_HOST, websocket=FLATTRADE_WS)
        if not api.set_session(creds["user_id"], "", creds["access_token"]):
            return None
        return api
    except Exception:
        return None


MARGIN_FLOOR_INR = 50_000.0  # same floor ATOM/PROTON's check_account_margin() uses


def check_account_margin(api) -> tuple[bool, float | None]:
    """Real Flattrade-reported free margin, account-level (cash + collateral —
    Flattrade's get_limits() schema, distinct from Shoonya's collat/marginavailable
    fields used in proton_live.py's version of this check). Fails closed: any
    error/missing field/no session refuses entry rather than assuming margin is fine."""
    if api is None:
        return False, None
    try:
        limits = api.get_limits()
        if not isinstance(limits, dict) or limits.get("stat") != "Ok":
            return False, None
        cash = float(limits.get("cash", 0) or 0)
        collateral = float(limits.get("collateral", 0) or 0)
        avail = cash + collateral
        return avail >= MARGIN_FLOOR_INR, avail
    except Exception:
        return False, None


def _leg_ltp(api, exchange: str, token: str) -> float:
    """Real LTP for one leg, or NaN if the quote call fails."""
    try:
        q = api.get_quotes(exchange, token)
        if q and q.get("stat") == "Ok":
            return float(q.get("lp", "nan"))
    except Exception:
        pass
    return float("nan")


def _resolve_legs(expiry: date, spot: float, sp: float, lp: float, sc: float, lc: float) -> dict:
    """Real tsym/token for the 4 target strikes at this expiry, via the same
    broker-master-driven resolver ATOM's weekly path uses (read-only, no
    subscription side effects)."""
    atm = round(spot / STRIKE_GAP) * STRIKE_GAP
    max_offset = max(abs(atm - lp), abs(lc - atm))
    atm_range = int(np.ceil(max_offset / STRIKE_GAP)) + 1
    tr = TokenResolver(nifty_spot=spot)
    rows = tr.resolve_weekly_nifty_for_expiry(expiry, atm_range=atm_range)
    by_key = {(row["strike"], row["opt_type"]): row for row in rows}
    legs = {
        "short_put": by_key.get((sp, "PE")),
        "long_put": by_key.get((lp, "PE")),
        "short_call": by_key.get((sc, "CE")),
        "long_call": by_key.get((lc, "CE")),
    }
    return legs


@dataclass(frozen=True)
class RealCombo:
    """value: combined combo price, NaN if unpriceable (unchanged semantics
    from before this existed). leg_prices: the 4 individual LTPs that value
    was computed from — None when value is NaN. Added 2026-07-14: these were
    always fetched internally but silently discarded, so no ENTER/HOLD/EXIT
    ledger event ever recorded per-leg prices, only the combined number
    (found building a daily PnL report that needed all 4 legs)."""
    value: float
    leg_prices: dict | None


def _real_combo_value(api, legs: dict) -> RealCombo:
    """Cost to close = what you'd pay to buy back the short IC, priced off
    real live LTPs. value=NaN if any leg is missing/unquotable (caller falls
    back to BS modeling)."""
    if any(leg is None for leg in legs.values()):
        return RealCombo(float("nan"), None)
    sp_ltp = _leg_ltp(api, legs["short_put"]["exchange"], legs["short_put"]["token"])
    lp_ltp = _leg_ltp(api, legs["long_put"]["exchange"], legs["long_put"]["token"])
    sc_ltp = _leg_ltp(api, legs["short_call"]["exchange"], legs["short_call"]["token"])
    lc_ltp = _leg_ltp(api, legs["long_call"]["exchange"], legs["long_call"]["token"])
    if any(np.isnan(v) for v in (sp_ltp, lp_ltp, sc_ltp, lc_ltp)):
        return RealCombo(float("nan"), None)
    value = (sp_ltp - lp_ltp) + (sc_ltp - lc_ltp)
    return RealCombo(value, {"short_put": sp_ltp, "long_put": lp_ltp,
                             "short_call": sc_ltp, "long_call": lc_ltp})


def _combo_value(S: float, sp: float, lp: float, sc: float, lc: float, T: float, sigma: float) -> float:
    if T <= 0:
        put_val = max(sp - S, 0) - max(lp - S, 0)
        call_val = max(S - sc, 0) - max(S - lc, 0)
        return put_val + call_val
    return (
        (black_scholes_put(S, sp, T, RISK_FREE_RATE, sigma) - black_scholes_put(S, lp, T, RISK_FREE_RATE, sigma))
        + (black_scholes_call(S, sc, T, RISK_FREE_RATE, sigma) - black_scholes_call(S, lc, T, RISK_FREE_RATE, sigma))
    )


def _mark_open_cycle(state: dict, cycle: dict, closes: pd.Series, today: date) -> dict:
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


def _try_enter(state: dict, closes: pd.Series, today: date, now: datetime) -> dict:
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

    expiry = resolve_monthly_expiry("NIFTY", now)
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
    """Call once per trading day. Marks an open cycle (PT/SL/expiry check), or
    if none is open, decides whether to enter a new one. Returns the ledger
    event that was written."""
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
