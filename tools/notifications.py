"""Antariksh Notification Layer — pushes reports, alerts, escalations to Chairman.

Sends directly via Telegram Bot API (token from Picoclaw .security.yml).
"""

import os
import sys
import logging
from datetime import datetime, timezone, timedelta

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
    """Send message via Telegram Bot API directly — bypasses Picoclaw."""
    import yaml
    import requests

    chat_id = "8317944043"
    security_path = "/root/.picoclaw/.security.yml"

    try:
        if os.path.exists(security_path):
            with open(security_path) as f:
                security = yaml.safe_load(f)
            token = (
                security.get("channel_list", {})
                .get("telegram", {})
                .get("settings", {})
                .get("token", "")
            )
        else:
            token = os.environ.get("TELEGRAM_BOT_TOKEN", "")

        if not token:
            logger.warning("No Telegram bot token found")
            return False

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "Markdown",
            },
            timeout=10,
        )

        if resp.ok:
            logger.info(f"Telegram sent: {alert_type} ({len(message)} chars)")
            return True
        else:
            logger.error(f"Telegram API error: {resp.status_code} {resp.text}")
            return False

    except Exception as e:
        logger.error(f"Telegram send failed: {e}")
        return False
