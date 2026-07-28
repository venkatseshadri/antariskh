"""Test ATR(RV-ratio)-adaptive SL for HYDROGEN's delta-strike weekly IC —
same idea as the SHERPA ATR-SL test this session (scale SL threshold by
current-vol/trailing-median-vol), applied to the combo-value SL instead of
a single-leg premium SL. Baseline = flat SL_MULT=1.0 (current design)."""
import numpy as np

from backtester import black_scholes_call, black_scholes_put
from monthly_ic_pilot import (
    _historical_daily_closes as nifty_closes, trailing_rv as n_rv,
    trailing_median_rv as n_median_rv, WING as N_WING, PT_FRAC,
    STRIKE_GAP as N_GAP, LOT_SIZE as N_LOT, RISK_FREE_RATE,
)
from weekly_ic_backtest import next_tuesday_expiry
from sensex_weekly_ic_backtest import (
    load_sensex_daily_closes, trailing_rv as s_rv, trailing_median_rv as s_median_rv,
    next_expiry as sensex_next_expiry, STRIKE_GAP as S_GAP, LOT_SIZE as S_LOT, WING_PCT as S_WING_PCT,
)
from strike_selection_compare import strikes_delta

BROKERAGE_PER_ORDER, SLIPPAGE_TICKS, TICK, SLIPPAGE_PCT, STAT_CHARGES_PCT = 20.0, 1, 0.05, 0.0025, 0.0007
BASE_SL_MULT = 1.0


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


def run(index, target_delta, sl_multiplier=None):
    if index == "NIFTY":
        closes = nifty_closes(); rv_fn, med_fn, expiry_fn, gap, lot = n_rv, n_median_rv, next_tuesday_expiry, N_GAP, N_LOT
        wing_fn = lambda S0: N_WING
    else:
        closes = load_sensex_daily_closes(); rv_fn, med_fn, expiry_fn, gap, lot = s_rv, s_median_rv, sensex_next_expiry, S_GAP, S_LOT
        wing_fn = lambda S0: round(S0 * S_WING_PCT / S_GAP) * S_GAP

    dates = list(closes.index); date_set = set(dates); trades, cycle = [], None
    for d in dates:
        if cycle is not None:
            S = float(closes[d]); T = max((cycle["expiry"] - d).days / 365, 0)
            legs_now = leg_prices(S, cycle["sp"], cycle["lp"], cycle["sc"], cycle["lc"], T, cycle["sigma"])
            val = (legs_now["short_put"] - legs_now["long_put"]) + (legs_now["short_call"] - legs_now["long_call"])
            credit = cycle["credit"]; sl_mult = cycle["sl_mult"]
            reason = None
            if val <= credit * (1 - PT_FRAC): reason = "PT"
            elif val >= credit * (1 + sl_mult): reason = "SL"
            elif d >= cycle["expiry"]: reason = "EXPIRY"
            if reason:
                exit_fills = {k: unwind_fill(v, k.startswith("short")) for k, v in legs_now.items()}
                raw = (credit - val) * lot
                turnover = sum(cycle["entry_fills"].values()) + sum(exit_fills.values())
                slip = sum(abs(cycle["entry_fills"][k] - cycle["entry_raw"][k]) for k in cycle["entry_fills"]) * lot
                slip += sum(abs(exit_fills[k] - legs_now[k]) for k in exit_fills) * lot
                costed = raw - 8 * BROKERAGE_PER_ORDER - turnover * lot * STAT_CHARGES_PCT - slip
                trades.append({"raw": raw, "costed": costed, "reason": reason})
                cycle = None
            continue
        if d.strftime("%a") != "Fri": continue
        rv, med = rv_fn(closes, d), med_fn(closes, d)
        if np.isnan(rv) or np.isnan(med) or rv <= med: continue
        expiry = expiry_fn(d, date_set)
        if expiry <= d and expiry != d: continue
        S0 = float(closes[d]); T0 = max((expiry - d).days / 365, 1 / 365)
        sp, sc = strikes_delta(S0, rv, T0, gap, target_delta)
        wing = wing_fn(S0); lp, lc = sp - wing, sc + wing
        legs0 = leg_prices(S0, sp, lp, sc, lc, T0, rv)
        credit = (legs0["short_put"] - legs0["long_put"]) + (legs0["short_call"] - legs0["long_call"])
        if credit <= 1.0: continue
        entry_fills = {k: fill(v, k.startswith("short")) for k, v in legs0.items()}
        sl_mult = BASE_SL_MULT
        if sl_multiplier is not None:
            ratio = min(max(rv / med, 0.5), 2.0)
            sl_mult = BASE_SL_MULT * ratio * sl_multiplier
        cycle = {"entry_date": d, "expiry": expiry, "sp": sp, "lp": lp, "sc": sc, "lc": lc,
                 "sigma": rv, "credit": credit, "entry_raw": legs0, "entry_fills": entry_fills, "sl_mult": sl_mult}
    return trades


def summarize(trades, key):
    if not trades: return {"n": 0}
    pnls = [t[key] for t in trades]; wins = sum(1 for p in pnls if p > 0)
    by_reason = {}
    for t in trades: by_reason[t["reason"]] = by_reason.get(t["reason"], 0) + 1
    return {"n": len(trades), "win_rate": round(100 * wins / len(trades), 1),
            "total": round(sum(pnls), 2), "avg": round(sum(pnls) / len(pnls), 2), "by_reason": by_reason}


def main():
    for index, td in [("NIFTY", 0.25), ("SENSEX", 0.20)]:
        print(f"\n=== {index} 0.{int(td*100)}-delta, costed ===")
        for label, mult in [("flat SL=1.0 (baseline)", None), ("ATR mult=0.75", 0.75),
                              ("ATR mult=1.0", 1.0), ("ATR mult=1.25", 1.25)]:
            trades = run(index, td, mult)
            s = summarize(trades, "costed")
            print(f"  {label:>22}: n={s['n']:>3} win%={s['win_rate']:>5} total=Rs{s['total']:>9,.0f} "
                  f"avg=Rs{s['avg']:>8,.2f} {s['by_reason']}")


if __name__ == "__main__":
    main()
