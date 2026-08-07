"""PROTON — weekly NIFTY iron-condor backtest, entry-day-of-week experiment.

Same locked strategy as NEUTRON (monthly_ic_pilot.py), just weekly expiry
instead of monthly:
  - Enter only if trailing 20d realized vol > its own trailing ~6mo median
  - Short strikes at 1SD (entry-day trailing RV, sqrt(T)-scaled) off spot
  - 150pt wing, close at 60% credit captured, stop at 1.0x credit lost
  - Priced via Black-Scholes (no historical option chain, same as NEUTRON's
    backtest — RV stands in for IV)

Tests every entry weekday (Wed/Thu/Fri/Mon/Tue) independently against next
Tuesday's expiry, to find which entry day works best — per user request,
"run expiry to expiry so we know which day is better."

ASSUMPTION: treats NIFTY weekly expiry as Tuesday for the full 2015-2026
range. Actual expiry weekday changed historically (Thursday for most of
that span, moved to Tuesday only recently) — this backtest does NOT model
that shift, same simplification NEUTRON's own backtest made for monthly
(assumed last-Tuesday-of-month throughout). Flagging, not silently deciding.
"""

import numpy as np
import pandas as pd
from datetime import timedelta

from monthly_ic_pilot import (
    _historical_daily_closes, trailing_rv, trailing_median_rv, _combo_value,
    WING, SL_MULT, PT_FRAC, RISK_FREE_RATE, STRIKE_GAP, LOT_SIZE,
)

ENTRY_WEEKDAYS = ["Wed", "Thu", "Fri", "Mon", "Tue"]  # order within a weekly cycle


def next_tuesday_expiry(entry_date, date_set):
    d = entry_date
    while d.weekday() != 1:  # Tuesday = 1
        d += timedelta(days=1)
    while d not in date_set and d > entry_date:
        d -= timedelta(days=1)  # holiday: expiry shifts to prior trading day
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

        expiry = next_tuesday_expiry(d, date_set)
        if expiry <= d and expiry != d:
            continue  # holiday edge case, skip
        S0 = float(closes[d])
        T0 = max((expiry - d).days / 365, 1 / 365)
        move = entry_rv * np.sqrt(T0)
        sp = round(S0 * (1 - move) / STRIKE_GAP) * STRIKE_GAP
        sc = round(S0 * (1 + move) / STRIKE_GAP) * STRIKE_GAP
        lp = sp - WING
        lc = sc + WING
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
    closes = _historical_daily_closes()
    print(f"Daily closes: {len(closes)} days, {closes.index.min()} to {closes.index.max()}\n")
    all_results = {}
    for wd in ENTRY_WEEKDAYS:
        trades = run_bucket(closes, wd)
        stats = summarize(trades)
        all_results[wd] = {"stats": stats, "trades": trades}
        print(f"{wd:>4}: n={stats['n']:>3}  win%={stats['win_rate']}  "
              f"total/lot=Rs{stats['total_pnl_per_lot']}  "
              f"avg/lot=Rs{stats['avg_pnl_per_lot']}  worst=Rs{stats['worst']}")
    return all_results


if __name__ == "__main__":
    main()
