"""Antariksh Notification Layer — pushes reports, alerts, escalations to Chairman.

Wired to TelegramBridge (Phase 1). Called by orchestrator, Ralph Loop,
OM pre-flight, CEO board report, and emergency handlers.
"""

import os
import sys
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))


def _now() -> str:
    return datetime.now(IST).strftime("%H:%M IST")


# ============================================================
# Public API — call these from anywhere
# ============================================================


def push_om_preflight(health_report: dict) -> bool:
    """Push OM pre-flight GO/NOGO report to Chairman."""
    overall = health_report.get("overall", "NOGO")
    emoji = "🟢" if overall == "GO" else "🔴"

    msg = f"{emoji} **Antariksh Pre-Flight — {_now()}**\n{health_report.get('telegram_md', 'No data')}"
    return _send(msg, "om_preflight")


def push_board_report(report: dict) -> bool:
    """Push CEO daily board report to Chairman (16:00 IST)."""
    msg = f"📊 **Antariksh Board Report — {_now()}**\n{report.get('text', 'No data')}"
    return _send(msg, "board_report")


def push_ralph_escalation(crew_name: str, failures: int, details: list) -> bool:
    """Push Ralph Loop PRD escalation alert to Chairman."""
    metric_names = ", ".join(d.get("name", "?") for d in details)
    msg = (
        f"🚨 **RALPH ESCALATION — {crew_name.upper()}** 🚨\n"
        f"{failures} consecutive PRD failures\n"
        f"Metrics: {metric_names}\n"
        f"Time: {_now()}\n"
        f"Action required: Review {crew_name} crew performance"
    )
    return _send(msg, "ralph_escalation")


def push_risk_breach(breach_type: str, detail: str) -> bool:
    """Push immediate risk breach alert (SL hit, capital floor, etc.)."""
    msg = f"⚠️ **RISK BREACH — {breach_type.upper()}** ⚠️\n{detail}\nTime: {_now()}"
    return _send(msg, "risk_breach")


def push_halt_alert(reason: str, triggered_by: str) -> bool:
    """Push trading halt alert (CEO or risk guard initiated)."""
    msg = (
        f"🛑 **TRADING HALTED** 🛑\n"
        f"Reason: {reason}\n"
        f"Triggered by: {triggered_by}\n"
        f"Time: {_now()}"
    )
    return _send(msg, "halt")


def push_info(message: str) -> bool:
    """Push informational message to Chairman."""
    msg = f"ℹ️ [{_now()}] {message}"
    return _send(msg, "info")


# ============================================================
# Internal — send via Telegram bridge
# ============================================================


def _send(message: str, alert_type: str) -> bool:
    """Send message via TelegramBridge. Falls back to Kubera notification queue."""
    sent = False
    try:
        from telegram_bridge import TelegramBridge

        sent = TelegramBridge.send(message, message_type=alert_type)
    except Exception:
        pass

    # Always queue to Kubera's notification file as backup
    # (TelegramBridge may console-log instead of actually sending)
    import json

    queue_path = "/root/.picoclaw/workspace/state/pending_notifications.json"
    try:
        os.makedirs(os.path.dirname(queue_path), exist_ok=True)
        existing = []
        if os.path.exists(queue_path):
            with open(queue_path) as f:
                existing = json.load(f)
        existing.append(
            {
                "type": alert_type,
                "message": message,
                "timestamp": datetime.now(IST).isoformat(),
            }
        )
        with open(queue_path, "w") as f:
            json.dump(existing, f, indent=2)
        logger.info(f"Queued notification for Kubera: {alert_type}")
        return True
    except Exception as e:
        logger.error(f"Notification queue write failed: {e}")
        return sent
