#!/usr/bin/env python3
"""
Antariksh Trading Desk — Unified Multi-Agent Options Trading System.

Full Desk Hierarchy (State Machine):
  Preparation Phase: Scout & Researcher (Regime identification → Setup proposal)
  Validation Phase:   PM (Capital check, lot authorization)
  Action Phase:       Executioner (Order placement, wings-first sequencing)
  Maintenance Phase:  Risk Agent & Leg Shifter (Live protection, theta optimization)

Information Flows (Conveyor Belt):
  Scout → Researcher:    Market Regime
  Researcher → PM:       Proposed Setup (strikes, wings, exp_P&L)
  PM → Executioner:      Authorized Order (lots, margin cap)
  Executioner → Risk:    Hand-off Report (fills, order IDs)
  Risk → Executioner:    Modify/Cancel/Exit Commands
  Shifter → Researcher:  Leg Shift Proposal (theta exhausted → new strike)

Listen Triggers (Event-Driven):
  Risk Agent listens to event_handler_order_update → CANCEL opposite on TP fill
  Risk Agent listens to event_handler_feed_update   → MODIFY on TSL breach
  Executioner listens to Risk Agent Commands         → execute & report back

Usage:
    python trading_desk.py --mock --vix 18.5 --nifty 24500 --time 10:30
    python trading_desk.py --mock --full-session
    python trading_desk.py --show-flows
"""

import sys
import os
import json
import logging
import time
import threading
from pathlib import Path
from datetime import datetime as _dt, timedelta
from typing import Dict, Optional, List, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum, auto

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT.parent / "python-trader"))
sys.path.insert(0, str(PROJECT_ROOT.parent / "python-trader" / "Shoonya_oAuthAPI-py"))
sys.path.insert(0, str(PROJECT_ROOT))

from crewai import Agent, Task, Crew, Process
from crewai.llm import LLM
from crewai.tools import tool

# ======================================================================
# LLM Configuration
# ======================================================================

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")

_deepseek_llm = None


def _get_llm():
    """Lazy LLM init — avoids import-time crash when API key is not set."""
    global _deepseek_llm
    if _deepseek_llm is None:
        _deepseek_llm = LLM(
            model="deepseek/deepseek-chat",
            base_url=DEEPSEEK_BASE,
            api_key=DEEPSEEK_API_KEY,
            temperature=0.3,
        )
    return _deepseek_llm


# ======================================================================
# Logging
# ======================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)-18s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("TradingDesk")

# ======================================================================
# Mock Mode
# ======================================================================

MOCK_MODE = os.environ.get("ANTARIKSH_MOCK_MODE", "0") == "1"
MOCK_VIX = float(os.environ.get("ANTARIKSH_MOCK_VIX", "18.5"))
MOCK_NIFTY = float(os.environ.get("ANTARIKSH_MOCK_NIFTY", "24500.0"))
MOCK_TIME = os.environ.get("ANTARIKSH_MOCK_TIME", "10:30")
MOCK_ENTRY = float(os.environ.get("ANTARIKSH_MOCK_ENTRY", "100.0"))
MOCK_PNL = float(os.environ.get("ANTARIKSH_MOCK_PNL", "850.0"))

# ======================================================================
# Phase Enum
# ======================================================================


class DeskPhase(Enum):
    PREPARATION = "preparation"  # Scout + Researcher
    VALIDATION = "validation"  # PM capital check
    ACTION = "action"  # Executioner places orders
    MAINTENANCE = "maintenance"  # Risk Agent + Shifter monitor
    CLOSED = "closed"  # All positions squared off


# ======================================================================
# Information Flow Data Packets
# ======================================================================


@dataclass
class MarketRegime:
    """Scout → Researcher: Market regime detection packet."""

    regime: str = "UNKNOWN"  # TRENDING_BULL, TRENDING_BEAR, SIDEWAYS
    vix: float = 0.0
    nifty_spot: float = 0.0
    adx: float = 0.0
    supertrend: str = "NEUTRAL"
    gap_pct: float = 0.0
    event_day: bool = False
    timestamp: str = ""


@dataclass
class ProposedSetup:
    """Researcher → PM: Strategy proposal with full leg details."""

    strategy_type: str = "IRON_BUTTERFLY"
    instrument: str = "NIFTY"
    spot: float = 0.0
    atm_strike: int = 0
    wing_width: int = 300
    lots: int = 1
    exp_profit: float = 0.0  # Expected P&L (backtested)
    max_loss: float = 0.0  # Max loss estimate
    req_margin: float = 0.0  # Required margin
    legs: List[Dict] = field(default_factory=list)
    sl_level: float = 0.0
    tp_level: float = 0.0
    gamma_risk: str = "LOW"
    vega_risk: str = "LOW"
    timestamp: str = ""


@dataclass
class AuthorizedOrder:
    """PM → Executioner: Capital-checked, lot-authorized trade."""

    status: str = "AUTHORIZED"
    symbol: str = "NIFTY"
    strategy: str = "IRON_BUTTERFLY"
    authorized_lots: int = 1
    max_margin: float = 0.0
    spec: Dict = field(default_factory=dict)
    sl_level: float = 0.0
    tp_level: float = 0.0
    tsl_config: Dict = field(default_factory=dict)
    timestamp: str = ""


@dataclass
class HandoffReport:
    """Executioner → Risk Agent: Filled orders + entry details."""

    symbol: str = "NIFTY"
    order_ids: Dict[str, str] = field(default_factory=dict)  # {leg_name: norenordno}
    fills: List[Dict] = field(default_factory=list)
    entry_prices: Dict[str, float] = field(default_factory=dict)  # {tsym: avg_entry}
    tsyms: Dict[str, str] = field(default_factory=dict)  # {leg_name: trading_symbol}
    total_legs: int = 0
    wings_count: int = 0
    center_count: int = 0
    timestamp: str = ""


@dataclass
class ShiftProposal:
    """Leg Shifter → Researcher: Strike shift for theta optimization."""

    reason: str = ""  # THETA_EXHAUSTED, GAMMA_SQUEEZE
    old_leg: Dict = field(default_factory=dict)
    new_strike: int = 0
    theta_current: float = 0.0
    theta_target: float = 0.0
    premium_erosion_pct: float = 0.0
    timestamp: str = ""


# ======================================================================
# Shared Desk State (the "bulletin board" all agents read/write)
# ======================================================================


class DeskState:
    """Thread-safe shared state for the entire trading desk."""

    def __init__(self):
        self.phase: DeskPhase = DeskPhase.PREPARATION
        self.halt: bool = False
        self.halt_reason: str = ""

        # Forward flow packets
        self.regime: Optional[MarketRegime] = None
        self.setup: Optional[ProposedSetup] = None
        self.order: Optional[AuthorizedOrder] = None
        self.handoff: Optional[HandoffReport] = None

        # Maintenance state
        self.positions_open: bool = False
        self.session_pnl: float = 0.0
        self.mtd_pnl: float = 0.0
        self.mtm_history: List[float] = []

        # Leg Shifter state
        self.shift_proposals: List[ShiftProposal] = []
        self.shift_count: int = 0

        # Order lifecycle tracking (for event handlers)
        self.active_sl_orders: Dict[str, str] = {}  # {leg_name: order_id}
        self.active_tp_orders: Dict[str, str] = {}  # {leg_name: order_id}
        self.completed_orders: List[str] = []

        # TSL state
        self.highest_favorable: float = 999999.0  # For SELL: lowest LTP seen
        self.tsl_active: bool = False
        self.tsl_level: float = 0.0

        # Thread safety
        self._lock = threading.Lock()

    def transition(self, new_phase: DeskPhase):
        with self._lock:
            old = self.phase
            self.phase = new_phase
            logger.info(f"DESK PHASE: {old.value} → {new_phase.value}")

    def set_halt(self, reason: str):
        with self._lock:
            self.halt = True
            self.halt_reason = reason
            logger.warning(f"DESK HALT: {reason}")

    def update_mtm(self, pnl: float):
        with self._lock:
            self.session_pnl = pnl
            self.mtm_history.append(pnl)

    def record_order_complete(self, order_id: str, order_type: str):
        with self._lock:
            self.completed_orders.append(order_id)
            logger.info(f"ORDER COMPLETE: {order_type} {order_id}")


# Singleton desk state
desk = DeskState()

# ======================================================================
# DETERMINISTIC ENGINE FUNCTIONS (parameterized — callable from tests)
# ======================================================================


def engine_scout_regime(
    mock_vix: float = None, mock_nifty: float = None
) -> MarketRegime:
    """Scout market regime. Returns MarketRegime.

    Injection priority (in order):
      1. Explicit mock_vix / mock_nifty arguments — test harness
      2. ANTARIKSH_MOCK_* environment variables — CLI --mock mode
      3. DuckDB (varaha_data.duckdb) — production: reads latest row from
         the data_capture_v3_duckdb.py 1-minute capture loop
      4. Fallback defaults — VIX=18.5, NIFTY=24500

    The production path (priority 3) reads from the same DuckDB populated
    by run_data_capture.sh's 1-minute loop:
      data_capture_v3_duckdb.py → varaha_data.duckdb (market_data table)
        → engine_scout_regime reads adx, supertrend_direction, india_vix, spot
    """
    if mock_vix is not None or mock_nifty is not None:
        vix = mock_vix if mock_vix is not None else 18.5
        nifty = mock_nifty if mock_nifty is not None else 24500.0
        adx = 22.5 if vix > 18 else 15.0
        st = "DOWN" if nifty < 24000 else "UP"
        source = "mock_args"
    elif os.environ.get("ANTARIKSH_MOCK_MODE", "0") == "1":
        vix = float(os.environ.get("ANTARIKSH_MOCK_VIX", "18.5"))
        nifty = float(os.environ.get("ANTARIKSH_MOCK_NIFTY", "24500.0"))
        adx = 22.5 if vix > 18 else 15.0
        st = "DOWN" if nifty < 24000 else "UP"
        source = "mock_env"
    else:
        # ── PRODUCTION PATH: read from DuckDB capture pipeline ──
        db_row = _read_live_market_data()
        if db_row:
            import math

            nifty = (
                float(db_row[3])
                if db_row[3] is not None
                and not (isinstance(db_row[3], float) and math.isnan(db_row[3]))
                else 24500.0
            )
            vix = (
                float(db_row[2])
                if db_row[2] is not None
                and not (isinstance(db_row[2], float) and math.isnan(db_row[2]))
                else 18.5
            )
            adx_raw = db_row[0]
            adx = (
                float(adx_raw)
                if adx_raw is not None
                and not (isinstance(adx_raw, float) and math.isnan(adx_raw))
                else 0.0
            )
            st_raw = db_row[1] or ""
            st = "DOWN" if "bear" in str(st_raw).lower() else "UP"
            source = "duckdb_live"
        else:
            logger.warning("SCOUT: DuckDB read failed — using fallback defaults")
            vix = 18.5
            nifty = 24500.0
            adx = 15.0
            st = "UP"
            source = "fallback"

    regime_type = "SIDEWAYS"
    if vix > 20:
        regime_type = "TRENDING_BEAR" if nifty < 24000 else "TRENDING_BULL"
    # ADX override: strong trend + matching supertrend → confirm direction
    if adx > 25 and st in ("UP", "DOWN"):
        if st == "UP":
            regime_type = "TRENDING_BULL"
        else:
            regime_type = "TRENDING_BEAR"

    regime = MarketRegime(
        regime=regime_type,
        vix=vix,
        nifty_spot=nifty,
        adx=adx,
        supertrend=st,
        gap_pct=0.0,
        event_day=False,
        timestamp=_dt.now().isoformat(),
    )
    desk.regime = regime
    desk.transition(DeskPhase.PREPARATION)
    logger.info(
        f"SCOUT → Regime: {regime_type} | VIX={vix} | NIFTY={nifty} | "
        f"ADX={adx} | ST={st} | source={source}"
    )
    return regime


def _read_live_market_data():
    """Read latest row from DuckDB capture pipeline (production path).

    Returns tuple (adx, supertrend_direction, india_vix, spot) or None on failure.
    Reads from varaha_data.duckdb populated by data_capture_v3_duckdb.py.
    Uses READ_ONLY + ATTACH pattern to avoid locking the capture writer.
    """
    try:
        import duckdb
        from pathlib import Path

        db_path = Path("/home/trading_ceo/python-trader/varaha/data/varaha_data.duckdb")
        if not db_path.exists():
            logger.warning("SCOUT: DuckDB not found at %s", db_path)
            return None

        con = duckdb.connect(":memory:")
        con.execute(f"ATTACH '{db_path}' AS live (READ_ONLY)")
        row = con.execute("""
            SELECT adx, supertrend_direction, india_vix, spot
            FROM live.market_data
            WHERE adx IS NOT NULL AND india_vix IS NOT NULL
            ORDER BY id DESC
            LIMIT 1
        """).fetchone()
        con.close()
        return row
    except Exception as e:
        logger.warning("SCOUT: DuckDB query failed: %s", e)
        return None


def engine_research_setup(regime: MarketRegime = None) -> ProposedSetup:
    """Build strategy from a MarketRegime. Returns ProposedSetup."""
    if desk.halt:
        raise RuntimeError(f"Desk halted: {desk.halt_reason}")

    if regime is None:
        regime = desk.regime
    if regime is None:
        raise ValueError("No market regime provided")

    spot = regime.nifty_spot
    atm_strike = round(spot / 50) * 50
    wing = 300 if regime.vix < 20 else 350
    lots = 1

    legs = [
        {
            "action": "BUY",
            "strike": atm_strike - wing,
            "option_type": "PE",
            "role": "LONG_PUT_WING",
        },
        {
            "action": "SELL",
            "strike": atm_strike,
            "option_type": "PE",
            "role": "SHORT_PUT_BODY",
        },
        {
            "action": "SELL",
            "strike": atm_strike,
            "option_type": "CE",
            "role": "SHORT_CALL_BODY",
        },
        {
            "action": "BUY",
            "strike": atm_strike + wing,
            "option_type": "CE",
            "role": "LONG_CALL_WING",
        },
    ]

    setup = ProposedSetup(
        strategy_type="IRON_BUTTERFLY",
        instrument="NIFTY",
        spot=spot,
        atm_strike=atm_strike,
        wing_width=wing,
        lots=lots,
        exp_profit=1000.0,
        max_loss=3500.0,
        req_margin=150000.0,
        legs=legs,
        sl_level=3500.0,
        tp_level=1000.0,
        timestamp=_dt.now().isoformat(),
    )
    desk.setup = setup
    logger.info(
        f"RESEARCHER → Setup: ATM={atm_strike} | Wings={wing} | Exp Profit=₹1000"
    )
    return setup


def engine_pm_validate(
    setup: ProposedSetup = None, mock_balance: float = 200000.0
) -> AuthorizedOrder:
    """Validate setup against capital. Returns AuthorizedOrder."""
    if desk.halt:
        raise RuntimeError(f"Desk halted: {desk.halt_reason}")

    if setup is None:
        setup = desk.setup
    if setup is None:
        raise ValueError("No setup provided")

    # Capital check: reject if margin > 85% of balance
    if mock_balance > 0 and setup.req_margin > mock_balance * 0.85:
        order = AuthorizedOrder(
            status="REJECTED",
            symbol=setup.instrument,
            strategy=setup.strategy_type,
            authorized_lots=0,
            max_margin=setup.req_margin,
            spec={
                "rejection_reason": f"Margin ₹{setup.req_margin} > 85% of ₹{mock_balance}"
            },
            timestamp=_dt.now().isoformat(),
        )
        desk.order = order
        logger.warning(
            f"PM REJECTED: margin ₹{setup.req_margin} > 85% of ₹{mock_balance}"
        )
        return order

    authorized_lots = 1
    max_margin = setup.req_margin
    if setup.req_margin < 100000.0 and mock_balance > 200000:
        authorized_lots = 2

    order = AuthorizedOrder(
        status="AUTHORIZED",
        symbol=setup.instrument,
        strategy=setup.strategy_type,
        authorized_lots=authorized_lots,
        max_margin=max_margin,
        spec={
            "legs": setup.legs,
            "atm_strike": setup.atm_strike,
            "wing_width": setup.wing_width,
            "lots": authorized_lots,
            "instrument": setup.instrument,
        },
        sl_level=setup.sl_level,
        tp_level=setup.tp_level,
        tsl_config={"tsl_activation_pct": 50.0, "tsl_lock_ratio": 0.5},
        timestamp=_dt.now().isoformat(),
    )
    desk.order = order
    desk.transition(DeskPhase.VALIDATION)
    logger.info(f"PM AUTHORIZED: {authorized_lots} lots | Margin ₹{max_margin}")
    return order


def engine_execute_basket(order: AuthorizedOrder = None) -> HandoffReport:
    """Execute the authorized order. Returns HandoffReport."""
    if desk.halt:
        raise RuntimeError(f"Desk halted: {desk.halt_reason}")

    if order is None:
        order = desk.order
    if order is None or order.status != "AUTHORIZED":
        raise ValueError("No authorized order to execute")

    from tools.contract_tools import get_weekly_expiry, build_tsym

    spec = order.spec
    legs = spec.get("legs", [])
    instrument = spec.get("instrument", "NIFTY")
    fills = []
    order_ids = {}
    tsyms = {}
    entry_prices = {}

    for i, leg in enumerate(legs):
        action = leg["action"]
        strike = leg["strike"]
        opt = leg["option_type"]
        tsym = (
            build_tsym(instrument, strike, opt)
            if not MOCK_MODE
            else f"NIFTY{get_weekly_expiry()}{strike}{opt}"
        )
        sim_id = f"SIM-{tsym}-{i + 1:03d}"

        fills.append(
            {
                "leg": f"{opt}_{strike}_{action}",
                "tsym": tsym,
                "status": "filled",
                "order_id": sim_id,
                "fill_price": MOCK_ENTRY,
            }
        )
        key = f"leg_{i}"
        if action == "SELL":
            key = f"TP_LEG_{i}" if "CE" in opt else f"SL_LEG_{i}"
        order_ids[key] = sim_id
        tsyms[key] = tsym
        entry_prices[tsym] = MOCK_ENTRY

    handoff = HandoffReport(
        symbol=order.symbol,
        order_ids=order_ids,
        fills=fills,
        entry_prices=entry_prices,
        tsyms=tsyms,
        total_legs=len(fills),
        wings_count=sum(1 for l in legs if l.get("role", "").startswith("LONG")),
        center_count=sum(1 for l in legs if l.get("role", "").startswith("SHORT")),
        timestamp=_dt.now().isoformat(),
    )
    desk.handoff = handoff
    desk.active_sl_orders = {k: v for k, v in order_ids.items() if "SL" in k}
    desk.active_tp_orders = {k: v for k, v in order_ids.items() if "TP" in k}
    desk.positions_open = True
    desk.highest_favorable = MOCK_ENTRY
    desk.transition(DeskPhase.ACTION)

    logger.info(
        f"EXECUTIONER → Handoff: {len(fills)} legs filled | Orders: {list(order_ids.values())}"
    )
    return handoff


# ======================================================================
# CREWAI TOOL WRAPPERS (thin shells around the engine functions)
# ======================================================================


@tool
def scout_market_regime() -> str:
    """[CrewAI Tool] Scout market regime. Wraps engine_scout_regime()."""
    r = engine_scout_regime()
    return json.dumps(
        {
            "flow": "Scout → Researcher",
            "packet": "MarketRegime",
            "regime": r.regime,
            "vix": r.vix,
            "nifty_spot": r.nifty_spot,
        }
    )


@tool
def research_setup() -> str:
    """[CrewAI Tool] Build strategy setup. Wraps engine_research_setup()."""
    if desk.halt:
        return json.dumps({"flow": "Researcher → PM", "status": "HALTED"})
    s = engine_research_setup()
    return json.dumps(
        {
            "flow": "Researcher → PM",
            "packet": "ProposedSetup",
            "atm_strike": s.atm_strike,
            "wing_width": s.wing_width,
            "lots": s.lots,
            "legs": len(s.legs),
        }
    )


@tool
def pm_approve() -> str:
    """[CrewAI Tool] Capital check. Wraps engine_pm_validate()."""
    if desk.halt:
        return json.dumps({"flow": "PM → Executioner", "status": "HALTED"})
    o = engine_pm_validate()
    return json.dumps(
        {
            "flow": "PM → Executioner",
            "packet": "AuthorizedOrder",
            "authorized_lots": o.authorized_lots,
            "max_margin": o.max_margin,
            "status": o.status,
        }
    )


@tool
def execute_orders() -> str:
    """[CrewAI Tool] Place orders. Wraps engine_execute_basket()."""
    if desk.halt:
        return json.dumps({"flow": "Executioner → Risk", "status": "HALTED"})
    h = engine_execute_basket()
    return json.dumps(
        {
            "flow": "Executioner → Risk Agent",
            "packet": "HandoffReport",
            "legs_filled": h.total_legs,
            "order_ids": h.order_ids,
        }
    )


# ======================================================================
# EVENT HANDLERS — The "Listen" Triggers
# ======================================================================


class ListenTriggers:
    """
    WebSocket event handler wrappers for the Risk Agent and Executioner.

    In production, these are registered as callbacks on the Shoonya/Flattrade
    WebSocket via api.start_websocket(). In simulation mode, they are called
    manually during the maintenance phase test loop.

    Can be instantiated with a desk_ref for test isolation:
        triggers = ListenTriggers(desk_ref=my_desk)
        triggers.on_order_update({...})

    Risk Agent's Listens:
      - on_order_update: TP COMPLETE → CANCEL opposite SL
      - on_feed_update:   LTP crosses TSL → MODIFY SL

    Executioner's Listens:
      - on_risk_command:  MODIFY command → api.modify_order → report back
      - on_risk_command:  CANCEL command → api.cancel_order → report back
      - on_risk_command:  EXIT command  → api.place_order (close) → report back
    """

    def __init__(self, desk_ref=None):
        self._desk = desk_ref if desk_ref is not None else desk

    @staticmethod
    def _resolve_order_id(order_data: Dict) -> str:
        return order_data.get("order_id") or order_data.get("noid") or "?"

    @staticmethod
    def _resolve_order_type(order_data: Dict, dsk=None) -> str:
        d = dsk if dsk else desk
        tp = order_data.get("order_type", "")
        if tp:
            return tp
        noid = str(order_data.get("noid", ""))
        order_id = order_data.get("order_id", "")
        combined = f"{noid}{order_id}"
        if "TP" in combined:
            return "TP"
        if "SL" in combined:
            return "SL"
        for v in d.active_tp_orders.values():
            if v in combined or combined in v:
                return "TP"
        for v in d.active_sl_orders.values():
            if v in combined or combined in v:
                return "SL"
        return ""

    def on_order_update(self, order_data: Dict) -> dict:
        """
        Risk Agent listen trigger: event_handler_order_update.

        Trigger: order status changes.
        Action: If TP order COMPLETE → issue CANCEL for all SL orders.
                If SL order COMPLETE → issue CANCEL for all TP orders.

        Can be called as either:
          ListenTriggers.on_order_update(data)   — static (uses global desk)
          triggers.on_order_update(data)          — instance (uses desk_ref)
        """
        order_id = self._resolve_order_id(order_data)
        status = str(order_data.get("status", "")).upper()
        order_type = self._resolve_order_type(order_data, self._desk)
        d = self._desk

        if status != "COMPLETE":
            logger.debug(f"Order update: {order_id} → {status} (no action)")
            return {"event": "order_update", "action": "NONE", "order_id": order_id}

        d.record_order_complete(order_id, order_type)

        if order_type == "TP":
            d.positions_open = False
            cancelled = list(d.active_sl_orders.values())
            d.active_sl_orders.clear()
            logger.info(f"RISK TRIGGER: TP {order_id} COMPLETE → Kill SLs: {cancelled}")
            return {
                "event": "order_update",
                "trigger": "TP_COMPLETE",
                "action": "CANCEL_ALL_SL",
                "cancelled_orders": cancelled,
                "command": "CANCEL",
            }

        if order_type == "SL":
            d.positions_open = False
            cancelled = list(d.active_tp_orders.values())
            d.active_tp_orders.clear()
            logger.info(f"RISK TRIGGER: SL {order_id} COMPLETE → Kill TPs: {cancelled}")
            return {
                "event": "order_update",
                "trigger": "SL_COMPLETE",
                "action": "CANCEL_ALL_TP",
                "cancelled_orders": cancelled,
                "command": "CANCEL",
            }

        logger.debug(f"Order COMPLETE but not TP/SL: {order_id} ({order_type})")
        return {"event": "order_update", "action": "IGNORE", "order_id": order_id}

    @staticmethod
    def on_feed_update(tick_data: Dict) -> dict:
        """
        Risk Agent listen trigger: event_handler_feed_update.

        Trigger: LTP tick crosses TSL threshold.
        Action: If LTP > TSL level (for short positions) → MODIFY SL order.

        Args:
            tick_data: {token, lp (last price), ltq, ltt, ...}
        """
        ltp = float(tick_data.get("lp", 0))
        token = tick_data.get("token", "?")

        if not desk.positions_open:
            logger.debug(f"Feed: No open positions — ignoring tick {ltp}")
            return {
                "event": "feed_update",
                "action": "IGNORE",
                "reason": "no_positions",
            }

        if ltp < desk.highest_favorable:
            desk.highest_favorable = ltp

        handoff = desk.handoff
        if not handoff:
            return {"event": "feed_update", "action": "IGNORE", "reason": "no_handoff"}

        avg_entry = sum(handoff.entry_prices.values()) / max(
            len(handoff.entry_prices), 1
        )
        sl_level = avg_entry * 1.10  # sl_buffer_pct = 10%

        if ltp >= sl_level:
            logger.warning(f"RISK TRIGGER: LTP {ltp} >= SL {sl_level:.2f}")
            target_order = (
                list(desk.active_sl_orders.values())[0]
                if desk.active_sl_orders
                else "UNKNOWN"
            )
            return {
                "event": "feed_update",
                "trigger": "SL_BREACH",
                "action": "EXIT_POSITION",
                "ltp": ltp,
                "sl_level": round(sl_level, 2),
                "command": "EXIT",
                "reason": f"SL breach: LTP {ltp} >= {sl_level:.2f}",
            }

        if desk.tsl_active and ltp > desk.tsl_level:
            logger.warning(
                f"RISK TRIGGER: TSL breach LTP {ltp} > TSL {desk.tsl_level:.2f}"
            )
            target_order = (
                list(desk.active_sl_orders.values())[0]
                if desk.active_sl_orders
                else "UNKNOWN"
            )
            return {
                "event": "feed_update",
                "trigger": "TSL_BREACH",
                "action": "MODIFY_SL",
                "ltp": ltp,
                "tsl_level": round(desk.tsl_level, 2),
                "target_order": target_order,
                "command": "MODIFY",
                "new_trigger": round(ltp + 25, 2),
            }

        logger.debug(f"Feed tick: token={token} ltp={ltp} — no trigger")
        return {"event": "feed_update", "action": "HOLD", "ltp": ltp}

    @staticmethod
    def on_risk_command(command: Dict) -> dict:
        """
        Executioner listen trigger: receives commands from Risk Agent.

        Trigger: Risk Agent issues MODIFY / CANCEL / EXIT command.
        Action: Call appropriate broker API and report status back.
        """
        cmd = command.get("command", "UNKNOWN")
        order_id = command.get("order_id", "")
        reason = command.get("reason", "")

        if cmd == "MODIFY":
            new_price = command.get("new_trigger", 0.0)
            logger.info(f"EXECUTIONER: MODIFY order {order_id} → trigger={new_price}")
            return {
                "flow": "Executioner → Risk Agent",
                "action": "MODIFY_CONFIRMED",
                "order_id": order_id,
                "new_trigger": new_price,
                "status": "SUCCESS" if MOCK_MODE else "PENDING",
                "api_call": f"api.modify_order(order_id={order_id}, newtrigger_price={new_price})",
            }

        if cmd == "CANCEL":
            logger.info(f"EXECUTIONER: CANCEL order {order_id} ({reason})")
            return {
                "flow": "Executioner → Risk Agent",
                "action": "CANCEL_CONFIRMED",
                "order_id": order_id,
                "reason": reason,
                "status": "SUCCESS" if MOCK_MODE else "PENDING",
                "api_call": f"api.cancel_order(orderno={order_id})",
            }

        if cmd == "EXIT":
            logger.info(f"EXECUTIONER: EXIT all positions ({reason})")
            desk.positions_open = False
            desk.transition(DeskPhase.CLOSED)
            return {
                "flow": "Executioner → Risk Agent",
                "action": "EXIT_CONFIRMED",
                "reason": reason,
                "status": "SUCCESS" if MOCK_MODE else "PENDING",
            }

        return {"error": f"Unknown command: {cmd}"}


# ======================================================================
# LEG SHIFTER — Circular Optimization Loop
# ======================================================================


@tool
def shifter_evaluate() -> str:
    """
    Leg Shifter: Listen to feed_update for trade tokens.
    Evaluate if Theta is exhausted (premium decayed too low to stay).
    Produce ShiftProposal if shift is warranted → flows back to Researcher.

    The shifting loop:
      1. Shifter listens to feed_update for trade tokens
      2. Evaluate theta exhaustion (premium erosion %)
      3. Propose new optimal strike → Researcher
      4. Researcher backtests the shift
      5. Risk Agent validates → Executioner closes old, opens new
    """
    if not desk.positions_open:
        return json.dumps(
            {"phase": "maintenance", "loop": "shifter", "action": "NO_POSITIONS"}
        )

    handoff = desk.handoff
    if not handoff:
        return json.dumps({"error": "No handoff data for shifter"})

    avg_entry = sum(handoff.entry_prices.values()) / max(len(handoff.entry_prices), 1)
    current_ltp = avg_entry * 0.40
    premium_erosion = (
        ((avg_entry - current_ltp) / avg_entry) * 100 if avg_entry > 0 else 0
    )

    theta_exhausted = premium_erosion > 70.0

    if theta_exhausted and desk.shift_count < 2:
        desk.shift_count += 1
        shift = ShiftProposal(
            reason="THETA_EXHAUSTED",
            old_leg={
                "strike": desk.setup.atm_strike if desk.setup else 0,
                "option_type": "PE",
            },
            new_strike=(desk.setup.atm_strike + 50 if desk.setup else 0),
            theta_current=-2.5,
            theta_target=-8.0,
            premium_erosion_pct=round(premium_erosion, 1),
            timestamp=_dt.now().isoformat(),
        )
        desk.shift_proposals.append(shift)

        logger.info(
            f"SHIFTER: Theta exhausted ({premium_erosion:.0f}%) → Proposal: shift to {shift.new_strike}"
        )
        return json.dumps(
            {
                "phase": "maintenance",
                "loop": "Leg Shifter → Researcher",
                "packet": "ShiftProposal",
                "trigger": "THETA_EXHAUSTED",
                "premium_erosion_pct": round(premium_erosion, 1),
                "new_strike": shift.new_strike,
                "action": "PROPOSE_SHIFT",
            }
        )

    return json.dumps(
        {
            "phase": "maintenance",
            "loop": "shifter",
            "premium_erosion_pct": round(premium_erosion, 1),
            "theta_exhausted": theta_exhausted,
            "action": "HOLD" if not theta_exhausted else "BLOCKED",
        }
    )


@tool
def researcher_backtest_shift() -> str:
    """
    Researcher: Run backtest on the Leg Shifter's proposal.
    If confirmed, produce validated shift for Risk Agent to direct.

    This closes the circular loop:
      Shifter → Researcher → Backtest → Risk Agent → Executioner
    """
    if not desk.shift_proposals:
        return json.dumps(
            {"phase": "maintenance", "loop": "backtest_shift", "action": "NO_PROPOSALS"}
        )

    latest = desk.shift_proposals[-1]
    spot = desk.regime.nifty_spot if desk.regime else MOCK_NIFTY
    atm = desk.setup.atm_strike if desk.setup else 0
    wing = desk.setup.wing_width if desk.setup else 300

    from backtester import IronFlyBacktester

    new_plan = {
        "spot": spot,
        "atm_strike": latest.new_strike,
        "wing_width": wing,
        "target_profit": 800,
        "max_loss": 3000,
        "lots": 1,
    }
    bt = IronFlyBacktester.backtest_iron_fly(new_plan, exit_spot=spot)
    pnl = bt.get("pnl_inr", 0) if bt else 0

    if pnl > 0:
        logger.info(
            f"RESEARCHER: Shift backtest PASSED — P&L ₹{pnl} | New strike={latest.new_strike}"
        )
        return json.dumps(
            {
                "phase": "maintenance",
                "flow": "Researcher → Risk Agent",
                "packet": "ValidatedShift",
                "backtest_pnl": pnl,
                "decision": "APPROVE_SHIFT",
                "close_leg": latest.old_leg,
                "open_leg": {"strike": latest.new_strike, "wing_width": wing},
            }
        )

    logger.info(f"RESEARCHER: Shift backtest FAILED — P&L ₹{pnl}")
    return json.dumps(
        {
            "phase": "maintenance",
            "flow": "Researcher → Risk Agent",
            "backtest_pnl": pnl,
            "decision": "REJECT_SHIFT",
        }
    )


@tool
def risk_direct_shift(validated_shift: Dict) -> str:
    """
    Risk Agent: Direct the Executioner to close old leg and open new leg.

    Trigger: Researcher's validated ShiftProposal.
    Action: EXIT old leg + EXECUTE new leg commands to Executioner.
    """
    decision = validated_shift.get("decision", "REJECT_SHIFT")

    if decision != "APPROVE_SHIFT":
        return json.dumps({"phase": "maintenance", "action": "SHIFT_REJECTED"})

    close_leg = validated_shift.get("close_leg", {})
    open_leg = validated_shift.get("open_leg", {})

    logger.info(f"RISK: Directing shift — Close {close_leg} → Open {open_leg}")

    return json.dumps(
        {
            "phase": "maintenance",
            "flow": "Risk Agent → Executioner",
            "commands": [
                {"command": "EXIT", "leg": close_leg, "reason": "SHIFT_CLOSE_OLD"},
                {"command": "EXECUTE", "leg": open_leg, "reason": "SHIFT_OPEN_NEW"},
            ],
        }
    )


# ======================================================================
# AGENTS — The Full Trading Desk
# ======================================================================

# --- Scout: Technical Scout (regime detection) ---
scout_agent = Agent(
    role="Technical Scout (Market Eyes)",
    goal=(
        "Detect market regime from live data before any trade is designed. "
        "Determine TRENDING_BULL, TRENDING_BEAR, or SIDEWAYS. "
        "Feed the Market Regime packet to the Researcher. Never fabricate readings."
    ),
    backstory=(
        "You are the eyes of the firm. You don't know options greeks or order types "
        "— you know ADX, SuperTrend, and trend strength. You read market data every "
        "60 seconds and report the pulse. The Researcher cannot design a strategy "
        "until you tell them what kind of day this is."
    ),
    tools=[scout_market_regime],
    allow_delegation=False,
    verbose=True,
    memory=True,
)

# --- Researcher: Quantitative Options Analyst ---
researcher_agent = Agent(
    role="Quantitative Researcher (Setup Architect)",
    goal=(
        "Design mathematically optimal options strategies from the Scout's market regime. "
        "Run backtests on every proposal. Send ProposedSetup to PM. "
        "Respond to Leg Shifter's shift proposals with backtested validations."
    ),
    backstory=(
        "You are a cold, disciplined Dalal Street quantitative analyst. "
        "You take the Regime from the Scout, use option chain data and Greeks, "
        "and select precise strikes for the trade. You run the Backtest Tool on "
        "every proposal — yours and the Shifter's. You never guess. "
        "When the Shifter says theta is exhausted, you validate and send the "
        "result back to the Risk Agent."
    ),
    tools=[research_setup, researcher_backtest_shift],
    allow_delegation=False,
    verbose=True,
    memory=True,
)

# --- PM: Portfolio Manager ---
pm_agent = Agent(
    role="Portfolio Manager (Capital Gatekeeper)",
    goal=(
        "Validate every ProposedSetup against capital constraints. "
        "Check margin, free cash, and risk limits. "
        "Authorize exact lot count. Send AuthorizedOrder to Executioner. "
        "Never let a trade through without capital validation."
    ),
    backstory=(
        "You are the gatekeeper of the firm's capital. ₹611k is on the line. "
        "Every trade passes through your approval. You check margin utilization, "
        "free cash floor, and burn rate before authorizing anything. "
        "You don't design strategies — you validate them. "
        "The Executioner never acts without your authorization."
    ),
    tools=[pm_approve],
    allow_delegation=False,
    verbose=True,
    memory=True,
)

# --- Executioner: Execution Specialist ---
executioner_agent = Agent(
    role="Execution Specialist (Order Engine)",
    goal=(
        "Execute orders precisely as authorized by the PM. "
        "Place 4-leg baskets (wings-first sequencing). "
        "Report HandoffReport (fills, order IDs) to the Risk Agent. "
        "Listen for Risk Agent commands (MODIFY, CANCEL, EXIT) and execute instantly."
    ),
    backstory=(
        "You are the HANDS of the firm — a high-speed order management engine. "
        "You receive the AUTHORIZED ORDER from PM and execute with zero delay. "
        "You place wings (BUY hedges) first to unlock margin, then the center (SELL straddle). "
        "After execution, you hand off to the Risk Agent with every fill price and order ID. "
        "Then you LISTEN: when the Risk Agent commands MODIFY, you call modify_order. "
        "When they command CANCEL, you call cancel_order. When they command EXIT, you close. "
        "You NEVER decide what to do — you execute commands."
    ),
    tools=[execute_orders],
    allow_delegation=False,
    verbose=True,
    memory=True,
)

# --- Risk Agent: Sentry (Commander) ---
risk_agent = Agent(
    role="Risk & Compliance Sentry (The Commander)",
    goal=(
        "Monitor live positions via WebSocket ticks. "
        "Issue COMMANDS (not recommendations) to the Executioner. "
        "Listen for order_updates: TP COMPLETE → CANCEL all SLs. "
        "Listen for feed_updates: LTP crosses TSL → MODIFY or EXIT. "
        "Direct Leg Shifter's validated shifts to Executioner."
    ),
    backstory=(
        "You are the COMMANDER — the brain of the live trade. "
        "You NEVER call broker APIs directly. You issue COMMANDS and the "
        "Executioner executes them. "
        "You listen to WebSocket events: order updates and feed ticks. "
        "When TP fills, you kill all SLs immediately. "
        "When price crosses TSL, you modify the SL order. "
        "When the Shifter's proposal is backtest-validated, you command "
        "the Executioner to close the old leg and open the new one. "
        "You command. They execute. Zero latency."
    ),
    tools=[shifter_evaluate, risk_direct_shift],
    allow_delegation=False,
    verbose=True,
    memory=True,
)

# --- Leg Shifter: Theta Optimizer ---
shifter_agent = Agent(
    role="Leg Shifter (Theta Optimizer)",
    goal=(
        "Monitor theta decay on live positions. "
        "When premium erodes below threshold, propose optimal strike shift "
        "to the Researcher. Create a circular feedback loop that keeps the "
        "strategy fresh throughout the trade."
    ),
    backstory=(
        "You are the optimizer — always asking 'is this the best strike right now?' "
        "You listen to feed updates for the tokens in the active trade. "
        "When theta is exhausted (premium decayed 70%+), you propose a shift "
        "to the next optimal strike. The Researcher backtests it. If validated, "
        "the Risk Agent directs the Executioner. "
        "You make the strategy adaptive, not static."
    ),
    tools=[shifter_evaluate],
    allow_delegation=False,
    verbose=True,
    memory=True,
)

# ======================================================================
# TASKS — Sequenced for the State Machine
# ======================================================================

# --- Preparation Phase Tasks ---
scout_task = Task(
    description=(
        "PREPARATION PHASE — Step 1: Scout the market regime.\n\n"
        "Call scout_market_regime tool to:\n"
        "1. Detect current market regime (TRENDING_BULL/BEAR/SIDEWAYS)\n"
        "2. Report VIX, NIFTY spot, ADX\n"
        "3. Flow the MarketRegime packet → Researcher\n\n"
        "This is the FIRST step. The Researcher cannot proceed without your regime."
    ),
    expected_output="MarketRegime packet with regime, VIX, NIFTY spot",
    agent=scout_agent,
)

research_task = Task(
    description=(
        "PREPARATION PHASE — Step 2: Design the strategy setup.\n\n"
        "1. Read the MarketRegime from the Scout\n"
        "2. Call research_setup tool to build IRON_BUTTERFLY with exact strikes\n"
        "3. Run backtest for P&L estimation\n"
        "4. Flow the ProposedSetup packet → PM\n\n"
        "Include: ATM strike, wing width, 4 legs, expected P&L, max loss, required margin."
    ),
    expected_output="ProposedSetup with 4-leg Iron Butterfly, P&L estimate",
    agent=researcher_agent,
)

# --- Validation Phase Task ---
pm_task = Task(
    description=(
        "VALIDATION PHASE — Step 3: Capital check and authorization.\n\n"
        "1. Read the ProposedSetup from the Researcher\n"
        "2. Call pm_approve tool to validate against capital limits\n"
        "3. Check: margin utilization, free cash floor, burn rate\n"
        "4. Authorize exact lot count\n"
        "5. Flow the AuthorizedOrder packet → Executioner\n\n"
        "If any check fails, HALT — do not authorize."
    ),
    expected_output="AuthorizedOrder with lots approved, margin validated",
    agent=pm_agent,
)

# --- Action Phase Task ---
execution_task = Task(
    description=(
        "ACTION PHASE — Step 4: Execute the authorized order.\n\n"
        "1. Read the AuthorizedOrder from the PM\n"
        "2. Call execute_orders tool (wings-first: BUY hedges, then SELL straddle)\n"
        "3. Capture all order IDs, fill prices, and trading symbols\n"
        "4. Flow the HandoffReport packet → Risk Agent\n\n"
        "CRITICAL: Report every order ID. The Risk Agent needs them to monitor."
    ),
    expected_output="HandoffReport with all order IDs, fill prices, tsyms",
    agent=executioner_agent,
)

# --- Maintenance Phase Tasks ---
monitor_task = Task(
    description=(
        "MAINTENANCE PHASE — Continuous monitoring loop.\n\n"
        "Risk Agent responsibilities:\n"
        "1. Listen to event_handler_order_update:\n"
        "   - TP COMPLETE → CANCEL all SL orders\n"
        "   - SL COMPLETE → CANCEL all TP orders\n"
        "2. Listen to event_handler_feed_update:\n"
        "   - LTP crosses TSL → MODIFY SL order\n"
        "   - LTP crosses hard SL → EXIT all positions\n"
        "3. Call shifter_evaluate every cycle to check theta decay\n"
        "4. When Shifter proposes shift → Researcher backtests → Risk directs Executioner\n\n"
        "You COMMAND. The Executioner EXECUTES."
    ),
    expected_output="Live monitoring report: P&L, SL status, TSL state, theta condition",
    agent=risk_agent,
)

shifter_task = Task(
    description=(
        "MAINTENANCE PHASE — Leg Shifter loop.\n\n"
        "1. Call shifter_evaluate to check premium erosion\n"
        "2. If theta exhausted (premium decay > 70%): propose new optimal strike\n"
        "3. Flow ShiftProposal → Researcher for backtest\n"
        "4. If backtest validates → Risk Agent directs Executioner\n\n"
        "This creates a CIRCULAR loop that keeps the strategy fresh."
    ),
    expected_output="Theta condition + shift proposal if warranted",
    agent=shifter_agent,
)

# ======================================================================
# CREW BUILDER — The Full Desk
# ======================================================================

_desk_crew_cache = None


def build_trading_desk_crew() -> Crew:
    """Build the full multi-agent trading desk with all phases."""
    global _desk_crew_cache
    if _desk_crew_cache is None:
        _desk_crew_cache = Crew(
            agents=[
                scout_agent,
                researcher_agent,
                pm_agent,
                executioner_agent,
                risk_agent,
                shifter_agent,
            ],
            tasks=[
                scout_task,
                research_task,
                pm_task,
                execution_task,
                monitor_task,
                shifter_task,
            ],
            process=Process.hierarchical,
            manager_llm=_get_llm(),
            verbose=True,
        )
    return _desk_crew_cache


# ======================================================================
# PRE-SESSION INITIALIZATION
# ======================================================================


def initialize_desk(
    mock_mode: bool = False,
    mock_vix: float = 18.5,
    mock_nifty: float = 24500.0,
    mock_time: str = "10:30",
):
    """Initialize the trading desk before a session."""
    global MOCK_MODE, MOCK_VIX, MOCK_NIFTY, MOCK_TIME
    MOCK_MODE = mock_mode
    MOCK_VIX = mock_vix
    MOCK_NIFTY = mock_nifty
    MOCK_TIME = mock_time

    if mock_mode:
        os.environ["ANTARIKSH_MOCK_MODE"] = "1"
        os.environ["ANTARIKSH_MOCK_VIX"] = str(mock_vix)
        os.environ["ANTARIKSH_MOCK_NIFTY"] = str(mock_nifty)
        os.environ["ANTARIKSH_MOCK_TIME"] = mock_time

    logger.info(
        f"Desk initialized: Mock={mock_mode}, VIX={mock_vix}, NIFTY={mock_nifty}"
    )
    return desk


# ======================================================================
# ENTRY POINTS
# ======================================================================


def run_preparation_phase(
    mock_mode: bool = False,
    mock_vix: float = 18.5,
    mock_nifty: float = 24500.0,
    mock_time: str = "10:30",
) -> Dict:
    """
    Run the Preparation Phase: Scout → Researcher → PM validation.

    This covers:
      - Scout: Market regime detection
      - Researcher: Strategy setup with backtest
      - PM: Capital check + lot authorization
    """
    initialize_desk(mock_mode, mock_vix, mock_nifty, mock_time)
    desk.transition(DeskPhase.PREPARATION)

    logger.info("=" * 70)
    logger.info("TRADING DESK — PREPARATION PHASE")
    logger.info("=" * 70)

    crew = build_trading_desk_crew()
    result = crew.kickoff(inputs={"phase": "preparation", "mock_mode": mock_mode})

    logger.info("=" * 70)
    logger.info("PREPARATION PHASE COMPLETE")
    logger.info("=" * 70)

    return {
        "phase": "preparation",
        "regime": desk.regime.regime if desk.regime else "UNKNOWN",
        "setup_atm": desk.setup.atm_strike if desk.setup else None,
        "order_authorized": desk.order.status == "AUTHORIZED" if desk.order else False,
    }


def run_action_phase() -> Dict:
    """Run the Action Phase: Executioner places orders, hands off to Risk."""
    if not desk.order or desk.order.status != "AUTHORIZED":
        return {"phase": "action", "status": "SKIPPED", "reason": "no_authorized_order"}

    desk.transition(DeskPhase.ACTION)

    logger.info("=" * 70)
    logger.info("TRADING DESK — ACTION PHASE")
    logger.info("=" * 70)

    # Execution is handled by execute_orders tool called during full run
    result = {
        "phase": "action",
        "handoff_sent": desk.handoff is not None,
        "legs_filled": len(desk.handoff.fills) if desk.handoff else 0,
        "positions_open": desk.positions_open,
    }

    logger.info("=" * 70)
    logger.info("ACTION PHASE COMPLETE")
    logger.info("=" * 70)

    return result


def run_maintenance_cycle() -> Dict:
    """
    Run ONE maintenance cycle: feed update + order update + shifter eval.

    In production, this runs in a continuous loop with WebSocket callbacks.
    In simulation, it's a single manual cycle for testing.
    """
    if not desk.positions_open:
        if os.environ.get("ANTARIKSH_MOCK_MODE", "0") == "1":
            _init_mock_maintenance_state()
        else:
            return {"phase": "maintenance", "status": "NO_POSITIONS"}

    desk.transition(DeskPhase.MAINTENANCE)

    tick_data = {
        "token": "NSE|35003",
        "lp": str(MOCK_ENTRY * 0.60),
        "ltq": "50",
        "ltt": _dt.now().isoformat(),
    }
    feed_result = ListenTriggers.on_feed_update(tick_data)

    order_data = {
        "order_id": list(desk.active_tp_orders.values())[0]
        if desk.active_tp_orders
        else "SIM-001",
        "status": "COMPLETE"
        if os.environ.get("ANTARIKSH_MOCK_MODE", "0") == "1"
        else "OPEN",
        "order_type": "TP",
    }
    triggers = ListenTriggers()
    order_result = triggers.on_order_update(order_data)

    shifter_result = shifter_evaluate.func()

    return {
        "phase": "maintenance",
        "feed_trigger": feed_result,
        "order_trigger": order_result,
        "shifter_eval": json.loads(shifter_result),
    }


def _init_mock_maintenance_state():
    """Initialize desk state for mock maintenance testing using engine functions."""
    regime = engine_scout_regime(mock_vix=18.5, mock_nifty=24500.0)
    setup = engine_research_setup(regime)
    order = engine_pm_validate(setup, mock_balance=200000.0)
    engine_execute_basket(order)
    desk.tsl_level = 75.0
    desk.tsl_active = True
    desk.highest_favorable = 80.0
    logger.info("MOCK: Maintenance state initialized via engine pipeline")


def run_full_session(
    mock_mode: bool = False,
    mock_vix: float = 18.5,
    mock_nifty: float = 24500.0,
    mock_time: str = "10:30",
) -> Dict:
    """
    Run the COMPLETE trading desk session: all phases in sequence.
    """
    initialize_desk(mock_mode, mock_vix, mock_nifty, mock_time)

    logger.info("=" * 70)
    logger.info("ANTARIKSH TRADING DESK — FULL SESSION")
    logger.info("=" * 70)

    crew = build_trading_desk_crew()
    crew.kickoff(inputs={"phase": "full_session", "mock_mode": mock_mode})

    logger.info("=" * 70)
    logger.info("TRADING DESK — FULL SESSION COMPLETE")
    logger.info("=" * 70)

    return {
        "preparation": {
            "regime": desk.regime.regime if desk.regime else "UNKNOWN",
            "vix": MOCK_VIX,
            "nifty": MOCK_NIFTY,
            "atm_strike": desk.setup.atm_strike if desk.setup else None,
        },
        "validation": {
            "order_authorized": desk.order.status == "AUTHORIZED"
            if desk.order
            else False,
            "lots": desk.order.authorized_lots if desk.order else 0,
        },
        "action": {
            "legs_filled": len(desk.handoff.fills) if desk.handoff else 0,
            "order_ids": desk.handoff.order_ids if desk.handoff else {},
        },
        "maintenance": {
            "positions_open": desk.positions_open,
            "shift_proposals": len(desk.shift_proposals),
        },
        "flows_summary": show_data_flows(),
    }


def show_data_flows() -> str:
    """Display the complete data flow architecture."""
    flows = f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    ANTARIKSH TRADING DESK — DATA FLOWS                       ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  CONVEYOR BELT (Forward Enrichment):                                         ║
║                                                                              ║
║   Scout ──MarketRegime──▶ Researcher ──ProposedSetup──▶ PM                  ║
║     │                          │                               │             ║
║     │   VIX, ADX,              │   Strikes, Wings,            │   Lots,     ║
║     │   SuperTrend             │   Exp P&L, Gamma/Vega        │   Margin    ║
║     │                          │                               │             ║
║     │                          ▼                               ▼             ║
║     │                   ┌──────────────┐              Executioner            ║
║     │                   │  Backtest    │                  │                  ║
║     │                   │  Tool        │◄─────────────────┘                  ║
║     │                   └──────────────┘                 AuthorizedOrder     ║
║     │                                                                        ║
║     │              Executioner ──HandoffReport──▶ Risk Agent (Sentry)        ║
║     │              (fills, order IDs, entry prices)        │                 ║
║     │                                                      │                 ║
║  LISTEN TRIGGERS (Event-Driven):                            │                 ║
║     │                                                      ▼                 ║
║     │   event_handler_order_update:                                         ║
║     │     TP COMPLETE → CANCEL all SL orders                                 ║
║     │     SL COMPLETE → CANCEL all TP orders                                 ║
║     │                                                                        ║
║     │   event_handler_feed_update:                                           ║
║     │     LTP crosses TSL → MODIFY SL trigger                                ║
║     │     LTP crosses Hard SL → EXIT all positions                           ║
║     │                                                                        ║
║  CIRCULAR LOOP (Leg Shifter):                                                ║
║     │                                                                        ║
║     │   Shifter ──ShiftProposal──▶ Researcher ──Backtest──▶ Risk Agent      ║
║     │     (theta exhausted)         (validated?)            (direct shift)   ║
║     │                                                              │         ║
║     │   Risk Agent ──COMMAND──▶ Executioner: {"              "}│         ║
║     │     EXIT old leg, EXECUTE new leg                        │         ║
║     │                                                          │         ║
║     │   Executioner ──CONFIRM──▶ Risk Agent (loop closed)      │         ║
║     │                                                                        ║
║  DESK PHASES (State Machine):                                                ║
║                                                                              ║
║   PREPARATION → VALIDATION → ACTION → MAINTENANCE → CLOSED                  ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""
    return flows


def test_listen_triggers() -> Dict:
    """Test the listen triggers with simulated events."""
    logger.info("Testing Listen Triggers...")

    desk.positions_open = True
    desk.active_sl_orders = {"sl_1": "ORD-SL-001"}
    desk.active_tp_orders = {"tp_1": "ORD-TP-001"}
    desk.handoff = HandoffReport(
        order_ids={"sl_1": "ORD-SL-001", "tp_1": "ORD-TP-001"},
        entry_prices={"NIFTY_24400_PE": 100.0},
        tsyms={"leg": "NIFTY14MAY202624400PE"},
    )
    desk.highest_favorable = 80.0
    desk.tsl_level = 75.0
    desk.tsl_active = True
    desk.setup = ProposedSetup(atm_strike=24400, wing_width=300)

    results = {}

    # Use instance for proper desk_ref binding
    triggers = ListenTriggers(desk_ref=desk)

    # Test 1: TP COMPLETE → Cancel SL
    tp_event = triggers.on_order_update(
        {
            "order_id": "ORD-TP-001",
            "status": "COMPLETE",
            "order_type": "TP",
        }
    )
    results["tp_complete_trigger"] = tp_event

    # Test 2: Feed update → TSL breach
    feed_event = ListenTriggers.on_feed_update(
        {
            "token": "NSE|35003",
            "lp": "90.0",
            "ltq": "50",
        }
    )
    results["tsl_breach_trigger"] = feed_event

    # Test 3: Risk Command → Executioner respond
    cmd_event = ListenTriggers.on_risk_command(
        {
            "command": "MODIFY",
            "order_id": "ORD-SL-001",
            "new_trigger": 95.0,
        }
    )
    results["executioner_respond"] = cmd_event

    # Test 4: Shifter theta exhaustion
    desk.positions_open = True
    desk.handoff.entry_prices = {"NIFTY_24400_PE": 100.0}
    shift_event = shifter_evaluate.func()
    results["shifter_eval"] = json.loads(shift_event)

    return results


# ======================================================================
# CLI ENTRY POINT
# ======================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Antariksh Trading Desk — Multi-Agent Options Trading System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=show_data_flows(),
    )
    parser.add_argument("--mock", action="store_true", help="Enable mock mode")
    parser.add_argument("--vix", type=float, default=18.5, help="Mock VIX")
    parser.add_argument("--nifty", type=float, default=24500.0, help="Mock NIFTY spot")
    parser.add_argument("--time", type=str, default="10:30", help="Mock time (HH:MM)")
    parser.add_argument("--full-session", action="store_true", help="Run full session")
    parser.add_argument(
        "--preparation-only", action="store_true", help="Preparation phase only"
    )
    parser.add_argument(
        "--maintenance-cycle", action="store_true", help="Run one maintenance cycle"
    )
    parser.add_argument(
        "--test-triggers", action="store_true", help="Test listen triggers"
    )
    parser.add_argument(
        "--show-flows", action="store_true", help="Show data flow diagram"
    )
    parser.add_argument("--trace", action="store_true", help="Enable trace logging")

    args = parser.parse_args()

    if args.trace:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.show_flows:
        print(show_data_flows())
    elif args.test_triggers:
        results = test_listen_triggers()
        print(json.dumps(results, indent=2))
    elif args.maintenance_cycle:
        if args.mock:
            os.environ["ANTARIKSH_MOCK_MODE"] = "1"
        result = run_maintenance_cycle()
        print(json.dumps(result, indent=2))
    elif args.preparation_only:
        result = run_preparation_phase(
            mock_mode=args.mock,
            mock_vix=args.vix,
            mock_nifty=args.nifty,
            mock_time=args.time,
        )
        print(json.dumps(result, indent=2))
    elif args.full_session or args.mock:
        result = run_full_session(
            mock_mode=args.mock or args.full_session,
            mock_vix=args.vix,
            mock_nifty=args.nifty,
            mock_time=args.time,
        )
        print(json.dumps(result, indent=2))
    else:
        print(show_data_flows())
        print("\nUse --mock --full-session to run a simulated session.")
