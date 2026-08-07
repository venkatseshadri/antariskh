"""Tests the literal proposed plan: forced alternation, SENSEX enters Tuesday
(right after NIFTY's own Tuesday expiry), NIFTY enters Thursday (right after
SENSEX's own Thursday expiry) — vs each running independently on its own
proven best day (Friday for both). Same RV-filter/PT/SL mechanics as the
standalone backtests, just forced entry-day instead of Friday-gated.

CAVEAT carried from sensex_weekly_ic_backtest.py: SENSEX expiry assumed
constant Thursday across the full period — unverified for this instrument
(unlike NIFTY's documented Thursday->Tuesday shift). Flagging, not fixing.
"""
import numpy as np
from datetime import timedelta

from backtester import black_scholes_call, black_scholes_put
from monthly_ic_pilot import (
    _historical_daily_closes as nifty_closes, trailing_rv as n_rv,
    trailing_median_rv as n_median_rv, WING as N_WING, SL_MULT, PT_FRAC,
    STRIKE_GAP as N_GAP, LOT_SIZE as N_LOT, RISK_FREE_RATE,
)
from sensex_weekly_ic_backtest import (
    load_sensex_daily_closes, trailing_rv as s_rv, trailing_median_rv as s_median_rv,
    STRIKE_GAP as S_GAP, LOT_SIZE as S_LOT, WING_PCT as S_WING_PCT,
)
from weekly_ic_backtest import next_tuesday_expiry as nifty_next_expiry
from sensex_weekly_ic_backtest import next_expiry as sensex_next_expiry


def combo_value(S, sp, lp, sc, lc, T, sigma):
    if T <= 0:
        return (max(sp - S, 0) - max(lp - S, 0)) + (max(S - sc, 0) - max(S - lc, 0))
    return ((black_scholes_put(S, sp, T, RISK_FREE_RATE, sigma) - black_scholes_put(S, lp, T, RISK_FREE_RATE, sigma))
            + (black_scholes_call(S, sc, T, RISK_FREE_RATE, sigma) - black_scholes_call(S, lc, T, RISK_FREE_RATE, sigma)))


def try_enter(index, d, closes, date_set):
    S0 = float(closes[d])
    rv, med = (n_rv(closes, d), n_median_rv(closes, d)) if index == "NIFTY" else (s_rv(closes, d), s_median_rv(closes, d))
    if np.isnan(rv) or np.isnan(med) or rv <= med:
        return None, "vol_filter_skip"
    if index == "NIFTY":
        expiry = nifty_next_expiry(d, date_set)
        gap, lot, wing = N_GAP, N_LOT, N_WING
    else:
        expiry = sensex_next_expiry(d, date_set)
        gap, lot, wing = S_GAP, S_LOT, round(S0 * S_WING_PCT / S_GAP) * S_GAP
    if expiry <= d and expiry != d:
        return None, "expiry_edge_skip"
    T0 = max((expiry - d).days / 365, 1 / 365)
    move = rv * np.sqrt(T0)
    sp = round(S0 * (1 - move) / gap) * gap
    sc = round(S0 * (1 + move) / gap) * gap
    lp, lc = sp - wing, sc + wing
    credit = combo_value(S0, sp, lp, sc, lc, T0, rv)
    return {"index": index, "entry_date": d, "expiry": expiry, "sp": sp, "lp": lp,
            "sc": sc, "lc": lc, "sigma": rv, "credit": credit, "lot": lot}, None


def run_alternation(start, end):
    nc, sc_ = nifty_closes(), load_sensex_daily_closes()
    common = sorted(set(nc.index) & set(sc_.index))
    common = [d for d in common if start <= d <= end]
    n_dates, s_dates = set(nc.index), set(sc_.index)

    trades, gap_days, cycle = [], 0, None
    next_expected = None  # ("NIFTY","Thu") or ("SENSEX","Tue") — whichever is due

    for d in common:
        wd = d.strftime("%a")
        if cycle is not None:
            closes = nc if cycle["index"] == "NIFTY" else sc_
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
                pnl = (credit - val) * cycle["lot"]
                trades.append({"index": cycle["index"], "entry": cycle["entry_date"], "exit": d,
                                "reason": reason, "pnl": pnl})
                cycle = None
            else:
                continue

        # flat: is today a scheduled entry day for either leg?
        if wd == "Tue" and d in s_dates:
            pos, skip_reason = try_enter("SENSEX", d, sc_, s_dates)
        elif wd == "Thu" and d in n_dates:
            pos, skip_reason = try_enter("NIFTY", d, nc, n_dates)
        else:
            pos, skip_reason = None, None

        if pos is not None:
            cycle = pos
        elif wd in ("Tue", "Thu"):
            gap_days += 1

    return trades, gap_days


def main():
    start, end = __import__("datetime").date(2018, 3, 8), __import__("datetime").date(2024, 3, 22)
    trades, gap_days = run_alternation(start, end)
    for idx in ("NIFTY", "SENSEX"):
        sub = [t for t in trades if t["index"] == idx]
        if not sub:
            print(f"{idx}: no trades")
            continue
        wins = sum(1 for t in sub if t["pnl"] > 0)
        total = sum(t["pnl"] for t in sub)
        print(f"{idx}: n={len(sub)} win%={100*wins/len(sub):.1f} total=Rs{total:.0f} avg=Rs{total/len(sub):.2f}")
    combined = sum(t["pnl"] for t in trades)
    print(f"\nCombined raw PnL (both legs, forced Tue/Thu alternation): Rs{combined:.0f}")
    print(f"Missed scheduled entries (vol filter or expiry-edge skip): {gap_days}")


if __name__ == "__main__":
    main()
