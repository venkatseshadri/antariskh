#!/usr/bin/env python3
"""
Broker Limits Integration — Fetch live margin and capital from broker.

Asset manager calls update_broker_limits() once per day at market open.
Agents use these real, live limits instead of configuration defaults.
"""

import sys
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, Tuple
from dataclasses import dataclass

from format_utils import format_inr

sys.path.insert(0, str(Path(__file__).parent.parent / "python-trader"))
sys.path.insert(
    0, str(Path(__file__).parent.parent / "python-trader" / "Shoonya_oAuthAPI-py")
)

LIMITS_FILE = Path(__file__).parent / "data" / "broker_limits.json"


@dataclass
class BrokerLimits:
    """Live limits fetched from broker."""

    timestamp: str  # When fetched from broker
    total_margin_available: float  # Total margin available
    used_margin: float  # Currently used
    free_margin: float  # Available for new trades
    cash_available: float  # Free cash (not locked in positions)
    margin_multiplier: float  # Broker's margin multiplier (changes with VIX)
    symbol: str = "NIFTY"
    account_id: str = ""

    def get_net_available_margin(self) -> float:
        """Get available margin after safety buffer."""
        # Keep 10% buffer for VIX spikes
        return self.free_margin * 0.90

    def is_sufficient_for_trade(self, required_margin: float) -> bool:
        """Check if enough margin for new trade."""
        return self.get_net_available_margin() >= required_margin

    def get_safety_buffer_pct(self) -> float:
        """Get recommended safety margin % based on multiplier."""
        # Higher multiplier = higher volatility = larger buffer
        base_buffer = 0.10  # 10% minimum
        if self.margin_multiplier > 1.5:
            return 0.20  # 20% buffer for high volatility
        elif self.margin_multiplier > 1.2:
            return 0.15  # 15% buffer for moderate volatility
        return base_buffer


def _load_broker_limits() -> Optional[BrokerLimits]:
    """Load cached broker limits from disk."""
    if not LIMITS_FILE.exists():
        return None
    try:
        data = json.loads(LIMITS_FILE.read_text())
        return BrokerLimits(**data)
    except Exception as e:
        print(f"[BROKER_LIMITS] Error loading cached limits: {e}")
        return None


def _save_broker_limits(limits: BrokerLimits):
    """Save broker limits to disk."""
    try:
        data = {
            "timestamp": limits.timestamp,
            "total_margin_available": limits.total_margin_available,
            "used_margin": limits.used_margin,
            "free_margin": limits.free_margin,
            "cash_available": limits.cash_available,
            "margin_multiplier": limits.margin_multiplier,
            "symbol": limits.symbol,
            "account_id": limits.account_id,
        }
        LIMITS_FILE.write_text(json.dumps(data, indent=2))
    except Exception as e:
        print(f"[BROKER_LIMITS] Error saving limits: {e}")


def fetch_live_limits_from_broker(api) -> Optional[BrokerLimits]:
    """
    Fetch live margin and capital from broker API.

    Args:
        api: Shoonya API instance (NorenApiPy from varaha_auth)

    Returns:
        BrokerLimits with fresh data from broker, or None if fetch fails

    Example:
        from varaha_auth import Varaha
        varaha = Varaha()
        if varaha.login():
            limits = fetch_live_limits_from_broker(varaha.api)
    """
    try:
        # Call Shoonya's get_limits endpoint (no account_id needed)
        limits_resp = api.get_limits()

        if not limits_resp or limits_resp.get("stat") != "Ok":
            print(f"[BROKER_LIMITS] Broker returned error: {limits_resp}")
            return None

        # Parse response (Shoonya response format)
        margin_available = float(limits_resp.get("marginallowed", 0))
        used_margin = float(limits_resp.get("marginused", 0))
        free_margin = margin_available - used_margin
        cash_available = float(limits_resp.get("cash", 0))
        mult = float(limits_resp.get("multiplier", 1.0))
        account_id = limits_resp.get("accountid", "N/A")

        limits = BrokerLimits(
            timestamp=datetime.now().isoformat(),
            total_margin_available=margin_available,
            used_margin=used_margin,
            free_margin=free_margin,
            cash_available=cash_available,
            margin_multiplier=mult,
            symbol="NIFTY",
            account_id=str(account_id),
        )

        # Cache to disk
        _save_broker_limits(limits)

        print(f"[BROKER_LIMITS] Fetched from broker at {limits.timestamp}")
        print(f"  Total margin available: {format_inr(margin_available)}")
        print(f"  Used margin: {format_inr(used_margin)}")
        print(f"  Free margin: {format_inr(free_margin)}")
        print(f"  Cash available: {format_inr(cash_available)}")
        print(f"  Margin multiplier: {mult}x (VIX effect)")

        return limits

    except Exception as e:
        print(f"[BROKER_LIMITS] Error fetching from broker: {e}")
        return None


def get_cached_broker_limits() -> Optional[BrokerLimits]:
    """Get last cached limits from disk."""
    return _load_broker_limits()


def get_current_limits() -> Tuple[Optional[BrokerLimits], bool]:
    """
    Get current limits (live if available, cached otherwise).

    Returns:
        (BrokerLimits, is_live) where is_live=True if limits are fresh
    """
    cached = get_cached_broker_limits()
    if cached:
        # Check if less than 1 hour old
        timestamp = datetime.fromisoformat(cached.timestamp)
        age_minutes = (datetime.now() - timestamp).total_seconds() / 60
        is_fresh = age_minutes < 60
        return (cached, is_fresh)
    return (None, False)


def print_limits_summary():
    """Print current limits summary."""
    limits, is_fresh = get_current_limits()

    if not limits:
        print("[BROKER_LIMITS] No limits available. Fetch from broker first.")
        return

    freshness_marker = "✓ LIVE" if is_fresh else "⚠ CACHED"

    summary = f"""
╔════════════════════════════════════════════════════════════════╗
║              BROKER LIMITS — {freshness_marker}
╠════════════════════════════════════════════════════════════════╣
║ Timestamp:                      {limits.timestamp}
║ Total Margin Available:         ₹{limits.total_margin_available:,.0f}
║ Used Margin:                    ₹{limits.used_margin:,.0f}
║ Free Margin:                    ₹{limits.free_margin:,.0f}
║ Cash Available:                 ₹{limits.cash_available:,.0f}
║ Margin Multiplier:              {limits.margin_multiplier}x (VIX effect)
║
║ Recommended Safety Buffer:      {limits.get_safety_buffer_pct() * 100:.0f}%
║ Net Available (with buffer):    ₹{limits.get_net_available_margin():,.0f}
║
║ Account:                        {limits.account_id}
║ Symbol:                         {limits.symbol}
╚════════════════════════════════════════════════════════════════╝
"""
    print(summary)


# ======================================================================
# INTEGRATION WITH risk_config.py
# ======================================================================


def sync_with_config():
    """
    Sync broker limits with risk_config after fetching.

    Call this after update_broker_limits() to push values to config.
    """
    from risk_config import CAPITAL

    limits, is_fresh = get_current_limits()
    if not limits:
        print("[BROKER_LIMITS] No limits to sync with config")
        return

    # Update capital config with broker values
    CAPITAL.total_capital = limits.total_margin_available
    CAPITAL.free_cash_floor = 0  # Broker reports free_margin directly

    print(f"[BROKER_LIMITS] Synced with risk_config:")
    print(f"  CAPITAL.total_capital = ₹{CAPITAL.total_capital:,.0f}")


if __name__ == "__main__":
    print("[BROKER_LIMITS] Integration Module")
    print("=" * 60)

    # Example usage with Varaha (Shoonya API wrapper)
    print("\nExample usage at market open (09:15):")
    print("""
# Step 1: Login to Shoonya via Varaha
from varaha_auth import Varaha
varaha = Varaha()
if not varaha.login():
    print("Login failed")
    exit(1)

# Step 2: Fetch live limits from broker
from broker_limits import fetch_live_limits_from_broker, sync_with_config
limits = fetch_live_limits_from_broker(varaha.api)

# Step 3: Sync with config (all agents now use live data)
sync_with_config()

# Verify
from risk_config import get_config_summary
print(get_config_summary())
""")

    # Try to load and display cached limits
    print("\nCurrent status:")
    limits, is_fresh = get_current_limits()
    if limits:
        print_limits_summary()
    else:
        print(
            "[BROKER_LIMITS] No cached limits. See example above to fetch from broker."
        )
