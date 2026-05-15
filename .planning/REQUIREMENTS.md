# Antariksh — v1 Requirements (Brahmand MVC)

## Phase 1: Execution Agent
- [ ] **EXE-01**: Place fixed NIFTY Iron Butterfly orders (ATM ± 300 wings, 1 lot)
- [ ] **EXE-02**: Use broker_manager.py for Shoonya primary / Flattrade fallback
- [ ] **EXE-03**: Output TradeSignal (Pydantic) with all fields validated
- [ ] **EXE-04**: Mock mode covers all broker calls via ANTARIKSH_MOCK_MODE env var

## Phase 1: Risk Agent
- [ ] **RISK-01**: Validate incoming TradeSignal against RiskLimits (Pydantic)
- [ ] **RISK-02**: Enforce mock stop-loss (log SL order, do NOT place real broker orders)
- [ ] **RISK-03**: Log all risk decisions to state.db for Post-Mortem review
- [ ] **RISK-04**: Report violations via ExecutionReport (Pydantic)

## Phase 1: Post-Mortem Agent
- [ ] **PMORT-01**: Read state.db after market close → review today's trades, P&L, risk decisions
- [ ] **PMORT-02**: Query ChromaDB for similar past patterns and failure types
- [ ] **PMORT-03**: Generate ResearchNote (Pydantic) with observations and suggested actions
- [ ] **PMORT-04**: Write ResearchNotes to ChromaDB (research_notes collection) with metadata
- [ ] **PMORT-05**: Update daily_config.json with improved risk params, backstory adjustments

## Phase 1: Persistence Layer
- [ ] **PERSIST-01**: SQLite state.db with tables for active_trades, pnl_log, execution_reports, agent_decisions
- [ ] **PERSIST-02**: ChromaDB with collections: research_notes, failure_patterns, improvement_actions
- [ ] **PERSIST-03**: daily_config.json schema: agent backstories, risk params, strategy weights
- [ ] **PERSIST-04**: Morning restart reads daily_config.json → populates agent configs

## Phase 1: Agent/Tool Registries
- [ ] **REG-01**: agents_registry.yaml — agent blueprints with role, goal, backstory, {variable} slots
- [ ] **REG-02**: tools_registry.yaml — tool mappings by market type (NSE_OPTIONS, MCX_FUTURES, etc.)
- [ ] **REG-03**: Agent Factory: create_agent(role, market_config) → CrewAI Agent
- [ ] **REG-04**: Tool Factory: get_tools(market_type) → dict of CrewAI Tool objects

## Phase 1: RAG + ChromaDB
- [ ] **RAG-01**: Custom ChromaDB Tool (not CrewAI built-in knowledge_sources)
- [ ] **RAG-02**: Embedding model configurable via env var (OpenAI text-embedding-3-small or compatible)
- [ ] **RAG-03**: Metadata filtering on ChromaDB queries (date ranges, strategy types, tickers)
- [ ] **RAG-04**: Post-Mortem Agent is sole ChromaDB user in Phase 1

## Phase 1: Pydantic Schemas
- [ ] **SCHEMA-01**: TradeSignal — market, ticker, action, strategy_type, size, strikes, sl_level, tp_level, confidence, meta_data
- [ ] **SCHEMA-02**: RiskLimits — max_drawdown, max_lots, sl_enabled, tp_enabled, margin_cap
- [ ] **SCHEMA-03**: FlowState — active_trades, daily_pnl, agent_decisions, market_context, timestamp
- [ ] **SCHEMA-04**: ExecutionReport — order_id, status, fill_price, timestamp, agent_version
- [ ] **SCHEMA-05**: ResearchNote — observation, confidence, source, suggested_action, context_date

## Phase 1: Telegram
- [ ] **TELE-01**: Pre-flight status message at 09:30 AM IST
- [ ] **TELE-02**: Daily summary with P&L at 14:35 PM IST
- [ ] **TELE-03**: PicoClaw gateway with HITL in dry-run mode (log only, no auth needed)

### v2 Requirements (Phase 2 — deferred)
- Live broker order placement (Shoonya/Flattrade real orders)
- Regime Agent (ADX/SuperTrend market direction detection)
- Real SL/TP order placement via broker API
- WebSocket LTP feed for live price tracking
- TSL engine with real prices

### v3 Requirements (Phase 3 — deferred)
- Strategy Architect (Iron Butterfly vs Credit Spread selection)
- Dynamic strike calculation (not fixed ± 300)
- Research Agent ChromaDB enrichment during market hours

### Out of Scope (v1)
- Real money trading — dry-run only
- Dynamic strike selection — fixed ATM ± 300
- Multi-market expansion (MCX, NASDAQ, Crypto)
- HITL approval gates — all trades auto-approved in mock
- A2A protocol (agents-as-tools)
- Backtester with live option chain
