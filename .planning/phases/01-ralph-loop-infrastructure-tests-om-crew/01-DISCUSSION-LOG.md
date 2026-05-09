# Phase 1: Ralph Loop Infrastructure Tests + OM Crew - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-09
**Phase:** 1-ralph-loop-infrastructure-tests-om-crew
**Areas discussed:** OM crew architecture, Pre-flight failure policy, Ralph Loop test scope, PRD verification pattern, Test file organization, OM/Phase 1 integration, Mocking strategy, Watchdog scope, CrewAI compatibility, Ralph Loop readiness

---

## OM Crew Architecture

| Option | Description | Selected |
|--------|-------------|----------|
| 1 agent + 8 tools | Single agent with @tool functions (Phase 1 pattern) | |
| 3 specialized agents | PreFlightAgent (tokens/code/data/disk/network), CronWatchdog, Reporter | ✓ |
| 8 agents (one per requirement) | Maximum parallelism, most LLM cost | |

**User's choice:** 3 agents — PreFlightAgent, CronWatchdog, Reporter. User challenged the assumption that multi-agent is always better, noted LLM cost concern. Cost analysis showed $0.12/month difference (negligible).

**Notes:** User's prior criticism was about 1 agent for the ENTIRE company, not about a focused crew. Deterministic checks remain as @tool functions regardless of agent count.

---

## Pre-Flight Failure Policy

| Option | Description | Selected |
|--------|-------------|----------|
| Halt session | No tokens = halt. Safest | |
| Proceed with warning | Hope token refresh works mid-session | |
| Retry first, then decide | 3 retries, 1-min gaps, then decide | ✓ (for paper mode) |
| Context-dependent | Paper: proceed with Flattrade. Real: halt (Shoonya margin) | ✓ |
| Always halt on any token fail | Simple, one rule | |
| Shoonya-critical only | Flattrade fail = warn, Shoonya fail = halt | |
| OM auto-decides (paper) | OM makes GO/NOGO, paper trades are zero-risk | ✓ |
| Always ask Chairman | Telegram message, wait for response | |
| Ask Chairman for CRITICAL | CRITICAL = ask, WARNING = auto | |
| Disk/network/data = HALT; crons = WARN | Specific non-broker failure classification | ✓ |
| All failures = HALT | Safest | |
| Tiered: CRITICAL/WARNING | Classify by severity, configurable thresholds | ✓ (with gradual downgrade) |

**User's choice:** Fallback chain: Shoonya → Flattrade (check margin) → paper → halt. Retry 3x with 1-min gaps. OM auto-decides GO/NOGO for paper. All failures reported to CEO initially, gradual downgrading as confidence builds. Telegram must include concrete evidence (log lines, timestamps, values).

**Notes:** "if the expectation is real trade, but Shoonya fails, then notify ceo can't take real trade in shoonya, checking if alternate trade in flattrade is possible with the available FlatTrade margin, if not possible then go with paper trade." — Venkat

---

## Ralph Loop Test Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Mixed: engine for 3, integration for 1 | Scheduler/parsing/evolution = engine. Escalation = integration | |
| All engine-only | 4 deterministic unit tests, fast, no LLM | ✓ |
| All integration | Load real YAMLs, run full cycle | |
| Split: engine scheduler + integration cycle | RL-01 as two-part test | |
| Integration only for RL-01 | E2E proof of Ralph Loop | |

**User's choice:** All 4 engine-only. RL-01 verifies scheduler timing + correct crew selection. Crew output vs PRD validation comes in crew-specific phases. "If its deterministic then engine-only is fine. Anytime PRD verification is involved then integration is required."

**Notes:** Big picture discussed — Ralph Loop exists for expectation vs reality comparison. Engine-only tests verify infrastructure. Crew output validation happens in Phase 2-6 when each crew is built.

---

## PRD Verification Pattern

| Option | Description | Selected |
|--------|-------------|----------|
| Binary + progress % | met/unmet + numeric progress (50% toward target) | |
| Binary only | met or unmet, no nuance | |
| Traffic light (GREEN/YELLOW/RED) | 3 states: above target, above floor, below floor | ✓ |
| Reset on PRD change | Fresh verification, old data archived | |
| Keep all history, same rules | Old sessions verified against new target | |
| Per-version tracking | Tag data by PRD version | |
| Backtest on PRD change | Show comparison, fresh verification, history archived | ✓ |
| Seed min_samples from history | Use history to jumpstart new PRD | |
| Always reset (simple) | Clean slate regardless | |

**User's choice:** GREEN/YELLOW/RED traffic light. On PRD change, backtest history against new target, show side-by-side comparison. Fresh verification starts. Historical data preserved for insights. "For now i am ok with 1 [reset], but if the history win rate can be used, then why throw away the information?"

**Notes:** User raised concern about PRD reduction — if target lowered, old sessions may already meet new target. Backtest-on-change addresses this.

---

## Test File Organization

| Option | Description | Selected |
|--------|-------------|----------|
| New files per crew | tests/test_ralph_loop.py + tests/test_om_crew.py | ✓ |
| Expand existing | test_scenarios.py grows to 53 tests | |
| Categorized new files | Sub-classes within test files | |

**User's choice:** New files per crew. Follows Phase 2's crew-by-crew structure. Each crew's tests surface separately in code review.

---

## OM/Phase 1 Integration

| Option | Description | Selected |
|--------|-------------|----------|
| Pre-flight cron at 8:00 AM | Separate cron, OM writes GO/NOGO to file | ✓ |
| OM called by session_orchestrator | Single cron entry, tighter coupling | |
| OM as always-on watchdog | systemd service, continuously running | |
| Separate systemd watchdog | Mid-session health separate from OM | ✓ |

**User's choice:** Separate 8:00 AM cron. Rationale: "i prefer seperate cron, as i tomorrow i can have a remediation between 8 to 9:15 to fix before trading hour starts, also if tomorrow i add mcx trading in the evening, i don't need a seperate check in the evening." Mid-session health handled by separate systemd watchdog.

---

## Mocking Strategy for OM Tests

| Option | Description | Selected |
|--------|-------------|----------|
| Extend env-var pattern | ANTARIKSH_MOCK_DISK_FULL etc. | ✓ |
| unittest.mock patching | Python mock for system calls | |
| Fixture-based mocking | Reusable test classes | |

**User's choice:** Env-var pattern (same as Phase 1). Consistent with existing MockBrokerManager and ScenarioRunner.

---

## the agent's Discretion

- Test execution order: RL tests first, then OM tests
- OM tools can be built as standalone Python modules in `tools/` before CrewAI wiring
- Reusable test helpers for common OM failure scenarios

## Deferred Ideas

| Idea | Reason |
|------|--------|
| Mid-session watchdog (9:15-3:30) | Separate systemd service, not Phase 1 |
| Confidence-based severity auto-downgrade | Needs operational history first |
| MCX evening pre-flight | Future phase, OM design is reusable |
| OM as always-on daemon | Replaced by separate systemd watchdog |
