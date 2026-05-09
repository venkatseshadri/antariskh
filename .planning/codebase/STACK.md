# Antariksh Technology Stack

**Generated:** 2026-05-09
**Focus:** TECH — Languages, runtime, frameworks, libraries, dependencies, configuration

---

## 1. Language & Runtime

| Attribute | Value | Source |
|---|---|---|
| Language | Python 3.12.3 | `.venv/pyvenv.cfg:3-4` |
| Interpreter | `/usr/bin/python3.12` (CPython) | `.venv/pyvenv.cfg:4` |
| Environment | Virtual environment at `.venv/` | `.venv/pyvenv.cfg:1` |
| Shebang | `#!/usr/bin/env python3` | All `.py` files |

---

## 2. Dependency Management

**No formal dependency manifest exists.** There is no `requirements.txt`, `pyproject.toml`, `setup.py`, `setup.cfg`, or `package.json` anywhere in the project tree. All dependencies are installed directly into the `.venv/` virtual environment.

### Detected Libraries (from import analysis)

| Library | Usage | Files |
|---|---|---|
| **crewai** | Multi-agent orchestration framework (Agent, Task, Crew, Process, LLM, `@tool` decorator) | `crew_structure.py:27-29` |
| **pyyaml** | YAML config parsing (rules, creds, PRDs) | `broker_manager.py:48`, `ralph_loop.py:33` |
| **requests** | HTTP client for broker API calls | `broker_manager.py:15` |
| **scipy** | Statistical functions for Black-Scholes (scipy.stats.norm) | `backtester.py:26,36` |
| **croniter** | Cron expression parsing (optional) | `ralph_loop.py:39` |
| **pytest** | Test framework (v9.0.2 detected) | `tests/test_scenarios.py`, `tests/scenario_runner.py` |
| **pytest-json-report** | JSON test report output | `tests/run_all.sh:11` |

### Standard Library Dependencies

`json`, `pathlib`, `datetime`, `logging`, `subprocess`, `argparse`, `typing`, `os`, `sys`, `math`, `tempfile`, `re`, `dataclasses`, `unittest.mock` — used throughout.

### Project Path Injections

Several modules inject sibling project paths at runtime for cross-module imports:

```python
sys.path.insert(0, str(PROJECT_ROOT / "python-trader"))          # broker_manager.py:18, crew_structure.py:24, phase1_mvs.py:22
sys.path.insert(0, str(PROJECT_ROOT / "antariksh"))              # crew_structure.py:25, phase1_mvs.py:23
sys.path.insert(0, str(PROJECT_ROOT / "python-trader/Shoonya_oAuthAPI-py"))  # broker_manager.py:19
```

These reference a sibling directory `/home/trading_ceo/python-trader/` containing Shoonya broker API bindings (not in this repo).

---

## 3. Configuration Management

### Primary Config: `config/antariksh_rules.yaml`

**Path:** `config/antariksh_rules.yaml` (302 lines)
**Role:** L3 Parameters layer of the three-layer governance model. Write-protected — no LLM or agent may mutate it. Changes require Chairman commit, 24-hour cooldown, and holdout backtest.

Sections:
- **capital** — Total INR, risk capital, trading capital, free cash floor
- **daily** — Target profit, session SL, portfolio SL, 30-day DD
- **burn_rate_watch** — 10-day window, 30% threshold
- **strategy** — NIFTY Iron Butterfly, lot size, wing widths
- **windows** — Entry/exit times, hard square-off, LLM cutoff
- **gate** — 3-layer gate (VIX, supertrend, confirmation)
- **sanity_checks** — 19 pre-trade checks across 5 tiers (all hard-fail)
- **kill_switches** — Daily, 30-day, hard-kill and soft-kill triggers
- **cooldowns** — Loss day and consecutive loss day rules
- **llm_tiers** — Provider fallback chains (critical/bulk/cheap)
- **llm_resilience** — Retry, circuit breaker, prompt caching
- **providers** — Claude Sonnet, Claude Haiku, DeepSeek, Minimax
- **phase_1** — Soak test duration, success criteria

### Event Calendar: `config/event_calendar.json`

**Path:** `config/event_calendar.json` (92 lines)
JSON array of 2026 events with `skip_trading: true` flag. Contains 22 dates covering RBI MPC, Budget, holidays, elections.

### Constitution: `ralph/constitution.yaml`

**Path:** `ralph/constitution.yaml` (57 lines)
Vision, mission, goals (annual ₹36L, monthly ₹3L), capital preservation limits, resource limits per crew, board definition, and authority escalation chain.

### PRD Files: `ralph/prds/*.yaml`

Six role performance requirements documents, each with metrics (target/floor/min_samples), authority can/cannot lists, and frequency schedules:

| File | Role |
|---|---|
| `ralph/prds/ceo_prd.yaml` | CEO (Vishnu) |
| `ralph/prds/pm_prd.yaml` | Portfolio Manager |
| `ralph/prds/om_prd.yaml` | Operations Manager |
| `ralph/prds/ta_prd.yaml` | Trading Analyst |
| `ralph/prds/am_prd.yaml` | Asset Manager |
| `ralph/prds/pa_prd.yaml` | Post-Mortem Analyst |

### Broker Credentials

Referenced from sibling project `/home/trading_ceo/python-trader/`:
- **Shoonya:** `python-trader/Shoonya_oAuthAPI-py/cred.yml` — YAML with Access_token, UID, Account_ID
- **Flattrade:** `python-trader/tokens.json` — JSON with token and client fields

### Environment Variables

Runtime configuration via environment variables:
- `ANTARIKSH_MOCK_MODE` — Toggle mock mode (default: "0")
- `ANTARIKSH_MOCK_VIX` — Mock VIX value (default: 18.5)
- `ANTARIKSH_MOCK_NIFTY` — Mock NIFTY spot (default: 24500.0)
- `ANTARIKSH_MOCK_TIME` — Mock ISO timestamp
- `ANTARIKSH_MOCK_EVENT_DAY` — Force event day (default: "0")
- `ANTARIKSH_MOCK_EVENT_NAME` — Event day label
- `ANTARIKSH_MOCK_PNL` — Mock session P&L (default: 850)
- `ANTARIKSH_MOCK_TRAJECTORY` — Comma-separated P&L trajectory
- `ANTARIKSH_MOCK_BROKER_DOWN` — Simulate broker failure
- `ANTARIKSH_MOCK_SENTINEL_BLACKOUT` — Simulate sentinel blackout
- `DEEPSEEK_API_KEY` — DeepSeek API key
- `DEEPSEEK_BASE_URL` — DeepSeek API base URL

---

## 4. LLM Integration

### Framework
**CrewAI** (`crewai` package) mediates all LLM calls via `crewai.llm.LLM`. The LLM is instantiated once at module level in `crew_structure.py:38-43`.

### Primary Provider
**DeepSeek** — model `deepseek/deepseek-chat`, base URL `https://api.deepseek.com/v1`, temperature 0.3.

### Tier Architecture
Defined in `config/antariksh_rules.yaml` (lines 192-214):
```
critical: claude_sonnet → minimax → claude_haiku  (Strategist, Sentinel, Risk Guard, Orchestrator)
bulk:     deepseek → minimax → claude_haiku        (Scanner, Auditor)
cheap:    claude_haiku → minimax → deepseek        (auxiliary)
```

The Executor uses `none` — deterministic only, no LLM in the critical execution path.

### Resilience Settings
- Max retries per provider: 2, with backoff [2s, 5s]
- Request timeout: 30 seconds
- Circuit breaker: 3 failures in 60s → 300s cooldown
- Prompt caching enabled for Anthropic agents

---

## 5. Project Architecture

### Two-Phase Design

**Phase 1 (MVS):** `phase1_mvs.py` — Single-file minimum viable system with classes for MarketDataBridge, GateChecker (3-layer), TradeDecisionEngine, TelegramBridge, CFOAuditor, Backtester, and Phase1Orchestrator. Orchestrated by `session_orchestrator.py`.

**Phase 2 (CrewAI):** `crew_structure.py` — Single orchestrator agent with 6 deterministic tools (`@tool` decorator) running in sequential CrewAI process. Contains:
- **Tools** (deterministic, no LLM): `scan_market`, `generate_trade_plan`, `check_risk`, `execute_trade`, `monitor_positions`, `log_audit`
- **Engines** (deterministic, class-based): `RiskGuardEngine`, `AuditorEngine`, `ReEntryTracker`
- **Shared state:** Module-level `market_state: Dict`

### Ralph Loop Meta-Layer

`ralph/ralph_loop.py` — Verify-retry orchestration wrapping CrewAI. Core classes:
- `RalphLoop` — Generic verify-retry loop (while not done: run → verify → feedback → repeat)
- `CrewAIRalphLoop` — CrewAI-specialized wrapper
- `PRDRalphLoop` — PRD-driven metrics verification
- `RalphScheduler` — Cron/HH:MM-based scheduling
- `RolePRD` — YAML-loaded metric targets with check_metric()

### Module Map

| Module | Purpose | Phase |
|---|---|---|
| `phase1_mvs.py` | MVS scaffold (gate, trade plan, backtest, Telegram, CFO) | Phase 1 |
| `crew_structure.py` | CrewAI multi-agent core (orchestrator + 6 tools + engines) | Phase 2 |
| `session_orchestrator.py` | CLI entry for entry/exit sessions | Phase 1 |
| `broker_manager.py` | Dual-broker abstraction (Shoonya primary, Flattrade fallback) | Both |
| `telegram_bridge.py` | Telegram messaging via picoclaw RPC | Both |
| `cfo_auditor.py` | Audit logging and L1 invariant checking | Phase 1 |
| `backtester.py` | Black-Scholes based Iron Fly P&L simulation | Both |
| `exec_report.py` | CEO report generator (daily/weekly/monthly) | Both |
| `token_refresh_dual.py` | Daily token refresh for both brokers | Infra |
| `event_calendar.py` | Hardcoded 2026 event calendar | Both |
| `cron_simulator.py` | Cron job simulator for testing | Test |
| `crew_test.py` | CrewAI test harness (4 test scenarios) | Test |
| `test_full_scenario.py` | End-to-end scenario test | Test |
| `ralph/ralph_loop.py` | Ralph Loop meta-layer | Phase 2+ |

### Empty Directories (planned expansion)

- `agents/` — Individual agent definitions (currently all in `crew_structure.py`)
- `tools/` — Tool implementations (currently all in `crew_structure.py`)
- `crews/` — Crew compositions
- `autonomy/` — Autonomous execution logic
- `harvested/` — Harvested trading outcomes
- `hitl/` — Human-in-the-loop interface

### Test Infrastructure

**Framework:** pytest (v9.0.2) with `pytest-json-report`

**32 scenario tests** in `tests/test_scenarios.py` across 8 categories:
- HP (4): Happy Path
- RM (6): Risk Management
- DD (4): Drawdown
- MC (5): Market Conditions
- SF (5): System Failures
- OP (3): Operator/HITL
- LC (3): Lifecycle
- EC (2): Edge Cases

**Test fixtures** in `tests/fixtures/`:
- `mock_llm.py` — Canned LLM responses for agent role detection
- `mock_broker.py` — Mock broker with order capture
- `seed_history.py` — Synthetic JSONL history seeding

**Test runner:** `tests/run_all.sh` — Shell script running pytest and report generator
**Report generator:** `tests/generate_report.py` — Converts pytest JSON results to markdown

---

## 6. Logging

- **Format:** `"%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"` (crew_structure) or `"%(asctime)s | %(levelname)-8s | %(message)s"` (others)
- **Outputs:** StreamHandler (stdout) + FileHandler (date-stamped files in `logs/`)
- **Log files:**
  - `logs/phase1_YYYYMMDD.log` — Phase 1 MVS runs
  - `logs/orchestrator_YYYYMMDD.log` — Session orchestrator runs
  - `logs/cfo_audit_YYYYMMDD.jsonl` — Immutable JSONL audit trail
  - `logs/token_refresh_YYYYMMDD.log` — Token refresh logs

---

## 7. External Codebase Dependency

The project depends on a sibling directory `/home/trading_ceo/python-trader/` containing:
- Shoonya broker API bindings (`Shoonya_oAuthAPI-py/`) with `api_helper.NorenApiPy`
- Flattrade token auto-refresh script (`get_flattrade_token_auto.py`)
- Credential files (`cred.yml`, `tokens.json`)

This sibling directory is **not** in this repository but is injected into `sys.path` at runtime.
