# Phase 01: Dress Rehearsal — Context

**Gathered:** 2026-05-13
**Status:** Ready for planning

<domain>
## Phase Boundary

Deliver an autonomous NIFTY Iron Butterfly dry-run trading system using CrewAI — 3 agents (Execution, Risk, Post-Mortem) with full Brahmand architecture: Pydantic schemas, SQLite persistence, ChromaDB RAG memory, Agent/Tool registries, and a self-learning circadian rhythm loop.

Fixed strikes (ATM ± 300 wings), mock stop-loss enforcement, all decisions logged. Post-Mortem Agent is the learning bridge: reviews trades after close, queries ChromaDB for past patterns, feeds insights back for tomorrow's execution. No real money, no dynamic strike selection, no multi-market expansion yet. Phase validates the architecture end-to-end, not trading profitability.
</domain>

<decisions>
## Implementation Decisions

### Architecture — 3-Agent CrewAI MVC
- **D-01:** Three agents: Execution Agent (fixed Iron Butterfly order placement), Risk Agent (mock SL + drawdown limits), Post-Mortem Agent (reviews day's trades → queries ChromaDB for past patterns → writes improvement observations → feeds learnings back into tomorrow's execution and risk config)
- **D-02:** Two-phase rhythm: Market hours — Execution Agent places trades, Risk Agent validates and monitors. Post-market — Post-Mortem Agent reviews state.db, queries ChromaDB, writes observations, updates daily_config.json for next run
- **D-03:** Fixed NIFTY Iron Butterfly: ATM ± 300 wings, 1 lot, positions opened between 10:30–11:30 IST
- **D-04:** Agent expansion path after MVP: Regime Agent → Strategy Architect → Margin Agent → Contract Expert → PM. All registries built to accept them without rework. Post-Mortem Agent evolves toward full Architect role (dynamic backstory rewriting, multi-crew spawning)

### Pydantic Schemas (Minimal for 3-agent loop)
- **D-05:** `TradeSignal` — market, ticker, action (BUY/SELL), strategy_type, size, strikes (atm, ce_wing, pe_wing), sl_level, tp_level, confidence, meta_data
- **D-06:** `RiskLimits` — max_drawdown, max_lots, sl_enabled, tp_enabled, margin_cap
- **D-07:** `FlowState` — active_trades list, daily_pnl, agent_decisions array, market_context snapshot, timestamp
- **D-08:** `ExecutionReport` — order_id, status, fill_price, timestamp, agent_version
- **D-09:** `ResearchNote` — observation, confidence, source (ChromaDB query / new insight), suggested_action, context_date (written by Post-Mortem Agent, consumed by Execution Agent via ChromaDB query next day)

### Persistence — Three-Tier
- **D-10:** `state.db` (SQLite) — Operational state: active_trades, pnl_log, agent_decisions, execution_reports
- **D-11:** ChromaDB — Semantic memory: research_notes, improvement_observations, failure_patterns with metadata (date, strategy, ticker)
- **D-12:** `daily_config.json` — Agent backstories, risk params, strategy weights output by Maintenance Window, consumed on next restart

### Agent Registry + Tool Registry
- **D-13:** `config/agents_registry.yaml` — Agent blueprints: role, goal, backstory templates with `{variable}` slots for dynamic population
- **D-14:** `config/tools_registry.yaml` — Tool mappings: market → tool_set (e.g., NSE_OPTIONS → [order_tool, sl_tool, greeks_tool])
- **D-15:** Agent Factory pattern — `create_agent(role, market_config)` reads registry, populates backstory, assigns tools, returns CrewAI Agent
- **D-16:** Tool Factory pattern — `get_tools(market_type)` reads tools_registry.yaml, returns dict of CrewAI Tool objects

### Maintenance Window (Self-Learning Loop — Post-Mortem Agent)
- **D-17:** Post-market (15:45 IST) — Post-Mortem Agent reads state.db (today's trades, P&L, Risk Agent decisions) + queries ChromaDB (past patterns) → generates ResearchNote observations → writes to ChromaDB → rewrites daily_config.json for next day
- **D-18:** Morning restart (08:45 IST) — Flow reads daily_config.json → populates Execution and Risk Agent backstories with updated params from last session's learning
- **D-19:** Post-Mortem Agent is the sole ChromaDB RAG user in this phase — queries past patterns, writes new observations. Execution Agent receives enriched context via daily_config.json, not direct ChromaDB queries

### RAG Implementation
- **D-20:** Custom ChromaDB Tool exposed to Post-Mortem Agent — not CrewAI's built-in `knowledge_sources`. Need metadata filtering (date ranges, strategy types, tickers) that built-in doesn't expose
- **D-21:** Embedding model: OpenAI `text-embedding-3-small` or compatible (config-driven, swap via env var)
- **D-22:** ChromaDB collections: `research_notes` (Post-Mortem's daily observations), `failure_patterns` (Risk Agent's SL breaches, missed entries), `improvement_actions` (config changes Post-Mortem made, tracked for audit)

### Telegram Messaging
- **D-23:** Two-Message Protocol from ROADMAP: 09:30 AM (pre-flight status) + 2:35 PM (daily summary with P&L)
- **D-24:** Gateway: PicoClaw with HITL in dry-run mode — messages go through for logging/audit, no actual trade authorization needed yet
- **D-25:** Resume pattern from existing `telegram_bridge.py` and `pipeline_orchestrator.py` TelegramReporter crew

### Broker Integration
- **D-26:** Shoonya primary, Flattrade fallback (existing `broker_manager.py`)
- **D-27:** yfinance `^INDIAVIX` as third VIX fallback with warning log when used
- **D-28:** Mock mode: environment variable `ANTARIKSH_MOCK_MODE=1` bypasses all broker calls, uses `ANTARIKSH_MOCK_VIX` and `ANTARIKSH_MOCK_NIFTY`

### the agent's Discretion
- Exact ChromaDB collection schema (field names, metadata structure)
- Embedding model selection (can use DeepSeek compatible if available)
- SQLite table schemas (as long as they serve the Pydantic models)
- Error recovery strategy details for broker outages
- Maintenance Window scheduling mechanism (cron vs systemd timer vs CrewAI Flow)
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Brahmand Architecture
- `/opt/hayagreeva/cloud_sync/CrewAI_Export` — Full Brahmand design: 5-phase evolution, Agent/Factory + Tool Registry, Communication Schema, Circadian Rhythm, Maintenance Window. Source of truth for all architectural decisions.
- `/opt/hayagreeva/cloud_sync/Project_Varaha_CrewAI_Design.md` — Original Varaha × CrewAI design: 3 crews, HITL gates, trust engine, risk register. Reference for broker strategy and risk patterns.

### Antariksh Project
- `/home/trading_ceo/antariksh/ARCHITECTURE.md` — 24-agent, 10-crew system inventory. All existing agents, data flows, and crew interactions.
- `/home/trading_ceo/antariksh/GAPS_AND_ROADMAP.md` — What's mocked vs production. Broker wiring, test status, future phases.
- `/home/trading_ceo/antariksh/CONTEXT.md` — Session context and priority queue.
- `/home/trading_ceo/antariksh/QUICKSTART.md` — Project setup, environment variables, quick test commands.

### Trading Desk Reference (existing CrewAI implementation to evolve)
- `/home/trading_ceo/antariksh/trading_desk.py` (1702 lines) — Full 6-agent desk with dataclass-based InfoFlows. Reference for agent patterns and ListenTriggers.
- `/home/trading_ceo/antariksh/crew_structure.py` (967 lines) — Phase 2 CrewAI with 7 agents. Reference for crew assembly and mock mode.

### Tools & Config
- `/home/trading_ceo/antariksh/tools/execution_tools.py` (621 lines) — Existing execution tools (order placement, contract resolution).
- `/home/trading_ceo/antariksh/tools/risk_tools.py` (606 lines) — Existing risk tools (TSL, kill switches, OCO logic).
- `/home/trading_ceo/antariksh/config/antariksh_rules.yaml` (302 lines) — L3 gate parameters, strategy config, broker settings.
- `/home/trading_ceo/antariksh/broker_manager.py` (317 lines) — Dual Shoonya + Flattrade abstraction.
</canonical_refs>

<specifics>
## Specific Ideas

- Fixed Iron Butterfly ONLY — ATM ± 300 wings, NIFTY, 1 lot. Post-Mortem Agent enriches with past pattern data via daily_config.json but does NOT change strategy selection
- Mock SL in Risk Agent: validates TradeSignal against RiskLimits, logs the SL order, does NOT place real broker orders yet
- ChromaDB persistence MUST survive process restart (CrewAI Flow is ephemeral, data is permanent)
- Post-Mortem Agent is the Maintenance Window — reads today's state, queries past patterns, writes config for tomorrow. Two-phase circadian rhythm from day one
- "Start with Execution + Risk, add Post-Mortem to prove RAG → then add Regime → Architect → PM one by one"
- Agent/Tool registries must be designed so adding a "NASDAQ Options" or "MCX Futures" crew means adding blueprint entries, not code changes
- Self-learning loop: state.db (what happened) + ChromaDB (what we learned) + daily_config.json (what changes tomorrow) — Post-Mortem Agent owns this entire pipeline
</specifics>

<code_context>
## Existing Code Insights

### Reusable Assets
- `broker_manager.py` — Dual broker abstraction. Execution Agent will use `get_broker_manager().execute_trade()` and `get_vix()` directly
- `telegram_bridge.py` — PicoClaw integration stub. Two-message protocol already defined (09:30 + 14:35)
- `pipeline_orchestrator.py` — Multi-crew orchestration pattern. Existing TelegramReporter crew can be adapted
- `crews/pa_crew.py` — Existing Post-Mortem crew (Position Accountant): trade review, counterfactuals, pattern detection. Reference pattern for Post-Mortem Agent's review logic
- `tools/pa_tools.py` — Existing Post-Mortem tools: trade analysis, pattern detection, SL optimization. Adapt for ChromaDB-integrated review
- `crew_structure.py:76-450` — Mock mode handling, tool definitions, crew assembly patterns
- `tools/execution_tools.py` — Order placement tools (`place_order`, `modify_order`, `cancel_order`)
- `tools/risk_tools.py` — TSL engine (`MonitorPnLGreeksTool`), kill switches, OCO logic
- `config/antariksh_rules.yaml` — VIX gate, SL/TP levels, broker tokens, LLM config
- `event_calendar.py` — 2026 event calendar (hardcoded, referenced by GateChecker)
- `config/event_calendar.json` — JSON event data (used by existing phase1_mvs.py gate logic)

### Established Patterns
- Mock mode via env vars (`ANTARIKSH_MOCK_MODE`, `ANTARIKSH_MOCK_VIX`, `ANTARIKSH_MOCK_NIFTY`)
- DeepSeek LLM via `deepseek/deepseek-chat` with environment-variable API key
- CrewAI `Process.hierarchical` with manager agent pattern from trading_desk.py
- Dataclass-based info packets between agents (MarketRegime, ProposedSetup, AuthorizedOrder)
- `@listen` decorator for event-driven agent triggers from trading_desk.py

### Integration Points
- New 3-agent Flow integrates into existing `pipeline_orchestrator.py` or runs standalone
- ChromaDB runs as local process — no external service dependency
- SQLite state.db lives in `antariksh/data/state.db`
- daily_config.json lives in `antariksh/config/daily_config.json`
- Agent/Tool registries live alongside existing `config/antariksh_rules.yaml`
- Telegram bridge reuses existing `pipeline_orchestrator.py` TelegramReporter pattern
- Phase1 monolith (`phase1_mvs.py`) is reference-only — no code reuse, no integration
</code_context>

<deferred>
## Deferred Ideas

- Dynamic strike selection — Phase 2 (when Strategy Architect + Regime Agent join)
- Multi-market expansion (MCX, NASDAQ, Crypto) — Phase 3+ (when PM + Margin Agent join)
- Real SL order placement (broker API) — Phase 2 (when Risk Agent has live trading auth)
- HITL approval gate before execution — Phase 2 (when PM agent joins)
- A2A Protocol (Agents-as-Tools) for cross-agent delegation — Phase 3 (when crew count exceeds 6)
- Dynamic agent spawning from registry during market hours — Phase 4 (full autonomy)
- Backtester with live option chain from DuckDB — Phase 2 (Research Agent needs historical context)
- Bracket orders (OCO) — Phase 2 (Risk Agent needs real broker integration)
</deferred>

---

*Phase: 01-dress-rehearsal*
*Context gathered: 2026-05-13*
