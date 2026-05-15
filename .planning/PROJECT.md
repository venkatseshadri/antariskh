# Antariksh — Autonomous Intraday Options Trading System

## What This Is

Antariksh is a self-learning, autonomous multi-agent intraday options trading system implementing the Brahmand architecture: CrewAI agents with Pydantic schemas, SQLite persistence, ChromaDB RAG memory, Agent/Tool registries, and a circadian self-improvement rhythm. Primary strategy: NIFTY Iron Butterfly + Credit Spreads via Shoonya/Flattrade brokers. Goal: ₹36L/year passive income for retirement at 50.

## Brahmand Architecture

```
                     ┌─────────────────────────────────┐
                     │     CIRCADIAN RHYTHM            │
                     │                                  │
                     │  08:45 → daily_config.json read  │
                     │  09:15 → 3-agent CrewAI kicks    │
                     │  15:30 → Post-Mortem reviews     │
                     │  15:45 → ChromaDB + config write │
                     └─────────────────────────────────┘

   MARKET HOURS:                          POST-MARKET:
   ┌──────────┐    ┌──────────┐          ┌───────────────┐
   │Execution │ →  │  Risk    │          │ Post-Mortem   │
   │  Agent   │    │  Agent   │          │   Agent       │
   │ Iron     │    │ Mock SL  │          │ state.db read │
   │ Butterfly│    │ RiskLimits│         │ ChromaDB RAG  │
   └──────────┘    └──────────┘          │ → config.json │
         ↓               ↓               └───────────────┘
   ┌──────────────────────────┐
   │   PERSISTENCE LAYER      │
   │  state.db │ ChromaDB     │
   │  daily_config.json       │
   └──────────────────────────┘
```

**Three-tier persistence:** state.db (what happened) → ChromaDB (what we learned) → daily_config.json (what changes tomorrow)

**Expansion path:** Execution + Risk → Post-Mortem → Regime → Architect → PM + Margin → Multi-market → Full autonomy

## Existing Codebase Inventory

**24 agents across 10 crews already built:**

| Crew | Agents | File | Status |
|------|--------|------|--------|
| Trading Desk | 6 (Scout, Researcher, PM, Executioner, Risk Sentry, Leg Shifter) | `trading_desk.py` | Built, mock mode functional |
| TA (Trading Analyst) | 4 (Scout, Validator, Analyst, Compliance) | `crews/ta_crew.py` | Built |
| PM (Portfolio Manager) | 2 (Strategist, Reporter) | `crews/pm_crew.py` | Built |
| AM (Asset Manager) | 2 (P&L Tracker, Reporter) | `crews/am_crew.py` | Built |
| PA (Post-Mortem) | 2 (Reviewer, Pattern Detector) | `crews/pa_crew.py` | Built |
| OM (Operations) | 3 (Pre-flight, Cron, GO/NOGO) | `crews/om_crew.py` | Built |
| CEO (Governance) | 2 (Guardian, Reporter) | `crews/ceo_crew.py` | Built |
| CTO (Tech) | 1 | `crews/cto_crew.py` | Built |
| Dev (Engineer) | 1 | `crews/dev_crew.py` | Built |
| QA (Quality) | 1 | `crews/qa_crew.py` | Built |

**Test coverage:** `tests/test_integration_end_to_end.py` at 39/39. Mock mode functional. No production broker wiring yet.

## Requirements

### Phase 1: Dress Rehearsal (Brahmand MVC) — Active

See `.planning/phases/01-dress-rehearsal/01-CONTEXT.md` for 28 implementation decisions.

- [ ] 3-agent CrewAI system (Execution + Risk + Post-Mortem)
- [ ] Pydantic schemas (TradeSignal, RiskLimits, FlowState, ExecutionReport, ResearchNote)
- [ ] SQLite state.db persistence
- [ ] ChromaDB RAG (research_notes, failure_patterns, improvement_actions collections)
- [ ] Agent Registry (YAML) + Tool Registry (YAML)
- [ ] Agent Factory + Tool Factory patterns
- [ ] daily_config.json circadian rhythm
- [ ] Two-Message Telegram protocol (09:30 + 14:35)
- [ ] Mock mode for all broker calls

### Phase 2: Live Broker + Regime — Deferred

- [ ] Live broker order placement (Shoonya/Flattrade)
- [ ] Live SL/TP placement
- [ ] WebSocket LTP feed
- [ ] TSL engine with real prices
- [ ] Regime Agent (ADX/SuperTrend)

### Validated (Old Phase 1 Monolith — reference)

- ✓ Session orchestrator with cron
- ✓ Event calendar (22 dates)
- ✓ Token refresh (dual broker)
- ✓ Telegram bridge (PicoClaw)
- ✓ 32/32 scenario tests

## Context

**Technical environment:** Python 3.12+, CrewAI multi-agent framework with Flows, DeepSeek LLM for agent cognition, Shoonya + Flattrade broker APIs, DuckDB for market data, ChromaDB for semantic memory, SQLite for operational state, PicoClaw for Telegram integration.

**Design philosophy:** Deterministic tools for risk/execution decisions. LLM cognition only for decisions requiring judgment. Mock mode for all broker calls until production wiring. TDD for new Brahmand components.

**Canonical design:** `/opt/hayagreeva/cloud_sync/CrewAI_Export` — Full Brahmand architecture (5-phase evolution, Agent/Factory + Tool Registry, Communication Schema, Circadian Rhythm, Maintenance Window).

## Constraints

- **Tech stack:** Python 3.12+, CrewAI, DeepSeek LLM, YAML configs, ChromaDB, SQLite
- **Budget:** DeepSeek API costs (LLM calls), Shoonya/Flattrade broker APIs (free), Telegram (free via PicoClaw)
- **Security:** API keys via env vars only; ChromaDB runs locally; repo is private on GitHub
- **Performance:** Parallel CrewAI agent execution; LLM context windows must stay under limits
- **Compatibility:** Phase 1 Brahmand coexists with existing codebase; no breaking changes to tested components

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Brahmand architecture over monolith | Self-learning circadian rhythm, multi-market expansion, A2A protocol — impossible in monolith | Chosen |
| 3-agent MVC (Execution + Risk + Post-Mortem) first | Prove RAG + self-learning loop end-to-end before adding complexity | Chosen |
| Pydantic over Python dataclasses | Validation, serialization, Brahmand's universal language contract | Chosen |
| Custom SQLite over CrewAI built-in persistence | Full control over schema for self-learning; matches Brahmand's daily_config.json pattern | Chosen |
| ChromaDB over CrewAI built-in knowledge_sources | Metadata filtering (date ranges, strategy types, tickers) that built-in can't provide | Chosen |
| YAML for registries | CrewAI documentation uses YAML; Brahmand spec specifies YAML; existing config uses YAML | Chosen |
| Agent Factory over static agents | Enable dynamic agent spawning and multi-market expansion without code changes | Chosen |
| Post-Mortem Agent as self-learning bridge | Owns the full maintenance window: read state.db → query ChromaDB → write config | Chosen |
| Work on existing codebase (not greenfield) | 24 agents, 10 crews, 39/39 integration tests already built — evolve, don't replace | Chosen |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition:**
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

---

*Last updated: 2026-05-13 — Brahmand architecture pivot*
