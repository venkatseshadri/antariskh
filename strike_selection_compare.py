"""Strike-selection comparison: 1SD (current PROTON/NEUTRON/SENSEX method,
RV-based) vs 0.20-delta vs 0.25-delta shorts — same Friday entry, same
PT_FRAC/SL_MULT/expiry mechanics, same wing sizing. Only the short-strike
selection formula changes, isolating that one variable.

NIFTY: Kaggle 11yr set, Tuesday expiry, STRIKE_GAP=50, WING=150, LOT=75.
SENSEX: Kaggle 6yr set, Thursday expiry (unverified history, see
sensex_weekly_ic_backtest.py caveat), STRIKE_GAP=100, WING~0.75% of spot, LOT=10.
"""
import math
from datetime import timedelta
from statistics import NormalDist

import numpy as np

from backtester import black_scholes_call, black_scholes_put
from monthly_ic_pilot import (
    _historical_daily_closes as nifty_closes, trailing_rv as n_rv,
    trailing_median_rv as n_median_rv, WING as N_WING, SL_MULT, PT_FRAC,
    STRIKE_GAP as N_GAP, LOT_SIZE as N_LOT, RISK_FREE_RATE,
)
from weekly_ic_backtest import next_tuesday_expiry
from sensex_weekly_ic_backtest import (
    load_sensex_daily_closes, trailing_rv as s_rv, trailing_median_rv as s_median_rv,
    next_expiry as sensex_next_expiry, STRIKE_GAP as S_GAP, LOT_SIZE as S_LOT, WING_PCT as S_WING_PCT,
)

_N = NormalDist()


def combo_value(S, sp, lp, sc, lc, T, sigma):
    if T <= 0:
        return (max(sp - S, 0) - max(lp - S, 0)) + (max(S - sc, 0) - max(S - lc, 0))
    return ((black_scholes_put(S, sp, T, RISK_FREE_RATE, sigma) - black_scholes_put(S, lp, T, RISK_FREE_RATE, sigma))
            + (black_scholes_call(S, sc, T, RISK_FREE_RATE, sigma) - black_scholes_call(S, lc, T, RISK_FREE_RATE, sigma)))


def delta_strike(S, T, sigma, target_delta, option_type, gap, r=RISK_FREE_RATE):
    if T <= 1e-6 or sigma <= 0:
        return round(S / gap) * gap
    d1 = _N.inv_cdf(target_delta if option_type == "call" else 1 - target_delta)
    k = S * math.exp((r + 0.5 * sigma ** 2) * T - d1 * sigma * math.sqrt(T))
    return round(k / gap) * gap


def strikes_1sd(S0, rv, T0, gap):
    move = rv * np.sqrt(T0)
    sp = round(S0 * (1 - move) / gap) * gap
    sc = round(S0 * (1 + move) / gap) * gap
    return sp, sc


def strikes_delta(S0, rv, T0, gap, target_delta):
    sp = delta_strike(S0, T0, rv, target_delta, "put", gap)
    sc = delta_strike(S0, T0, rv, target_delta, "call", gap)
    return sp, sc


def run_bucket(index: str, method: str, target_delta: float = None):
    if index == "NIFTY":
        closes = nifty_closes()
        rv_fn, med_fn, expiry_fn, gap, lot = n_rv, n_median_rv, next_tuesday_expiry, N_GAP, N_LOT
        wing_fn = lambda S0: N_WING
    else:
        closes = load_sensex_daily_closes()
        rv_fn, med_fn, expiry_fn, gap, lot = s_rv, s_median_rv, sensex_next_expiry, S_GAP, S_LOT
        wing_fn = lambda S0: round(S0 * S_WING_PCT / S_GAP) * S_GAP

    dates = list(closes.index)
    date_set = set(dates)
    trades = []
    cycle = None

    for d in dates:
        if cycle is not None:
            S = float(closes[d])
            T = max((cycle["expiry"] - d).days / 365, 0)
            val = combo_value(S, cycle["sp"], cycle["lp"], cycle["sc"], cycle["lc"], T, cycle["sigma"])
            credit = cycle["credit"]
            reason = None
            if val <= credit * (1 - PT_FRAC):
                reason = "PT"
            elif val >= credit * (1 + SL_MULT):
                reason = "SL"
            elif d >= cycle["expiry"]:
                reason = "EXPIRY"
            if reason:
                pnl = (credit - val) * lot
                trades.append({"entry": cycle["entry_date"], "exit": d, "reason": reason, "pnl": pnl})
                cycle = None
            continue

        if d.strftime("%a") != "Fri":
            continue
        rv, med = rv_fn(closes, d), med_fn(closes, d)
        if np.isnan(rv) or np.isnan(med) or rv <= med:
            continue
        expiry = expiry_fn(d, date_set)
        if expiry <= d and expiry != d:
            continue
        S0 = float(closes[d])
        T0 = max((expiry - d).days / 365, 1 / 365)

        if method == "1sd":
            sp, sc = strikes_1sd(S0, rv, T0, gap)
        else:
            sp, sc = strikes_delta(S0, rv, T0, gap, target_delta)
        wing = wing_fn(S0)
        lp, lc = sp - wing, sc + wing
        credit = combo_value(S0, sp, lp, sc, lc, T0, rv)
        if credit <= 0:
            continue
        cycle = {"entry_date": d, "expiry": expiry, "sp": sp, "lp": lp, "sc": sc, "lc": lc,
                 "sigma": rv, "credit": credit}

    return trades


def summarize(trades):
    if not trades:
        return {"n": 0, "win_rate": None, "total": 0, "avg": None, "worst": None}
    pnls = [t["pnl"] for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    mid = len(trades) // 2
    h1 = sum(t["pnl"] for t in trades[:mid])
    h2 = sum(t["pnl"] for t in trades[mid:])
    return {"n": len(trades), "win_rate": round(100 * wins / len(trades), 1),
            "total": round(sum(pnls), 2), "avg": round(sum(pnls) / len(pnls), 2),
            "worst": round(min(pnls), 2), "h1": round(h1, 0), "h2": round(h2, 0)}


def main():
    methods = [("1sd", None), ("delta", 0.20), ("delta", 0.25)]
    for index in ("NIFTY", "SENSEX"):
        print(f"\n=== {index} — Friday entry, strike method comparison ===")
        for method, td in methods:
            trades = run_bucket(index, method, td)
            s = summarize(trades)
            label = "1SD (current)" if method == "1sd" else f"{td:.2f}-delta"
            if s["n"] == 0:
                print(f"  {label:>15}: no trades")
                continue
            print(f"  {label:>15}: n={s['n']:>3} win%={s['win_rate']:>5} "
                  f"total=Rs{s['total']:>10,.0f} avg=Rs{s['avg']:>8,.2f} worst=Rs{s['worst']:>9,.2f} "
                  f"| H1=Rs{s['h1']:>9,.0f} H2=Rs{s['h2']:>9,.0f}")


if __name__ == "__main__":
    main()
