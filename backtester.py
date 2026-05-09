#!/usr/bin/env python3
"""
Backtester — P&L calculation for dry-run trades.
Uses real option-pricing logic, not mock P&L.
Dry-run mode: no broker execution, pure backtest.
"""

import json
import logging
from typing import Dict, Optional
from datetime import datetime
from math import log, sqrt, exp

logger = logging.getLogger("Backtester")

# ============================================================
# BLACK-SCHOLES OPTION PRICING
# ============================================================

def black_scholes_call(S, K, T, r, sigma):
    """Black-Scholes call option price"""
    if T <= 0:
        return max(S - K, 0)
    d1 = (log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt(T))
    d2 = d1 - sigma * sqrt(T)
    from scipy.stats import norm
    return S * norm.cdf(d1) - K * exp(-r * T) * norm.cdf(d2)

def black_scholes_put(S, K, T, r, sigma):
    """Black-Scholes put option price"""
    if T <= 0:
        return max(K - S, 0)
    d1 = (log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt(T))
    d2 = d1 - sigma * sqrt(T)
    from scipy.stats import norm
    return K * exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)

# ============================================================
# IRON FLY BACKTEST
# ============================================================

class IronFlyBacktester:
    """
    Iron Fly P&L calculator.
    Entry: 4-leg position (long OTM put, short ATM put, short ATM call, long OTM call).
    Exit: close all 4 legs at exit price or time.
    """

    # Black-Scholes inputs
    RISK_FREE_RATE = 0.06  # 6% annual
    IMPLIED_VOL = 0.20     # 20% IV (typical for NIFTY)
    DAYS_TO_EXPIRY = 7     # Weekly expiry

    @staticmethod
    def calculate_leg_premium(option_type: str, spot: float, strike: float,
                             days_to_expiry: int = DAYS_TO_EXPIRY, iv: float = IMPLIED_VOL) -> float:
        """Calculate option premium using Black-Scholes"""
        T = days_to_expiry / 365.0

        try:
            if option_type == "CE":  # Call
                return black_scholes_call(spot, strike, T, IronFlyBacktester.RISK_FREE_RATE, iv)
            elif option_type == "PE":  # Put
                return black_scholes_put(spot, strike, T, IronFlyBacktester.RISK_FREE_RATE, iv)
            else:
                logger.error(f"Unknown option type: {option_type}")
                return 0.0
        except Exception as e:
            logger.error(f"Black-Scholes calculation failed: {e}, returning 0")
            return 0.0

    @staticmethod
    def backtest_iron_fly(trade_plan: Dict, exit_spot: Optional[float] = None) -> Dict:
        """
        Backtest Iron Fly trade.

        Args:
            trade_plan: Contains entry spot, ATM strike, wing width, etc.
            exit_spot: Exit spot price (for P&L calc). If None, use entry spot.

        Returns:
            Dict with entry price, exit price, P&L, return %, etc.
        """
        if not trade_plan:
            logger.error("No trade plan provided")
            return None

        entry_spot = trade_plan.get("spot")
        atm = trade_plan.get("atm_strike")
        wing_width = trade_plan.get("wing_width", 300)
        target_profit = trade_plan.get("target_profit", 1000)
        max_loss = trade_plan.get("max_loss", 3500)
        lots = trade_plan.get("lots", 1)

        if not exit_spot:
            # Default: close at entry spot (no move)
            exit_spot = entry_spot

        logger.info(f"Backtesting Iron Fly: entry={entry_spot}, exit={exit_spot}, ATM={atm}")

        try:
            # Entry: premium collected
            long_put_entry = IronFlyBacktester.calculate_leg_premium("PE", entry_spot, atm - wing_width)
            short_put_entry = IronFlyBacktester.calculate_leg_premium("PE", entry_spot, atm)
            short_call_entry = IronFlyBacktester.calculate_leg_premium("CE", entry_spot, atm)
            long_call_entry = IronFlyBacktester.calculate_leg_premium("CE", entry_spot, atm + wing_width)

            # Net debit at entry (Iron Fly is a credit spread)
            entry_credit = (short_put_entry + short_call_entry) - (long_put_entry + long_call_entry)

            # Exit: premium to close all 4 legs
            long_put_exit = IronFlyBacktester.calculate_leg_premium("PE", exit_spot, atm - wing_width)
            short_put_exit = IronFlyBacktester.calculate_leg_premium("PE", exit_spot, atm)
            short_call_exit = IronFlyBacktester.calculate_leg_premium("CE", exit_spot, atm)
            long_call_exit = IronFlyBacktester.calculate_leg_premium("CE", exit_spot, atm + wing_width)

            # Net debit at exit
            exit_debit = (long_put_exit + long_call_exit) - (short_put_exit + short_call_exit)

            # P&L = credit received - debit to close (per lot)
            pnl_per_lot = entry_credit - exit_debit

            # Multiply by lot size (1 lot NIFTY = 75 multiplier)
            NIFTY_MULTIPLIER = 75
            total_pnl = pnl_per_lot * lots * NIFTY_MULTIPLIER

            return_pct = (total_pnl / (max_loss * lots * NIFTY_MULTIPLIER)) * 100 if max_loss else 0

            result = {
                "entry_spot": entry_spot,
                "exit_spot": exit_spot,
                "atm": atm,
                "wing_width": wing_width,
                "entry_credit": entry_credit,
                "exit_debit": exit_debit,
                "pnl_per_lot": pnl_per_lot,
                "total_pnl": total_pnl,
                "pnl_inr": round(total_pnl, 2),
                "return_pct": round(return_pct, 2),
                "max_loss": max_loss,
                "target_profit": target_profit,
                "hit_target": bool(total_pnl >= target_profit),
                "hit_stoploss": bool(total_pnl <= -max_loss),
                "mtd_pnl": total_pnl,  # Will be accumulated by CFO
                "lots": lots,
            }

            logger.info(f"Backtest result: P&L ₹{result['pnl_inr']}, return {result['return_pct']}%")
            return result

        except Exception as e:
            logger.error(f"Backtest failed: {e}")
            return None

# ============================================================
# STANDALONE FUNCTION
# ============================================================

def backtest_trade(trade_plan: Dict, exit_spot: Optional[float] = None) -> Optional[Dict]:
    """Backtest a trade (wrapper for backwards compatibility)"""
    return IronFlyBacktester.backtest_iron_fly(trade_plan, exit_spot)
