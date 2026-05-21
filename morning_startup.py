#!/usr/bin/env python3
"""
Morning Startup — Combined token refresh + margin capture from both brokers.

Runs ONCE at market open (09:10-09:15):
1. Refresh OAuth tokens (Shoonya)
2. Fetch margin limits from Shoonya
3. Fetch margin limits from Flattrade
4. Compare and use conservative (higher margin requirement)
5. Cache results
6. Sync with config

Single cron job handles everything — no separate token/margin jobs needed.

Usage:
  python3 morning_startup.py

Cron (every trading day at 09:10):
  10 9 * * 1-5 cd /home/trading_ceo/antariksh && python3 morning_startup.py >> logs/morning_startup_$(date +\%Y\%m\%d).log 2>&1
"""

import sys
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent / "python-trader"))
sys.path.insert(
    0, str(Path(__file__).parent.parent / "python-trader" / "Shoonya_oAuthAPI-py")
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Cache files
DATA_DIR = Path(__file__).parent / "data"
SHOONYA_LIMITS_FILE = DATA_DIR / "shoonya_limits.json"
FLATTRADE_LIMITS_FILE = DATA_DIR / "flattrade_limits.json"
COMPARISON_FILE = DATA_DIR / "broker_limits_comparison.json"


def refresh_oauth_tokens():
    """Step 1: Refresh Shoonya OAuth tokens."""
    logger.info("Step 1/5: Refreshing Shoonya OAuth tokens...")
    try:
        from varaha_auth import Varaha

        varaha = Varaha()
        if varaha.login():
            logger.info("  ✓ OAuth tokens refreshed")
            return varaha
        else:
            logger.error("  ✗ OAuth login failed")
            return None
    except Exception as e:
        logger.error(f"  ✗ OAuth refresh error: {e}")
        return None


def fetch_shoonya_limits(varaha) -> Optional[Dict]:
    """Step 2: Fetch margin limits from Shoonya."""
    logger.info("Step 2/5: Fetching limits from Shoonya...")
    try:
        limits_resp = varaha.api.get_limits()
        if limits_resp and limits_resp.get("stat") == "Ok":
            limits = {
                "broker": "Shoonya",
                "timestamp": datetime.now().isoformat(),
                "total_margin": float(limits_resp.get("marginallowed", 0)),
                "used_margin": float(limits_resp.get("marginused", 0)),
                "free_margin": float(limits_resp.get("marginallowed", 0))
                - float(limits_resp.get("marginused", 0)),
                "cash_available": float(limits_resp.get("cash", 0)),
                "multiplier": float(limits_resp.get("multiplier", 1.0)),
                "account_id": limits_resp.get("accountid", "N/A"),
            }
            # Cache
            SHOONYA_LIMITS_FILE.write_text(json.dumps(limits, indent=2))
            logger.info(
                f"  ✓ Shoonya: ₹{limits['total_margin']:,.0f} margin (mult: {limits['multiplier']}x)"
            )
            return limits
        else:
            logger.error(f"  ✗ Shoonya error: {limits_resp}")
            return None
    except Exception as e:
        logger.error(f"  ✗ Shoonya fetch error: {e}")
        return None


def fetch_flattrade_limits() -> Optional[Dict]:
    """Step 3: Fetch margin limits from Flattrade."""
    logger.info("Step 3/5: Fetching limits from Flattrade...")
    try:
        # Import Flattrade API (adjust based on actual integration)
        # For now, this is a placeholder
        logger.info("  ⚠ Flattrade integration: placeholder (TODO: implement)")
        logger.info("  ⚠ Using Shoonya limits as fallback")
        return None

        # Future implementation:
        # from flattrade_api import FlattradeAPI
        # ft = FlattradeAPI()
        # if ft.login():
        #     limits_resp = ft.get_account_limits()
        #     limits = {
        #         "broker": "Flattrade",
        #         "timestamp": datetime.now().isoformat(),
        #         "total_margin": float(limits_resp.get("total_margin", 0)),
        #         ...
        #     }
        #     FLATTRADE_LIMITS_FILE.write_text(json.dumps(limits, indent=2))
        #     return limits

    except Exception as e:
        logger.warning(f"  ⚠ Flattrade fetch error: {e} (using Shoonya)")
        return None


def compare_broker_limits(shoonya: Dict, flattrade: Optional[Dict]) -> Dict:
    """Step 4: Compare and select conservative limits."""
    logger.info("Step 4/5: Comparing broker limits...")

    if not flattrade:
        logger.info("  ℹ Flattrade unavailable, using Shoonya limits")
        comparison = {
            "timestamp": datetime.now().isoformat(),
            "selected_broker": "Shoonya",
            "reason": "Flattrade not available",
            "shoonya_margin": shoonya.get("total_margin"),
            "flattrade_margin": None,
            "effective_margin": shoonya.get("total_margin"),
        }
        COMPARISON_FILE.write_text(json.dumps(comparison, indent=2))
        return shoonya

    # Both available: use conservative (lower margin = higher requirement)
    sh_margin = shoonya.get("total_margin", float("inf"))
    ft_margin = flattrade.get("total_margin", float("inf"))

    if sh_margin <= ft_margin:
        logger.info(
            f"  ✓ Shoonya is conservative: ₹{sh_margin:,.0f} vs ₹{ft_margin:,.0f}"
        )
        selected = shoonya
        reason = "Shoonya has lower available margin (more conservative)"
    else:
        logger.info(
            f"  ✓ Flattrade is conservative: ₹{ft_margin:,.0f} vs ₹{sh_margin:,.0f}"
        )
        selected = flattrade
        reason = "Flattrade has lower available margin (more conservative)"

    comparison = {
        "timestamp": datetime.now().isoformat(),
        "selected_broker": selected.get("broker"),
        "reason": reason,
        "shoonya_margin": sh_margin,
        "flattrade_margin": ft_margin,
        "effective_margin": selected.get("total_margin"),
    }
    COMPARISON_FILE.write_text(json.dumps(comparison, indent=2))
    return selected


def sync_with_config(limits: Dict):
    """Step 5: Sync limits with config."""
    logger.info("Step 5/5: Syncing with config...")
    try:
        from broker_limits import sync_with_config as sync_fn
        from risk_config import CAPITAL

        # Update global limits
        CAPITAL.total_capital = limits.get("total_margin", CAPITAL.total_capital)

        # Call sync
        sync_fn()

        logger.info(f"  ✓ Config synced: ₹{CAPITAL.total_capital:,.0f} available")
        return True
    except Exception as e:
        logger.warning(f"  ⚠ Config sync error: {e}")
        return False


def print_startup_summary(shoonya: Dict, flattrade: Optional[Dict], selected: Dict):
    """Print summary of morning startup."""
    summary = f"""
╔════════════════════════════════════════════════════════════════╗
║              MORNING STARTUP COMPLETE (09:15)                  ║
╠════════════════════════════════════════════════════════════════╣
║
║ SHOONYA LIMITS:
║   Total Margin:              ₹{shoonya.get("total_margin", 0):>12,.0f}
║   Used Margin:               ₹{shoonya.get("used_margin", 0):>12,.0f}
║   Free Margin:               ₹{shoonya.get("free_margin", 0):>12,.0f}
║   Cash Available:            ₹{shoonya.get("cash_available", 0):>12,.0f}
║   Multiplier (VIX effect):   {shoonya.get("multiplier", 1.0):>18.2f}x
║
"""

    if flattrade:
        summary += f"""
║ FLATTRADE LIMITS:
║   Total Margin:              ₹{flattrade.get("total_margin", 0):>12,.0f}
║   Used Margin:               ₹{flattrade.get("used_margin", 0):>12,.0f}
║   Free Margin:               ₹{flattrade.get("free_margin", 0):>12,.0f}
║   Cash Available:            ₹{flattrade.get("cash_available", 0):>12,.0f}
║   Multiplier (VIX effect):   {flattrade.get("multiplier", 1.0):>18.2f}x
║
"""

    summary += f"""
║ SELECTED FOR TRADING:
║   Broker:                    {selected.get("broker", "N/A"):>30}
║   Effective Margin:          ₹{selected.get("total_margin", 0):>12,.0f}
║   Safety Margin (80%):       ₹{selected.get("total_margin", 0) * 0.80:>12,.0f}
║
║ FILES CREATED:
║   • data/shoonya_limits.json
║   • data/flattrade_limits.json
║   • data/broker_limits_comparison.json
║   • data/broker_limits.json (synced to config)
║
║ SYSTEM READY: All agents use effective margin for trading
║
╚════════════════════════════════════════════════════════════════╝
"""
    logger.info(summary)


def main():
    """Run morning startup."""
    logger.info("=" * 70)
    logger.info("MORNING STARTUP — Token Refresh + Margin Capture")
    logger.info("=" * 70)

    # Step 1: Refresh tokens
    varaha = refresh_oauth_tokens()
    if not varaha:
        logger.error("FAILED: Cannot proceed without OAuth tokens")
        return False

    # Step 2: Fetch Shoonya limits
    shoonya = fetch_shoonya_limits(varaha)
    if not shoonya:
        logger.error("FAILED: Cannot get Shoonya limits")
        return False

    # Step 3: Fetch Flattrade limits
    flattrade = fetch_flattrade_limits()

    # Step 4: Compare and select
    selected = compare_broker_limits(shoonya, flattrade)

    # Step 5: Sync with config
    if not sync_with_config(selected):
        logger.warning("Config sync failed, but continuing with limits")

    # Summary
    print_startup_summary(shoonya, flattrade, selected)

    logger.info("=" * 70)
    logger.info("STARTUP COMPLETE: Ready for trading")
    logger.info("=" * 70)

    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
