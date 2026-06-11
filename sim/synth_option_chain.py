"""PORCUPINE synthetic option chain — premiums that move with the scripted spot.

A deliberately simple model (NOT an accurate pricer): intrinsic + a Gaussian-in-
moneyness time value that decays linearly through the session (theta) and scales
with VIX. The point is for premiums to move the RIGHT direction and magnitude as
spot moves + time passes, so the position manager's SL / TP / theta-roll / morph /
exit triggers fire at realistic times in a timed replay.

tsym format `NIFTY{expiry}{CE|PE}{strike}` matches what position_manager's morph
path constructs, and contract_builder reads the tsym straight out of option_prices —
so the real entry, morph, and SL/TP lookups all resolve against this chain.
"""
import math


def option_ltp(spot: float, strike: int, otype: str,
               frac_time_left: float, vix: float, tv_scale: float = 200.0) -> float:
    """intrinsic + time-value. frac_time_left: 1.0 at open → 0.0 at close."""
    intrinsic = max(0.0, spot - strike) if otype == "CE" else max(0.0, strike - spot)
    theta = max(0.05, min(1.0, frac_time_left))          # floor so ATM never hits 0
    atm_tv = vix * 5.0 * theta                            # ATM time value (~vix*5 at open)
    tv = atm_tv * math.exp(-((spot - strike) / tv_scale) ** 2)
    return round(intrinsic + tv, 2)


def build_chain(spot: float, frac_time_left: float, vix: float, expiry: str,
                timestamp: str, width: int = 600, step: int = 50,
                instrument: str = "NIFTY") -> list[dict]:
    """option_prices rows for strikes ATM±width, both CE/PE, at one timestamp."""
    atm = round(spot / step) * step
    exp = expiry.replace("-", "")
    rows = []
    for k in range(-width, width + 1, step):
        strike = atm + k
        for ot in ("CE", "PE"):
            rows.append({
                "tsym": f"{instrument}{exp}{ot}{strike}",
                "strike": strike,
                "option_type": ot,
                "ltp": option_ltp(spot, strike, ot, frac_time_left, vix),
                "oi": 100000,
                "volume": 10000,
                "timestamp": timestamp,
            })
    return rows
