"""SENSEX weekly IC — entry-day-of-week experiment, mirrors weekly_ic_backtest.py's
NIFTY methodology exactly (same RV-filter, same 1SD-off-spot strike selection,
same PT_FRAC=0.6/SL_MULT=1.0), applied to real SENSEX minute data instead of
assuming the old iron-fly calendar's "Wed/Thu" carries over untested.

Data: Kaggle sandeepkapri/sensex-minute-data-08-mar-2018-to-22-mar-2024 (real,
~6yr, 554,949 1-min bars) — NOT the same source as NIFTY's Kaggle set, but same
resolution/quality class.

Deltas from the NIFTY version (SENSEX contract specs differ, per
config/token_resolver.py and tools/ta_tools.py):
  - STRIKE_GAP=100 (NIFTY=50), LOT_SIZE=10 (NIFTY=75)
  - Weekly expiry = Thursday (SENSEX_WEEKDAY=3), not Tuesday
  - WING scaled proportionally to spot (~0.75%, same ratio as NIFTY's 150pt
    wing at NIFTY's typical level) instead of reusing the raw 150-point
    number — SENSEX trades 33k-80k over this period vs NIFTY's 10k-24k, so a
    fixed 150pt wing would be a much tighter (miscalibrated) band on SENSEX.
"""

import numpy as np
import pandas as pd
from datetime import timedelta
from pathlib import Path

from backtester import black_scholes_call, black_scholes_put

CSV_PATH = Path(
    "/root/.cache/kagglehub/datasets/sandeepkapri/sensex-minute-data-08-mar-2018-to-22-mar-2024"
    "/versions/4/sensex_candlestick_data.csv"
)

STRIKE_GAP = 100
LOT_SIZE = 10
WING_PCT = 0.0075   # same ratio as NIFTY's locked 150pt/~20000 wing
SL_MULT = 1.0
PT_FRAC = 0.6
RISK_FREE_RATE = 0.06
RV_WINDOW = 20
RV_MEDIAN_LOOKBACK = 126
EXPIRY_WEEKDAY = 3  # Thursday (SENSEX_WEEKDAY, token_resolver.py:29)

ENTRY_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]


def load_sensex_daily_closes() -> pd.Series:
    df = pd.read_csv(CSV_PATH, usecols=["Date", "Time", "Close"])
    df["ts"] = pd.to_datetime(df["Date"] + " " + df["Time"], format="%d-%m-%Y %H:%M:%S")
    df = df.set_index("ts").sort_index()
    df["day"] = df.index.date
    return df.groupby("day")["Close"].last()


def _log_returns(closes: pd.Series, asof) -> pd.Series:
    s = closes[closes.index <= asof]
    return np.log(s / s.shift(1)).dropna()


def trailing_rv(closes: pd.Series, asof, window: int = RV_WINDOW) -> float:
    logret = _log_returns(closes, asof)
    if len(logret) < window:
        return float("nan")
    return float(logret.tail(window).std() * np.sqrt(252))


def trailing_median_rv(closes: pd.Series, asof) -> float:
    logret = _log_returns(closes, asof)
    rv = logret.rolling(RV_WINDOW).std() * np.sqrt(252)
    rv = rv.tail(RV_MEDIAN_LOOKBACK).dropna()
    if rv.empty:
        return float("nan")
    return float(rv.median())


def _combo_value(S, sp, lp, sc, lc, T, sigma):
    if T <= 0:
        put_val = max(sp - S, 0) - max(lp - S, 0)
        call_val = max(S - sc, 0) - max(S - lc, 0)
        return put_val + call_val
    return (
        (black_scholes_put(S, sp, T, RISK_FREE_RATE, sigma) - black_scholes_put(S, lp, T, RISK_FREE_RATE, sigma))
        + (black_scholes_call(S, sc, T, RISK_FREE_RATE, sigma) - black_scholes_call(S, lc, T, RISK_FREE_RATE, sigma))
    )


def next_expiry(entry_date, date_set):
    d = entry_date
    while d.weekday() != EXPIRY_WEEKDAY:
        d += timedelta(days=1)
    while d not in date_set and d > entry_date:
        d -= timedelta(days=1)
    return d


def run_bucket(closes: pd.Series, weekday: str) -> list[dict]:
    dates = list(closes.index)
    date_set = set(dates)
    trades = []
    cycle = None

    for d in dates:
        if cycle is not None:
            S = float(closes[d])
            expiry = cycle["expiry"]
            T = max((expiry - d).days / 365, 0)
            val = _combo_value(S, cycle["sp"], cycle["lp"], cycle["sc"], cycle["lc"], T, cycle["sigma"])
            credit = cycle["credit"]
            pt_level = credit * (1 - PT_FRAC)
            sl_level = credit * (1 + SL_MULT)
            reason = None
            if val <= pt_level:
                reason = "PT"
            elif val >= sl_level:
                reason = "SL"
            elif d >= expiry:
                reason = "EXPIRY"
            if reason:
                pnl_per_lot = (credit - val) * LOT_SIZE
                trades.append({"entry_date": cycle["entry_date"], "expiry": expiry,
                                "exit_date": d, "reason": reason, "pnl_per_lot": pnl_per_lot})
                cycle = None
            continue

        if d.strftime("%a") != weekday:
            continue

        entry_rv = trailing_rv(closes, d)
        median_rv = trailing_median_rv(closes, d)
        if np.isnan(entry_rv) or np.isnan(median_rv) or entry_rv <= median_rv:
            continue

        expiry = next_expiry(d, date_set)
        if expiry <= d and expiry != d:
            continue
        S0 = float(closes[d])
        T0 = max((expiry - d).days / 365, 1 / 365)
        move = entry_rv * np.sqrt(T0)
        wing = round(S0 * WING_PCT / STRIKE_GAP) * STRIKE_GAP
        sp = round(S0 * (1 - move) / STRIKE_GAP) * STRIKE_GAP
        sc = round(S0 * (1 + move) / STRIKE_GAP) * STRIKE_GAP
        lp = sp - wing
        lc = sc + wing
        credit = _combo_value(S0, sp, lp, sc, lc, T0, entry_rv)
        cycle = {"entry_date": d, "expiry": expiry, "sp": sp, "lp": lp,
                 "sc": sc, "lc": lc, "sigma": entry_rv, "credit": credit}

    return trades


def summarize(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0, "win_rate": None, "total_pnl_per_lot": 0.0,
                "avg_pnl_per_lot": None, "worst": None}
    pnls = [t["pnl_per_lot"] for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    return {
        "n": len(trades),
        "win_rate": round(100 * wins / len(trades), 1),
        "total_pnl_per_lot": round(sum(pnls), 2),
        "avg_pnl_per_lot": round(sum(pnls) / len(pnls), 2),
        "worst": round(min(pnls), 2),
    }


def main():
    closes = load_sensex_daily_closes()
    print(f"SENSEX daily closes: {len(closes)} days, {closes.index.min()} to {closes.index.max()}\n")
    mid = len(closes) // 2
    h1_end, h2_start = closes.index[mid], closes.index[mid]

    for wd in ENTRY_WEEKDAYS:
        trades = run_bucket(closes, wd)
        stats = summarize(trades)
        h1 = [t for t in trades if t["entry_date"] <= h1_end]
        h2 = [t for t in trades if t["entry_date"] > h1_end]
        h1_pnl = sum(t["pnl_per_lot"] for t in h1)
        h2_pnl = sum(t["pnl_per_lot"] for t in h2)
        print(f"{wd:>4}: n={stats['n']:>3}  win%={stats['win_rate']}  "
              f"total/lot=Rs{stats['total_pnl_per_lot']}  avg/lot=Rs{stats['avg_pnl_per_lot']}  "
              f"worst=Rs{stats['worst']}  | H1=Rs{h1_pnl:.0f} H2=Rs{h2_pnl:.0f}")


if __name__ == "__main__":
    main()
