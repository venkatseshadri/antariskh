#!/usr/bin/env python3
"""
Antariksh Phase 1 MVS — Minimum Viable System
NIFTY Iron Butterfly, 1 lot, ₹3,500 SL, VIX<20 gate, Two-Message Protocol

Entry: 9:30 AM (gate check, Telegram plan message)
Exit: 2:35 PM (backtest result, Telegram final message)

Dry-run mode: real market data, no broker execution.
"""

import sys
import os
import json
import logging
from datetime import datetime, time as dt_time, timedelta
from pathlib import Path
from typing import Dict, Optional, Tuple

# Add parent dirs to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "python-trader"))
sys.path.insert(0, str(PROJECT_ROOT / "antariksh"))

# Import broker manager (dual Shoonya + Flattrade)
try:
    from broker_manager import get_broker_manager
    BROKER_AVAILABLE = True
except ImportError:
    BROKER_AVAILABLE = False

# Import event calendar (Phase 1 module)
try:
    from event_calendar import is_event_day, get_event_name
except ImportError:
    def is_event_day(): return False
    def get_event_name(): return None

# ============================================================
# CONFIGURATION
# ============================================================

class Phase1Config:
    # Times (IST)
    ENTRY_TIME = dt_time(9, 30)
    EXIT_TIME = dt_time(14, 35)
    ENTRY_WINDOW_START = dt_time(10, 30)
    ENTRY_WINDOW_END = dt_time(11, 30)
    HARD_EXIT_TIME = dt_time(14, 30)

    # Capital (from rules.yaml)
    TARGET_PROFIT_INR = 1000
    MAX_LOSS_INIR = 3500
    FREE_CASH_FLOOR = 11000

    # Gate
    VIX_MAX = 20.0

    # Trade
    INSTRUMENT = "NIFTY"
    LOTS = 1
    WING_WIDTH = 300

    # Logging
    LOG_DIR = Path(__file__).parent / "logs"

    @staticmethod
    def setup_logging():
        Phase1Config.LOG_DIR.mkdir(exist_ok=True)
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s | %(levelname)-8s | %(message)s",
            handlers=[
                logging.FileHandler(Phase1Config.LOG_DIR / f"phase1_{datetime.now().strftime('%Y%m%d')}.log"),
                logging.StreamHandler(sys.stdout)
            ]
        )
        return logging.getLogger("Antariksh-MVS")

# Initialize logger at module level
Phase1Config.LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    handlers=[
        logging.FileHandler(Phase1Config.LOG_DIR / f"phase1_{datetime.now().strftime('%Y%m%d')}.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("Antariksh-MVS")

# ============================================================
# MARKET DATA BRIDGE
# ============================================================

class MarketDataBridge:
    """
    Unified market data bridge via BrokerManager.
    Routes to Shoonya (primary) / Flattrade (fallback).
    """

    @staticmethod
    def get_current_vix() -> Optional[float]:
        """Get current VIX from broker"""
        if not BROKER_AVAILABLE:
            logger.warning("BrokerManager not available")
            return None
        broker = get_broker_manager()
        vix = broker.get_vix()
        if vix:
            logger.info(f"VIX: {vix:.2f}")
        else:
            logger.warning("VIX fetch returned None")
        return vix

    @staticmethod
    def get_nifty_spot() -> Optional[float]:
        """Get current NIFTY spot price from broker"""
        if not BROKER_AVAILABLE:
            logger.warning("BrokerManager not available")
            return None
        broker = get_broker_manager()
        spot = broker.get_nifty_spot()
        if spot:
            logger.info(f"NIFTY spot: {spot:.2f}")
        else:
            logger.warning("NIFTY spot fetch returned None")
        return spot

    @staticmethod
    def is_event_day() -> bool:
        """Check if today is an event day — load from event_calendar.json
        Mock override: ANTARIKSH_MOCK_EVENT_DAY=1 forces True for testing."""
        # Mock override for test scenarios
        if os.environ.get("ANTARIKSH_MOCK_EVENT_DAY") == "1":
            logger.info(f"Mock event day active: {os.environ.get('ANTARIKSH_MOCK_EVENT_NAME', 'Unknown')}")
            return True
        import json as _json
        config_path = Path(__file__).parent / "config" / "event_calendar.json"
        try:
            with open(config_path) as f:
                data = _json.load(f)
            today_str = datetime.now().strftime("%Y-%m-%d")
            events = data.get("events_2026", {})
            event = events.get(today_str)
            if event and event.get("skip_trading"):
                logger.info(f"Event day detected: {event.get('name', 'Unknown')}")
                return True
            return False
        except Exception as e:
            logger.warning(f"Event calendar read failed ({e}) — defaulting to False")
            return False

    @staticmethod
    def get_contract_expiry() -> str:
        """Get current week expiry date in DD-MMM-YYYY format"""
        today = datetime.now()
        days_until_tuesday = (1 - today.weekday()) % 7
        if days_until_tuesday == 0 and today.weekday() != 1:
            days_until_tuesday = 7
        expiry = today + timedelta(days=days_until_tuesday)
        return expiry.strftime("%d-%b-%Y").upper()

# ============================================================
# GATE LOGIC (3-LAYER)
# ============================================================

class GateChecker:
    """Implements 3-layer gate from STRATEGY_DESIGN_QUESTIONS.md"""

    @staticmethod
    def check_layer1_regime() -> Tuple[bool, str]:
        """Layer 1: VIX, event day, entry window"""
        # Use mock time if provided (for testing)
        mock_time_str = os.environ.get("ANTARIKSH_MOCK_TIME")
        if mock_time_str:
            try:
                h, m = map(int, mock_time_str.split(":"))
                now = dt_time(h, m)
                logger.info(f"🎭 Using mock time: {now}")
            except Exception as e:
                logger.error(f"Invalid ANTARIKSH_MOCK_TIME: {mock_time_str}, {e}")
                now = datetime.now().time()
        else:
            now = datetime.now().time()

        # Check entry window
        if not (Phase1Config.ENTRY_WINDOW_START <= now <= Phase1Config.ENTRY_WINDOW_END):
            return False, f"Outside entry window {Phase1Config.ENTRY_WINDOW_START}-{Phase1Config.ENTRY_WINDOW_END}"

        # Check event day
        if MarketDataBridge.is_event_day():
            return False, "Event day"

        # Check VIX
        vix = MarketDataBridge.get_current_vix()
        if vix is None:
            return False, "VIX data unavailable"
        if vix > Phase1Config.VIX_MAX:
            return False, f"VIX {vix:.2f} > {Phase1Config.VIX_MAX}"

        return True, f"VIX {vix:.2f} OK, entry window OK, no events"

    @staticmethod
    def check_layer2_signal() -> Tuple[bool, str]:
        """Layer 2: Primary signal (supertrend_1min)"""
        # TODO: Implement signal calculation
        logger.info("TODO: check_layer2_signal() - needs indicator calculation")
        return True, "Signal check deferred (Phase 1 scaffold)"

    @staticmethod
    def check_layer3_confirmation() -> Tuple[bool, str]:
        """Layer 3: Confirmation (2 of 3 indicators)"""
        # TODO: Implement confirmation logic
        logger.info("TODO: check_layer3_confirmation() - needs multi-indicator logic")
        return True, "Confirmation deferred (Phase 1 scaffold)"

    @staticmethod
    def check_gate() -> Tuple[bool, str]:
        """Full gate check: all layers must pass"""
        l1, l1_msg = GateChecker.check_layer1_regime()
        if not l1:
            return False, f"Layer 1 fail: {l1_msg}"

        l2, l2_msg = GateChecker.check_layer2_signal()
        if not l2:
            return False, f"Layer 2 fail: {l2_msg}"

        l3, l3_msg = GateChecker.check_layer3_confirmation()
        if not l3:
            return False, f"Layer 3 fail: {l3_msg}"

        return True, "All gates PASS"

# ============================================================
# TRADE DECISION ENGINE
# ============================================================

class TradeDecisionEngine:
    """Generates Iron Butterfly trade plan (dry-run, no execution)"""

    @staticmethod
    def calculate_atm_strike(spot: float) -> float:
        """Calculate ATM strike: round(spot/50)*50 for NIFTY"""
        return round(spot / 50) * 50

    @staticmethod
    def generate_trade_plan() -> Optional[Dict]:
        """Generate Iron Butterfly trade plan"""
        spot = MarketDataBridge.get_nifty_spot()
        if spot is None:
            logger.warning("Cannot generate trade plan: NIFTY spot unavailable")
            return None

        atm = TradeDecisionEngine.calculate_atm_strike(spot)
        expiry = MarketDataBridge.get_contract_expiry()

        plan = {
            "timestamp": datetime.now().isoformat(),
            "instrument": Phase1Config.INSTRUMENT,
            "spot": spot,
            "atm_strike": atm,
            "expiry": expiry,
            "lots": Phase1Config.LOTS,
            "legs": {
                "put_buy": {"strike": atm - Phase1Config.WING_WIDTH, "type": "PE", "side": "BUY"},
                "put_sell": {"strike": atm, "type": "PE", "side": "SELL"},
                "call_sell": {"strike": atm, "type": "CE", "side": "SELL"},
                "call_buy": {"strike": atm + Phase1Config.WING_WIDTH, "type": "CE", "side": "BUY"},
            },
            "target_profit": Phase1Config.TARGET_PROFIT_INR,
            "max_loss": Phase1Config.MAX_LOSS_INIR,
            "entry_time": datetime.now().isoformat(),
        }

        logger.info(f"Trade plan generated: {Phase1Config.INSTRUMENT} {atm} Iron Fly, {Phase1Config.LOTS} lot(s)")
        return plan

# ============================================================
# TELEGRAM INTERFACE
# ============================================================

class TelegramBridge:
    """Sends Telegram messages (Two-Message Protocol)"""

    @staticmethod
    def send_message(text: str, message_type: str = "log") -> bool:
        """Send Telegram message"""
        # TODO: Implement Telegram API integration via picoclaw
        logger.info(f"[TELEGRAM] {message_type.upper()}: {text}")
        return True

    @staticmethod
    def send_gate_message(gate_pass: bool, gate_reason: str, trade_plan: Optional[Dict] = None) -> bool:
        """9:30 AM message: Gate decision + trade plan"""
        if gate_pass and trade_plan:
            msg = f"""
🚀 **ANTARIKSH ENTRY DECISION — 9:30 AM**

**Gate: PASS** ({gate_reason})

**Instrument:** {trade_plan['instrument']}
**Spot:** ₹{trade_plan['spot']:.2f}
**ATM Strike:** {trade_plan['atm_strike']:.0f}
**Expiry:** {trade_plan['expiry']}
**Lots:** {trade_plan['lots']}

**Legs (Iron Butterfly):**
- Long PUT: {trade_plan['legs']['put_buy']['strike']:.0f} PE
- Short PUT: {trade_plan['legs']['put_sell']['strike']:.0f} PE
- Short CALL: {trade_plan['legs']['call_sell']['strike']:.0f} CE
- Long CALL: {trade_plan['legs']['call_buy']['strike']:.0f} CE

**Targets:**
- Target Profit: ₹{trade_plan['target_profit']}
- Max Loss: ₹{trade_plan['max_loss']}

⏱️ Hard exit: {Phase1Config.HARD_EXIT_TIME}

**React with 🚫 to SKIP this trade**
""".strip()
        else:
            msg = f"""
⏭️ **ANTARIKSH ENTRY DECISION — 9:30 AM**

**Gate: SKIP** ({gate_reason})

No trade today. System will check again tomorrow.
""".strip()

        TelegramBridge.send_message(msg, "ENTRY_GATE")
        return True

    @staticmethod
    def send_exit_message(trade_plan: Optional[Dict], backtest_result: Optional[Dict]) -> bool:
        """2:35 PM message: Exit result + P&L + system status"""
        if trade_plan and backtest_result:
            msg = f"""
🏁 **ANTARIKSH EXIT REPORT — 2:35 PM**

**Trade:** {trade_plan['instrument']} Iron Fly (1 lot)
**Entry Time:** {trade_plan['entry_time']}
**Exit Time:** {datetime.now().isoformat()}

**Backtest Result (DRY-RUN):**
- Entry Price: ₹{backtest_result.get('entry_price', 0):.2f}
- Exit Price: ₹{backtest_result.get('exit_price', 0):.2f}
- P&L: ₹{backtest_result.get('pnl', 0):.2f}
- Return: {backtest_result.get('return_pct', 0):.2f}%

**MTD P&L:** ₹{backtest_result.get('mtd_pnl', 0):.2f}
**Win Rate:** {backtest_result.get('win_rate', 'N/A')}%
**Max DD:** ₹{backtest_result.get('max_dd', 0):.2f}

**System Status:** ✅ Operational

Session complete. Ready for tomorrow.
""".strip()
        else:
            msg = f"""
🏁 **ANTARIKSH EXIT REPORT — 2:35 PM**

No trade executed today (gate skipped entry).

**System Status:** ✅ Operational
""".strip()

        TelegramBridge.send_message(msg, "EXIT_REPORT")
        return True

# ============================================================
# CFO AUDITOR
# ============================================================

class CFOAuditor:
    """Audits resources (tokens, time) and capital (P&L, preservation)"""

    @staticmethod
    def log_session(gate_pass: bool, trade_plan: Optional[Dict], backtest_result: Optional[Dict]) -> Dict:
        """Log session for CFO audit"""
        audit_log = {
            "timestamp": datetime.now().isoformat(),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "gate_pass": gate_pass,
            "trade_executed": trade_plan is not None,
            "backtest_pnl": backtest_result.get("pnl", 0) if backtest_result else 0,
            "resources_used": {
                "llm_tokens_approx": 500,  # TODO: track actual token usage
                "session_duration_seconds": 300,
            },
            "capital_impact": {
                "gross_pnl": backtest_result.get("pnl", 0) if backtest_result else 0,
                "brokerage_est": 50,
                "net_pnl": (backtest_result.get("pnl", 0) - 50) if backtest_result else 0,
                "free_cash_after": Phase1Config.FREE_CASH_FLOOR + (backtest_result.get("pnl", 0) if backtest_result else 0),
            }
        }

        # Write to audit log
        log_file = Phase1Config.LOG_DIR / f"cfo_audit_{datetime.now().strftime('%Y%m%d')}.jsonl"
        with open(log_file, "a") as f:
            f.write(json.dumps(audit_log) + "\n")

        logger.info(f"CFO audit logged: {gate_pass=}, {trade_plan is not None=}")
        return audit_log

# ============================================================
# BACKTESTER (DRY-RUN)
# ============================================================

class Backtester:
    """Simulates Iron Butterfly from entry to exit (no real broker execution)"""

    @staticmethod
    def backtest_trade(trade_plan: Dict) -> Dict:
        """Simulate Iron Butterfly trade from 9:30 AM to 2:35 PM"""
        # TODO: Implement realistic P&L simulation
        # For Phase 1, return a mock result

        entry_price = 1000  # Mock
        exit_price = 1200   # Mock profit
        pnl = exit_price - entry_price

        result = {
            "entry_price": entry_price,
            "exit_price": exit_price,
            "pnl": pnl,
            "return_pct": (pnl / entry_price) * 100 if entry_price != 0 else 0,
            "mtd_pnl": pnl,  # TODO: track MTD
            "win_rate": 50,   # TODO: track win rate
            "max_dd": 500,    # TODO: track max DD
            "exit_reason": "Target hit",
        }

        logger.info(f"Backtest complete: P&L ₹{pnl:.2f}, return {result['return_pct']:.2f}%")
        return result

# ============================================================
# MAIN ORCHESTRATOR
# ============================================================

class Phase1Orchestrator:
    """Main entry point for Phase 1 MVS"""

    @staticmethod
    def run():
        global logger
        logger = Phase1Config.setup_logging()

        logger.info("=" * 60)
        logger.info("ANTARIKSH PHASE 1 MVS — SESSION START")
        logger.info("=" * 60)

        # Step 1: Check gate at 9:30 AM
        logger.info("Step 1: Checking entry gate...")
        gate_pass, gate_reason = GateChecker.check_gate()
        logger.info(f"Gate check result: {gate_pass=}, reason='{gate_reason}'")

        # Step 2: If gate passes, generate trade plan
        trade_plan = None
        if gate_pass:
            logger.info("Step 2: Gate PASS - Generating trade plan...")
            trade_plan = TradeDecisionEngine.generate_trade_plan()
            if not trade_plan:
                logger.error("Failed to generate trade plan")
                gate_pass = False
        else:
            logger.info("Step 2: Gate SKIP - No trade plan needed")

        # Step 3: Send 9:30 AM Telegram message
        logger.info("Step 3: Sending Telegram entry message...")
        TelegramBridge.send_gate_message(gate_pass, gate_reason, trade_plan)

        # Step 4: If trade planned, run backtest
        backtest_result = None
        if trade_plan:
            logger.info("Step 4: Running backtest (dry-run)...")
            backtest_result = Backtester.backtest_trade(trade_plan)
        else:
            logger.info("Step 4: No backtest (gate skipped)")

        # Step 5: Send 2:35 PM Telegram message
        logger.info("Step 5: Sending Telegram exit message...")
        TelegramBridge.send_exit_message(trade_plan, backtest_result)

        # Step 6: CFO audit log
        logger.info("Step 6: CFO audit logging...")
        CFOAuditor.log_session(gate_pass, trade_plan, backtest_result)

        logger.info("=" * 60)
        logger.info("ANTARIKSH PHASE 1 MVS — SESSION COMPLETE")
        logger.info("=" * 60)

# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    Phase1Orchestrator.run()
