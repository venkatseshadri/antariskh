"""Honest-costed version of strike_selection_compare.py's winning candidates:
NIFTY 1SD vs 0.25-delta, SENSEX 1SD vs 0.20-delta. Same cost model as
weekly_ic_backtest_costed.py / sensex_weekly_ic_backtest_costed.py."""
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
from strike_selection_compare import strikes_1sd, strikes_delta

BROKERAGE_PER_ORDER, SLIPPAGE_TICKS, TICK, SLIPPAGE_PCT, STAT_CHARGES_PCT = 20.0, 1, 0.05, 0.0025, 0.0007


def leg_prices(S, sp, lp, sc, lc, T, sigma):
    return {"short_put": black_scholes_put(S, sp, T, RISK_FREE_RATE, sigma),
            "long_put": black_scholes_put(S, lp, T, RISK_FREE_RATE, sigma),
            "short_call": black_scholes_call(S, sc, T, RISK_FREE_RATE, sigma),
            "long_call": black_scholes_call(S, lc, T, RISK_FREE_RATE, sigma)}


def fill(px, is_sell):
    slip = SLIPPAGE_TICKS * TICK + px * SLIPPAGE_PCT
    return max(0.0, px - slip) if is_sell else px + slip


def unwind_fill(px, is_sell):
    slip = SLIPPAGE_TICKS * TICK + px * SLIPPAGE_PCT
    return px + slip if is_sell else max(0.0, px - slip)


def run_costed(index, method, target_delta, lot):
    if index == "NIFTY":
        closes = nifty_closes()
        rv_fn, med_fn, expiry_fn, gap = n_rv, n_median_rv, next_tuesday_expiry, N_GAP
        wing_fn = lambda S0: N_WING
    else:
        closes = load_sensex_daily_closes()
        rv_fn, med_fn, expiry_fn, gap = s_rv, s_median_rv, sensex_next_expiry, S_GAP
        wing_fn = lambda S0: round(S0 * S_WING_PCT / S_GAP) * S_GAP

    dates = list(closes.index)
    date_set = set(dates)
    trades, cycle = [], None

    for d in dates:
        if cycle is not None:
            S = float(closes[d])
            T = max((cycle["expiry"] - d).days / 365, 0)
            legs_now = leg_prices(S, cycle["sp"], cycle["lp"], cycle["sc"], cycle["lc"], T, cycle["sigma"])
            val = (legs_now["short_put"] - legs_now["long_put"]) + (legs_now["short_call"] - legs_now["long_call"])
            credit = cycle["credit"]
            reason = None
            if val <= credit * (1 - PT_FRAC):
                reason = "PT"
            elif val >= credit * (1 + SL_MULT):
                reason = "SL"
            elif d >= cycle["expiry"]:
                reason = "EXPIRY"
            if reason:
                exit_fills = {"short_put": unwind_fill(legs_now["short_put"], True), "long_put": unwind_fill(legs_now["long_put"], False),
                              "short_call": unwind_fill(legs_now["short_call"], True), "long_call": unwind_fill(legs_now["long_call"], False)}
                raw = (credit - val) * lot
                turnover = sum(cycle["entry_fills"].values()) + sum(exit_fills.values())
                slip = sum(abs(cycle["entry_fills"][k] - cycle["entry_raw"][k]) for k in cycle["entry_fills"]) * lot
                slip += sum(abs(exit_fills[k] - legs_now[k]) for k in exit_fills) * lot
                costed = raw - 8 * BROKERAGE_PER_ORDER - turnover * lot * STAT_CHARGES_PCT - slip
                trades.append({"raw": raw, "costed": costed})
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
        sp, sc = (strikes_1sd(S0, rv, T0, gap) if method == "1sd" else strikes_delta(S0, rv, T0, gap, target_delta))
        wing = wing_fn(S0)
        lp, lc = sp - wing, sc + wing
        legs0 = leg_prices(S0, sp, lp, sc, lc, T0, rv)
        credit = (legs0["short_put"] - legs0["long_put"]) + (legs0["short_call"] - legs0["long_call"])
        if credit <= 1.0:
            continue
        entry_fills = {"short_put": fill(legs0["short_put"], True), "long_put": fill(legs0["long_put"], False),
                       "short_call": fill(legs0["short_call"], True), "long_call": fill(legs0["long_call"], False)}
        cycle = {"entry_date": d, "expiry": expiry, "sp": sp, "lp": lp, "sc": sc, "lc": lc,
                 "sigma": rv, "credit": credit, "entry_raw": legs0, "entry_fills": entry_fills}
    return trades


def summarize(trades, key):
    if not trades:
        return {"n": 0}
    pnls = [t[key] for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    return {"n": len(trades), "win_rate": round(100 * wins / len(trades), 1),
            "total": round(sum(pnls), 2), "avg": round(sum(pnls) / len(pnls), 2)}


def main():
    for index, method, td, lot in [("NIFTY", "1sd", None, N_LOT), ("NIFTY", "delta", 0.25, N_LOT),
                                     ("SENSEX", "1sd", None, S_LOT), ("SENSEX", "delta", 0.20, S_LOT)]:
        trades = run_costed(index, method, td, lot)
        raw = summarize(trades, "raw")
        costed = summarize(trades, "costed")
        label = "1SD" if method == "1sd" else f"{td}-delta"
        print(f"{index:>7} {label:>10}: RAW avg=Rs{raw['avg']:>9,.2f} total=Rs{raw['total']:>10,.0f} | "
              f"COSTED win%={costed['win_rate']:>5} avg=Rs{costed['avg']:>9,.2f} total=Rs{costed['total']:>10,.0f}")


if __name__ == "__main__":
    main()
