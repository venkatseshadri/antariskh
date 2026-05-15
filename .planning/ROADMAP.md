# Antariksh Roadmap — Brahmand Architecture

**Architecture:** CrewAI multi-agent autonomous trading with Pydantic schemas, SQLite persistence, ChromaDB RAG, Agent/Tool registries, and circadian self-learning loop.

**Existing codebase:** 24 agents, 10 crews already built (trading_desk.py, crew_structure.py, crews/, tools/, pipeline_orchestrator.py). GAPS_AND_ROADMAP.md tracks mock→production wiring.

## Phase 1: Dress Rehearsal — Brahmand MVC (Current)
**Goal:** 3-agent CrewAI system (Execution + Risk + Post-Mortem) with full Brahmand architecture from day one
**Requirements:** EXE-01 to EXE-04, RISK-01 to RISK-04, PMORT-01 to PMORT-05, PERSIST-01 to PERSIST-04, REG-01 to REG-04, RAG-01 to RAG-04
**Canonical refs:** `/opt/hayagreeva/cloud_sync/CrewAI_Export` (Brahmand design), `.planning/phases/01-dress-rehearsal/01-CONTEXT.md`
**Success Criteria:**
1. Execution Agent places fixed NIFTY Iron Butterfly (ATM ± 300 wings, 1 lot) via broker
2. Risk Agent enforces mock SL against RiskLimits, logs all decisions
3. Post-Mortem Agent reviews state.db → queries ChromaDB → writes ResearchNotes → updates daily_config.json
4. Full circadian rhythm: morning restart reads daily_config.json, post-market writes learnings
5. Agent Registry (YAML) + Tool Registry (YAML) support Agent Factory for all 3 agents
6. Pydantic schemas (TradeSignal, RiskLimits, FlowState, ExecutionReport, ResearchNote) validated end-to-end
7. Two-Message Telegram protocol: 09:30 pre-flight + 14:35 daily summary
8. Mock mode covers all broker calls; production wiring is Phase 2

## Phase 2: Live Broker + Regime Agent
**Goal:** Replace mocks with live broker execution + add Regime Agent for market context
**Depends on:** Phase 1 (Pydantic schemas, registries, persistence)
**Requirements:** REGIME-01 to REGIME-04, BROKER-01 to BROKER-06
**Success Criteria:**
1. Regime Agent detects SIDEWAYS/TRENDING via ADX/SuperTrend from DuckDB
2. Execution Agent places real orders via Shoonya/Flattrade
3. Risk Agent places real SL orders (not just mock)
4. Live fill prices, order statuses, and P&L tracking
5. TSL engine active with live LTP feed

## Phase 3: Strategy Architect + Credit Spreads
**Goal:** Dynamic strategy selection — Iron Butterfly (sideways) vs Credit Spread (trending)
**Depends on:** Phase 2 (Regime Agent + live broker)
**Requirements:** ARCH-01 to ARCH-05
**Success Criteria:**
1. Strategy Architect selects strategy based on Regime Agent output
2. Dynamic strike calculation (not just fixed ± 300)
3. Both Iron Butterfly and Credit Spread strategies live-tested
4. Research Agent enriches with ChromaDB past-pattern context

## Phase 4: Portfolio Manager + Margin Agent
**Goal:** Capital authorization, multi-strategy allocation, margin enforcement
**Depends on:** Phase 3 (Strategy Architect)
**Requirements:** PM-01 to PM-06, MARGIN-01 to MARGIN-04
**Success Criteria:**
1. PM authorizes trades based on margin, risk appetite, daily config
2. Margin Agent calculates required margin, checks broker free balance
3. HITL approval gate via PicoClaw Telegram
4. Daily capital limits enforced (₹3,500 SL, ₹4,500 portfolio SL)

## Phase 5: Multi-Market Expansion
**Goal:** Agent Registry enables MCX, NASDAQ, Crypto crews with zero code changes
**Depends on:** Phase 4 (PM + Margin Agent)
**Requirements:** MULTI-01 to MULTI-06
**Success Criteria:**
1. Adding "NASDAQ Options" crew = YAML blueprint entry only
2. Tool Registry maps market → broker tools correctly
3. Agent Factory spawns market-specific contract/execution agents
4. PM manages margin across multiple crews simultaneously

## Phase 6: Full Autonomy
**Goal:** Dynamic agent spawning, A2A protocol, self-improving backstories
**Depends on:** Phase 5 (Multi-market)
**Requirements:** AUTO-01 to AUTO-08
**Success Criteria:**
1. Architect Agent spawns specialist agents on-demand during market hours
2. Agents-as-Tools (A2A protocol) for cross-agent delegation
3. Maintenance Window rewrites agent backstories based on performance
4. Trust ladder progression: L0 (shadow) → L1 (1 lot) → L2 (2 lots) → L3 (4 lots) → L4 (full autonomy)

## Traceability

| Category | REQ-IDs | Phase |
|----------|---------|-------|
| Execution Agent | EXE-01 to EXE-04 | 1 |
| Risk Agent | RISK-01 to RISK-04 | 1 |
| Post-Mortem Agent | PMORT-01 to PMORT-05 | 1 |
| Persistence Layer | PERSIST-01 to PERSIST-04 | 1 |
| Registry (Agent/Tool) | REG-01 to REG-04 | 1 |
| RAG + ChromaDB | RAG-01 to RAG-04 | 1 |
| Broker (live wiring) | BROKER-01 to BROKER-06 | 2 |
| Regime Agent | REGIME-01 to REGIME-04 | 2 |
| Strategy Architect | ARCH-01 to ARCH-05 | 3 |
| Portfolio Manager | PM-01 to PM-06 | 4 |
| Margin Agent | MARGIN-01 to MARGIN-04 | 4 |
| Multi-market | MULTI-01 to MULTI-06 | 5 |
| Full autonomy | AUTO-01 to AUTO-08 | 6 |
| **Total** | **~55 requirements** | **6 phases** |
