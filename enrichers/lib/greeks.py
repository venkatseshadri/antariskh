"""Black-Scholes Greeks + aggregate iron-fly Greeks.

Lifted verbatim from varaha_advanced_indicators.py.
Pure math — no DB, no broker.
"""

import math
from datetime import datetime
from typing import Dict, Optional


def black_scholes_greeks(
    S: float, K: float, T: float, r: float, sigma: float, option_type: str = "C"
) -> Dict:
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return {"delta": 0, "gamma": 0, "vega": 0, "theta": 0}
    try:
        from scipy.stats import norm

        d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)

        nd1 = norm.pdf(d1)
        Nd1 = norm.cdf(d1)
        Nd2 = norm.cdf(d2)

        if option_type == "C":
            delta = Nd1
            theta = (
                -S * nd1 * sigma / (2 * math.sqrt(T)) - r * K * math.exp(-r * T) * Nd2
            ) / 365
        else:
            delta = Nd1 - 1
            theta = (
                -S * nd1 * sigma / (2 * math.sqrt(T))
                + r * K * math.exp(-r * T) * (1 - Nd2)
            ) / 365

        gamma = nd1 / (S * sigma * math.sqrt(T))
        vega = S * nd1 * math.sqrt(T) / 100

        return {
            "delta": round(delta, 4),
            "gamma": round(gamma, 6),
            "vega": round(vega, 4),
            "theta": round(theta, 4),
        }
    except ImportError:
        return {"delta": 0, "gamma": 0, "vega": 0, "theta": 0}
    except Exception:
        return {"delta": 0, "gamma": 0, "vega": 0, "theta": 0}


def compute_aggregate_greeks(
    spot: float, expiry: str, atm_strike: int, vix: Optional[float]
) -> Dict:
    if not vix or vix <= 0:
        return {
            "agg_delta": None,
            "agg_gamma": None,
            "agg_vega": None,
            "agg_theta": None,
            "wings_delta": None,
            "body_delta": None,
        }
    try:
        r = 0.06
        sigma = vix / 100

        exp_date = datetime.strptime(expiry, "%d-%b-%Y").date()
        days_to_exp = (exp_date - datetime.now().date()).days
        T = days_to_exp / 365 if days_to_exp > 0 else 0.001

        wings_delta = 0
        wings_gamma = 0
        wings_vega = 0
        wings_theta = 0

        step = 50
        for i in range(1, 6):
            call_strike = atm_strike + (i * step)
            call_greeks = black_scholes_greeks(spot, call_strike, T, r, sigma, "C")
            wings_delta += call_greeks["delta"]
            wings_gamma += call_greeks["gamma"]
            wings_vega += call_greeks["vega"]
            wings_theta += call_greeks["theta"]

            put_strike = atm_strike - (i * step)
            put_greeks = black_scholes_greeks(spot, put_strike, T, r, sigma, "P")
            wings_delta += put_greeks["delta"]
            wings_gamma += put_greeks["gamma"]
            wings_vega += put_greeks["vega"]
            wings_theta += put_greeks["theta"]

        atm_call = black_scholes_greeks(spot, atm_strike, T, r, sigma, "C")
        atm_put = black_scholes_greeks(spot, atm_strike, T, r, sigma, "P")

        body_delta = -(atm_call["delta"] + atm_put["delta"])
        body_gamma = -(atm_call["gamma"] + atm_put["gamma"])
        body_vega = -(atm_call["vega"] + atm_put["vega"])
        body_theta = -(atm_call["theta"] + atm_put["theta"])

        agg_delta = wings_delta + body_delta
        agg_gamma = wings_gamma + body_gamma
        agg_vega = wings_vega + body_vega
        agg_theta = wings_theta + body_theta

        return {
            "agg_delta": round(agg_delta, 4),
            "agg_gamma": round(agg_gamma, 6),
            "agg_vega": round(agg_vega, 4),
            "agg_theta": round(agg_theta, 4),
            "wings_delta": round(wings_delta, 4),
            "body_delta": round(body_delta, 4),
        }
    except Exception:
        return {
            "agg_delta": None,
            "agg_gamma": None,
            "agg_vega": None,
            "agg_theta": None,
            "wings_delta": None,
            "body_delta": None,
        }
