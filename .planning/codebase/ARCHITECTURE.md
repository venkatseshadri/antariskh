# Antariksh Architecture

**Date:** 2026-05-09
**Focus:** System Design, Data Flow, Module Boundaries

---

## 1. System Design Pattern

Antariksh follows a **Hierarchical Multi-Agent** pattern built on CrewAI, governed by a **meta-layer verify-retry loop** called Ralph Loop.

```
┌─────────────────────────────────────────────────────────────┐
│                    RALPH LOOP (Governance)                   │
│  PRD-driven verify-retry meta-layer wrapping CrewAI crews   │
├─────────────────────────────────────────────────────────────┤
│                    BOARD (CHAIRMAN + DIRECTOR)               │
│  - Chairman (trading_ceo): sets L1 constitution, reviews    │
│  - Director (Claude): interim CEO, advisory                 │
├─────────────────────────────────────────────────────────────┤
│                    CEO (VISHNU) — Autonomous Agent           │
│  - Coordinates 5 crews via PRDs                             │
│  - Reports to Board                                          │
├──────────┬──────────┬──────────┬──────────┬─────────────────┤
│   PM     │   OM     │   TA     │   AM     │   PA            │
│ Portfolio│Operations│ Trading  │ Asset    │ Post-Mortem     │
│ Manager  │ Manager  │ Analyst  │ Manager  │ Analyst         │
├──────────┴──────────┴──────────┴──────────┴─────────────────┤
│           CREWAI 6-TOOL AGENTS (Phase 2 implementation)      │
│  scan_market → generate_trade_plan → check_risk →           │
│  execute_trade → monitor_positions → log_audit               │
└─────────────────────────────────────────────────────────────┘
```

The Overlord is a **Company-as-Code System**, not just a trading bot. It has a board, CEO, CFO, departments, PRDs, a constitution, and an audit trail.

---

## 2. Governance Layers

### 2.1 Ralph Loop — Meta-Governance (`ralph/ralph_loop.py`)

The Ralph Loop is a **PRD-driven verify-retry loop** that sits ABOVE CrewAI:

- Each crew role has a **PRD** (Performance Requirements Document) defining measurable KPIs (target, floor, min_samples).
- `PRDRalphLoop` runs an agent, evaluates its output against PRD metrics, and retries with feedback if falling short.
- `RalphScheduler` checks which roles are due (via cron or HH:MM schedule strings) and runs only those due.
- The Ralph Loop pattern: `while not done: run → verify → feedback → repeat` (up to `max_iterations`).

Key files:
- `ralph/ralph_loop.py` — RalphLoop, CrewAIRalphLoop, PRDRalphLoop, RalphScheduler, load_prd_yaml, run_ralph_cycle
- `ralph/constitution.yaml` — Sovereign constitution: vision, mission, capital limits, board members, authority chain
- `ralph/prds/ceo_prd.yaml` — CEO PRD (crew_uptime, monthly_pnl_goal, alignment_violations, board_report_on_time)
- `ralph/prds/pm_prd.yaml` — Portfolio Manager PRD (win_rate, profit_factor, strategy_has_spec, post_mortem_action_rate)
- `ralph/prds/om_prd.yaml` — Operations Manager PRD (pre_flight_pass, tokens_refreshed, uptime_pct, backup_verified)
- `ralph/prds/ta_prd.yaml` — Trading Analyst PRD (execution_accuracy, gate_check_run, sl_placed, tsl_applied, compliance_reported_to_pm)
- `ralph/prds/am_prd.yaml` — Asset Manager PRD (mtd_dd_vs_limit, margin_utilization_pct, broker_cost_per_session, burn_rate_trend)
- `ralph/prds/pa_prd.yaml` — Post-Mortem Analyst PRD (review_coverage, recommendations_actionable_pct, alternative_analysis_run)

### 2.2 Constitution — Three-Layer Governance

| Layer | Name | Lives In | Mutability |
|-------|------|----------|------------|
| L1 | Purpose / Invariants | `python-trader/varaha/STRATEGY_DESIGN_QUESTIONS.md` | Chairman-only |
| L2 | Mechanism Existence | `CHARTER.md` | Chairman territory |
| L3 | Parameters | `config/antariksh_rules.yaml` | CFO screens proposals; Chairman approves with 24h cooldown + holdout |

The constitution (`ralph/constitution.yaml`) sets:
- Annual goal: ₹36L/year
- Monthly goal: ₹3L/month
- Capital preservation: daily SL ₹3,500, portfolio SL ₹4,500, 30-day DD ₹30,000, free cash floor ₹11,000
- Authority chain: Chairman > CEO > CFO/PM/OM/TA/AM/PA
- Resource limits per crew (max strategists, max broker connections, max simultaneous trades, etc.)

### 2.3 Company-as-Code Hierarchy

**Board:**
- Chairman (User: `trading_ceo`) — sets L1 constitution, reviews period-end
- Director (Claude) — interim CEO until Vishnu is built; advisory

**CEO (Vishnu):**
- Agent to be built in Phase 2, defined in `ralph/prds/ceo_prd.yaml`
- Owns daily operations, dispatches crews, presents board reports
- Cannot override Risk Guard halt or modify constitution

**CFO (Phase 2+):**
- Defined in `cfo_auditor.py` (Phase 1: logger only)
- Phase 2+: Risk + OpEx management, token-usage tracking, capital allocation
- L1 invariants enforced via both `cfo_auditor.py:CFOAuditor` (Phase 1) and `crew_structure.py:AuditorEngine` + `crew_structure.py:RiskGuardEngine` (Phase 2)

**6 Crews (PRD-defined, Phase 2 target):**
1. **PM** (Portfolio Manager) — strategy definition, indicator selection, lot sizing
2. **OM** (Operations Manager) — broker health, token refresh, cron health, disk usage
3. **TA** (Trading Analyst) — execution compliance, gate enforcement, SL/TSL verification
4. **AM** (Asset Manager) — MTD drawdown, margin utilization, broker costs, burn rate
5. **PA** (Post-Mortem Analyst) — trade review, alternative analysis, recommendation generation
6. **CEO** (Vishnu) — crew orchestration, board reporting, alignment verification

---

## 3. Phase 1 vs Phase 2 Architecture

### Phase 1 (Dry-Run MVS) — Current Working State

Phase 1 is a **single-script deterministic pipeline** — no LLM, no multi-agent:

```
cron (scheduler/*.sh)
    │
    ▼
session_orchestrator.py (entry or exit)
    │
    ├─► phase1_mvs.py:GateChecker.check_gate()
    │       └─► MarketDataBridge.get_current_vix()
    │       └─► MarketDataBridge.is_event_day()
    │
    ├─► phase1_mvs.py:TradeDecisionEngine.generate_trade_plan()
    │       └─► MarketDataBridge.get_nifty_spot()
    │       └─► MarketDataBridge.get_contract_expiry()
    │
    ├─► backtester.py:IronFlyBacktester.backtest_iron_fly()
    │       └─► Black-Scholes option pricing
    │
    ├─► telegram_bridge.py:TelegramBridge.send_entry_gate() / send_exit_report()
    │       └─► picoclaw RPC (picoclaw/rpc.py)
    │
    └─► cfo_auditor.py:CFOAuditor.log_session()
            └─► logs/cfo_audit_YYYYMMDD.jsonl
```

Key characteristics:
- **No CrewAI dependency** — pure Python functions called sequentially
- **Dry-run mode**: real market data (VIX/NIFTY from Shoonya broker), but no real order execution
- **Two-Message Protocol**: 9:30 AM entry gate + plan message, 2:35 PM exit + P&L message
- **Backtester uses real Black-Scholes pricing** (not mock P&L)
- **CFO audit is append-only logging** (no autonomous enforcement)

Entry points:
- `session_orchestrator.py` — main entry, called as `python session_orchestrator.py entry` or `python session_orchestrator.py exit`
- `phase1_mvs.py` — contains all Phase 1 business logic (GateChecker, TradeDecisionEngine, Backtester, CFOAuditor, TelegramBridge), also runnable standalone via `python phase1_mvs.py`

### Phase 2 (CrewAI Multi-Agent) — Partially Implemented

Phase 2 introduces **CrewAI with 7 defined agent roles**, though currently implemented as a **single-agent (Orchestrator) with 6 tools** in `crew_structure.py`:

```
crew_structure.py:run_full_session()
    │
    └─► Crew (1 agent: orchestrator, 1 task: run_session_task)
            │
            ├─► Tool: scan_market()      — Layer 1 gate (VIX, window, events)
            ├─► Tool: generate_trade_plan() — Iron Fly 4-leg basket
            ├─► Tool: check_risk()        — RiskGuardEngine.full_check()
            ├─► Tool: execute_trade()     — Place 4-leg basket (stubbed)
            ├─► Tool: monitor_positions() — MTM P&L calc (stubbed)
            └─► Tool: log_audit()         — AuditorEngine.append_session()
```

**7 planned agents** (from `CREW_SPEC.md`) mapped to current implementation:

| # | Agent | Current Status | LLM Tier |
|---|-------|---------------|----------|
| 1 | Orchestrator | IMPLEMENTED — 1 agent with 6 tools | critical (DeepSeek) |
| 2 | Scanner | DEFERRED — merged into `scan_market` tool | bulk |
| 3 | Strategist | DEFERRED — merged into `generate_trade_plan` tool | critical |
| 4 | Executor | DEFERRED — merged into `execute_trade` tool | none (deterministic) |
| 5 | Sentinel | DEFERRED — merged into `monitor_positions` tool | critical |
| 6 | Risk Guard | ENGINE-ONLY — `RiskGuardEngine` is pure code; LLM for recs only | critical |
| 7 | Auditor | ENGINE-ONLY — `AuditorEngine` is deterministic | bulk |

Crew communication is **design-deferred** — the current architecture uses a shared `market_state` dict (defined in `crew_structure.py:68-84`) for inter-agent data transfer. Future multi-crew communication (PM→TA, CEO→PM, etc.) is specified in PRDs (e.g., `compliance_reported_to_pm`, `execution_data_sent_to_am` fields) but not yet implemented.

---

## 4. Data Flow

### 4.1 Market Data Pipeline

```
Shoonya API (primary) ←→ Flattrade API (fallback)
        │
        ▼
broker_manager.py:BrokerManager (singleton)
    ├─► get_vix()           → returns INDIAVIX value
    ├─► get_nifty_spot()    → returns NIFTY50 LTP
    ├─► get_ltp()           → returns any instrument LTP
    ├─► place_order()       → Flattrade primary, Shoonya fallback
    ├─► get_position()      → reads open positions
    └─► close_position()    → market order to close
        │
        ▼
phase1_mvs.py:MarketDataBridge (Phase 1 wrapper)
    └─► broker_manager.get_broker_manager()
```

Daily token refresh via `token_refresh_dual.py`:
- Shoonya: runs `python-trader/Shoonya_oAuthAPI-py/GetAuthcode.py` → updates `cred.yml`
- Flattrade: runs `python-trader/get_flattrade_token_auto.py` → updates `tokens.json`

### 4.2 Trade Decision Flow

```
Market Data (VIX, NIFTY spot)
    │
    ▼
Layer 1 Gate: VIX ≤ 20? Entry window valid? No event day?
    │ NO → SKIP → Telegram "Gate SKIP" + CFO log
    │ YES
    ▼
Layer 2 Signal: supertrend_1min (DEFERRED in Phase 1)
    │ PASS
    ▼
Layer 3 Confirmation: 2-of-3 indicators (DEFERRED in Phase 1)
    │ PASS
    ▼
Trade Plan: NIFTY Iron Butterfly, 1 lot, ±300 wings
    │
    ▼
Risk Check: RiskGuardEngine.full_check()
    │ HALT → Trading paused + alert
    │ PASS
    ▼
Execute: 4-leg basket (STUBBED — Phase 2)
    │
    ▼
Monitor: MTM P&L, SL proximity (STUBBED — Phase 2)
    │
    ▼
Exit: Hard exit at 14:30 IST
    │
    ▼
Audit: Immutable JSONL log
```

### 4.3 Reporting Flow

```
Trade Session
    │
    ▼
Phase 1: exec_report.py generates daily/weekly/monthly reports
    │
    ├─► Reports saved to exec_reports/DAILY_YYYY-MM-DD.md
    ├─► Reports sent to Telegram via picoclaw RPC (DEFERRED — TODO)
    │
    ▼
Phase 2: log_audit tool appends to logs/cfo_audit_YYYYMMDD.jsonl
    │
    └─► Immutable audit trail — append-only, JSONL format
```

### 4.4 Telegram Communication (Two-Message Protocol)

```
9:30 AM Entry:
    telegram_bridge.py:TelegramBridge.send_entry_gate()
        └─► Telegram.send() → picoclaw RPC → Telegram group "antariksh"

2:35 PM Exit:
    telegram_bridge.py:TelegramBridge.send_exit_report()
        └─► Telegram.send() → picoclaw RPC → Telegram group "antariksh"

Alerts:
    telegram_bridge.py:TelegramBridge.send() with severity=critical/warning/ok
```

---

## 5. Module Boundaries

### 5.1 Core Modules

| Module | File | Purpose | Phase |
|--------|------|---------|-------|
| Session Orchestrator | `session_orchestrator.py` | Entry point for cron-scheduled trading sessions | 1 |
| Phase 1 MVS | `phase1_mvs.py` | All Phase 1 business logic (gate, trade plan, backtest, CFO, Telegram) | 1 |
| Crew Structure | `crew_structure.py` | Phase 2 CrewAI with single Orchestrator agent + 6 tools; RiskGuardEngine, AuditorEngine, ReEntryTracker | 2 |
| Broker Manager | `broker_manager.py` | Dual-broker abstraction (Shoonya + Flattrade); singleton pattern | 1, 2 |
| Backtester | `backtester.py` | Black-Scholes option pricing + Iron Fly P&L calculation | 1, 2 |
| Telegram Bridge | `telegram_bridge.py` | Send messages via picoclaw RPC/shell script | 1, 2 |
| CFO Auditor | `cfo_auditor.py` | Audit logger + L1 invariant checks; singleton pattern | 1, 2 |
| Exec Report | `exec_report.py` | Daily/weekly/monthly executive report generator | 1 |
| Token Refresh | `token_refresh_dual.py` | Daily token refresh for Shoonya + Flattrade | 1, 2 |
| Event Calendar | `event_calendar.py` | Hardcoded 2026 event dates; dual-source (module + JSON) | 1 |

### 5.2 Ralph Loop Layer

| Module | File | Purpose |
|--------|------|---------|
| Ralph Loop | `ralph/ralph_loop.py` | Generic verify-retry loop, CrewAI wrapper, PRD-driven loop, scheduler |
| Constitution | `ralph/constitution.yaml` | Vision, mission, capital limits, authority, resource limits |
| PRDs | `ralph/prds/*.yaml` | 6 role PRDs with measurable metrics and authority definitions |

### 5.3 Configuration

| File | Purpose |
|------|---------|
| `config/antariksh_rules.yaml` | L3 parameters: capital, strategy, gates, kill switches, LLM tiers, Phase advancement criteria |
| `config/event_calendar.json` | 22 event dates for 2026 with skip_trading flags |
| `ralph/constitution.yaml` | Board composition, authority chain, resource limits |

### 5.4 Scheduler

| File | Purpose |
|------|---------|
| `scheduler/run_phase1_9am.sh` | Cron script for 9:30 AM entry gate |
| `scheduler/run_phase1_2pm.sh` | Cron script for 2:35 PM exit |
| `cron_simulator.py` | Test harness for all 5 cron jobs (token refresh, entry, exit, daily/weekly reports) |

---

## 6. Event-Driven Patterns

### 6.1 Cron-Based Execution

The system is entirely cron-driven. Five scheduled jobs:

| Job | Time | Script | Description |
|-----|------|--------|-------------|
| Token Refresh | 07:00 IST | `token_refresh_dual.py` | Refresh Shoonya + Flattrade tokens |
| Entry Gate | 09:30 IST | `session_orchestrator.py entry` | Gate check + trade plan + Telegram |
| Exit | 14:35 IST | `session_orchestrator.py exit` | Backtest + P&L + Telegram + CFO audit |
| Daily Report | 18:00 IST | `exec_report.py daily` | Sandbagging report |
| Weekly Report | 20:00 Sun | `exec_report.py weekly` | Weekly deep dive |

### 6.2 Token Refresh Pipeline

Runs daily at 07:00 IST before any session starts:
1. `token_refresh_dual.py` runs `get_flattrade_token_auto.py` (auto-OAuth)
2. `token_refresh_dual.py` runs `Shoonya_oAuthAPI-py/GetAuthcode.py`
3. Dual-broker pattern: at least one broker must succeed for system to function
4. Logs to `logs/token_refresh_YYYYMMDD.log`

### 6.3 Kill Switches and Circuit Breakers

From `config/antariksh_rules.yaml`:
- **Daily kill switch**: -₹4,500 session P&L → halt all entries
- **Rolling 30-day kill switch**: -₹30,000 → halt for week, Chairman restart
- **Hard kill triggers**: structural violation, two consecutive SL breaches, operator override of code halt
- **LLM circuit breaker**: 3 failures within 60s → 5-min cooldown for that provider
- **Cooldowns**: loss day → 24h pause + reflection log; 2 consecutive losses → weekend pause

### 6.4 PRD-Driven Scheduled Verification

The `RalphScheduler` (in `ralph/ralph_loop.py`) checks each crew role's PRD at its scheduled times ("frequency" fields in PRD YAMLs):
- Pre-market checks (08:00–09:18 IST)
- Post-session checks (15:35–16:00 IST)  
- Weekly (Friday 18:00 IST)
- Monthly (last trading day 19:00 IST)

---

## 7. Key Design Patterns

### 7.1 Singleton Pattern
- `broker_manager.py:get_broker_manager()` — singleton BrokerManager
- `cfo_auditor.py:get_cfo_auditor()` — singleton CFOAuditor
- `crew_structure.py:_build_crew()` — lazy-singleton crew cache

### 7.2 Strategy Pattern (Dual-Broker)
- `broker_manager.py:BrokerManager` abstracts Shoonya + Flattrade behind unified interface
- Primary data source: Shoonya (most uptime)
- Execution broker: Flattrade (₹0 brokerage)
- Fallback ordering: Flattrade → Shoonya for orders, Shoonya → Flattrade for data

### 7.3 Two-Phase Architecture
- Phase 1: Deterministic pipeline (no LLM), dry-run, real market data
- Phase 2: CrewAI multi-agent with LLM-backed orchestration; tools are deterministic (no LLM in critical paths)

### 7.4 Hard Code Risk Enforcement
- `RiskGuardEngine` (in `crew_structure.py`) — all L1 capital checks are HARD CODE, no LLM
- `AuditorEngine` (in `crew_structure.py`) — L1 invariant validation is deterministic
- The Risk Guard AGENT only generates recommendation TEXT — the Engine enforces limits
- Read-only-on-risk rule: no LLM can override hard capital limits

### 7.5 Immutable Audit Trail
- JSONL format: append-only, one line per session
- Phase 1: `cfo_auditor.py` writes to `logs/cfo_audit_YYYYMMDD.jsonl`
- Phase 2: `AuditorEngine.append_session()` writes to same directory
- Phase 2 integrates Phase 1 logs via `AuditorEngine.read_phase1_logs()` and `calculate_mtd_from_logs()`

### 7.6 Mock Mode for Testing
- Environment variable `ANTARIKSH_MOCK_MODE=1` enables mock data
- Mock VIX: `ANTARIKSH_MOCK_VIX`, Mock NIFTY: `ANTARIKSH_MOCK_NIFTY`
- Mock time: `ANTARIKSH_MOCK_TIME` (ISO format)
- Mock event day: `ANTARIKSH_MOCK_EVENT_DAY=1`
- `ScenarioRunner` (in `tests/scenario_runner.py`) provides context manager for clean test setup/teardown

### 7.7 Lazy Building
- `crew_structure.py:_build_crew()` only connects to LLM on first `kickoff()`, not on import
- This allows test fixtures to patch environment variables before crew creation

### 7.8 VerificationResult Dataclass
- `ralph/ralph_loop.py:VerificationResult` — simple `(complete: bool, reason: str)` tuple
- Used by all Ralph Loop variants for verification feedback
