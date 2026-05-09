# Antariksh — Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-09)

**Core value:** Don't burn capital — all risk gates are hard code, not agent judgment
**Current focus:** Phase 2 — Multi-Crew Ralph Loop Architecture (TDD buildout)

## Current Position

**Phase 1:** ✅ Complete (Monday-ready dry-run)
- Session orchestrator, token refresh, event calendar, executor reports, Telegram bridge
- 32/32 scenario tests passing (engine-only, mock LLM/market)
- 9:30 AM / 2:35 PM cron deployed
- Broker connectivity via Shoonya + Flattrade (token refresh dual)

**Phase 2:** 🔨 In Progress (Ralph Loop multi-crew architecture)
- Ralph Loop foundations: ✅ constitution.yaml, 6 PRDs, ralph_loop.py (8 classes), goals/
- GSD alignment: ✅ codebase map (7 docs), PROJECT.md, config.json, REQUIREMENTS.md, ROADMAP.md
- Crews to build: OM (17 tests), TA (15), PM (12), AM (11), PA (14), CEO (20) — 0 built
- Integration: GA (15), INT (12) — 0 built
- Next: RL-01 to RL-04 Ralph Loop tests → OM crew → TA crew → ...

## Current Milestone

**Milestone:** Phase 2 MVP — shadow/dry-run parallel to Phase 1 live
**Phase:** 1 (of 7) — Ralph Loop Infrastructure Tests + OM Crew
**Requirements:** RAL-01 to RAL-04, OPS-01 to OPS-08 (12 total)
**Status:** Not started
**Blockers:** None

## Recent Changes

| Date | What | Why |
|------|------|-----|
| 2026-05-09 | GSD alignment: map-codebase + new-project artifacts | Structure Phase 2 build with spec-driven process |
| 2026-05-09 | Hardcoded DeepSeek API key redacted from crew_structure.py | Security — now env-only |
| 2026-05-09 | GitHub repo created (venkatseshadri/antariskh) | Version control for Phase 2 |
| 2026-05-09 | 6 PRD YAMLs created (ceo, pm, om, ta, am, pa) | Ralph Loop verification targets |
| 2026-05-09 | Ralph Loop engine built (8 classes) | Governance foundation |
| 2026-05-09 | constitution.yaml ratified | Immutable vision/goals/limits/authority |
| 2026-05-09 | Phase 1 ISSUE_UPDATE: event_calendar.py is_event_day() fixed | Prevent trading on RBI/Budget/holidays |
| 2026-05-08 | Phase 1 dry-run built: orchestrator, token refresh, exec reports, Telegram | Monday-ready |
| 2026-05-08 | 32 scenario tests written and passing | Phase 1 verification |

## Deferred Decisions

| Decision | Context | When to decide |
|----------|---------|----------------|
| Inter-crew communication protocol | File-based vs shared dict vs call chain | After all crews built (Phase 7) |
| Full autonomy trust ladder | L0→L4 progression | Phase 3-4 |
| Multi-instrument (SENSEX) | Additional market | Phase 3 |
| MCX evening trading | Additional session | Phase 4 |
| CEO Vishnu avatar implementation | Current interim CEO (Claude) placeholder | Phase 2+ |

## Active Agents

- Chairman: trading_ceo (user)
- Director: claude (advisory + interim CEO)
- CEO Vishnu: Not yet built (Phase 2+)

## Git

- Repo: https://github.com/venkatseshadri/antariskh (private)
- Branch: master
- Last commit: 06f4b15 — "feat: full Antariksh autonomous trading system"

## Key Files

- Constitution: ralph/constitution.yaml
- PRDs: ralph/prds/ (6 files: ceo, pm, om, ta, am, pa)
- Ralph Loop: ralph/ralph_loop.py
- Phase 1 MVS: phase1_mvs.py
- Crew Structure: crew_structure.py
- Rules: config/antariksh_rules.yaml
- Event Calendar: config/event_calendar.json
- Tests: tests/test_scenarios.py (32 passing)
- GSD Planning: .planning/ (PROJECT.md, config.json, REQUIREMENTS.md, ROADMAP.md, STATE.md)

---
*Last updated: 2026-05-09 after GSD project initialization*
