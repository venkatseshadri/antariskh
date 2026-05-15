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
    """Post-Mortem writes these for RAG storage."""

    date: str  # "2026-05-15"
    trade_id: str
    strategy: str
    market_regime: str

    # Outcomes
    entry_price: float
    exit_price: float
    pnl: float

    # Analysis
    success: bool
    failure_reason: Optional[str] = None
    lesson_learned: str

    # For RAG embedding
    execution_summary: str
