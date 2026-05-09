# Antariksh — Project State

## Project Reference
See: .paul/PROJECT.md (updated 2026-05-09)

**Core value:** Don't burn capital — all risk gates are hard code, not agent judgment
**Current focus:** Phase 2 — Multi-Crew Ralph Loop Architecture (TDD buildout)

## Loop Position
**Phase:** 2 (of 7) — COMPLETE ✅
**Next:** Phase 3 — Portfolio Manager Crew

## Blockers
- None (01-01 resolved: parsed_value fix + 12 RL tests pass)

## Decisions (accumulated from Phase 1 context)
- D-01: OM crew = 3 agents (PreFlightAgent, CronWatchdog, Reporter)
- D-04: Deterministic checks stay as @tool functions
- D-07: Broker fail chain: Shoonya → Flattrade(margin) → paper → halt
- D-08: Retry: 3 attempts, 1-min gaps
- D-11: OM auto-decides GO/NOGO for paper trades
- D-12: Telegram report MUST include concrete evidence (log lines, values)
- D-13: Separate 8:00 AM cron, not chained to Phase 1
- D-15: Mid-session health → separate systemd watchdog (not Phase 1)
- D-16: 4 RL tests = engine-only (deterministic)
- D-18: PRD reporting = GREEN/YELLOW/RED traffic light
- D-21: PRD change → backtest history against new target
- D-22: OM tests use env-var mocking (ANTARIKSH_MOCK_*)
- D-24: _parse_metric_value() fix needed for bool/% targets
- D-25: CrewAI v1.14.4 `Process.hierarchical` confirmed

## Deferred Decisions
| Decision | When to decide |
|----------|----------------|
| Inter-crew communication protocol | After all crews built (Phase 7) |
| Full autonomy trust ladder (L0→L4) | Phase 3-4 |
| Multi-instrument (SENSEX) | Phase 3 |
| MCX evening trading | Phase 4 |
| Mid-session systemd watchdog | Separate work (not in Phase 1) |

## Session
**Last session:** 2026-05-09 — Phase 1 context gathered (gsd-discuss-phase 1 → migrated to PAUL)
**Next:** /paul:plan 1-01

## Git
- Repo: https://github.com/venkatseshadri/antariskh (private)
- Branch: master

---
*Last updated: 2026-05-09*
