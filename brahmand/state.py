"""Pydantic state models for Brahmand architecture."""

from pydantic import BaseModel, Field
from typing import List, Dict, Optional
from datetime import datetime


class BrahmandState(BaseModel):
    """Shared state across all agents. Persists in SQLite."""

    # Portfolio metrics
    portfolio_value: float = Field(default=100000.0, description="Account value in ₹")
    daily_pnl: float = Field(default=0.0, description="Today's realized P&L")
    session_pnl: float = Field(default=0.0, description="Current session's floating P&L")

    # Active positions
    active_trades: List[Dict] = Field(
        default_factory=list,
        description="List of {trade_id, strategy, entry_price, sl, tp, current_pnl}",
    )
    completed_trades: List[Dict] = Field(
        default_factory=list,
        description="Closed trades from today — for PA analysis",
    )

    # Market context
    market_regime: str = Field(default="UNKNOWN", description="SIDEWAYS or TRENDING")
    vix_level: float = Field(default=18.0, description="Current VIX")
    nifty_spot: float = Field(default=24500.0, description="NIFTY spot price")

    # Risk tracking
    margin_available: float = Field(default=200000.0, description="Free margin in ₹")
    margin_used: float = Field(default=0.0, description="Margin currently in use")

    # Lessons from yesterday
    yesterdays_lessons: List[str] = Field(
        default_factory=list,
        description="Key learnings from Post-Mortem — Executor uses these",
    )

    # Metadata
    last_updated: datetime = Field(default_factory=datetime.now)
    session_start: datetime = Field(default_factory=datetime.now)
    agent_active: str = Field(default="", description="Which agent is running now")


class TradeSignal(BaseModel):
    """Universal format for trade decisions."""

    trade_id: str
    instrument: str  # e.g., "NIFTY25MAY24500CE"
    strategy: str  # "IRON_FLY" or "CREDIT_SPREAD"
    legs: List[Dict] = Field(default_factory=list)  # [{action: BUY/SELL, strike, type}]
    entry_price: float
    sl_price: float
    tp_price: float
    lots: int = 1

    # Context
    rationale: str
    confidence: float = Field(ge=0, le=1)
    based_on_lessons: List[str] = Field(default_factory=list)

    # Tracing
    timestamp: datetime = Field(default_factory=datetime.now)
    market_regime: str = "UNKNOWN"
    vix_at_entry: float = 18.0


class TradeReview(BaseModel):
    """Post-Mortem writes these for RAG storage.

    Captures all PA learning dimensions:
    - strategy_success: did Iron Fly/CS work?
    - entry_window_patterns: was this the right entry time?
    - sl_optimization: was SL optimal?
    - vix_thresholds: was VIX in tradeable range?
    - lot_scaling: was position size appropriate?
    """

    # Identifiers & Context
    date: str  # "2026-05-15"
    trade_id: str
    strategy: str  # IRON_FLY, CREDIT_SPREAD
    market_regime: str  # SIDEWAYS, TRENDING

    # Market Context (for query filtering)
    vix_at_entry: float = 18.0  # VIX level when trade entered
    entry_time: str = ""  # "10:35" — for time_window extraction
    entry_window: str = ""  # "10:30-11:00" — computed from entry_time

    # Trade Execution
    entry_price: float
    exit_price: float
    pnl: float
    lots: int = 1

    # Outcomes & Quality
    success: bool  # Profitable or not
    sl_hit: bool = False
    tp_hit: bool = False
    failure_reason: Optional[str] = None

    # PA Learning Dimensions
    # strategy_success: captured by (strategy, market_regime, success)
    strategy_score: Optional[float] = None  # Recommendation confidence

    # entry_window_patterns: captured by (entry_time, entry_window, pnl)
    entry_quality: str = "unknown"  # EXCELLENT, GOOD, FAIR, CRITICAL

    # sl_optimization: captured by (sl, pnl, sl_hit)
    sl_used: float = 3500.0
    optimal_sl: Optional[float] = None
    sl_improvement: Optional[float] = None

    # vix_thresholds: captured by (vix_at_entry, success)
    vix_ceiling: Optional[float] = None  # Recommended max VIX for this strategy

    # lot_scaling: captured by (pnl, lots)
    margin_available: Optional[float] = None
    margin_used: Optional[float] = None
    recommended_lots: Optional[int] = None

    # Narrative
    lesson_learned: str  # What to do next time
    execution_summary: str  # Full context for RAG embedding
