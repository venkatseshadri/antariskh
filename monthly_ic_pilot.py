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
LOT_SIZE = 65  # NIFTY, per broker scrip master (corrected 2026-07-29 — was 75,
# stale after NSE's lot-size revision; caused a real order rejection today,
# "Quantity 75 is not a multiple of lot size 65.00")

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


def _shoonya_session():
    """Same cred file/token ATOM, Penguin, and proton_live.py already use
    (atom.broker_session.load_live_api — proven order placement, ATOM's
    2026-07-13 live canary test). Wraps its raise-on-failure contract into
    the None-on-failure contract this module expects (2026-07-27, added so
    NEUTRON+/HYDROGEN+ can optionally run on Shoonya instead of Flattrade —
    accepts the shared-account risk with ATOM/PROTON+ that Flattrade
    isolation was originally built to avoid; mitigated the same way PROTON+
    does, via check_account_margin() before every entry)."""
    try:
        atom_src = "/home/trading_ceo/atom/src"
        if atom_src not in sys.path:
            sys.path.insert(0, atom_src)
        from atom.broker_session import load_live_api
        return load_live_api()
    except Exception:
        return None


def get_broker_session(broker: str):
    """Dispatches to _flattrade_session() or _shoonya_session() by name.
    Unrecognized broker string fails closed (returns None) rather than
    silently defaulting to either broker."""
    broker = (broker or "").upper()
    if broker == "FLATTRADE":
        return _flattrade_session()
    if broker == "SHOONYA":
        return _shoonya_session()
    return None


MARGIN_FLOOR_INR = 50_000.0  # same floor ATOM/PROTON's check_account_margin() uses


def check_account_margin(api, broker: str = "FLATTRADE") -> tuple[bool, float | None, float | None]:
    """Real broker-reported free margin, account-level. Field names differ by
    broker's get_limits() schema — both Flattrade and Shoonya return
    cash+collateral (verified 2026-07-29 against a real live Shoonya
    response: the response has no "collat"/"col"/"marginavailable" keys at
    all — an earlier version of this function copied proton_live.py's
    field-name guess for those without checking, which silently zeroed out
    collateral and compared cash-only against the floor, producing a false
    "insufficient margin" on a real entry attempt with ~Rs573k actually
    available). Fails closed: any error/missing field/no session refuses
    entry rather than assuming margin is fine.

    Returns (margin_ok, avail=cash+collateral, cash=cash alone). `cash` is
    ShoonyaApi-py's officially documented "Cash Margin available" field
    (github.com/Shoonya-Dev/ShoonyaApi-py README) — added 2026-08-02 so
    callers can gate option-BUY legs on cash alone. Real Shoonya rejection
    hit live 2026-07-29: `RED:RULE:{Allow CAC credit but disallow collateral
    and daylong cash for option buy}` — buying an option (a hedge leg)
    requires actual cash, not collateral, but this function's own `avail`
    treats them as one fungible pool. get_limits() also returns undocumented
    cash_coll/mf_cash_coll/mf_coll fields that likely segment collateral's
    SEBI-mandated cash-equivalent portion more precisely, but no official
    field-level docs exist for them (checked ShoonyaApi-py README + FAQ,
    2026-08-02) — not used here, `cash` alone is the conservative, sourced
    choice; a caller requiring `cash` to cover an option-buy leg can only
    ever be more restrictive than reality, never less, unlike guessing at
    the undocumented fields' semantics."""
    if api is None:
        return False, None, None
    try:
        limits = api.get_limits()
        if not isinstance(limits, dict) or limits.get("stat") != "Ok":
            return False, None, None
        if (broker or "").upper() == "SHOONYA":
            cash = float(limits.get("cash", 0) or 0)
            collateral = float(limits.get("collateral", 0) or 0)
            avail = cash + collateral
        else:  # FLATTRADE
            cash = float(limits.get("cash", 0) or 0)
            collateral = float(limits.get("collateral", 0) or 0)
            avail = cash + collateral
        return avail >= MARGIN_FLOOR_INR, avail, cash
    except Exception:
        return False, None, None


# ── Real-order primitives (2026-07-27) — shared by NEUTRON+/HYDROGEN+'s
# LIVE_ENABLED path, same NorenRestApiPy method signatures proton_live.py
# already proved against Shoonya (same vendor API family, Flattrade's
# NorenApi.place_order/cancel_order/get_positions take identical args).
# This module's own run_daily()/base NEUTRON paper simulation above is
# untouched and stays paper-only forever — these are broker-mechanical
# building blocks the orbiter files' real-order path calls into, not a
# change to this file's own behavior.

BUY, SELL = "B", "S"
LIMIT = "LMT"
SL_LIMIT = "SL-LMT"
NRML = "M"
MARKETABLE_BUFFER_PCT = 0.02
SL_TRIGGER_BUFFER_PCT = 0.01
MAX_LOTS = 1  # same hard cap proton_live.py uses


@dataclass(frozen=True)
class LiveOrderResult:
    ok: bool
    norenordno: str | None
    raw: dict


def _ok(resp) -> bool:
    return isinstance(resp, dict) and resp.get("stat") == "Ok"


def _norenordno(resp):
    return resp.get("norenordno") if isinstance(resp, dict) else None


def marketable_limit(action: str, ltp: float) -> float:
    mult = 1 + MARKETABLE_BUFFER_PCT if action == BUY else 1 - MARKETABLE_BUFFER_PCT
    return round(ltp * mult, 1)


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


def cancel_resting_sl(api, sl_order_ids: dict) -> dict:
    canceled = {}
    for leg_name, ordno in (sl_order_ids or {}).items():
        if not ordno:
            continue
        r = cancel_order(api, ordno)
        canceled[leg_name] = {"ok": r.ok, "raw": r.raw}
    return canceled


def broker_position_qty(api, tsym: str) -> int | None:
    try:
        positions = api.get_positions() or []
        by_tsym = {p["tsym"]: int(float(p["netqty"])) for p in positions}
        return by_tsym.get(tsym, 0)
    except Exception:
        return None


def broker_confirms_flat(api, tsyms: list[str]) -> bool:
    """Checks the SPECIFIC contracts about to be traded are flat at the broker
    before entering — catches a stray/leftover position in that exact strike,
    not just 'whatever our own state remembers' (our own state is None by the
    time this runs, so there is nothing else to compare against)."""
    for tsym in tsyms:
        qty = broker_position_qty(api, tsym)
        if qty is None or qty != 0:
            return False
    return True


def resting_sl_fired_unreconciled(api, short_tsym: str) -> bool:
    """Broker-agnostic (REST get_positions) reconciliation check — did the
    resting SL-LMT order on this short leg already fire at the broker since
    our last tick, without us knowing? Between 15-min polls the broker-side
    stop can trigger on its own; without this check the software poll would
    keep computing PT/SL/TSL off a leg that's already closed, and could try
    to close it a second time. Same pattern as proton_live.py's _check_exit
    reconciliation, generalized here since this module's callers manage
    legs per-side rather than per-position. Fails safe: an unreadable broker
    response returns False (don't halt on an API hiccup — a stuck real
    problem will still be caught on the very next tick)."""
    qty = broker_position_qty(api, short_tsym)
    return qty is not None and qty == 0


def shoonya_order_status(norenordno: str) -> dict | None:
    """Reads the latest status for a Shoonya order number from feed.py's own
    order_updates SQLite table (Shoonya-account-scoped — feed.py's WS already
    has order_update_callback wired for ATOM/PROTON+'s account, and Shoonya's
    order-update channel reports ALL activity on the logged-in account, not
    just orders placed via the session object that opened the WS). Read-only,
    never opens a second Shoonya WS — Shoonya allows exactly one WS per
    account (enforced elsewhere, atom/tests/test_broker_ws.py), so a
    NEUTRON+/HYDROGEN+ process running on NEUTRON_BROKER=SHOONYA must NEVER
    call start_websocket() itself; this is how it gets fill/reject visibility
    instead, for free, riding on Penguin's already-running connection.
    Only meaningful when BROKER=SHOONYA — Flattrade orders never appear here
    (separate broker, no shared infrastructure). Returns None on any read
    failure or missing order (e.g. feed.py's WS was down, or BROKER=FLATTRADE)."""
    try:
        path = get_sqlite_capture_path("ORDERS")
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            row = con.execute(
                "SELECT status, reporttype, prc, qty, received_at FROM order_updates "
                "WHERE norenordno=? ORDER BY received_at DESC LIMIT 1",
                (norenordno,),
            ).fetchone()
        finally:
            con.close()
        if row is None:
            return None
        return {"status": row[0], "reporttype": row[1], "price": row[2], "qty": row[3], "received_at": row[4]}
    except Exception:
        return None


FILL_FAILURE_STATUSES = {"REJECTED", "CANCELED", "CANCELLED"}


def fill_rejected(fill_confirmation: dict | None) -> bool:
    """True only when Shoonya's order-update feed explicitly confirms this
    order was rejected/canceled. The REST accept (stat=Ok) only means
    "queued for processing," not filled — found live 2026-07-29: a MORPH_ADD
    call spread had both legs accepted then rejected by a cash-vs-collateral
    broker rule, but stage was recorded "complete" anyway because only the
    REST accept was checked, never the actual fill status. None
    (Flattrade, or a Shoonya read that couldn't confirm either way) is NOT
    treated as a rejection — falls back to trusting the REST accept, same
    as before this existed."""
    return bool(fill_confirmation) and fill_confirmation.get("status") in FILL_FAILURE_STATUSES


def confirm_shoonya_fill(norenordno: str | None, broker: str) -> dict | None:
    """Single read of feed.py's shared order_updates table for this order's
    latest known status — real fill confirmation via the SAME WS every
    Shoonya-routed system (ATOM, PROTON+, and now NEUTRON+/HYDROGEN+ if
    NEUTRON_BROKER=SHOONYA) already streams into, rather than just trusting
    place_order()'s immediate REST accept response (which only means
    'queued', not 'filled'). No-op for Flattrade (broker != SHOONYA) or a
    missing norenordno. One check, not a poll loop (2026-08-05 — was a
    5x1s sleep-poll; the WS write is near-instant once the exchange
    actually processes the order, and repeated local DB reads add nothing
    a single read doesn't already give). Enrichment/corroboration, not the
    hard gate — _verify_real_entry's get_positions() check is what actually
    blocks a phantom fill from being recorded as real; this can still be
    genuinely absent for a real order that's still in flight, same as
    before."""
    if broker.upper() != "SHOONYA" or not norenordno:
        return None
    return shoonya_order_status(norenordno)


def nucleus_ceiling(tier: str) -> tuple[float | None, str | None]:
    """Capital ceiling from NUCLEUS (antariksh/nucleus.py), dynamically swept
    across all 4 tiers off real broker margin. Fail-closed: any read/parse/
    staleness failure returns (None, reason) — caller must refuse entry rather
    than assume unlimited capital. Same contract as proton_live.py's
    _nucleus_ceiling(), generalized to take any tier key (T3_HYDROGEN,
    T4_NEUTRON)."""
    alloc_file = Path(__file__).resolve().parent / "data" / "nucleus_allocation.json"
    try:
        raw = json.loads(alloc_file.read_text())
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
    if age_min > 1080:  # 18h — covers overnight gap, matches proton_live.py
        return None, "STALE"
    return ceiling, None


def fo_market_is_open(now: datetime | None = None) -> bool:
    """NSE F&O has NO pre-open session (unlike equity's 09:00-09:08 window) —
    trading genuinely starts at 09:15, not 09:00. NEUTRON+ NIFTY's cron fires
    its first tick at 09:00 (0,15,30,45 9-15 * * 1-5) — found live 2026-08-04:
    a real entry attempt at 09:00:24-34 got a REST "stat: Ok" + a real-looking
    order number back from Shoonya for all 3 legs, but broker order history
    later showed "Error Occurred : 5 \"no data\"" for every one of them — the
    exchange never actually registered any of them, yet the code recorded
    stage="complete" and saved state as if a real position existed (state
    fill_confirmation was null but fill_rejected(None) trusts the REST accept
    by design — reasonable for WS lag, wrong for a pre-open silent drop).
    State desync self-halted the tier for ~23h until manually reconciled.
    Real fix is the fill-confirmation gate below; this is the cheaper
    root-trigger fix — refuse real order placement before the exchange is
    actually open, so this exact submission window can't recur. 2026-08-05."""
    now = now or datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.hour * 100 + now.minute
    return 915 <= t <= 1530


def _leg_ltp(api, exchange: str, token: str) -> float:
    """Real LTP for one leg, or NaN if the quote call fails or returns a
    mismatched instrument. Found live 2026-07-29: under concurrent load
    (ATOM+/PROTON+/NEUTRON+ all polling the same Shoonya account
    simultaneously), get_quotes() twice returned a price suspiciously close
    to the underlying spot instead of the requested option's real premium —
    caused a false PT/IV_CRUSH trigger and a bad exit-order price. The
    response always echoes back its own token/exch (verified live), so
    cross-checking those against what was actually requested before
    trusting "lp" closes this class of bug regardless of the exact
    broker-side mechanism."""
    try:
        q = api.get_quotes(exchange, token)
        if (
            q
            and q.get("stat") == "Ok"
            and str(q.get("token")) == str(token)
            and str(q.get("exch")) == str(exchange)
        ):
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
