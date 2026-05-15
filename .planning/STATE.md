# Antariksh — Project State

## Project Reference

See: .planning/PROJECT.md

**Core value:** Don't burn capital — all risk gates are hard code, not agent judgment
**Current focus:** Phase 1 (Dress Rehearsal) — Brahmand 3-agent CrewAI MVC

## Current Position

**Phase 1 (Dress Rehearsal):** 🔨 Context gathered
- **Architecture:** 3-agent CrewAI (Execution + Risk + Post-Mortem) with full Brahmand stack
- **Context:** 28 implementation decisions locked in 01-CONTEXT.md
- **Persistence:** Custom SQLite state.db + ChromaDB RAG + daily_config.json
- **Registries:** agents_registry.yaml + tools_registry.yaml (YAML)
- **Schemas:** Pydantic (TradeSignal, RiskLimits, FlowState, ExecutionReport, ResearchNote)
- **Next:** Planning → Research → Execute

**Existing Codebase (24 agents, 10 crews):**
- `trading_desk.py` (1702 lines) — 6-agent desk, Scout→Researcher→PM→Executioner→Risk→Shifter
- `crew_structure.py` (967 lines) — Phase 2 7-agent CrewAI with DeepSeek LLM
- `pipeline_orchestrator.py` — Multi-crew orchestration (CEO, PM, TA, OM, AM, PA)
- `crews/` — CEO, PM, TA, OM, AM, PA, CTO, Dev, QA, TelegramReporter
- `tools/` — execution_tools.py (621), risk_tools.py (606), contract_tools.py (533), etc.
- `tests/test_integration_end_to_end.py` — 39/39 passing
- Reference: monolith `phase1_mvs.py` (499 lines) — dry-run Phase 1, NOT the forward path

**Phase 1 (Old Monolith):** ✅ Complete (reference only)
- Session orchestrator, token refresh, event calendar, executor reports, Telegram bridge
- 32/32 scenario tests passing (engine-only, mock LLM/market)
- 9:30 AM / 2:35 PM cron deployed

## GAP: Mock → Production

See GAPS_AND_ROADMAP.md — 14 mock components need production wiring (Phase 2 priority):
- Broker API order placement, live LTP fills, WebSocket feed, TSL engine, Greek computation, fund balance

## Git

- Repo: https://github.com/venkatseshadri/antariskh (private)
- Branch: master

## Key Files

- Phase 1 Context: `.planning/phases/01-dress-rehearsal/01-CONTEXT.md`
- Brahmand Design: `/opt/hayagreeva/cloud_sync/CrewAI_Export`
- Varaha Design: `/opt/hayagreeva/cloud_sync/Project_Varaha_CrewAI_Design.md`
- Architecture: `ARCHITECTURE.md` (416 lines)
- Gaps & Roadmap: `GAPS_AND_ROADMAP.md` (169 lines)
- Trading Desk: `trading_desk.py` (1702 lines)
- Crew Structure: `crew_structure.py` (967 lines)
- Pipeline Orchestrator: `pipeline_orchestrator.py`
- Config: `config/antariksh_rules.yaml` (302 lines)
- Tests: `tests/test_integration_end_to_end.py` (39/39)

---

*Last updated: 2026-05-13 — Phase 1 Brahmand context gathered*
