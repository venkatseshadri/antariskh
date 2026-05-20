#!/usr/bin/env python3
"""
Standalone margin calculator. Runs at 8:00 AM using tokens refreshed at 7:00 AM.
Uses existing cred.yml (Shoonya) and tokens.json (Flattrade).
"""

import sys
import os
import logging
from pathlib import Path
from datetime import datetime

from format_utils import format_inr

PROJECT_ROOT = Path(__file__).parent.parent
PYTHON_TRADER = PROJECT_ROOT / "python-trader"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    handlers=[
        logging.FileHandler(
            Path(__file__).parent
            / "logs"
            / f"margin_calculator_{datetime.now().strftime('%Y%m%d')}.log"
        ),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("MarginCalculator")


def fetch_shoonya_margin():
    """Fetch Shoonya margin using cred.yml refreshed at 7:00 AM."""
    logger.info("=" * 70)
    logger.info("SHOONYA MARGIN FETCH")
    logger.info("=" * 70)

    try:
        sys.path.insert(0, str(PYTHON_TRADER))

        from varaha_auth import VarahaConnect

        varaha = VarahaConnect()
        if varaha.start_session():  # Uses cred.yml from 7:00 AM refresh
            from broker_limits import fetch_live_limits_from_broker, sync_with_config

            limits = fetch_live_limits_from_broker(varaha.api)
            if limits:
                sync_with_config()
                logger.info(
                    f"✅ Shoonya margin: {format_inr(limits.total_margin_available)} "
                    f"(used: {format_inr(limits.used_margin)})"
                )
                return True
            else:
                logger.warning("⚠️  Shoonya: fetch_live_limits returned None")
                return False
        else:
            logger.warning("⚠️  Shoonya: start_session failed")
            return False

    except Exception as e:
        logger.error(f"❌ Shoonya margin error: {e}")
        import traceback

        logger.error(traceback.format_exc())
        return False


def fetch_flattrade_margin():
    """Fetch Flattrade margin using tokens.json refreshed at 7:00 AM."""
    logger.info("=" * 70)
    logger.info("FLATTRADE MARGIN FETCH")
    logger.info("=" * 70)

    try:
        sys.path.insert(0, str(PYTHON_TRADER))

        # TODO: Implement Flattrade margin fetch
        # For now, log placeholder
        logger.info("ℹ️  Flattrade margin: placeholder (TODO: implement broker_limits for FT)")
        return False

    except Exception as e:
        logger.error(f"❌ Flattrade margin error: {e}")
        return False


def main():
    logger.info("MARGIN CALCULATOR JOB — START")
    logger.info(f"Timestamp: {datetime.now().isoformat()}")
    logger.info("Using tokens from 7:00 AM refresh")

    results = {
        "shoonya": fetch_shoonya_margin(),
        "flattrade": fetch_flattrade_margin(),
    }

    logger.info("=" * 70)
    logger.info("SUMMARY")
    logger.info("=" * 70)
    logger.info(f"Shoonya: {'✅ OK' if results['shoonya'] else '❌ FAIL'}")
    logger.info(f"Flattrade: {'✅ OK' if results['flattrade'] else '⏳ TODO'}")

    all_ok = results.get("shoonya", False)
    if all_ok:
        logger.info("✅ Margin calculation complete")
    else:
        logger.warning("⚠️  Margin calculation partial/failed")

    logger.info("=" * 70)


if __name__ == "__main__":
    main()
