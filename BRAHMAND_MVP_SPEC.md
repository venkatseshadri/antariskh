# Brahmand MVP Specification — SUPERSEDED

> **Status:** ARCHIVED — superseded by 10-crew system (see `ARCHITECTURE.md`)  
> **Date:** 2026-05-13 (original) / 2026-05-15 (archived)  
> **Reason:** This 3-agent Flow blueprint was the initial prototype. The project evolved into a 10-crew corporate hierarchy with Ralph Loop PRD verification, Chairman orchestrator, inter-crew learning pipelines, CTO-Dev-QA engineering pipeline, and self-improvement mandate. The 3-agent concept (Executor, Risk, Post-Mortem) is now covered by the TA crew + Risk Guard + PA crew with orders of magnitude more capability.

**Original spec preserved below for historical reference.**

---

## 1. ARCHITECTURE OVERVIEW

### 1.1 Core Philosophy
- **Flow-based orchestration** (not standalone crews)
- **Persistent state** across daily process kills
- **RAG-only learning** via ChromaDB (no dynamic reprompting for MVP)
- **Minimal state to start** — expand as new agents join
- **Clear data handoffs** via Pydantic schemas

### 1.2 The 3 Agents (Adapted from Antariksh)

| Agent | Source | Role | Timing |
|-------|--------|------|--------|
| **Executor** | Trading Desk → Executioner | Place trades based on regime + yesterday's lessons | Market hours (09:15-15:30) |
| **Risk Agent** | Trading Desk → Risk Agent | Monitor positions, manage SL/TP, shift legs | During execution, continuous |
| **Post-Mortem Agent** | PA Crew | Analyze day's trades, extract lessons, update ChromaDB | Maintenance window (post-market) |

---

## 2. PROJECT STRUCTURE

```
/home/trading_ceo/antariksh/
├── brahmand/                          # NEW: Brahmand module
│   ├── __init__.py
│   ├── flow.py                        # BrahmandFlow orchestrator
│   ├── state.py                       # Pydantic models (BrahmandState, TradeSignal, etc.)
│   ├── agents/
│   │   ├── executor_agent.py          # Extracted from trading_desk.py
│   │   ├── risk_agent.py              # Extracted from trading_desk.py
│   │   └── postmortem_agent.py        # Extracted from pa_crew.py
│   ├── tools/
│   │   ├── executor_tools.py          # Refactored execution tools
│   │   ├── risk_tools.py              # Refactored risk monitoring tools
│   │   └── postmortem_tools.py        # Analysis & ChromaDB write tools
│   ├── persistence/
│   │   ├── state_manager.py           # SQLite persistence for BrahmandState
│   │   └── rag_manager.py             # ChromaDB operations (store/query trade reviews)
│   └── config.py                      # Constants, paths, model settings
│
├── tests/
│   └── test_brahmand_mvp.py           # Unit + integration tests
│
└── brahmand_flow.py                   # CLI entry point (--test-duration flag)
```

---

## 3. PYDANTIC STATE MODELS

### 3.1 BrahmandState (Persistent)

```python
from pydantic import BaseModel, Field
from typing import List, Dict, Optional
from datetime import datetime

class BrahmandState(BaseModel):
    """Shared state across all 3 agents. Persists across restarts."""
    
    # Portfolio metrics
    portfolio_value: float = Field(default=100000.0, description="Current account value")
    daily_pnl: float = Field(default=0.0, description="Today's P&L")
    
    # Active positions
    active_trades: List[Dict] = Field(default_factory=list, 
        description="[{trade_id, legs, entry_price, entry_time, sl, tp, current_pnl}]")
    
    # Market context
    market_regime: str = Field(default="UNKNOWN", description="TRENDING or SIDEWAYS")
    vix_level: float = Field(default=0.0)
    
    # Feedback from yesterday's Post-Mortem
    yesterdays_lessons: List[str] = Field(default_factory=list,
        description="Lessons extracted yesterday. Executor queries these.")
    
    # Metadata
    last_updated: datetime = Field(default_factory=datetime.now)
    agent_active: str = Field(default="", description="Which agent is currently running")
```

### 3.2 TradeSignal (Communication Schema)

```python
class TradeSignal(BaseModel):
    """Universal format for all trade decisions."""
    
    trade_id: str
    instrument: str  # e.g., "NIFTY25MAY23500CE"
    action: str  # "BUY" or "SELL"
    quantity: int
    entry_price: float
    sl_price: float
    tp_price: float
    
    # Why this trade?
    rationale: str  # "Sideways market detected, Iron Fly setup"
    confidence: float = Field(ge=0, le=1)  # 0-1 score
    
    # Tracing
    timestamp: datetime = Field(default_factory=datetime.now)
    based_on_lessons: List[str] = Field(default_factory=list,
        description="Which yesterday's lessons influenced this trade")
```

### 3.3 TradeReview (For ChromaDB)

```python
class TradeReview(BaseModel):
    """Post-Mortem writes these. Executor queries them."""
    
    date: str  # "2026-05-13"
    trade_id: str
    strategy: str  # "Iron Fly", "Credit Spread"
    market_regime: str
    
    # Outcomes
    entry_price: float
    exit_price: float
    pnl: float
    
    # Analysis
    success: bool  # Profitable or not
    failure_reason: Optional[str]  # Why it failed (if it did)
    lesson_learned: str  # What to do differently next time
    
    # For RAG embedding
    execution_summary: str  # Full context string for semantic search
```

---

## 4. PERSISTENCE STRATEGY

### 4.1 SQLite (State Management)

**File location:**
- Testing: `/tmp/brahmand_state_test.db` (ephemeral)
- Production: `/home/trading_ceo/antariksh/.brahmand_data/state.db` (persistent)

**Schema:**
```sql
CREATE TABLE brahmand_state (
    id INTEGER PRIMARY KEY,
    state_json TEXT,  -- Serialized BrahmandState
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

**Usage:**
- Flow loads state at startup: `state_manager.load_latest_state()`
- Agents update state after major actions: `state_manager.save_state(state)`
- Post-Mortem queries state: `state_manager.get_state_at_date(date)`

### 4.2 ChromaDB (Trade Reviews RAG)

**File location:**
- Testing: `/tmp/brahmand_rag_test/` (ephemeral)
- Production: `/home/trading_ceo/antariksh/.brahmand_data/rag/` (persistent)

**Collection:** `trade_reviews`

**Storage format:**
```python
{
    "ids": ["trade_2026-05-13_001", ...],
    "documents": [TradeReview.execution_summary, ...],  # Text for embedding
    "metadatas": [{"date": "2026-05-13", "pnl": 1500, "success": True}, ...],
    "embeddings": [vectorized...]
}
```

**Executor query pattern:**
```python
# Before deciding on a trade, Executor asks:
results = rag_manager.query(
    query_text="Iron Fly in sideways market, VIX ~18",
    n_results=5
)
# Returns 5 most similar past trades + their outcomes
```

---

## 5. THE FLOW: Step-by-Step Execution

### 5.1 Flow Structure (CrewAI Flows)

```python
from crewai.flow.flow import Flow, start, listen

class BrahmandFlow(Flow):
    
    @start()
    def initialize(self):
        """Load state from SQLite, prepare for the day."""
        self.state = state_manager.load_latest_state()
        self.state.agent_active = "INITIALIZING"
        
    @listen(initialize)
    def run_executor(self):
        """Execute trades based on market regime + yesterday's lessons."""
        # Query ChromaDB for similar past trades
        lessons = rag_manager.query(
            query_text=f"Trades in {self.state.market_regime} market"
        )
        
        # Update state with lessons
        self.state.yesterdays_lessons = [r.lesson for r in lessons]
        self.state.agent_active = "EXECUTOR"
        
        # Run Executor agent
        executor_crew.kickoff(inputs={
            "market_regime": self.state.market_regime,
            "lessons": self.state.yesterdays_lessons
        })
        
        # Save updated state
        state_manager.save_state(self.state)
    
    @listen(run_executor)
    def run_risk_agent(self):
        """Monitor active trades continuously."""
        self.state.agent_active = "RISK_AGENT"
        
        # Risk Agent monitors in real-time
        risk_crew.kickoff(inputs={
            "active_trades": self.state.active_trades
        })
        
        state_manager.save_state(self.state)
    
    @listen(run_risk_agent)
    def run_postmortem(self):
        """Analyze day, extract lessons, update ChromaDB."""
        self.state.agent_active = "POSTMORTEM"
        
        # Post-Mortem analyzes
        postmortem_crew.kickoff(inputs={
            "daily_pnl": self.state.daily_pnl,
            "active_trades": self.state.active_trades
        })
        
        # Post-Mortem writes reviews to ChromaDB
        # (via postmortem_tools.py)
```

### 5.2 Timing Modes

**MVP Testing (1 hour):**
```
09:15 → Initialize
09:16 → Run Executor
09:17 → Run Risk Agent (monitor for 59 mins)
10:16 → Run Post-Mortem (analyze, write to RAG)
```

**Production (Full day):**
```
09:15 → Initialize
09:16 → Run Executor
09:17 → Run Risk Agent (monitor until 15:30)
15:31 → Stop Risk Agent
16:00 → Run Post-Mortem
```

---

## 6. CLI ENTRY POINT

### 6.1 `brahmand_flow.py`

```python
#!/usr/bin/env python3
"""
Entry point for Brahmand Flow.

Usage:
  python3 brahmand_flow.py --test-duration 1h
  python3 brahmand_flow.py --mode production
"""

import argparse
from brahmand.flow import BrahmandFlow

def main():
    parser = argparse.ArgumentParser(description="Brahmand Trading Flow")
    parser.add_argument('--test-duration', default='1h', 
                       help='Test duration (e.g., 1h, 30m)')
    parser.add_argument('--mode', default='test', 
                       choices=['test', 'production'])
    parser.add_argument('--skip-postmortem', action='store_true',
                       help='Skip Post-Mortem for testing')
    
    args = parser.parse_args()
    
    flow = BrahmandFlow()
    result = flow.kickoff()
    
    print(f"Brahmand Flow completed. Final state: {result}")

if __name__ == "__main__":
    main()
```

---

## 7. TEST STRUCTURE

### 7.1 `tests/test_brahmand_mvp.py`

```python
import pytest
from brahmand.flow import BrahmandFlow
from brahmand.state import BrahmandState
from brahmand.persistence import StateManager, RAGManager

class TestBrahmandMVP:
    
    def test_state_persistence(self):
        """State saves and loads correctly."""
        state = BrahmandState(portfolio_value=100000, daily_pnl=500)
        StateManager().save_state(state)
        loaded = StateManager().load_latest_state()
        assert loaded.portfolio_value == 100000
    
    def test_executor_agent_creates_trade_signal(self):
        """Executor produces a valid TradeSignal."""
        # Mock: Run Executor
        # Assert: TradeSignal is valid Pydantic object
        pass
    
    def test_risk_agent_monitors_position(self):
        """Risk Agent monitors active trades."""
        # Mock: Add active trade to state
        # Run Risk Agent
        # Assert: SL/TP updated
        pass
    
    def test_postmortem_writes_to_chromadb(self):
        """Post-Mortem stores TradeReview in ChromaDB."""
        # Mock: Completed trade
        # Run Post-Mortem
        # Assert: ChromaDB has new review
        pass
    
    def test_executor_queries_rag(self):
        """Executor queries ChromaDB before deciding."""
        # Add sample reviews to ChromaDB
        # Run Executor
        # Assert: Query results used in decision
        pass
    
    def test_flow_end_to_end(self):
        """Full Flow runs without errors."""
        flow = BrahmandFlow()
        result = flow.kickoff()
        assert result is not None
```

---

## 8. KEY IMPLEMENTATION NOTES

### 8.1 Adapting from Antariksh

**Executor Agent:**
- Source: `trading_desk.py` → Executioner agent logic
- Keep: Order placement, strike selection, position sizing
- Change: Inject `yesterdays_lessons` into agent backstory

**Risk Agent:**
- Source: `trading_desk.py` → Risk Agent + Leg Shifter logic
- Keep: WebSocket monitoring, SL/TP management, shift logic
- Change: Update state after each modification

**Post-Mortem Agent:**
- Source: `crews/pa_crew.py` → Post-Analysis agents
- Keep: Trade review, counterfactual analysis, lesson extraction
- Change: Write TradeReview objects to ChromaDB (new)

### 8.2 Dependencies

```
crewai>=0.30.0
pydantic>=2.0
chromadb>=0.4.0
sqlite3 (stdlib)
```

### 8.3 Error Handling

- **State load fails:** Use default BrahmandState
- **ChromaDB unavailable:** Log warning, Executor proceeds without RAG
- **Agent crashes:** Catch, log to SQLite, continue to next agent
- **Persistence failure:** Alert via Telegram, fail safely

### 8.4 Future Expansion Hooks

When new agents join (Strategy Architect, Margin Agent, PM, etc.):
1. Add fields to `BrahmandState`
2. Create new agent files in `brahmand/agents/`
3. Add `@listen()` methods in Flow
4. Extend `tools/` as needed
5. No changes to core flow logic needed

---

## 9. SUCCESS CRITERIA (MVP)

- [ ] BrahmandFlow runs 1-hour test without errors
- [ ] Executor places a trade → TradeSignal logged
- [ ] Risk Agent receives signal → Updates state
- [ ] Post-Mortem analyzes → TradeReview written to ChromaDB
- [ ] Next Flow run → Executor queries ChromaDB, uses lessons
- [ ] All state persists across process kills
- [ ] Tests pass: `pytest tests/test_brahmand_mvp.py -v`

---

## 10. NEXT QUESTIONS FOR DEEPSEEK

Before coding, clarify:

1. **Broker integration:** Should Executor use mock trades or real Shoonya calls? (For MVP, suggest mocks)
2. **WebSocket:** Should Risk Agent listen to real WS or use tick simulation?
3. **Market hours:** Enforce 09:15-15:30 bounds, or allow testing outside hours?
4. **Telegram alerts:** Should each agent send updates? (Keep minimal for MVP)

---

## 11. FILE CHECKLIST

After implementation, verify:
- [ ] `/home/trading_ceo/antariksh/brahmand/__init__.py` exists
- [ ] `/home/trading_ceo/antariksh/brahmand_flow.py` is executable
- [ ] `/home/trading_ceo/antariksh/tests/test_brahmand_mvp.py` has 5+ tests
- [ ] `.brahmand_data/` directory created with `.gitignore`
- [ ] `CONTEXT.md` updated with Brahmand status
- [ ] All imports resolvable (no missing modules)

---

**Ready for DeepSeek! 🚀**
