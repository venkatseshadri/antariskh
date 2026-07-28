#!/usr/bin/env python3
"""
Standalone margin calculator. Runs at 8:00 AM using tokens refreshed at 7:00 AM.
Uses existing cred.yml (Shoonya) and tokens.json (Flattrade).
"""

import sys
import os
import json
import subprocess
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

        from varaha.varaha_auth import VarahaConnect

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
    """Fetch Flattrade margin — runs in subprocess to avoid module conflicts with Shoonya."""
    import subprocess

    script = (
        """
import json, sys
from datetime import datetime
from pathlib import Path

PYTHON_TRADER = Path('"""
        + str(PYTHON_TRADER)
        + """')
FT_CREDS = PYTHON_TRADER / 'FlattradeApi' / 'tokens.json'

ft_tokens = json.loads(FT_CREDS.read_text())
sys.path.insert(0, str(PYTHON_TRADER / 'FlattradeApi-py'))
from api_helper import NorenApiPy as FlattradeApi

api = FlattradeApi()
ret = api.set_session(userid='FT055702', accesstoken=ft_tokens.get('access_token'))
if not ret:
    print(json.dumps({'ok': False, 'error': 'login failed'}))
    sys.exit(1)

limits = api.get_limits()
if not limits or limits.get('stat') != 'Ok':
    print(json.dumps({'ok': False, 'error': limits.get('emsg', 'get_limits failed')}))
    sys.exit(1)

cash = float(limits.get('cash', 0))
used = float(limits.get('marginused', 0))
col = float(limits.get('collateral', 0))
grcoll = float(limits.get('grcoll', 0))
margin_avail = float(limits.get('marginavailable', limits.get('marginallowed', cash + col)))
free = margin_avail - used

result = {
    'ok': True,
    'timestamp': datetime.now().isoformat(),
    'total_margin_available': margin_avail,
    'used_margin': used,
    'free_margin': free,
    'cash_available': cash,
    'collateral_value': col,
    'gross_collateral': grcoll,
    'account_id': limits.get('actid', 'FT055702'),
}
print(json.dumps(result))
"""
    )

    try:
        output = subprocess.check_output(
            [sys.executable, "-c", script],
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
        data = json.loads(output.strip().split("\n")[-1])
        if not data.get("ok"):
            logger.error("❌ Flattrade margin: %s", data.get("error", "unknown"))
            return False

        ft_limits_file = Path(__file__).parent / "data" / "broker_limits_flattrade.json"
        ft_limits_file.parent.mkdir(parents=True, exist_ok=True)
        ft_limits_file.write_text(json.dumps(data, indent=2))

        logger.info(
            "✅ Flattrade margin: %s (free: %s, used: %s)",
            format_inr(data["total_margin_available"]),
            format_inr(data["free_margin"]),
            format_inr(data["used_margin"]),
        )
        logger.info("   Saved to %s", ft_limits_file)
        return True

    except subprocess.TimeoutExpired:
        logger.error("❌ Flattrade margin: subprocess timed out")
        return False
    except Exception as e:
        logger.error("❌ Flattrade margin error: %s", e)
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

    # ── T17: Telegram alert on daily margin fetch failure ──────────────
    if not all_ok:
        _alert_margin_fetch_failure(results)


def _alert_margin_fetch_failure(results: dict):
    try:
        brahmand_root = Path(__file__).resolve().parent.parent.parent / "brahmand"
        if str(brahmand_root) not in sys.path:
            sys.path.insert(0, str(brahmand_root))
        from notify import send_telegram

        msg_parts = ["⚠️ DAILY MARGIN FETCH FAILED"]
        for broker, ok in results.items():
            msg_parts.append(f"  {broker}: {'OK' if ok else 'FAILED'}")
        msg_parts.append("Trading on stale margin data.")
        send_telegram("\n".join(msg_parts), dedupe_key="margin_fetch_fail")
    except Exception as e:
        logger.warning(f"Telegram alert failed: {e}")


if __name__ == "__main__":
    main()
