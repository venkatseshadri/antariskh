#!/usr/bin/env python3
"""
Entry Check Daemon — Generate fresh entry signals every 5 minutes during market hours.
"""
import sys
import time
import logging
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from agents.entry.entry_check import check_entry

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")
logger = logging.getLogger("EntryCheckDaemon")


def is_market_open() -> bool:
    t = datetime.now()
    dow = t.weekday()  # 0=Mon, 6=Sun
    hour, min = t.hour, t.minute
    time_min = hour * 100 + min
    return dow <= 4 and 915 <= time_min <= 1530


def main():
    logger.info("Entry check daemon started (9:15-15:30 IST, weekdays)")

    while True:
        if is_market_open():
            try:
                check_entry("NIFTY")
                logger.info("✅ Fresh entry signal generated")
            except Exception as e:
                logger.error(f"Entry check failed: {e}")
        else:
            logger.info("Market closed")
            break

        time.sleep(300)  # 5 minutes


if __name__ == "__main__":
    main()
