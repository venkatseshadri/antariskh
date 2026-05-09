# Antariksh — Autonomous Intraday Options Trading System

## Core Value

Don't burn capital. Every trade decision passes through hard runtime risk gates (₹3,500 daily SL, ₹4,500 portfolio SL, VIX<20 skip, 19 sanity checks) enforced in code, not agent judgment.

## What We're Building

Autonomous multi-crew trading system for NIFTY intraday options (Iron Butterfly + Credit Spread strategies) via Shoonya/Flattrade brokers. 4-crew hierarchical organization under CEO governance with Ralph Loop PRD-driven verification. Goal: ₹36L/year passive income for retirement at 50.

**Phase 1 (live):** Monday-ready dry-run — session orchestrator, token refresh, event calendar, Telegram bridge, 32/32 tests passing.

**Phase 2 (current):** Multi-crew Ralph Loop architecture — Operations Manager, Trading Analyst, Portfolio Manager, Asset Manager, Post-Mortem Analyst, CEO. TDD: 120 tests, 0 crews built yet.

## Requirements

### Validated (Phase 1)
- Session orchestrator with 9:30 AM / 2:35 PM cron
- Event calendar (22 NSE holiday/RBI dates)
- Token refresh (Shoonya + Flattrade dual-broker)
- Telegram bridge (PicoClaw) with HITL gates
- Executor reports (JSON) with Two-Message Protocol
- 32/32 scenario tests passing
- Ralph Loop constitution + 6 PRDs
- Ralph Loop engine (8 classes)

### Active (Phase 2)
- OPS-01..08: Operations Manager crew (17 tests)
- RAL-01..04: Ralph Loop infrastructure tests (4 tests)
- TRA-01..07: Trading Analyst crew (15 tests)
- PM-01..07: Portfolio Manager crew (12 tests)
- AM-01..07: Asset Manager crew (11 tests)
- PA-01..06: Post-Mortem Analyst crew (14 tests)
- CEO-01..06: CEO crew (20 tests)
- GA-01..15: Governance & Alignment (15 tests)
- INT-01..08: Inter-crew communication (12 tests)

### Out of Scope
- MCX evening trading — Phase 3-4
- SENSEX instruments — Phase 3
- Full autonomy (L4 trust ladder) — Phase 4
- Multi-strategy simultaneous execution — capped at 2
- Manual trading interface

## Constraints
- **Stack:** Python 3.12, CrewAI 1.14.4, DeepSeek LLM, YAML, pytest
- **Timeline:** Phase 1 live Monday; Phase 2 TDD timeline TBD
- **Security:** API keys env-only; repo private
- **Compatibility:** Must coexist with Phase 1 (parallel: Phase 1 live, Phase 2 shadow)

## Key Decisions
| Decision | Rationale | Outcome |
|----------|-----------|---------|
| 4-crew hierarchy + CEO | Proper separation of concerns | Pending |
| Ralph Loop PRD verification | Meta-governance above CrewAI | Pending |
| TDD with 120 tests | Architectural safety net | Pending |
| Start with OM + TA | Immediate infra + validation needs | Active |
| CrewAI 1.14.4 + Process.hierarchical | Multi-crew CEO governance | Confirmed |
| DeepSeek LLM over GPT-4 | Cost efficiency | Good |

---
*Last updated: 2026-05-09*
