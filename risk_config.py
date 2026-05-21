#!/usr/bin/env python3
"""
Risk Management Configuration — Central policy for all capital and risk limits.

All agents reference these values. Update here, not in agent code.
Asset manager sets these values based on firm policy.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any
from format_utils import format_inr

# ======================================================================
# CAPITAL CONFIGURATION
# ======================================================================


@dataclass
class CapitalConfig:
    """Capital allocation and usage limits."""

    # Total capital available for trading
    total_capital: float = 611_000.00  # Update per asset manager decision

    # Minimum free cash that must always remain (floor)
    free_cash_floor: float = 50_000.00  # As per asset manager

    # Maximum margin utilization % (0.0-1.0)
    max_margin_utilization_pct: float = 0.85  # 85%

    # Expected margin when market is volatile (VIX spike safety margin)
    vix_spike_margin_multiplier: float = 1.25  # 25% margin increase buffer

    def get_available_margin(self, margin_locked: float) -> float:
        """Calculate available margin for new trades."""
        return self.total_capital - margin_locked - self.free_cash_floor


# ======================================================================
# RISK LIMITS CONFIGURATION
# ======================================================================


@dataclass
class RiskLimitsConfig:
    """Per-trade and daily risk limits."""

    # Maximum loss per single trade (in rupees)
    max_loss_per_trade: float = 30_000.00  # As per asset manager

    # Maximum cumulative loss per trading day
    max_loss_per_day: float = 100_000.00  # As per asset manager

    # Maximum concurrent active trades
    max_concurrent_trades: int = 4

    # Maximum shifts allowed per trade
    max_shifts_per_trade: int = 2

    # Target profit as % of margin required
    target_profit_pct_of_margin: float = 0.05  # 5% of margin locked

    # Theta exhaustion threshold (decay %)
    theta_exhaustion_threshold_pct: float = 0.70  # 70%

    # Hedge decay threshold for HEDGE_SHIFTER
    hedge_decay_threshold_pct: float = 0.50  # 50%

    # SELL decay threshold for SELL_SHIFTER
    sell_decay_threshold_pct: float = 0.60  # 60%

    # Maximum time position can stay open
    max_position_age_minutes: int = 45

    def is_daily_loss_exceeded(self, daily_loss: float) -> bool:
        """Check if daily loss limit is exceeded."""
        return daily_loss >= self.max_loss_per_day

    def is_trade_loss_exceeded(self, trade_loss: float) -> bool:
        """Check if trade loss limit is exceeded."""
        return trade_loss >= self.max_loss_per_trade

    def is_max_trades_exceeded(self, active_trades: int) -> bool:
        """Check if max concurrent trades limit is exceeded."""
        return active_trades >= self.max_concurrent_trades


# ======================================================================
# MARGIN & EXECUTION CONFIGURATION
# ======================================================================


@dataclass
class ExecutionConfig:
    """Order execution and margin parameters."""

    # NIFTY lot size (shares per lot)
    nifty_lot_size: int = 65

    # Wing widths to try (in rupees/points)
    wing_widths: list = field(default_factory=lambda: [50, 100, 150, 200, 250])

    # Default wing width when creating new positions
    default_wing_width: int = 100

    # Margin matrix file path
    margin_matrix_path: str = "/home/trading_ceo/brahmand/data/margin_matrix.json"

    # Order ledger file path
    order_ledger_path: str = str(Path(__file__).parent / "data" / "order_ledger.json")

    # Whether to route orders through broker (LIVE) or ledger (PAPER)
    live_mode_enabled: bool = False

    def get_order_ledger_file(self) -> str:
        """Get path to order ledger file."""
        return self.order_ledger_path


# ======================================================================
# POSITION MANAGEMENT CONFIGURATION
# ======================================================================


@dataclass
class PositionManagementConfig:
    """Parameters for position morphing and adjustments."""

    # TSL (Trailing Stop Loss) activation threshold (% of max profit)
    tsl_activation_threshold_pct: float = 0.25  # Activate when profit >= 25% of max TP

    # Default lock ratio for TSL (% of favorable move locked)
    tsl_default_lock_ratio: float = 0.50  # Lock 50% of favorable moves

    # SL placement as % above entry (for SELL legs)
    sl_placement_pct: float = 0.10  # SL = entry * 1.10

    # TP placement as % below entry (for SELL legs)
    tp_placement_pct: float = 0.50  # TP = entry * 0.50

    # Score thresholds for MORPH detection
    morph_bullish_threshold: float = 3.0  # score >= 3.0 = BULLISH
    morph_bearish_threshold: float = -3.0  # score <= -3.0 = BEARISH

    # Wing widths for different morph scenarios
    wing_butterfly: int = 200  # Used in BULLISH/BEARISH morphs (4-leg)
    wing_spread: int = 200  # Used in PE/CE spread positions

    def is_bullish_signal(self, score: float) -> bool:
        """Check if score indicates BULLISH regime."""
        return score >= self.morph_bullish_threshold

    def is_bearish_signal(self, score: float) -> bool:
        """Check if score indicates BEARISH regime."""
        return score <= self.morph_bearish_threshold

    def is_neutral_signal(self, score: float) -> bool:
        """Check if score indicates NEUTRAL regime."""
        return self.morph_bearish_threshold < score < self.morph_bullish_threshold


# ======================================================================
# GLOBAL CONFIGURATION INSTANCES
# ======================================================================

# Create global instances
CAPITAL = CapitalConfig()
RISK = RiskLimitsConfig()
EXECUTION = ExecutionConfig()
POSITION = PositionManagementConfig()


# ======================================================================
# CONFIGURATION UPDATES (called by asset manager)
# ======================================================================


def update_capital_limits(
    total_capital: float = None,
    free_cash_floor: float = None,
    max_margin_utilization_pct: float = None,
):
    """Update capital limits (called by asset manager)."""
    global CAPITAL
    if total_capital is not None:
        CAPITAL.total_capital = total_capital
    if free_cash_floor is not None:
        CAPITAL.free_cash_floor = free_cash_floor
    if max_margin_utilization_pct is not None:
        CAPITAL.max_margin_utilization_pct = max_margin_utilization_pct
    print(
        f"[RISK_CONFIG] Capital limits updated: {format_inr(CAPITAL.total_capital, 0)} | Floor: {format_inr(CAPITAL.free_cash_floor, 0)}"
    )


def update_risk_limits(
    max_loss_per_trade: float = None,
    max_loss_per_day: float = None,
    max_concurrent_trades: int = None,
):
    """Update risk limits (called by asset manager)."""
    global RISK
    if max_loss_per_trade is not None:
        RISK.max_loss_per_trade = max_loss_per_trade
    if max_loss_per_day is not None:
        RISK.max_loss_per_day = max_loss_per_day
    if max_concurrent_trades is not None:
        RISK.max_concurrent_trades = max_concurrent_trades
    print(
        f"[RISK_CONFIG] Risk limits updated: Trade={RISK.max_loss_per_trade} | Daily={RISK.max_loss_per_day} | Max trades={RISK.max_concurrent_trades}"
    )


def get_config_summary() -> str:
    """Get summary of all configured limits."""
    summary = f"""
╔════════════════════════════════════════════════════════════════╗
║           RISK MANAGEMENT CONFIGURATION SUMMARY               ║
╠════════════════════════════════════════════════════════════════╣
║ CAPITAL:
║   Total Capital:                {format_inr(CAPITAL.total_capital, 0)}
║   Free Cash Floor:              {format_inr(CAPITAL.free_cash_floor, 0)}
║   Max Margin Utilization:       {CAPITAL.max_margin_utilization_pct * 100:.0f}%
║
║ RISK LIMITS:
║   Max Loss per Trade:           {format_inr(RISK.max_loss_per_trade, 0)}
║   Max Loss per Day:             {format_inr(RISK.max_loss_per_day, 0)}
║   Max Concurrent Trades:        {RISK.max_concurrent_trades}
║   Max Shifts per Trade:         {RISK.max_shifts_per_trade}
║
║ EXECUTION:
║   NIFTY Lot Size:               {EXECUTION.nifty_lot_size} shares
║   Default Wing Width:           {EXECUTION.default_wing_width} points
║   Wing Options:                 {EXECUTION.wing_widths}
║   Live Mode Enabled:            {EXECUTION.live_mode_enabled}
║
║ POSITION MANAGEMENT:
║   TSL Activation:               {POSITION.tsl_activation_threshold_pct * 100:.0f}% of max profit
║   Bullish Threshold:            {POSITION.morph_bullish_threshold}
║   Bearish Threshold:            {POSITION.morph_bearish_threshold}
║
╚════════════════════════════════════════════════════════════════╝
"""
    return summary


if __name__ == "__main__":
    print(get_config_summary())

    # Example: Asset manager updates limits
    print("\n[EXAMPLE] Asset manager updates capital limits...")
    update_capital_limits(
        total_capital=750_000,  # Increase to ₹750k
        free_cash_floor=75_000,  # Increase floor to ₹75k
    )

    print(get_config_summary())
