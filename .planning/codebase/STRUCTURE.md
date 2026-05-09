# Antariksh Directory Structure

**Date:** 2026-05-09

---

## Top-Level Layout

```
/home/trading_ceo/antariksh/
├── agents/                    # CrewAI agent definitions (EMPTY — deferred to Phase 2)
├── autonomy/                  # Autonomous agent runtime (EMPTY — deferred to Phase 2)
├── config/                    # Configuration files (YAML, JSON)
├── crews/                     # CrewAI crew definitions (EMPTY — single crew defined in crew_structure.py)
├── docs/                      # Reference documents (non-authoritative design docs)
├── exec_reports/              # Generated executive reports (Markdown)
├── harvested/                 # Treated/tagged trade data for retrospective analysis (EMPTY)
├── hitl/                      # Human-in-the-loop modules (EMPTY — deferred)
├── logs/                      # Runtime logs (JSONL audit trails, .log files)
├── ralph/                     # Ralph Loop meta-governance layer (PRDs, constitution, loop logic)
├── scheduler/                 # Cron shell scripts for scheduled execution
├── tests/                     # Test suite (32 scenario tests, fixtures, runner)
├── tools/                     # CrewAI tool definitions (EMPTY — tools defined inline in crew_structure.py)
├── .planning/                 # Planning artifacts (ROADMAP.md, codebase analysis docs)
├── .pytest_cache/             # Pytest cache
├── .venv/                     # Python virtual environment
│
├── session_orchestrator.py    # ENTRY POINT: Phase 1 cron-dispatched session runner
├── phase1_mvs.py              # ENTRY POINT: Phase 1 Minimum Viable System (all business logic)
├── crew_structure.py          # ENTRY POINT: Phase 2 CrewAI (1 agent + 6 tools + engines)
├── backtester.py              # Black-Scholes Iron Fly backtester
├── broker_manager.py          # Dual-broker abstraction (Shoonya + Flattrade)
├── cfo_auditor.py             # CFO audit logger + L1 invariant checks (Phase 1)
├── cron_simulator.py          # Cron job simulator for testing
├── event_calendar.py          # Hardcoded 2026 event dates
├── exec_report.py             # Executive report generator (daily/weekly/monthly)
├── telegram_bridge.py         # Telegram messaging via picoclaw RPC
├── token_refresh_dual.py      # Daily token refresh for Shoonya + Flattrade
├── crew_test.py               # CrewAI test runner
├── test_full_scenario.py      # Full scenario integration test
│
├── CHARTER.md                 # Company charter (authority structure, governance model)
├── CREW_SPEC.md               # Phase 2 crew agent specifications + task flow
├── PHASE_1_DEPLOYMENT_SPEC.md # Phase 1 deployment requirements
├── PHASE1_README.md           # Phase 1 quickstart guide
├── QUICKSTART.md              # General quickstart
├── README.md                  # Project overview
├── SETUP_CRON.md             # Cron setup instructions
├── CLAUDE_MASTER_HANDOFF.md   # Claude-to-Claude handoff document
├── CLAUDE_MASTER_HANDOFF.md   # AI-to-AI handoff document
│
└── *.md (18 additional docs)  # DeepSeek plans, scenario testing, deployment specs
```

---

## Key File Locations by Function

### Entry Points

| File | Purpose | How It's Called |
|------|---------|-----------------|
| `session_orchestrator.py` | Phase 1 cron entry point | `python session_orchestrator.py entry` or `python session_orchestrator.py exit` |
| `phase1_mvs.py` | Phase 1 standalone runner (all logic) | `python phase1_mvs.py` (runs full session) |
| `crew_structure.py` | Phase 2 CrewAI entry point | `python crew_structure.py --mock --vix 18.5 --nifty 24500 --time 10:30` |

### Ralph Loop Governance

| Path | Purpose |
|------|---------|
| `ralph/__init__.py` | Empty package init |
| `ralph/ralph_loop.py` | Ralph Loop implementation (765 lines): RalphLoop, CrewAIRalphLoop, PRDRalphLoop, RalphScheduler, run_ralph_cycle |
| `ralph/constitution.yaml` | Constitution: vision, goals, capital limits, board, authority chain, resource limits |
| `ralph/prds/ceo_prd.yaml` | CEO PRD — 4 metrics, authority can/cannot |
| `ralph/prds/pm_prd.yaml` | Portfolio Manager PRD — 4 metrics |
| `ralph/prds/om_prd.yaml` | Operations Manager PRD — 6 metrics |
| `ralph/prds/ta_prd.yaml` | Trading Analyst PRD — 6 metrics |
| `ralph/prds/am_prd.yaml` | Asset Manager PRD — 6 metrics |
| `ralph/prds/pa_prd.yaml` | Post-Mortem Analyst PRD — 4 metrics |
| `ralph/goals/` | Future goals directory (currently `.gitkeep` only) |

### Configuration Files

| Path | Format | Purpose |
|------|--------|---------|
| `config/antariksh_rules.yaml` | YAML (302 lines) | L3 parameters: capital, strategy, gates, kill switches, LLM tiers, Phase advancement criteria |
| `config/event_calendar.json` | JSON (92 lines) | 22 event dates for 2026 with `skip_trading` flags |
| `ralph/constitution.yaml` | YAML (57 lines) | System constitution with authority chain |

### Runtime Logs

| Path Pattern | Format | Written By |
|-------------|--------|------------|
| `logs/orchestrator_YYYYMMDD.log` | Text | `session_orchestrator.py` |
| `logs/phase1_YYYYMMDD.log` | Text | `phase1_mvs.py` |
| `logs/cfo_audit_YYYYMMDD.jsonl` | JSONL | `cfo_auditor.py` or `crew_structure.py:AuditorEngine` |
| `logs/token_refresh_YYYYMMDD.log` | Text | `token_refresh_dual.py` |
| `logs/scheduler_9am.log` | Text | `scheduler/run_phase1_9am.sh` |
| `logs/scheduler_2pm.log` | Text | `scheduler/run_phase1_2pm.sh` |

### Executive Reports

| Path Pattern | Generator |
|-------------|-----------|
| `exec_reports/DAILY_YYYY-MM-DD.md` | `exec_report.py daily` |
| `exec_reports/WEEKLY_YYYY-MM-DD.md` | `exec_report.py weekly` |
| `exec_reports/MONTHLY_YYYY-MM-DD.md` | `exec_report.py monthly` |

### Scheduler Scripts

| Path | Purpose | Runs |
|------|---------|------|
| `scheduler/run_phase1_9am.sh` | 9:30 AM entry gate | `python3 phase1_mvs.py` |
| `scheduler/run_phase1_2pm.sh` | 2:35 PM exit report | `python3 phase1_mvs.py` |

### Test Suite

| Path | Purpose |
|------|---------|
| `tests/__init__.py` | (not present) |
| `tests/test_scenarios.py` | 32 scenario tests (HP=4, RM=6, DD=4, MC=5, SF=5, OP=3, LC=3, EC=2) |
| `tests/scenario_runner.py` | Context manager for mock injection, state reset, assertions |
| `tests/run_all.sh` | Shell script to run all scenarios + generate report |
| `tests/results.json` | Pytest JSON report output |
| `tests/generate_report.py` | Converts JSON results to markdown report |
| `tests/fixtures/__init__.py` | Fixtures package init |
| `tests/fixtures/mock_llm.py` | Mock LLM response fixtures |
| `tests/fixtures/mock_broker.py` | Mock broker response fixtures |
| `tests/fixtures/seed_history.py` | JSONL seed data generators (`seed_jsonl`, `seed_consecutive_losses`, `seed_30day_dd_at_threshold`) |

---

## Where Each Crew Lives

### Phase 1 (Deterministic Pipeline)

All crew logic is contained in `phase1_mvs.py` as static classes:

| Class | Lines | Role |
|-------|-------|------|
| `Phase1Config` | 43–78 | Configuration constants (times, capital, gate, trade) |
| `MarketDataBridge` | 96–162 | Unified market data (VIX, NIFTY, event calendar, expiry calc) |
| `GateChecker` | 168–233 | 3-layer gate (regime, signal, confirmation) |
| `TradeDecisionEngine` | 239–277 | Iron Fly trade plan generation |
| `TelegramBridge` | 283–369 | Two-Message Protocol sender |
| `CFOAuditor` | 375–405 | Audit logging |
| `Backtester` | 411–436 | Mock P&L backtester (TODO: real) |
| `Phase1Orchestrator` | 442–492 | Main orchestrator that chains all steps |

### Phase 2 (CrewAI Multi-Agent)

All crew logic is in `crew_structure.py` (850 lines):

| Class/Function | Lines | Role |
|---------------|-------|------|
| `scan_market` (tool) | 90–133 | Layer 1 gate check |
| `generate_trade_plan` (tool) | 136–172 | Iron Fly basket generator |
| `check_risk` (tool) | 175–195 | Risk Guard L1 check |
| `execute_trade` (tool) | 198–228 | Order placement (stubbed) |
| `monitor_positions` (tool) | 231–260 | MTM P&L tracker |
| `log_audit` (tool) | 263–291 | Audit logging |
| `orchestrator` (Agent) | 298–318 | CrewAI agent with 6 tools + DeepSeek LLM |
| `run_session_task` (Task) | 325–342 | Full session task description |
| `AuditorEngine` | 349–490 | Deterministic auditor: reads Phase 1 logs, calculates MTD, validates L1, appends sessions |
| `RiskGuardEngine` | 497–611 | Deterministic risk guard: 5 L1 checks (daily SL, portfolio SL, 30-day DD, free cash floor, burn rate) |
| `ReEntryTracker` | 618–650 | Tracks re-entry attempts per session (max 1) |
| `initialize_session()` | 657–669 | Pre-session init: loads Phase 1 audit trail, calculates MTD |
| `_build_crew()` | 678–688 | Lazy crew builder (no LLM on import) |
| `run_entry_session()` | 694–728 | Entry workflow |
| `run_exit_session()` | 731–759 | Exit workflow |
| `run_full_session()` | 763–797 | Full session in one kickoff |
| `run_risk_halt_test()` | 800–819 | Risk guard autonomous halt test |

---

## Naming Conventions

### Python Files
- **snake_case** for modules: `session_orchestrator.py`, `broker_manager.py`, `cfo_auditor.py`, `exec_report.py`
- **PascalCase** for classes: `Phase1Orchestrator`, `GateChecker`, `RiskGuardEngine`, `AuditorEngine`
- **UPPER_CASE** for class constants: `ENTRY_TIME`, `DAILY_SL`, `MIN_FREE_CASH`
- **snake_case** for functions/methods: `check_gate()`, `calculate_mtd_from_logs()`, `run_full_session()`

### YAML Files
- **snake_case** for config keys: `capital_floor`, `burn_rate_max`, `entry_open_ist`
- **space-indented** (2 spaces per YAML convention)

### JSON Files
- **snake_case** for keys: `skip_trading`, `gate_pass`, `session_pnl`

### Log Files
- Pattern: `{module}_{YYYYMMDD}.{ext}` — e.g., `phase1_20260509.log`, `cfo_audit_20260509.jsonl`

### Report Files
- Pattern: `{TYPE}_{YYYY-MM-DD}.md` — e.g., `DAILY_2026-05-08.md`, `EXEC_REPORT_2026-05-08.md`

### Test Functions
- Pattern: `test_{CATEGORY}_{NN}_{description}` — e.g., `test_HP_01_clean_win`, `test_RM_03_portfolio_sl_breach`

---

## Empty/Deferred Directories

These directories exist as placeholders for future Phase 2+ development:

| Directory | Planned For |
|-----------|-------------|
| `agents/` | Individual CrewAI agent definitions (Scanner, Strategist, Executor, Sentinel, Risk Guard, Auditor) |
| `autonomy/` | Autonomous agent runtime for Vishnu CEO agent |
| `crews/` | Multi-crew definitions (PM crew, OM crew, TA crew, AM crew, PA crew) |
| `tools/` | Separated tool files per agent (currently tools are defined inline in `crew_structure.py`) |
| `harvested/` | Treated/tagged trade data for retrospective analysis and PA reviews |
| `hitl/` | Human-in-the-loop approval workflows for parameter changes and strategy switches |
| `ralph/goals/` | Future goal definitions beyond PRDs |

---

## Supporting Files (Non-Code)

| File | Purpose |
|------|---------|
| `CHARTER.md` | Company charter — ratified 2026-05-08; authority structure, three-layer governance model |
| `CREW_SPEC.md` | Phase 2 crew agent role specs and task flow for all 7 agents |
| `PHASE_1_DEPLOYMENT_SPEC.md` | Phase 1 deployment requirements and milestones |
| `PHASE1_README.md` | Phase 1 quickstart and architecture overview |
| `README.md` | Project-level README |
| `QUICKSTART.md` | Environment setup and first-run instructions |
| `SETUP_CRON.md` | Cron job installation and validation instructions |
| `RALPH_LOOP_ANALYSIS.md` | Design analysis of Ralph Loop integration |
| `ralph_loop.md` | Ralph Loop concept document |
| `ralph_loop_full_reference.md` | Complete Ralph Loop reference |
| `CREWAI_VS_LANGGRAPH_DEEPSEEK.md` | CrewAI vs LangGraph comparison for DeepSeek |
| `DEEPSEEK_EXECUTION_PLAN.md` | DeepSeek integration execution plan |
| `DEEPSEEK_HANDOFF.md` | DeepSeek handoff documentation |
| `DEEPSEEK_REPORT.md` | DeepSeek project report |
| `DEEPSEEK_STATUS_LOG.md` | DeepSeek implementation status |
| `DEEPSEEK_TESTING_HANDOFF.md` | DeepSeek testing handoff |
| `CRITICAL_FIXES_REQUIRED.md` | List of critical fixes needed |
| `EXEC_REPORTING_FRAMEWORK.md` | Executive reporting framework specification |
| `ISSUE_UPDATE_DeepSeek.md` | Issue tracking for DeepSeek |
| `diagnostic_pending_scenarios.md` | Pending scenario diagnostics |
| `PICOCLAW_INSTRUCTIONS.md` | picoclaw integration instructions |
| `SCENARIO_COVERAGE_AND_GAPS_ANALYSIS.md` | Scenario coverage analysis |
| `SCENARIO_TEST_PLAN.md` | Scenario test plan |
| `SCENARIO_TEST_RESULTS.md` | Generated test results report |
| `SCENARIO_TESTING_ANALYSIS.md` | Scenario testing analysis |
| `TESTING_INFRASTRUCTURE.md` | Testing infrastructure documentation |
| `README_DEEPSEEK_START_HERE.md` | DeepSeek getting started guide |
| `CLAUDE_MASTER_HANDOFF.md` | AI-to-AI handoff document |
| `docs/Project_Varaha_CrewAI_Design.md` | Reference CrewAI design (non-authoritative) |
| `docs/Varaha_Sovereign_Constitution.md` | Governance overlay (non-authoritative) |
| `docs/Varaha_Sovereign_Constitution.pdf` | Constitution PDF |
| `docs/Varaha.pdf` | Varaha document PDF |

---

## External Dependencies (Outside `antariksh/`)

The system depends on code in `/home/trading_ceo/python-trader/`:

| Path | Purpose |
|------|---------|
| `python-trader/Shoonya_oAuthAPI-py/` | Shoonya broker SDK: `api_helper.py`, `GetAuthcode.py`, `cred.yml` |
| `python-trader/get_flattrade_token_auto.py` | Flattrade auto-OAuth token script |
| `python-trader/tokens.json` | Flattrade token storage |
| `python-trader/varaha/STRATEGY_DESIGN_QUESTIONS.md` | L1 Constitution (canonical strategy decisions document) |

Picoclaw integration at `/root/.picoclaw/`:
- `/root/.picoclaw/telegram_send.sh` — legacy shell script sender
- `/root/.picoclaw/rpc.py` — Python RPC handler
