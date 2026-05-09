# Phase 1: Ralph Loop Infrastructure Tests + OM Crew - Context

**Gathered:** 2026-05-09
**Status:** Ready for planning

<domain>
## Phase Boundary

Foundation verification for Phase 2 governance: prove the Ralph Loop engine works under test (4 tests), and build the Operations Manager crew (3-agent pre-flight infra watchdog) with 17 tests. All 21 tests are engine-only — no LLM required for deterministic infrastructure verification. OM delivers pre-flight readiness checklist, auto-decides GO/NOGO for paper trading, and sends evidence-backed Telegram reports at 8:00 AM IST.
</domain>

<decisions>
## Implementation Decisions

### OM Crew Architecture
- **D-01:** 3-agent crew: PreFlightAgent (tokens, code verification, data capture, disk, network checks), CronWatchdog (cron health + scheduling validation), Reporter (assembles evidence-backed health report for CEO)
- **D-02:** All deterministic checks are `@tool` functions, not agent cognition. Agents only decide GO/NOGO and generate the natural-language CEO report
- **D-03:** LLM cost of 3 agents vs 1 is negligible (~$0.12/month difference with DeepSeek)
- **D-04:** This is the FIRST proper multi-agent crew — the prior criticism was about 1 agent running the entire company, not about focused crews

### OM Test Organization
- **D-05:** `tests/test_om_crew.py` — 17 tests, one file. Follow existing test naming convention: `test_OM_{NN}_{descriptive_name}`
- **D-06:** RL tests go in `tests/test_ralph_loop.py` — 4 engine-only tests

### Pre-Flight Failure Policy
- **D-07:** Broker token failure fallback chain: Shoonya → Flattrade (check margin availability) → paper trade → halt session
- **D-08:** Retry policy: max 3 retries with 1-minute gaps between attempts (prevents broker lockout)
- **D-09:** Non-broker failures (disk, network, data stream): all initially classified as CRITICAL/WARNING and reported to CEO. Gradual auto-downgrade as system builds confidence over time
- **D-10:** Disk full, network down, DuckDB data dead = halt-level. Cron not running = warning-level (OM can manual-trigger)
- **D-11:** GO/NOGO authority: OM auto-decides for paper trades. All failures surfaced to Chairman via Telegram. OM does NOT wait for Chairman approval
- **D-12:** Telegram report MUST include concrete evidence (log lines, timestamps, actual values, disk %, broker latency) — un-hallucinatable proof that the system actually ran

### OM Schedule & Integration
- **D-13:** OM runs as separate cron at 8:00 AM IST — not chained to Phase 1's session_orchestrator.py
- **D-14:** If OM is down, Phase 1 still runs at 9:30 AM in legacy mode (pre-OM behavior)
- **D-15:** Mid-session health monitoring (9:15-3:30) is NOT in Phase 1 scope. Separate systemd watchdog for broker connectivity + system health — independent of CrewAI crews

### Ralph Loop Test Scope
- **D-16:** All 4 RL tests are engine-only (deterministic, no LLM). RL-01: scheduler timing + correct crew selection. RL-02: YAML parsing (happy path, missing file, malformed, missing fields). RL-03: escalation counter increment. RL-04: metric history accumulation + min_samples suggestion logic
- **D-17:** Crew output vs PRD validation comes in crew-specific phases (Phase 2 TA, Phase 3 PM, etc.), not in Phase 1 infrastructure tests

### PRD Verification Pattern
- **D-18:** Traffic light reporting: GREEN (≥ target), YELLOW (≥ floor, < target), RED (< floor). RED escalates to Chairman after N consecutive failures
- **D-19:** `progress_pct` added to VerificationResult alongside status enum — shows how close to target
- **D-20:** `min_samples` pattern: DATA_IMMATURE if < min_samples (never FALSE-PASS). Verification runs but status reflects immaturity
- **D-21:** On PRD change: backtest existing history against new target. Show comparison (old PRD: X/Y → new PRD: would-be Z/A). Fresh verification starts. Historical data archived for insights

### Mocking Strategy
- **D-22:** OM tests use env-var mocking pattern (same as Phase 1): `ANTARIKSH_MOCK_DISK_FULL=1`, `ANTARIKSH_MOCK_BROKER_DOWN=1`, `ANTARIKSH_MOCK_CRON_DEAD=1`, `ANTARIKSH_MOCK_NETWORK_DOWN=1`
- **D-23:** OM tools check env vars before real system calls — consistent with Phase 1's MockBrokerManager pattern

### Ralph Loop Readiness Gap
- **D-24:** `ralph_loop.py:_parse_metric_value()` cannot parse boolean ("True"/"False") or percentage ("100%", "≤80%") targets from PRD YAMLs. Must be fixed BEFORE RL-02 test is written. Fix is isolated to `_parse_metric_value()` in `ralph/ralph_loop.py:195-210`

### CrewAI Compatibility
- **D-25:** CrewAI v1.14.4 installed — `Process.hierarchical` confirmed available for multi-crew CEO governance in later phases

### the agent's Discretion
- Test execution ordering: RL tests first (infrastructure), then OM tests (crew). Enforced by convention, not CI
- Test helper functions: create reusable helpers for common OM failure scenarios
- OM tools can be built as standalone Python modules in `tools/` before wiring into CrewAI crew
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Ralph Loop Foundation
- `ralph/constitution.yaml` — Vision, mission, capital limits, authority chain, resource limits per crew
- `ralph/ralph_loop.py` — RalphLoop, CrewAIRalphLoop, PRDRalphLoop, RalphScheduler, VerificationResult, load_prd_yaml (needs fix per D-24)
- `ralph/prds/om_prd.yaml` — OM PRD: pre_flight_pass, tokens_refreshed, uptime_pct, backup_verified, code_unchanged, disk_ok, cron_active, reporter_ready

### Project Governance
- `.planning/PROJECT.md` — Core value (don't burn capital), constraints, key decisions
- `.planning/REQUIREMENTS.md` — 55 requirements across 7 phases, traceability matrix
- `.planning/ROADMAP.md` — Phase structure, success criteria, requirement mapping
- `config/antariksh_rules.yaml` — L3 parameters (capital, strategy, gate, sanity checks, kill switches)

### Testing Reference
- `.planning/codebase/TESTING.md` — Test patterns, ScenarioRunner, engine-only tests, mocking layers
- `.planning/codebase/CONVENTIONS.md` — Code style, @tool decorator patterns, error handling
- `tests/scenario_runner.py` — Context manager for mock injection (Phase 1 pattern, may extend for Phase 2)
- `tests/test_scenarios.py` — 32 existing scenario tests (8 categories, naming convention)

### Existing Crew Infrastructure
- `crew_structure.py` — Current CrewAI setup (1 Orchestrator + 6 tools), RiskGuardEngine, AuditorEngine, market_state dict
- `.planning/codebase/ARCHITECTURE.md` — Full system design, data flow, module boundaries
- `.planning/codebase/STACK.md` — Python 3.12, CrewAI 1.14.4, DeepSeek, YAML, pytest
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **RALPH LOOP ENGINE** (`ralph/ralph_loop.py`): 8 classes already built — RalphLoop, CrewAIRalphLoop, PRDRalphLoop, RalphScheduler, RolePRD, VerificationResult, load_prd_yaml, run_ralph_cycle. Only `_parse_metric_value()` needs the fix from D-24
- **PRD YAMLs** (`ralph/prds/*.yaml`): 6 PRDs with target/floor/min_samples metrics, authority can/cannot lists, frequency schedules. Ready to load after parser fix
- **Constitution** (`ralph/constitution.yaml`): Immutable vision/goals/limits/authority — not modified in this phase
- **ScenarioRunner** (`tests/scenario_runner.py`): Existing mock injection context manager — extendable for OM mock scenarios
- **MockBrokerManager** (`tests/fixtures/mock_broker.py`): Env-var based broker mocking — pattern to follow for OM tools
- **Telegram Bridge** (`telegram_bridge.py`): Already works — OM Reporter uses this for evidence-backed CEO report

### Established Patterns
- **TDD mandatory**: Write tests first, get user review, then build. Do NOT move to next step without passing tests
- **Engine-only for deterministic**: Pure math/parsing/counting logic tested without LLM. CrewAI integration tested with ScenarioRunner
- **`@tool` decorator**: Deterministic tools use CrewAI's `@tool` decorator (see `crew_structure.py` for examples)
- **Env-var mocking**: `ANTARIKSH_MOCK_*` env vars control mock behavior at runtime. Tool-level checks before real system calls
- **Singleton pattern**: `broker_manager.py:get_broker_manager()`, `cfo_auditor.py:get_cfo_auditor()` — OM may use similar for system health state
- **Test naming**: `test_{CATEGORY}_{NN}_{descriptive_name}` — e.g., `test_OM_01_token_refresh_both_fail`, `test_RL_01_scheduler_picks_correct_crew`

### Integration Points
- **Separate cron at 8:00 AM**: New cron entry for OM pre-flight. Does NOT modify existing 9:30 AM / 2:35 PM crons
- **Phase 1 remains unchanged**: OM writes GO/NOGO + report to a well-known path. Phase 1 reads it (or runs legacy mode if absent)
- **Ralph Loop tests are standalone**: Do not modify `crew_structure.py` or `phase1_mvs.py`
- **OM crew is a NEW CrewAI crew**: Separate from the existing Orchestrator in `crew_structure.py`. Multiple crews coexist under CEO in later phases
</code_context>

<specifics>
## Specific Ideas

- **Telegram evidence format:** Each health check includes concrete data — "Shoonya token: REFRESHED at 07:02:15 IST (last line: 'SUCCESS — token valid until 08:02')", "Disk: 45% free (234GB/512GB)", "Broker latency: 120ms (Shoonya), 85ms (Flattrade)"
- **Cron health check:** Verify actual crontab entries, not just process existence — compare against expected entries in `config/antariksh_rules.yaml`
- **Pre-flight report timeout:** If OM doesn't send Telegram by 8:05 AM, Chairman knows the system is down (implicit heartbeat failure detection)
- **Retry with exponential backoff concerns:** User explicitly chose 3 retries with 1-minute fixed gaps — broker lockout prevention is the priority
</specifics>

<deferred>
## Deferred Ideas

- **Mid-session watchdog:** Separate systemd service for broker connectivity + system health during 9:15-3:30. NOT in Phase 1. Independent of CrewAI crews
- **Confidence-based auto-downgrade:** Failure severity auto-downgraded as OM builds operational history. Deferred until OM has sufficient production data
- **MCX evening pre-flight:** User mentioned future evening trading. OM's 8:00 AM cron design is reusable — just add a second cron entry
- **OM as always-on daemon:** Continuous running watchdog instead of cron-triggered. Deferred — separate systemd watchdog handles this
- **Sentinel agent:** Original Phase 1 design had a Sentinel for mid-session monitoring. Absorbed into TA (position monitoring) + systemd watchdog (system health)
</deferred>

---

*Phase: 1-Ralph Loop Infrastructure Tests + OM Crew*
*Context gathered: 2026-05-09*
