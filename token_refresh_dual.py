#!/usr/bin/env python3
"""
Daily token refresh for both Shoonya and Flattrade.
Runs once daily via cron. Updates credentials/tokens in place.
"""

import sys
import os
import json
import logging
import subprocess
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent
PYTHON_TRADER = PROJECT_ROOT / "python-trader"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    handlers=[
        logging.FileHandler(
            Path(__file__).parent
            / "logs"
            / f"token_refresh_{datetime.now().strftime('%Y%m%d')}.log"
        ),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("TokenRefresh")


def refresh_flattrade():
    """Refresh Flattrade token via auto-OAuth script"""
    logger.info("=" * 70)
    logger.info("FLATTRADE TOKEN REFRESH")
    logger.info("=" * 70)

    script = PYTHON_TRADER / "get_flattrade_token_auto.py"
    if not script.exists():
        logger.error(f"Flattrade script not found: {script}")
        return False

    try:
        logger.info(f"Running: {script}")
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(PYTHON_TRADER),
            capture_output=True,
            text=True,
            timeout=120,
        )

        logger.info(f"Exit code: {result.returncode}")
        if result.stdout:
            logger.info("STDOUT:")
            logger.info(result.stdout[:500])
        if result.stderr:
            logger.warning("STDERR:")
            logger.warning(result.stderr[:500])

        if result.returncode == 0:
            # Check if token was written (new format: access_token, auth_code)
            token_file = PYTHON_TRADER / "tokens.json"
            if token_file.exists():
                with open(token_file, "r") as f:
                    tokens = json.load(f)
                    if "access_token" in tokens and "auth_code" in tokens:
                        logger.info(
                            f"✅ Flattrade token refreshed: {tokens.get('user_id', 'FT055702')} "
                            f"(exchange: {'OK' if tokens.get('exchange_ok') else tokens.get('exchange_error', 'N/A')})"
                        )
                        return True
            logger.warning("Token file not updated or new format missing")
            return False
        else:
            logger.error(f"Script failed with exit code {result.returncode}")
            return False

    except subprocess.TimeoutExpired:
        logger.error("Flattrade refresh timeout (120s exceeded)")
        return False
    except Exception as e:
        logger.error(f"Flattrade refresh error: {e}")
        return False


def refresh_shoonya():
    """Refresh Shoonya token via GetAuthcode.py"""
    logger.info("=" * 70)
    logger.info("SHOONYA TOKEN REFRESH")
    logger.info("=" * 70)

    script = PYTHON_TRADER / "Shoonya_oAuthAPI-py/GetAuthcode.py"
    if not script.exists():
        logger.error(f"Shoonya script not found: {script}")
        return False

    try:
        logger.info(f"Running: {script}")
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(PYTHON_TRADER / "Shoonya_oAuthAPI-py"),
            capture_output=True,
            text=True,
            timeout=120,
        )

        logger.info(f"Exit code: {result.returncode}")
        if result.stdout:
            logger.info("STDOUT:")
            logger.info(result.stdout[:500])
        if result.stderr:
            logger.warning("STDERR:")
            logger.warning(result.stderr[:500])

        if result.returncode == 0:
            # Check if cred.yml was updated
            cred_file = PYTHON_TRADER / "Shoonya_oAuthAPI-py/cred.yml"
            if cred_file.exists():
                mtime = datetime.fromtimestamp(cred_file.stat().st_mtime)
                age_seconds = (datetime.now() - mtime).total_seconds()
                if age_seconds < 300:  # Updated in last 5 minutes
                    logger.info(f"✅ Shoonya credentials refreshed (mtime: {mtime})")
                    return True
            logger.warning("Shoonya cred file not recently updated")
            return False
        else:
            logger.error(f"Script failed with exit code {result.returncode}")
            return False

    except subprocess.TimeoutExpired:
        logger.error("Shoonya refresh timeout (120s exceeded)")
        return False
    except Exception as e:
        logger.error(f"Shoonya refresh error: {e}")
        return False


def fetch_margins_after_token_refresh(shoonya_ok: bool, flattrade_ok: bool):
    """Tag along: fetch margins using freshly refreshed tokens (no new login)."""
    logger.info("=" * 70)
    logger.info("MARGIN CAPTURE — Using Fresh Tokens")
    logger.info("=" * 70)

    try:
        # Import after tokens are refreshed
        sys.path.insert(0, str(PROJECT_ROOT / "python-trader"))

        if shoonya_ok:
            try:
                # Use Varaha to get Shoonya margins (uses cred.yml we just refreshed)
                from varaha_auth import VarahaConnect
                varaha = VarahaConnect()
                if varaha.login():  # Uses existing cred.yml, no new OAuth needed
                    from broker_limits import fetch_live_limits_from_broker, sync_with_config
                    limits = fetch_live_limits_from_broker(varaha.api)
                    if limits:
                        sync_with_config()
                        logger.info(f"✅ Shoonya margin cached: ₹{limits.total_margin_available:,.0f}")
                    else:
                        logger.warning("⚠️  Shoonya margin fetch failed")
                else:
                    logger.warning("⚠️  Shoonya login failed (using cached)")
            except Exception as e:
                logger.warning(f"⚠️  Shoonya margin error: {e}")

        if flattrade_ok:
            try:
                # TODO: Implement Flattrade margin fetch using fresh token
                logger.info("ℹ️  Flattrade margin: placeholder (TODO: integrate)")
            except Exception as e:
                logger.warning(f"⚠️  Flattrade margin error: {e}")

    except Exception as e:
        logger.error(f"Margin capture error: {e}")


def main():
    logger.info("TOKEN REFRESH JOB — START")
    logger.info(f"Timestamp: {datetime.now().isoformat()}")

    results = {
        "flattrade": refresh_flattrade(),
        "shoonya": refresh_shoonya(),
    }

    logger.info("=" * 70)
    logger.info("SUMMARY")
    logger.info("=" * 70)
    logger.info(f"Flattrade: {'✅ OK' if results['flattrade'] else '❌ FAIL'}")
    logger.info(f"Shoonya: {'✅ OK' if results['shoonya'] else '❌ FAIL'}")

    all_ok = all(results.values())

    # Tag along: fetch margins using fresh tokens (no separate login)
    if any(results.values()):
        fetch_margins_after_token_refresh(results.get("shoonya", False), results.get("flattrade", False))

    logger.info("=" * 70)
    logger.info(f"Overall: {'✅ SUCCESS' if all_ok else '⚠️  PARTIAL/FAIL'}")
    logger.info("=" * 70)

    # Exit with code 0 if at least one broker succeeded
    sys.exit(0 if any(results.values()) else 1)


if __name__ == "__main__":
    main()
