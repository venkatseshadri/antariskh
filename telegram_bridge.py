#!/usr/bin/env python3
"""
Telegram Bridge — sends messages to Chairman via picoclaw/Kubera.
Uses picoclaw RPC to relay Telegram messages asynchronously.
"""

import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger("TelegramBridge")

PICOCLAW_SCRIPT = Path("/root/.picoclaw") / "telegram_send.sh"
PICOCLAW_RPC = Path("/root/.picoclaw") / "rpc.py"

class TelegramBridge:
    """Send messages to Telegram via picoclaw"""

    CHAT_ID = "antariksh"  # Telegram group/channel name (picoclaw resolves)

    @staticmethod
    def send(text: str, message_type: str = "log", parse_mode: str = "MarkdownV2") -> bool:
        """
        Send Telegram message via picoclaw.

        Args:
            text: Message body
            message_type: Category (entry_gate, exit_report, alert, etc.)
            parse_mode: Telegram parse mode (MarkdownV2, HTML, plain)

        Returns:
            True if sent successfully, False otherwise
        """
        if not text:
            logger.warning("Empty message, skipping")
            return False

        logger.info(f"[TELEGRAM] {message_type.upper()}: {text[:100]}...")

        # Try picoclaw RPC first (preferred)
        if PICOCLAW_RPC.exists():
            return TelegramBridge._send_via_rpc(text, message_type, parse_mode)

        # Fallback: picoclaw shell script
        if PICOCLAW_SCRIPT.exists():
            return TelegramBridge._send_via_script(text, message_type)

        # Fallback: log to console (no picoclaw available)
        logger.warning("picoclaw not available, logging to console only")
        print(f"\n{'='*70}")
        print(f"[{message_type.upper()}] ANTARIKSH TELEGRAM MESSAGE")
        print(f"{'='*70}")
        print(text)
        print(f"{'='*70}\n")
        return True

    @staticmethod
    def _send_via_rpc(text: str, message_type: str, parse_mode: str) -> bool:
        """Send via picoclaw Python RPC"""
        try:
            payload = {
                "method": "telegram.send",
                "params": {
                    "chat_id": TelegramBridge.CHAT_ID,
                    "text": text,
                    "parse_mode": parse_mode,
                    "metadata": {"source": "antariksh", "type": message_type}
                }
            }

            # Call picoclaw RPC
            result = subprocess.run(
                [sys.executable, str(PICOCLAW_RPC), json.dumps(payload)],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0:
                logger.info(f"✅ Message sent via RPC: {message_type}")
                return True
            else:
                logger.error(f"RPC send failed: {result.stderr[:200]}")
                return False

        except subprocess.TimeoutExpired:
            logger.error("RPC timeout (10s exceeded)")
            return False
        except Exception as e:
            logger.error(f"RPC error: {e}")
            return False

    @staticmethod
    def _send_via_script(text: str, message_type: str) -> bool:
        """Send via picoclaw shell script (legacy)"""
        try:
            result = subprocess.run(
                [str(PICOCLAW_SCRIPT), TelegramBridge.CHAT_ID, text],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0:
                logger.info(f"✅ Message sent via script: {message_type}")
                return True
            else:
                logger.error(f"Script send failed: {result.stderr[:200]}")
                return False

        except subprocess.TimeoutExpired:
            logger.error("Script timeout (10s exceeded)")
            return False
        except Exception as e:
            logger.error(f"Script error: {e}")
            return False

    @staticmethod
    def send_entry_gate(gate_pass: bool, gate_reason: str, trade_plan: Optional[dict] = None) -> bool:
        """Send 9:30 AM entry gate message"""
        if gate_pass and trade_plan:
            msg = f"""🚀 *ANTARIKSH ENTRY — 9:30 AM*

*Gate:* PASS ({gate_reason})

*Instrument:* {trade_plan.get('instrument', 'NIFTY')}
*Spot:* ₹{trade_plan.get('spot', 0):.0f}
*ATM Strike:* {trade_plan.get('atm_strike', 0):.0f}
*Expiry:* {trade_plan.get('expiry', 'N/A')}
*Lots:* {trade_plan.get('lots', 1)}

*Iron Butterfly Legs:*
• Long PUT: {trade_plan.get('atm_strike', 0) - trade_plan.get('wing_width', 300):.0f} PE
• Short PUT: {trade_plan.get('atm_strike', 0)} PE
• Short CALL: {trade_plan.get('atm_strike', 0)} CE
• Long CALL: {trade_plan.get('atm_strike', 0) + trade_plan.get('wing_width', 300):.0f} CE

*Targets:*
• Target Profit: ₹{trade_plan.get('target_profit', 1000)}
• Max Loss: ₹{trade_plan.get('max_loss', 3500)}
• Hard Exit: 14:30

*React with 🚫 to SKIP*
"""
        else:
            msg = f"""⏭️ *ANTARIKSH ENTRY — 9:30 AM*

*Gate:* SKIP ({gate_reason})

No trade today. System ready for tomorrow.
"""

        return TelegramBridge.send(msg, "entry_gate")

    @staticmethod
    def send_exit_report(trade_plan: Optional[dict], backtest_result: Optional[dict]) -> bool:
        """Send 2:35 PM exit report message"""
        if trade_plan and backtest_result:
            pnl = backtest_result.get('pnl_inr', 0)
            return_pct = backtest_result.get('return_pct', 0)
            hit_target = backtest_result.get('hit_target', False)
            hit_sl = backtest_result.get('hit_stoploss', False)

            status_emoji = "✅" if hit_target else "🛑" if hit_sl else "⏱️"

            msg = f"""{status_emoji} *ANTARIKSH EXIT — 2:35 PM*

*Trade:* {trade_plan.get('instrument', 'NIFTY')} Iron Fly \\(1 lot\\)
*Entry:* {trade_plan.get('entry_time', 'N/A')}
*Exit:* {backtest_result.get('exit_spot', 'N/A')} \\(from {trade_plan.get('spot', 'N/A')}\\)

*Backtest Result \\(DRY\\-RUN\\):*
• Entry Price: ₹{backtest_result.get('entry_credit', 0):.0f}
• Exit Price: ₹{backtest_result.get('exit_debit', 0):.0f}
• *P\\&L: ₹{pnl:.0f}*
• Return: {return_pct:.2f}%

*Period Stats:*
• MTD P\\&L: ₹{backtest_result.get('mtd_pnl', 0):.0f}
• Sessions: TBD
• Max DD: ₹0 \\(Phase 1\\)

*System Status:* ✅ Operational

Ready for tomorrow.
"""
        else:
            msg = """🏁 *ANTARIKSH EXIT — 2:35 PM*

No trade executed today \\(gate skipped\\).

*System Status:* ✅ Operational
"""

        return TelegramBridge.send(msg, "exit_report")

# ============================================================
# STANDALONE FUNCTIONS
# ============================================================

def send_message(text: str, message_type: str = "log") -> bool:
    """Send raw message"""
    return TelegramBridge.send(text, message_type)

def send_alert(severity: str, title: str, body: str) -> bool:
    """Send alert (red/yellow/green)"""
    emoji = "🔴" if severity == "critical" else "🟡" if severity == "warning" else "🟢"
    msg = f"{emoji} *{title}*\n\n{body}"
    return TelegramBridge.send(msg, f"alert_{severity}")
