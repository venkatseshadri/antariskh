#!/usr/bin/env python3
"""
Event Calendar — hardcoded 2026 event dates.
Blocks trading on high-impact days (RBI, Budget, Elections, NSE holidays).

Phase 1 module per 01-01-PLAN.md Task 1.
"""

from datetime import datetime
from typing import Optional


EVENTS = [
    ("2026-01-26", "Republic Day"),
    ("2026-01-30", "Economic Survey"),
    ("2026-02-01", "Union Budget"),
    ("2026-02-05", "RBI MPC Decision"),
    ("2026-03-14", "Holi"),
    ("2026-03-31", "Annual Closing"),
    ("2026-04-08", "RBI MPC Decision"),
    ("2026-04-14", "Dr Ambedkar Jayanti"),
    ("2026-04-19", "Mahavir Jayanti"),
    ("2026-05-01", "Maharashtra Day"),
    ("2026-05-02", "State Election Results"),
    ("2026-06-04", "RBI MPC Decision"),
    ("2026-08-06", "RBI MPC Decision"),
    ("2026-08-15", "Independence Day"),
    ("2026-09-01", "Ganesh Chaturthi"),
    ("2026-10-01", "RBI MPC Decision"),
    ("2026-10-02", "Gandhi Jayanti"),
    ("2026-10-19", "Diwali"),
    ("2026-11-01", "Kannada Rajyotsava"),
    ("2026-12-03", "RBI MPC Decision"),
    ("2026-12-25", "Christmas"),
]


def is_event_day(check_date: Optional[str] = None) -> bool:
    date_str = check_date or datetime.now().strftime("%Y-%m-%d")
    for event_date, _ in EVENTS:
        if event_date == date_str:
            return True
    return False


def get_event_name(check_date: Optional[str] = None) -> Optional[str]:
    date_str = check_date or datetime.now().strftime("%Y-%m-%d")
    for event_date, name in EVENTS:
        if event_date == date_str:
            return name
    return None
