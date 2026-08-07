#!/usr/bin/env python3
"""
Antariksh Mid-Session Health Watchdog
Polls broker connectivity and system health every 15 min during market hours.
Covers NSE/BSE (09:15-15:30) and MCX (09:15-23:30).
Alerts via Telegram when Penguin services are down.
"""

import sys
import time
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.om_tools import (
    network_connectivity_check,
    disk_usage_check,
    data_capture_health,
    penguin_capture_health,
)
from tools.notifications import push_halt_alert, push_info

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | WATCHDOG | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("Watchdog")

IST = timezone(timedelta(hours=5, minutes=30))
POLL_INTERVAL = 900
_last_alert_key = None


def _in_market_hours() -> str | None:
    now = datetime.now(IST)
    h, m = now.hour, now.minute
    t = h * 60 + m
    if 555 <= t <= 930:
        return "NSE_BSE"
    if 555 <= t <= 1410:
        return "MCX"
    return None


while True:
    window = _in_market_hours()
    if window:
        net = network_connectivity_check()
        disk = disk_usage_check()
        data = data_capture_health()
        penguin = penguin_capture_health()

        problems = []
        if not net.get("ok"):
            problems.append(f"network: {net.get('evidence', 'FAIL')}")
        if not disk.get("ok"):
            problems.append(f"disk: {disk.get('evidence', 'FAIL')}")
        if not penguin.get("ok"):
            problems.append(f"penguin: {penguin.get('evidence', 'FAIL')}")

        if problems:
            alert_key = "|".join(problems)
            if alert_key != _last_alert_key:
                msg = f"WATCHDOG [{window}]: " + "; ".join(problems)
                logger.warning(msg)
                try:
                    push_halt_alert(msg, "antariskh_watchdog")
                except Exception as e:
                    logger.error(f"Telegram alert failed: {e}")
                _last_alert_key = alert_key
        else:
            logger.info(
                f"Healthy [{window}] — {penguin.get('active_services', 0)}/7 services, "
                f"{penguin.get('evidence', '')}"
            )
            _last_alert_key = None
    else:
        logger.debug("Outside market hours — sleeping")
        _last_alert_key = None

    time.sleep(POLL_INTERVAL)
