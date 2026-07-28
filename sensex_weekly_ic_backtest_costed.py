"""SENSEX Friday-entry weekly IC with honest trading costs — same treatment
as antariksh/weekly_ic_backtest_costed.py, applied to sensex_weekly_ic_backtest.py's
winning bucket (Friday)."""

import numpy as np

from backtester import black_scholes_call, black_scholes_put
from sensex_weekly_ic_backtest import (
    load_sensex_daily_closes, trailing_rv, trailing_median_rv, next_expiry,
    STRIKE_GAP, LOT_SIZE, WING_PCT, SL_MULT, PT_FRAC, RISK_FREE_RATE,
)

BROKERAGE_PER_ORDER = 20.0
SLIPPAGE_TICKS = 1
TICK = 0.05
SLIPPAGE_PCT = 0.0025
STAT_CHARGES_PCT = 0.0007


def leg_prices(S, sp, lp, sc, lc, T, sigma):
    return {
        "short_put": black_scholes_put(S, sp, T, RISK_FREE_RATE, sigma),
        "long_put": black_scholes_put(S, lp, T, RISK_FREE_RATE, sigma),
        "short_call": black_scholes_call(S, sc, T, RISK_FREE_RATE, sigma),
        "long_call": black_scholes_call(S, lc, T, RISK_FREE_RATE, sigma),
    }


def fill(px, is_sell):
    slip = SLIPPAGE_TICKS * TICK + px * SLIPPAGE_PCT
    return max(0.0, px - slip) if is_sell else px + slip


def unwind_fill(px, is_sell):
    slip = SLIPPAGE_TICKS * TICK + px * SLIPPAGE_PCT
    return px + slip if is_sell else max(0.0, px - slip)


def run_friday_costed(closes):
    dates = list(closes.index)
    date_set = set(dates)
    trades = []
    cycle = None

    for d in dates:
        if cycle is not None:
            S = float(closes[d])
            expiry = cycle["expiry"]
            T = max((expiry - d).days / 365, 0)
            legs_now = leg_prices(S, cycle["sp"], cycle["lp"], cycle["sc"], cycle["lc"], T, cycle["sigma"])
            val = (legs_now["short_put"] - legs_now["long_put"]) + (legs_now["short_call"] - legs_now["long_call"])
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
                exit_fills = {
                    "short_put": unwind_fill(legs_now["short_put"], True),
                    "long_put": unwind_fill(legs_now["long_put"], False),
                    "short_call": unwind_fill(legs_now["short_call"], True),
                    "long_call": unwind_fill(legs_now["long_call"], False),
                }
                raw_pnl_per_lot = (credit - val) * LOT_SIZE
                turnover = sum(cycle["entry_fills"].values()) + sum(exit_fills.values())
                entry_slip_cost = sum(abs(cycle["entry_fills"][k] - cycle["entry_raw"][k]) for k in cycle["entry_fills"]) * LOT_SIZE
                exit_slip_cost = sum(abs(exit_fills[k] - legs_now[k]) for k in exit_fills) * LOT_SIZE
                costed_pnl_per_lot = raw_pnl_per_lot - (8 * BROKERAGE_PER_ORDER) - (turnover * LOT_SIZE * STAT_CHARGES_PCT) - entry_slip_cost - exit_slip_cost
                trades.append({"entry_date": cycle["entry_date"], "expiry": expiry, "exit_date": d,
                                "reason": reason, "raw_pnl_per_lot": round(raw_pnl_per_lot, 2),
                                "costed_pnl_per_lot": round(costed_pnl_per_lot, 2)})
                cycle = None
            continue

        if d.strftime("%a") != "Fri":
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
        lp, lc = sp - wing, sc + wing
        legs0 = leg_prices(S0, sp, lp, sc, lc, T0, entry_rv)
        credit = (legs0["short_put"] - legs0["long_put"]) + (legs0["short_call"] - legs0["long_call"])
        entry_fills = {
            "short_put": fill(legs0["short_put"], True), "long_put": fill(legs0["long_put"], False),
            "short_call": fill(legs0["short_call"], True), "long_call": fill(legs0["long_call"], False),
        }
        cycle = {"entry_date": d, "expiry": expiry, "sp": sp, "lp": lp, "sc": sc, "lc": lc,
                 "sigma": entry_rv, "credit": credit, "entry_raw": legs0, "entry_fills": entry_fills}
    return trades


def summarize(trades, key):
    if not trades:
        return {"n": 0}
    pnls = [t[key] for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    years = (trades[-1]["exit_date"] - trades[0]["entry_date"]).days / 365.25
    return {"n": len(trades), "win_rate": round(100 * wins / len(trades), 1),
            "total_per_lot": round(sum(pnls), 2), "avg_per_lot": round(sum(pnls) / len(pnls), 2),
            "worst": round(min(pnls), 2), "years": round(years, 2),
            "per_lot_per_month": round(sum(pnls) / len(pnls) * (len(trades) / years) / 12, 2) if years > 0 else None}


def main():
    closes = load_sensex_daily_closes()
    trades = run_friday_costed(closes)
    raw = summarize(trades, "raw_pnl_per_lot")
    costed = summarize(trades, "costed_pnl_per_lot")
    print(f"SENSEX Friday-entry weekly IC, {raw['n']} trades over {raw['years']}yr\n")
    print(f"RAW: win%={raw['win_rate']} total/lot=Rs{raw['total_per_lot']} avg/lot=Rs{raw['avg_per_lot']} worst=Rs{raw['worst']} ~Rs{raw['per_lot_per_month']}/lot/month")
    print(f"COSTED: win%={costed['win_rate']} total/lot=Rs{costed['total_per_lot']} avg/lot=Rs{costed['avg_per_lot']} worst=Rs{costed['worst']} ~Rs{costed['per_lot_per_month']}/lot/month")
    margin_floor = 30_000.0
    capital = 200_000.0
    lots = int(capital * 0.95 // margin_floor)
    monthly_pct = costed['per_lot_per_month'] * lots / capital * 100
    print(f"\nAt Rs{capital:,.0f} capital, {lots} lots (margin floor Rs{margin_floor:,.0f}/lot): ~{monthly_pct:.2f}%/month")


if __name__ == "__main__":
    main()
