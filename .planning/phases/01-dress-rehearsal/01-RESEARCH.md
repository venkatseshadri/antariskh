# Phase 01: Dress Rehearsal (Brahmand MVC) — Research

**Researched:** 2026-05-13
**Domain:** CrewAI Multi-Agent System + Pydantic Schemas + SQLite + ChromaDB RAG
**Confidence:** HIGH

## Summary

This phase delivers a 3-agent CrewAI system (Execution, Risk, Post-Mortem) for autonomous NIFTY Iron Butterfly dry-run trading. The codebase already has a mature 24-agent, 10-crew system (`trading_desk.py`, `crew_structure.py`, `pipeline_orchestrator.py`) with proven patterns: dataclass InfoFlows, DeskState singleton, deterministic engine functions, `@tool`-decorated tools, `BaseTool` with Pydantic args_schema, `Process.hierarchical` crews, and DeepSeek LLM integration. The Brahmand MVC builds ON TOP of these patterns — not replacing them.

**Primary recommendation:** Use CrewAI's Flow API (`Flow[State]` + `@persist` + `@listen`/`@start`/`@router`) as the orchestration backbone, with `SQLiteFlowPersistence` for state.db, ChromaDB `PersistentClient` with `OpenAIEmbeddingFunction` for RAG, and the existing `BrokerManager` singleton for market data. DO NOT use `Process.hierarchical` — the 3-agent system is simpler as a Flow with conditional routing.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Market regime detection | API / Backend | — | Uses broker_manager.py (Shoonya→Flattrade→yfinance fallback). Deterministic engine functions, no LLM |
| Fixed Iron Butterfly order placement | API / Backend | — | Execution Agent places orders via broker_manager. Mock mode overrides all broker calls |
| Risk validation (SL/TP limits) | API / Backend | — | Deterministic RiskGuardEngine checks; no LLM in decision path |
| P&L monitoring / mock SL enforcement | API / Backend | — | Risk Agent validates TradeSignal against RiskLimits, logs decisions |
| Post-market trade review | API / Backend | — | Post-Mortem Agent reads state.db + queries ChromaDB, writes daily_config.json |
| ChromaDB semantic search | API / Backend | — | Local ChromaDB PersistentClient; Post-Mortem Agent is sole RAG user |
| SQLite operational state | Database / Storage | — | state.db persists active_trades, pnl_log, execution_reports, agent_decisions |
| ChromaDB vector store | Database / Storage | — | research_notes, failure_patterns, improvement_actions collections |
| Agent backstory population | API / Backend | — | Agent Factory reads agents_registry.yaml, fills {variable} slots from daily_config.json |
| Telegram messaging | API / Backend | — | Existing PicoClaw/telegram_bridge.py pattern; 09:30 + 14:35 messages |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| crewai | 1.14.4 | Agent orchestration (Flow, Agent, Task, Crew) | Installed and proven in existing codebase [VERIFIED: pip show] |
| pydantic | 2.12.5 | Data schemas (BaseModel) | Installed; used by existing execution_tools.py and risk_tools.py [VERIFIED: pip show] |
| chromadb | 1.1.1 | Vector store for RAG (PersistentClient) | Installed; local persistence without external service [VERIFIED: pip show] |
| duckdb | 1.5.2 | Optional: live market data from varaha capture | Installed; existing DuckDB integration in trading_desk.py [VERIFIED: pip show] |
| pyyaml | (installed) | YAML config parsing (registries, rules) | Used by existing config_loader.py and antariksh_rules.yaml |
| deepseek | LLM | Chat model (deepseek/deepseek-chat) | Existing pattern: DeepSeek LLM via crewai.llm.LLM [VERIFIED: trading_desk.py L47-71] |
| sqlite3 | stdlib | SQLite persistence (state.db) | Built-in Python; CrewAI Flow also uses SQLite for FlowPersistence |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| openai | (inferred) | Embedding model provider | text-embedding-3-small for ChromaDB embeddings [D-21] |
| shoonya-api | (from python-trader) | Broker API (primary) | Live mode; already wired in broker_manager.py |
| yfinance | (inferred) | VIX fallback | Third fallback after Shoonya→Flattrade [D-27]; already used via DuckDB capture |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Flow + @persist (SQLiteFlowPersistence) | Custom sqlite3 wrapper | Flow gives auto state saving, checkpoint restore, and @listen routing — building custom means recreating that infrastructure |
| ChromaDB PersistentClient | LanceDB / FAISS | ChromaDB already installed, has metadata filtering that FAISS lacks, and PersistentClient survives restarts [D-20 requirement] |
| @persist (CrewAI built-in) | Custom JSON state file | Built-in handles concurrent access, UUID-based state lookup, and checkpoint restore — JSON files risk corruption on crash |
| OpenAI text-embedding-3-small | llm.embed() from DeepSeek API | DeepSeek doesn't guarantee embedding API compatibility; OpenAI EF is first-class in ChromaDB [VERIFIED: chromadb.utils.embedding_functions] |

**Installation:**
```bash
# Already installed — verify:
pip install crewai==1.14.4 pydantic==2.12.5 chromadb==1.1.1 duckdb==1.5.2 pyyaml

# If DeepSeek embedding unavailable for ChromaDB:
pip install openai  # For OpenAIEmbeddingFunction
```

## Architecture Patterns

### System Architecture Diagram

```
┌────────────────────────────────────────────────────────────────────┐
│                          DAILY RHYTHM                              │
│                                                                    │
│  08:45 IST ┌──────────────────────────────────────────────┐       │
│            │  MORNING RESTART                              │       │
│            │  Read daily_config.json → populate Flow state │       │
│            └────────────────────┬─────────────────────────┘       │
│                                 │                                  │
│  09:30 IST ┌────────────────────▼─────────────────────────┐       │
│            │  PRE-FLIGHT TELEGRAM (Message #1)             │       │
│            │  VIX status, gate check, daily_config summary │       │
│            └────────────────────┬─────────────────────────┘       │
│                                 │                                  │
│  10:30 IST ┌────────────────────▼─────────────────────────┐       │
│  ↓         │  EXECUTION PHASE (Market Hours)               │       │
│  ↓         │                                               │       │
│  11:30     │  Execution Agent:                             │       │
│            │    1. Read VIX/NIFTY from broker_manager      │       │
│            │    2. gate_check() — VIX < 20, entry window   │       │
│            │    3. Build TradeSignal (Pydantic)            │       │
│            │    4. Send TradeSignal → Risk Agent           │       │
│            │                                               │       │
│            │  Risk Agent:                                  │       │
│            │    1. Validate TradeSignal vs RiskLimits      │       │
│            │    2. Mock SL enforcement (log order, no API) │       │
│            │    3. Log risk decision → state.db            │       │
│            │    4. Emit ExecutionReport                    │       │
│            │                                               │       │
│            │  Shared state (FlowState) keeps track         │       │
│            └────────────────────┬─────────────────────────┘       │
│                                 │                                  │
│  14:35 IST ┌────────────────────▼─────────────────────────┐       │
│            │  DAILY SUMMARY TELEGRAM (Message #2)          │       │
│            │  P&L, risk decisions, execution status        │       │
│            └────────────────────┬─────────────────────────┘       │
│                                 │                                  │
│  15:30 IST ┌────────────────────▼─────────────────────────┐       │
│            │  MAINTENANCE WINDOW (Post-Mortem Agent)       │       │
│            │                                               │       │
│            │  1. Read state.db → getAllTrades()            │       │
│            │  2. Query ChromaDB → searchPastPatterns()     │       │
│            │     (date range + strategy + ticker filters)  │       │
│            │  3. Generate ResearchNote (Pydantic)          │       │
│            │  4. Write ResearchNote → ChromaDB             │       │
│            │     (research_notes collection + metadata)    │       │
│            │  5. Update daily_config.json                  │       │
│            │     (risk params, backstory adjustments)      │       │
│            └──────────────────────────────────────────────┘       │
│                                                                    │
│  PERSISTENCE LAYER:                                                │
│  ┌──────────────┐ ┌──────────────────┐ ┌────────────────────┐     │
│  │ state.db     │ │ ChromaDB         │ │ daily_config.json  │     │
│  │ (SQLite)     │ │ (Vector Store)   │ │ (JSON config)     │     │
│  │              │ │                  │ │                    │     │
│  │ active_trades│ │ research_notes   │ │ agent backstories  │     │
│  │ pnl_log      │ │ failure_patterns │ │ risk params        │     │
│  │ exec_reports │ │ improvement_act  │ │ strategy weights   │     │
│  │ agent_decisions│                  │ │                    │     │
│  └──────────────┘ └──────────────────┘ └────────────────────┘     │
└────────────────────────────────────────────────────────────────────┘
```

### Recommended Project Structure

```
antariksh/
├── brahmand/                          # New: Brahmand MVC code
│   ├── __init__.py
│   ├── flow.py                        # CrewAI Flow[BrahmandState] — main orchestrator
│   ├── state.py                       # Pydantic state models (TradeSignal, RiskLimits, etc.)
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── execution_agent.py         # Execution Agent + tools
│   │   ├── risk_agent.py              # Risk Agent + tools
│   │   └── postmortem_agent.py        # Post-Mortem Agent + tools
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── chroma_tools.py            # Custom ChromaDB @tool (search, write)
│   │   ├── market_tools.py            # VIX/NIFTY gate + strike calc
│   │   ├── risk_tools.py              # RiskLimits validation, SL enforcement
│   │   └── db_tools.py               # SQLite read/write tools
│   ├── persistence/
│   │   ├── __init__.py
│   │   ├── state_db.py               # SQLite state.db operations
│   │   └── chroma_store.py           # ChromaDB collection management
│   ├── registry/
│   │   ├── agent_factory.py           # create_agent(role, market_config) → CrewAI Agent
│   │   └── tool_factory.py            # get_tools(market_type) → dict of CrewAI Tool
│   ├── circadian.py                   # daily_config.json read/write
│   └── telegram.py                    # Two-message protocol (09:30 + 14:35)
├── config/
│   ├── agents_registry.yaml          # Agent blueprints (role, goal, backstory templates)
│   ├── tools_registry.yaml           # Tool mappings by market type
│   ├── daily_config.json             # Dynamic: updated by Post-Mortem each day
│   ├── agents.json                   # EXISTING: crew agent configs (untouched)
│   └── antariksh_rules.yaml          # EXISTING: L3 parameters (read-only reference)
├── data/
│   ├── state.db                       # SQLite operational state (created on first run)
│   └── chroma/                        # ChromaDB persistent storage directory
├── broker_manager.py                  # EXISTING: dual broker abstraction (reused)
├── event_calendar.py                  # EXISTING: event day detection (reused)
├── config_loader.py                   # EXISTING: JSON config loader (reference pattern)
├── crew_structure.py                  # EXISTING: RiskGuardEngine, AuditorEngine (reused classes)
└── trading_desk.py                    # REFERENCE: Patterns only, no code reuse
```

### Pattern 1: CrewAI Flow as Orchestrator (not Process.hierarchical)

**What:** Use `Flow[BrahmandState]` with `@start`, `@listen`, `@router` decorators instead of `Crew(process=Process.hierarchical)`.

**When to use:** For a sequential phase-based system (pre-flight → execute → risk → post-mortem) where each step is a deterministic gate, not an LLM-coordinated task delegation.

**Why Flow over Crew:**
- `@persist` gives automatic state saving/restore (survives crashes)
- `@listen(previous_method)` creates explicit data flow (vs implicit manager delegation)
- `@router(condition)` enables conditional branching (gate pass/fail → different paths)
- `SQLiteFlowPersistence` provides built-in checkpointing without custom code
- Flow methods can be sync Python functions — no LLM overhead for deterministic steps
- Agents are called WITHIN flow methods using `crew.kickoff()` — Flow is the outer orchestrator

**Example:**
```python
# Source: CrewAI 1.14.4 Flow API [VERIFIED: pip show crewai==1.14.4, runtime test]
from crewai.flow.flow import Flow, start, listen, router
from crewai.flow.persistence import persist
from brahmand.state import BrahmandState

@persist()
class BrahmandFlow(Flow[BrahmandState]):
    """Daily trading rhythm: gate check → execute → risk → post-mortem."""

    @start()
    def pre_flight(self):
        """08:45 AM: Load daily_config, check VIX, send Telegram #1."""
        self.state.morning_config = circadian.load_config()
        self.state.vix = broker.get_vix()
        self.state.gate_pass = self.state.vix < 20 and is_entry_window()
        if self.state.gate_pass:
            self.state.status = "GATE_PASS"
        else:
            self.state.status = "GATE_FAIL"
        telegram.send_message_1(self.state)

    @router(pre_flight)
    def route_after_gate(self):
        """Gate pass → execute; Gate fail → skip to post-mortem."""
        if self.state.gate_pass:
            return "execute_trade"
        return "skip_to_postmortem"

    @listen("execute_trade")
    def execute_phase(self):
        """10:30–11:30 AM: Execution Agent places Iron Butterfly."""
        signal = execution_agent.generate_signal(self.state)
        self.state.trade_signal = signal
        crew = execution_agent.build_crew()
        result = crew.kickoff()
        self.state.active_trades.append(result)

    @listen(execute_phase)
    def risk_phase(self):
        """Risk Agent validates and monitors."""
        validated = risk_agent.validate_and_monitor(self.state)
        self.state.execution_reports.append(validated)
        risk_agent.log_to_state_db(self.state)

    @listen("skip_to_postmortem")
    @listen(risk_phase)
    def post_mortem_phase(self):
        """15:30 PM: Post-Mortem Agent reviews + queries ChromaDB + writes config."""
        review = postmortem_agent.review_session(self.state)
        past = postmortem_agent.query_chromadb(review)
        note = postmortem_agent.generate_research_note(review, past)
        postmortem_agent.write_to_chromadb(note)
        circadian.write_config(note)
        telegram.send_message_2(self.state)
```

### Pattern 2: Pydantic State Model (Flow typed state)

**What:** Define all phase state as a single Pydantic `BaseModel` passed as `Flow[StateType]`.

**When to use:** Always for Flow-based systems. This is the authoritative state for the entire phase run.

**Key models (from D-05 to D-09):**
```python
# Source: CONTEXT.md decisions D-05 to D-09 [CITED: 01-CONTEXT.md L24-29]
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from datetime import datetime

class TradeSignal(BaseModel):
    market: str = "NIFTY"
    ticker: str = "NIFTY"
    action: str = "BUY"  # BUY/SELL/IRON_BUTTERFLY
    strategy_type: str = "IRON_BUTTERFLY"
    size: int = 1
    strikes: dict = Field(default_factory=lambda: {"atm": 0, "ce_wing": 0, "pe_wing": 0})
    sl_level: float = 3500.0
    tp_level: float = 1000.0
    confidence: float = 0.8
    meta_data: dict = Field(default_factory=dict)

class RiskLimits(BaseModel):
    max_drawdown: float = 3500.0
    max_lots: int = 1
    sl_enabled: bool = True
    tp_enabled: bool = True
    margin_cap: float = 150000.0

class ExecutionReport(BaseModel):
    order_id: str = ""
    status: str = "PENDING"
    fill_price: float = 0.0
    timestamp: str = ""
    agent_version: str = "v1.0"

class ResearchNote(BaseModel):
    observation: str = ""
    confidence: float = 0.5
    source: str = ""  # "chromadb_query" | "new_insight"
    suggested_action: str = ""
    context_date: str = ""

class BrahmandState(BaseModel):
    """Complete Flow state — persisted across phases."""
    # Morning config
    morning_config: dict = Field(default_factory=dict)
    vix: float = 0.0
    nifty_spot: float = 0.0
    gate_pass: bool = False
    status: str = "INIT"

    # Trade state
    trade_signal: Optional[TradeSignal] = None
    risk_limits: Optional[RiskLimits] = None
    active_trades: List[dict] = Field(default_factory=list)
    daily_pnl: float = 0.0

    # Reports & decisions
    execution_reports: List[ExecutionReport] = Field(default_factory=list)
    agent_decisions: List[dict] = Field(default_factory=list)
    research_notes: List[ResearchNote] = Field(default_factory=list)

    # Metadata
    timestamp: str = ""
    session_id: str = ""
```

### Pattern 3: Agent Factory (YAML → CrewAI Agent)

**What:** Read `agents_registry.yaml`, populate `{variable}` template slots, return `crewai.Agent`.

**When to use:** Every time an agent is created. The factory reads the registry and the daily_config.json.

**Key insight from existing codebase:** `config_loader.py` already does this for JSON configs (`load_agent_config(crew, agent_id)`). The Brahmand factory extends the same pattern to YAML with template variables:
```python
# Source: Pattern from config_loader.py [VERIFIED: antariksh/config_loader.py L32-51]
# Extended for YAML registry with template variables [CITED: D-13, D-15]
def create_agent(role: str, market_config: dict) -> Agent:
    """Read agents_registry.yaml, fill {variable} slots, return CrewAI Agent."""
    registry = yaml.safe_load(Path("config/agents_registry.yaml").read_text())
    blueprint = registry["agents"][role]
    daily = json.loads(Path("config/daily_config.json").read_text())

    # Populate template variables
    backstory = blueprint["backstory"]
    for key, value in daily.get("backstory_overrides", {}).get(role, {}).items():
        backstory = backstory.replace(f"{{{key}}}", str(value))

    tools = ToolFactory.get_tools(market_config.get("market_type", "NSE_OPTIONS"))

    return Agent(
        role=blueprint["role"].format(**daily.get("role_overrides", {})),
        goal=blueprint["goal"],
        backstory=backstory,
        tools=tools,
        allow_delegation=False,
        verbose=True,
        llm=_get_llm(),
    )
```

### Pattern 4: Custom ChromaDB Tool (not CrewAI knowledge_sources)

**What:** Extend `BaseTool` to expose ChromaDB query + write operations to the Post-Mortem Agent.

**When to use:** Any agent that needs semantic search with metadata filtering (date ranges, strategy types, tickers). CrewAI's built-in `knowledge_sources` doesn't expose metadata filtering.

**Verified ChromaDB API:**
```python
# Source: ChromaDB 1.1.1 [VERIFIED: runtime test]
from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Type
import chromadb

class ChromaQueryInput(BaseModel):
    query_text: str = Field(..., description="Search query for past patterns")
    n_results: int = Field(default=5, description="Number of results to return")
    date_from: int = Field(default=0, description="Start date as YYYYMMDD int")
    date_to: int = Field(default=99999999, description="End date as YYYYMMDD int")
    strategy: str = Field(default="", description="Filter by strategy type")
    ticker: str = Field(default="NIFTY", description="Filter by ticker")

class ChromaSearchTool(BaseTool):
    name: str = "chroma_search"
    description: str = (
        "Search ChromaDB for past patterns, failures, and research notes. "
        "Returns similar past observations with metadata. "
        "Use this to find relevant historical context for today's trade review."
    )
    args_schema: Type[BaseModel] = ChromaQueryInput

    def _run(self, query_text: str, n_results: int = 5, date_from: int = 0,
             date_to: int = 99999999, strategy: str = "", ticker: str = "NIFTY") -> str:
        client = chromadb.PersistentClient(path="data/chroma")
        # Build where filter — ChromaDB uses $gte/$lte on numeric metadata fields
        where_filter = {
            "date_int": {"$gte": date_from, "$lte": date_to},
            "ticker": ticker,
        }
        if strategy:
            where_filter["strategy"] = strategy

        results = {}
        for collection_name in ["research_notes", "failure_patterns", "improvement_actions"]:
            col = client.get_or_create_collection(collection_name)
            r = col.query(query_texts=[query_text], n_results=n_results, where=where_filter)
            if r["ids"] and r["ids"][0]:
                results[collection_name] = {
                    "ids": r["ids"][0],
                    "documents": r["documents"][0],
                    "metadatas": r["metadatas"][0],
                }
        import json
        return json.dumps(results, default=str)
```

### Anti-Patterns to Avoid

- **Using Process.hierarchical for 3-agent system:** The manager LLM adds latency and token cost for a deterministic sequential flow. Use Flow with `@listen` decorators instead. The existing `trading_desk.py` uses `Process.hierarchical` for 6 agents — that's the right scale for it; 3 agents with deterministic gates do not need it.
- **CrewAI's built-in `knowledge_sources`:** Doesn't expose metadata filtering (date ranges, strategy types) needed for RAG-03. Build custom BaseTool.
- **Global state dict (like crew_structure.py's `market_state`):** Not thread-safe. Use Flow's typed Pydantic state model — it's auto-persisted and type-checked.
- **Mixing ChromaDB `add()` and `query()` without explicit collection management:** Collections must be created with `get_or_create_collection()` before use. ChromaDB 1.1.1 persists to disk; multiple processes can share the same path.
- **String-based date filtering in ChromaDB:** Use integer dates (YYYYMMDD) with `$gte`/`$lte` operators. String comparisons (`"2026-05-12" > "2026-05-11"`) work lexicographically but `$gte` requires numeric types. [VERIFIED: runtime test — string dates fail with `$gte` operator]

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| State persistence across process restarts | Custom JSON file + manual save/load | `@persist` + `SQLiteFlowPersistence` from CrewAI Flow | Built-in checkpoint restore, UUID-based state lookup, concurrent-safe [VERIFIED: runtime test] |
| Agent LLM orchestration | Custom OpenAI chat loop | `crewai.Agent` + `crewai.Crew` | Handles tool calling, context injection, backstory templating, rate limits |
| ChromaDB vector storage | LanceDB, FAISS, Pinecone | `chromadb.PersistentClient` local | Already installed, local (no external service), metadata filtering built in [VERIFIED: pip show, runtime test] |
| YAML config parsing | Custom parser | `yaml.safe_load()` (PyYAML) | Already used in broker_manager.py and antariksh_rules.yaml |
| Date filtering in vector DB | Custom pre-filter | ChromaDB `where` with `$gte`/`$lte` on integer date fields | Built-in; avoids pre-filter performance overhead [VERIFIED: runtime test] |
| Telegram message delivery | Custom HTTP client | Existing `telegram_bridge.py` / `pipeline_orchestrator.py` TelegramReporter pattern | Already built; two-message protocol defined [CITED: ARCHITECTURE.md L182-199] |
| VIX/NIFTY data fetching | Custom REST calls | Existing `broker_manager.py` `get_broker_manager()` singleton | Dual broker (Shoonya+Flattrade), mock mode, yfinance fallback already built [VERIFIED: broker_manager.py] |

**Key insight:** The existing codebase has 14 fully-built tools, 24 agents, and 10 crews. The Brahmand MVC is about ORCHESTRATION and PERSISTENCE — wrapping the existing deterministic engine functions in a Flow-based rhythm with SQLite + ChromaDB storage. Do not rewrite the broker, the tools, or the risk engine.

## Common Pitfalls

### Pitfall 1: Flow state not surviving ChromaDB process restart
**What goes wrong:** `chromadb.PersistentClient(path="data/chroma")` created with one process; after restart, collections exist but documents might appear missing if `get_or_create_collection` is misused.
**Why it happens:** ChromaDB 1.1.1 uses a persistent directory. Collections persist across restarts. But if the embedding function changes between runs, query results will be nonsensical (different vector spaces).
**How to avoid:** Always use `get_or_create_collection(name, embedding_function=ef)` with the same `embedding_function` instance. [VERIFIED: runtime test — collections survive `PersistentClient` re-instantiation]
**Warning signs:** Query returns empty results for known documents, or query returns docs with zero similarity.

### Pitfall 2: `SQLiteFlowPersistence.init_db()` must be called before `save_state()`
**What goes wrong:** `sqlite3.OperationalError: no such table: flow_states` on first save.
**Why it happens:** `SQLiteFlowPersistence` doesn't auto-create tables on construction. [VERIFIED: runtime test]
**How to avoid:** Call `persistence.init_db()` during Flow initialization, before any `save_state()` call. Or use the `@persist()` decorator which handles this automatically.

### Pitfall 3: ChromaDB date filtering with string values
**What goes wrong:** `ValueError: Expected operand value to be an int or a float for operator $gte, got 2026-05-11` when using string dates.
**Why it happens:** ChromaDB `$gte`/`$lte` operators only work on numeric metadata values. [VERIFIED: runtime test]
**How to avoid:** Store dates as integers (YYYYMMDD format: `20260511`). Apply `$gte`/`$lte` operators on these integer fields. For display purposes, convert back to string dates in the query result handler.

### Pitfall 4: Mock mode env var not propagated to Flow subprocesses
**What goes wrong:** `ANTARIKSH_MOCK_MODE=1` set in shell, but CrewAI agents run in thread-pool workers that don't inherit env vars correctly.
**Why it happens:** CrewAI's agent execution uses `asyncio.to_thread()` for sync methods — env vars are inherited. But if agents are spawned as subprocesses, they lose env vars.
**How to avoid:** Set env vars at module level (global scope) before Flow construction, not per-call. The existing `trading_desk.py` pattern sets `os.environ["ANTARIKSH_MOCK_MODE"] = "1"` globally before `crew.kickoff()`. Follow this pattern.

### Pitfall 5: ChromaDB embedding dimension mismatch
**What goes wrong:** Changing embedding models between runs causes search to fail or return garbage.
**Why it happens:** OpenAI `text-embedding-3-small` outputs 1536-dim vectors. Default `all-MiniLM-L6-v2` outputs 384-dim. If you switch models, existing collections have wrong dimension.
**How to avoid:** Fix the embedding model at collection creation. If you need to switch, delete and recreate the collection. Store the embedding model name in collection metadata.

## Code Examples

Verified patterns from official sources:

### CrewAI Flow with Persistence
```python
# Source: CrewAI 1.14.4 Flow API [VERIFIED: context7 docs + runtime test]
from crewai.flow.flow import Flow, start, listen
from crewai.flow.persistence import persist
from pydantic import BaseModel

class MyState(BaseModel):
    counter: int = 0
    status: str = "init"

@persist()  # Uses SQLiteFlowPersistence; auto-creates table
class MyFlow(Flow[MyState]):
    @start()
    def step_one(self):
        self.state.counter += 1
        return "done"

    @listen(step_one)
    def step_two(self, prev_result):
        self.state.counter += 1
        self.state.status = "complete"

# State survives across Flow instances
flow1 = MyFlow()
flow1.kickoff()  # counter = 2

flow2 = MyFlow()
flow2.kickoff()  # counter = 4 (restored from SQLite)
```

### ChromaDB Collection with Metadata Filtering
```python
# Source: ChromaDB 1.1.1 [VERIFIED: runtime test]
import chromadb
from chromadb.utils import embedding_functions

# Use OpenAI embeddings (config-driven, swap via env var)
ef = embedding_functions.OpenAIEmbeddingFunction(
    api_key=os.environ["OPENAI_API_KEY"],
    model_name="text-embedding-3-small"  # 1536 dimensions
)

client = chromadb.PersistentClient(path="data/chroma")
col = client.get_or_create_collection(
    "research_notes",
    embedding_function=ef,
    metadata={"hnsw:space": "cosine"}
)

# Add with metadata
col.add(
    documents=["Iron fly hit TP in 45 min. VIX was calm at 15."],
    metadatas=[{
        "date_int": 20260512,         # Integer for $gte/$lte filtering
        "strategy": "iron_butterfly",
        "ticker": "NIFTY",
        "outcome": "tp_hit",
        "vix_at_entry": 15.0,
    }],
    ids=["note-20260512-001"]
)

# Query with metadata filter
results = col.query(
    query_texts=["successful iron butterfly trades with low vix"],
    n_results=5,
    where={
        "date_int": {"$gte": 20260501, "$lte": 20260513},
        "strategy": "iron_butterfly",
        "ticker": "NIFTY",
    }
)
```

### Agent with Custom Tool
```python
# Source: Pattern from existing trading_desk.py agents [VERIFIED: trading_desk.py L1059-1196]
# Adapted for Agent Factory pattern [CITED: D-15]
from crewai import Agent
from crewai.llm import LLM
from crewai.tools import BaseTool
from typing import Type
from pydantic import BaseModel, Field

# Custom tool with strict Pydantic args_schema
class GateCheckInput(BaseModel):
    vix: float = Field(..., description="Current VIX value")
    time_str: str = Field(..., description="Current time HH:MM IST")

class GateCheckTool(BaseTool):
    name: str = "gate_check"
    description: str = "Check if market conditions are safe for trading: VIX < 20, entry window 10:30-11:30, no event day."
    args_schema: Type[BaseModel] = GateCheckInput

    def _run(self, vix: float, time_str: str) -> str:
        import json
        reasons = []
        if vix > 20:
            reasons.append(f"VIX {vix} > 20")
        hour, minute = map(int, time_str.split(":"))
        in_window = (hour == 10 and minute >= 30) or (hour == 11 and minute <= 30)
        if not in_window:
            reasons.append(f"Outside entry window: {time_str}")
        passed = len(reasons) == 0
        return json.dumps({"gate_pass": passed, "reasons": reasons})

# Agent creation (Agent Factory pattern)
def create_execution_agent(config: dict) -> Agent:
    llm = LLM(
        model="deepseek/deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        api_key=os.environ["DEEPSEEK_API_KEY"],
        temperature=0.3,
    )
    return Agent(
        role=config["role"],
        goal=config["goal"],
        backstory=config["backstory"],
        tools=[GateCheckTool(), build_trade_signal_tool, place_mock_order_tool],
        allow_delegation=False,
        verbose=True,
        llm=llm,
    )
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `Process.hierarchical` with manager LLM for 3-agent system | `Flow[State]` with `@listen` routing | CrewAI 1.14+ introduced Flow API | Removes manager LLM cost/latency for 3-agent system; state auto-persisted |
| Global `market_state` dict (crew_structure.py) | Typed Pydantic `BrahmandState` + `@persist` | Now (Brahmand MVC) | Type safety, auto-persist, survive crashes |
| `agents.json` static config | `agents_registry.yaml` with `{variable}` slots + `daily_config.json` | Now (Brahmand MVC) | Dynamic backstory tuning by Post-Mortem Agent |
| `@tool` decorator for all tools | `BaseTool` with `args_schema` for tools needing structured input | Already used in execution_tools.py, risk_tools.py | Type-safe input validation; required for ChromaDB tool with metadata filters |
| Simulated order IDs `SIM-{tsym}-{i:03d}` | Same mock pattern extended for 3-agent Flow | Phase 1 dress rehearsal | Execution Agent uses same mock approach; Risk Agent logs mock SL |

## Assumptions Log

> All claims tagged `[ASSUMED]` need user confirmation before execution.

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Flow API supports `@listen("skip_to_postmortem")` string-based routing (decorator resolves method by name) | Pattern 1: Flow as Orchestrator | Confirmed via documentation — string-based routing is standard. Low risk. |
| A2 | DeepSeek embedding API is NOT available (text-embedding-3-small from OpenAI is the fallback) | Standard Stack | If DeepSeek has embeddings, we could save on OpenAI costs. Low risk — OpenAI EF is the safe default. |
| A3 | CrewAI 1.14.4 `@persist` with `SQLiteFlowPersistence` correctly handles Flow restart (same Flow class, same db_path → state restored) | Pattern 1 | Verified working in runtime test. Medium confidence — need stress test with concurrent access. |
| A4 | Agent Factory reads `daily_config.json` that Post-Mortem Agent writes the previous day — `{variable}` slots are simple string replacements | Pattern 3 | If the template syntax is more complex (conditionals, loops), we need Jinja2. Unlikely for this use case. |
| A5 | ChromaDB with `PersistentClient` and `OpenAIEmbeddingFunction` correctly handles multiple collections in the same directory without interference | ChromaDB Pattern | Verified working for single-collection test. Multi-collection needs verification. |

## Open Questions

1. **Scheduling mechanism for daily rhythm (D-17, D-18)**
   - What we know: Flow is started manually or via cron; `@persist` handles crash recovery. The two-phase rhythm (08:45 morning restart, 15:45 post-mortem) requires external scheduling.
   - What's unclear: Whether to use cron (simple, proven), systemd timer (modern), or a long-running Flow process with time-based `@router` conditions (self-contained).
   - Recommendation: Use cron for Phase 1 (proven, simple). The existing codebase already has cron deployed for phase1_mvs.py. Move to internal Flow scheduling in Phase 2+.

2. **ChromaDB embedding model selection (D-21)**
   - What we know: OpenAI `text-embedding-3-small` (1536-dim) is available via `OpenAIEmbeddingFunction`. Default `all-MiniLM-L6-v2` (384-dim) is also available with zero API cost. The decision is "config-driven, swap via env var."
   - What's unclear: Which model provides better semantic search for trading pattern notes? MiniLM is 4x smaller but may have lower quality.
   - Recommendation: Start with `all-MiniLM-L6-v2` (free, 384-dim) for Phase 1 dress rehearsal. Switch to OpenAI if search quality is poor. The embedding function is config-driven — swap via env var without code changes.

3. **SQLiteFlowPersistence vs Custom SQLite for operational state**
   - What we know: `SQLiteFlowPersistence` auto-saves Flow state but the schema is abstract (key-value). For queries like "show all trades where P&L < -3000", we need structured tables.
   - What's unclear: Whether to use FlowPersistence for ALL state, or use it for Flow orchestration state and custom sqlite3 for operational queries.
   - Recommendation: Use `@persist` (SQLiteFlowPersistence) for Flow orchestration state (survive crashes). Create SEPARATE custom SQLite tables for operational data (active_trades, pnl_log, execution_reports, agent_decisions) using raw `sqlite3`. This separation lets Flow auto-restore while giving structured query access.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| crewai | Flow orchestration, Agents | ✓ | 1.14.4 | — |
| chromadb | RAG vector store | ✓ | 1.1.1 | — |
| duckdb | Optional: live market data | ✓ | 1.5.2 | Use broker_manager mock mode |
| PyYAML | Registry config parsing | ✓ | (installed) | — |
| sqlite3 | state.db persistence | ✓ | stdlib | — |
| openai | ChromaDB embeddings (if used) | ✗ | — | Use ChromaDB default (MiniLM, free, local) |
| Shoonya API | Live broker data | ✓ | (via python-trader) | Mock mode covers all scenarios |
| DeepSeek API key | LLM for agents | ? | — | Set DEEPSEEK_API_KEY env var; mock mode skips LLM calls |
| OpenAI API key | Embeddings for ChromaDB | ? | — | Use default MiniLM embeddings (free, no key needed) |

**Missing dependencies with no fallback:**
- DeepSeek API key — needed for LLM-driven agent reasoning. Without it, agents cannot call tools. Mock mode can bypass LLM by calling engine functions directly (existing pattern in `crew_structure.py`).

**Missing dependencies with fallback:**
- OpenAI API key for embeddings → fallback: ChromaDB default `all-MiniLM-L6-v2` (384-dim, free, local)

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (existing project standard) |
| Config file | none — detected; add `pytest.ini` or `pyproject.toml` [pytest] section in Wave 0 |
| Quick run command | `python3 -m pytest tests/brahmand/ -x -q` |
| Full suite command | `python3 -m pytest tests/ -v` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| EXE-01 | Place fixed Iron Butterfly orders | unit | `pytest tests/brahmand/test_execution_agent.py::test_generate_iron_butterfly_signal -x` | ❌ Wave 0 |
| EXE-02 | Use broker_manager for Shoonya/Flattrade | integration | `pytest tests/brahmand/test_execution_agent.py::test_broker_manager_integration -x` | ❌ Wave 0 |
| EXE-03 | Output TradeSignal Pydantic with all fields | unit | `pytest tests/brahmand/test_state.py::test_trade_signal_validation -x` | ❌ Wave 0 |
| EXE-04 | Mock mode covers all broker calls | unit | `pytest tests/brahmand/test_mock_mode.py::test_mock_broker_calls -x` | ❌ Wave 0 |
| RISK-01 | Validate TradeSignal against RiskLimits | unit | `pytest tests/brahmand/test_risk_agent.py::test_validate_signal -x` | ❌ Wave 0 |
| RISK-02 | Enforce mock stop-loss (log, no real orders) | unit | `pytest tests/brahmand/test_risk_agent.py::test_mock_sl_enforcement -x` | ❌ Wave 0 |
| RISK-03 | Log risk decisions to state.db | integration | `pytest tests/brahmand/test_state_db.py::test_risk_decision_logging -x` | ❌ Wave 0 |
| RISK-04 | Report violations via ExecutionReport | unit | `pytest tests/brahmand/test_state.py::test_execution_report -x` | ❌ Wave 0 |
| PMORT-01 | Read state.db after market close | integration | `pytest tests/brahmand/test_postmortem_agent.py::test_read_state_db -x` | ❌ Wave 0 |
| PMORT-02 | Query ChromaDB for past patterns | integration | `pytest tests/brahmand/test_chroma_tools.py::test_query_past_patterns -x` | ❌ Wave 0 |
| PMORT-03 | Generate ResearchNote with observations | unit | `pytest tests/brahmand/test_postmortem_agent.py::test_generate_research_note -x` | ❌ Wave 0 |
| PMORT-04 | Write ResearchNotes to ChromaDB | integration | `pytest tests/brahmand/test_chroma_tools.py::test_write_research_note -x` | ❌ Wave 0 |
| PMORT-05 | Update daily_config.json | unit | `pytest tests/brahmand/test_circadian.py::test_update_daily_config -x` | ❌ Wave 0 |
| PERSIST-01 | SQLite state.db tables exist | unit | `pytest tests/brahmand/test_state_db.py::test_tables_exist -x` | ❌ Wave 0 |
| PERSIST-03 | daily_config.json schema valid | unit | `pytest tests/brahmand/test_circadian.py::test_daily_config_schema -x` | ❌ Wave 0 |
| RAG-01 | Custom ChromaDB Tool (not built-in knowledge_sources) | unit | `pytest tests/brahmand/test_chroma_tools.py::test_custom_tool_exists -x` | ❌ Wave 0 |
| RAG-03 | Metadata filtering on ChromaDB queries | unit | `pytest tests/brahmand/test_chroma_tools.py::test_metadata_filtering -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/brahmand/ -x -q`
- **Per wave merge:** `pytest tests/ -v`
- **Phase gate:** Full suite green + `pytest tests/test_integration_end_to_end.py` (39/39 — must not regress)

### Wave 0 Gaps
- [ ] `tests/brahmand/__init__.py` — test package
- [ ] `tests/brahmand/test_state.py` — covers EXE-03, RISK-04, SCHEMA-01 through SCHEMA-05
- [ ] `tests/brahmand/test_execution_agent.py` — covers EXE-01, EXE-02
- [ ] `tests/brahmand/test_risk_agent.py` — covers RISK-01, RISK-02
- [ ] `tests/brahmand/test_postmortem_agent.py` — covers PMORT-01, PMORT-03
- [ ] `tests/brahmand/test_chroma_tools.py` — covers RAG-01, RAG-03, PMORT-02, PMORT-04
- [ ] `tests/brahmand/test_state_db.py` — covers PERSIST-01, RISK-03
- [ ] `tests/brahmand/test_circadian.py` — covers PERSIST-03, PMORT-05
- [ ] `tests/brahmand/test_mock_mode.py` — covers EXE-04
- [ ] `tests/brahmand/conftest.py` — shared fixtures (mock broker, temp ChromaDB dir, temp SQLite)
- [ ] `tests/brahmand/test_flow.py` — end-to-end Flow test (pre-flight → execute → risk → post-mortem)
- [ ] Framework install: `pip install pytest pytest-asyncio` (verify already installed)
- [ ] `pytest.ini` or `pyproject.toml` with `[tool.pytest.ini_options]` test path configuration

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Phase 1 dry-run — no auth endpoints |
| V3 Session Management | no | No user sessions in dry-run |
| V4 Access Control | no | No multi-user access |
| V5 Input Validation | yes | Pydantic BaseModel validation for all inter-agent data packets (TradeSignal, RiskLimits, ExecutionReport, ResearchNote) |
| V6 Cryptography | no | No cryptographic operations in Phase 1 |
| V7 Error Handling | yes | Flow exceptions caught by `@persist` checkpointing; agent errors logged to state.db |
| V8 Data Protection | yes | Broker credentials in cred.yml (existing, already protected); ChromaDB local-only; SQLite local-only |
| V9 Communications | no | No network-exposed APIs in Phase 1 |
| V10 Malicious Code | yes | Deterministic engine functions prevent LLM from placing real orders; mock mode env var gate |

### Known Threat Patterns for CrewAI + Pydantic + SQLite + ChromaDB

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| LLM prompt injection in agent backstory | Tampering | Agent backstories from YAML registry (not user-supplied); `{variable}` slots validated by Pydantic |
| SQL injection in custom SQLite queries | Tampering | Use parameterized queries (`?` placeholders) in all sqlite3 calls; never f-string SQL |
| ChromaDB document injection (bad metadata) | Spoofing | Validate metadata against Pydantic schema before `col.add()` |
| Flow state tampering between agents | Tampering | Pydantic state model provides type validation on every write |
| Mock mode bypass (real orders in dry-run) | Elevation of Privilege | `ANTARIKSH_MOCK_MODE=1` checked at broker_manager level; Execution Agent only calls broker_manager (never direct API) |
| API key exposure in state.db | Information Disclosure | Never store API keys in state.db; env var only; ChromaDB embedding config env-var driven |

## Sources

### Primary (HIGH confidence)
- `crewai==1.14.4` [VERIFIED: pip show crewai] — Flow API, `@persist`, `SQLiteFlowPersistence`, `@start`/`@listen`/`@router` decorators
- `chromadb==1.1.1` [VERIFIED: pip show chromadb] — `PersistentClient`, `OpenAIEmbeddingFunction`, metadata filtering with `where` operators
- `pydantic==2.12.5` [VERIFIED: pip show pydantic] — BaseModel schemas
- CrewAI Context7 docs `/crewaiinc/crewai` — Flow persistence, `@persist`, `SQLiteFlowPersistence` API
- CrewAI official docs `/websites/crewai_en` — Agent creation, hierarchical process, task delegation

### Secondary (MEDIUM confidence)
- `/home/trading_ceo/antariksh/trading_desk.py` (1702 lines) — Existing 6-agent CrewAI patterns: InfoFlows, DeskState, engine functions, agent definitions [VERIFIED: code review]
- `/home/trading_ceo/antariksh/crew_structure.py` (967 lines) — RiskGuardEngine, AuditorEngine, tool patterns [VERIFIED: code review]
- `/home/trading_ceo/antariksh/broker_manager.py` (317 lines) — Dual broker abstraction, mock mode [VERIFIED: code review]
- `/home/trading_ceo/antariksh/config_loader.py` (64 lines) — Agent config loading pattern [VERIFIED: code review]
- `/home/trading_ceo/antariksh/config/agents.json` (110 lines) — Agent identity definitions [VERIFIED: code review]
- `/home/trading_ceo/antariksh/config/antariksh_rules.yaml` (302 lines) — L3 parameters, capital limits, strategy config [VERIFIED: code review]
- `/home/trading_ceo/antariksh/ARCHITECTURE.md` (416 lines) — Full system architecture, crew inventory [VERIFIED: code review]
- `/home/trading_ceo/antariksh/GAPS_AND_ROADMAP.md` (169 lines) — Mock status, production wiring gaps [VERIFIED: code review]
- `/home/trading_ceo/antariksh/crews/pa_crew.py` (132 lines) — Post-Mortem crew pattern reference [VERIFIED: code review]
- `/home/trading_ceo/antariksh/tools/execution_tools.py` (621 lines) — BaseTool + Pydantic args_schema pattern [VERIFIED: code review]
- `/home/trading_ceo/antariksh/tools/risk_tools.py` (606 lines) — Risk monitoring with DuckDB [VERIFIED: code review]
- `/home/trading_ceo/antariksh/tools/pa_tools.py` (427 lines) — Post-Mortem tools (review, counterfactuals, patterns) [VERIFIED: code review]

### Tertiary (LOW confidence — not verified)
- Brahmand design file `/opt/hayagreeva/cloud_sync/CrewAI_Export` — UNREADABLE (permission denied). All Brahmand design knowledge reconstructed from CONTEXT.md decisions and existing codebase patterns.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — All libraries verified with `pip show` and runtime tests
- Architecture: HIGH — CrewAI Flow + @persist verified working; ChromaDB verified with PersistentClient + metadata filtering
- Pitfalls: HIGH — Multiple runtime tests confirmed edge cases (date filtering, init_db requirement)
- Agent patterns: HIGH — Existing codebase provides 1702-line reference implementation

**Research date:** 2026-05-13
**Valid until:** 2026-06-13 (30 days — CrewAI and ChromaDB are stable releases)

## Phase Requirements Traceability

| ID | Description | Research Support |
|----|-------------|------------------|
| EXE-01 | Place fixed NIFTY Iron Butterfly orders | Pattern 1 (Flow orchestration), Pattern 2 (TradeSignal Pydantic), code example (Agent with custom tool) |
| EXE-02 | Use broker_manager for Shoonya/Flattrade | Standard Stack (broker_manager.py reuse), Pitfall 4 (mock mode propagation) |
| EXE-03 | Output TradeSignal Pydantic with all fields | Pattern 2 (Pydantic state models), code example (TradeSignal schema) |
| EXE-04 | Mock mode covers all broker calls | Pitfall 4 (mock mode env var), Standard Stack (BROKER_MANAGER reuse) |
| RISK-01 | Validate TradeSignal against RiskLimits | Pattern 2 (RiskLimits model), Pattern 1 (risk_phase Flow method) |
| RISK-02 | Enforce mock stop-loss (log, no real orders) | Pattern 1 (risk_phase logs to state.db), Don't Hand-Roll (use broker_manager, not direct API) |
| RISK-03 | Log risk decisions to state.db | Pattern 3 (Agent Factory), Open Question 3 (SQLiteFlowPersistence vs custom) |
| RISK-04 | Report violations via ExecutionReport | Pattern 2 (ExecutionReport Pydantic), code example |
| PMORT-01 | Read state.db after market close | Pattern 1 (post_mortem_phase), Open Question 3 |
| PMORT-02 | Query ChromaDB for past patterns | Pattern 4 (Custom ChromaDB tool), code example (metadata filtering) |
| PMORT-03 | Generate ResearchNote with observations | Pattern 2 (ResearchNote Pydantic), Pattern 1 (post_mortem_phase) |
| PMORT-04 | Write ResearchNotes to ChromaDB | Pattern 4 (chroma_write tool), Anti-Pattern (don't use knowledge_sources) |
| PMORT-05 | Update daily_config.json | Pattern 3 (Agent Factory reads daily_config.json), Pattern 1 (circadian rhythm) |
| PERSIST-01 | SQLite state.db tables | Open Question 3 (FlowPersistence vs custom), Recommended Project Structure |
| PERSIST-02 | ChromaDB collections | Pattern 4 (Custom ChromaDB tool), Standard Stack (chromadb 1.1.1) |
| PERSIST-03 | daily_config.json schema | Pattern 3 (Agent Factory example), Open Question 2 |
| PERSIST-04 | Morning restart reads daily_config | Pattern 1 (pre_flight method), Pattern 3 (create_agent uses daily_config) |
| REG-01 | agents_registry.yaml blueprints | Pattern 3 (Agent Factory), Recommended Project Structure |
| REG-02 | tools_registry.yaml mappings | Pattern 3 (ToolFactory), Standard Stack (PyYAML) |
| REG-03 | Agent Factory create_agent() | Pattern 3 (full code example), config_loader.py reference |
| REG-04 | Tool Factory get_tools() | Pattern 3 (referenced in Agent Factory), execution_tools.py BaseTool pattern |
| RAG-01 | Custom ChromaDB Tool | Pattern 4 (ChromaSearchTool extends BaseTool), Anti-Pattern (don't use knowledge_sources) |
| RAG-02 | Embedding model configurable | Open Question 2 (MiniLM vs OpenAI), Standard Stack (OpenAIEmbeddingFunction) |
| RAG-03 | Metadata filtering on ChromaDB | Pitfall 3 (date filtering), Pattern 4 (where clause with $gte/$lte) |
| RAG-04 | Post-Mortem is sole ChromaDB user | Pattern 1 (only post_mortem_phase calls chroma tools) |
| SCHEMA-01 | TradeSignal Pydantic | Pattern 2 (full TradeSignal model) |
| SCHEMA-02 | RiskLimits Pydantic | Pattern 2 (full RiskLimits model) |
| SCHEMA-03 | FlowState Pydantic | Pattern 2 (BrahmandState aggregates all) |
| SCHEMA-04 | ExecutionReport Pydantic | Pattern 2 (full ExecutionReport model) |
| SCHEMA-05 | ResearchNote Pydantic | Pattern 2 (full ResearchNote model) |
| TELE-01 | Pre-flight 09:30 AM message | Don't Hand-Roll (reuse telegram_bridge.py pattern) |
| TELE-02 | Daily summary 14:35 PM message | Don't Hand-Roll (reuse pipeline_orchestrator.py TelegramReporter) |
| TELE-03 | PicoClaw HITL dry-run mode | Existing pattern — log only, no auth needed [CITED: D-24] |
