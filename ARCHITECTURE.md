# Antariksh — Master System Architecture

**Last Updated:** 2026-05-15 | **Status:** Production-ready dry-run

---

## 0. SYSTEM OVERVIEW

Antariksh is a multi-layer autonomous options trading system for NIFTY Iron Butterfly. It has **4 layers**:

| Layer | Name | Purpose |
|-------|------|---------|
| **L0** | Config & Constitution | `antariksh_rules.yaml`, `constitution.yaml`, `self_improve.yaml`, `agents.json` — immutable rules |
| **L1** | CrewAI Crews (10) | Tactical execution — market scanning, strategy, trading, P&L, post-mortem |
| **L2** | Chairman Orchestrator | Query routing, cross-crew learning injection, crew dispatch |
| **L3** | Ralph Loop (meta) | PRD-driven verify-retry loop, scheduled oversight, self-improvement escalations |

**Workspace:** `PAUL` — Plan → Apply → Unify → Loop (no longer GSD `.planning/`)

**Trade Mode:** Dual-gate safety — `TRADE_MODE=LIVE` + `LIVE_KEY` secret required for real orders. Defaults to `PAPER` (simulated). Dry-run via `ANTARIKSH_MOCK_MODE=1`.

---

## 1. CREW INVENTORY — Who Everyone Is

```
                    ┌──────────────────────┐
                    │     CHAIRMAN / CEO   │
                    │   (ceo_crew — 2 ag)  │
                    │  Guardian + Reporter │
                    └──────────┬───────────┘
                               │ governance, alignment, escalation
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
     ┌────────────┐   ┌────────────┐   ┌────────────┐
     │    PM      │   │    TA      │   │  ASSET MGR │
     │  (2 ag)    │   │  (4 ag)    │   │  (2 ag)    │
     │ Strategist │   │ Scout      │   │ P&L Tracker│
     │ Reporter   │   │ Validator  │   │ Reporter   │
     └─────┬──────┘   │ Analyst    │   └─────┬──────┘
           │          │ Compliance │         │
           │          └─────┬──────┘         │
           │                │                │
           │    ┌───────────┴───────────┐    │
           │    │                       │    │
           │    ▼                       ▼    │
           │  ┌──────────────────────────┐   │
           │  │   TRADING DESK (crew)    │   │
           │  │   Scout→Researcher→PM→   │   │
           │  │   Executioner→Risk→Shifter│   │
           │  │   (6 agents)             │   │
           │  └──────────────────────────┘   │
           │                                 │
     ┌─────┴──────┐              ┌───────────┴───────┐
     │ POSITION   │              │  OPERATIONS MGR   │
     │ ACCOUNTANT │              │  (om_crew — 3 ag) │
     │ (2 ag)     │              │  Pre-flight        │
     │ Reviewer   │              │  Cron-Watchdog     │
     │ Pattern    │              │  GO/NOGO Reporter  │
     └────────────┘              └────────────────────┘

     SYSTEM INTEGRITY
     ┌─────────────────────────────────────┐
     │  CTO → DEV → QA  (engineering pipe) │
     │  cto_crew(1) → dev_crew(1) → qa(1) │
     └─────────────────────────────────────┘
```

| Crew | Agents | Process | Purpose |
|------|--------|---------|---------|
| **TA** (trading analyst) | 4 | hierarchical | Varaha model — Scout detects regime, Validator checks fills, Analyst validates Greeks/strikes, Compliance reports to PM |
| **PM** (portfolio mgr) | 2 | hierarchical | Strategy selection (Iron Fly vs Credit Spread), strike calculation, wing-width margin optimization |
| **AM** (asset manager) | 2 | hierarchical | Financial oversight — cumulative P&L, margin checks from broker, capital limit enforcement |
| **CEO** (governance) | 2 | hierarchical | Strategic alignment, crew performance aggregation, escalation, authority chain, growth scouting |
| **OM** (operations) | 3 | hierarchical | Pre-flight checks — broker tokens, code hash, data capture health, disk, network, cron → GO/NOGO |
| **PA** (post-mortem) | 2 | hierarchical | Trade review, counterfactuals, pattern detection, SL optimization, entry window analysis |
| **CTO** | 1 | hierarchical | Technical strategy, change gatekeeping, architecture review, POC design |
| **Dev** | 1 | sequential | Implements CTO-approved changes — auto-rollback on syntax error |
| **QA** | 1 | sequential | Runs test suites, checks regressions, produces signed PASS/FAIL |
| **Trading Desk** | 6 | hierarchical | Full E2E pipeline — state machine, Lister Triggers, Leg Shifter loop |

**Total: 24 agents across 10 crews**

---

## 2. HOW THEY INTERACT — The Data Flow

### 2.1 Morning Flow (09:15 — 09:22)

```
OM crew (pre-flight)
  ↓ GO/NOGO report
CEO crew (governance)
  ↓ alignment check passed
TA crew (market scan)
  ↓ Scout detects regime from DuckDB
  ↓ Analyst validates option chain
  ↓ Compliance reports to PM
PM crew (strategy design)
  ↓ selects strategy type, calculates strikes
  ↓ manages wing width via broker SPAN
  ↓ generates strategy summary
Trading Desk crew (execution)
  ↓ Scout → Researcher → PM → Executioner
  ↓ places 4-leg basket (wings-first)
  ↓ handoff to Risk Agent
Risk Agent (monitoring all day)
  ↓ WebSocket callbacks: order_update + feed_update
  ↓ OCO logic (TP fills → cancel SLs)
  ↓ TSL engine (modify SL on favorable moves)
  ↓ Leg Shifter loop (theta exhausted → shift proposal)
AM crew (financial tracking)
  ↓ tracks cumulative P&L, margin utilization
CEO crew (end-of-day)
  ↓ aggregates crew performance
  ↓ generates board report
```

### 2.2 Inter-Crew Communication

Crews communicate through the **Chairman orchestrator** (`tools/orchestrator.py`):

```
Chairman query → route_query() → dispatch_to_crew() → crew.kickoff()
                                        ↓
                              ingest_learnings() → get_learnings_for() → inject_learnings()
                                        ↓
                              run_ralph_check() → dispatch_with_ralph()
```

Learnings extracted from one crew's output are injected into the next crew's task description via regex pattern matching. No direct agent-to-agent calls between crews.

### 2.3 Trading Desk Internal Flow (State Machine)

```
 PREPARATION          VALIDATION           ACTION            MAINTENANCE         CLOSED
     │                    │                   │                    │                │
  Scout               PM (capital         Executioner        Risk Agent         All positions
    │                 check, lot          (wings-first       (WS callbacks)     squared
    ▼                 authorization)       order placement)      │               off
  Researcher              │                   │              Leg Shifter
    │                     │                   │              (theta loop)
    ▼                     ▼                   ▼                   │
 MarketRegime        AuthorizedOrder     HandoffReport       Modify/Cancel/
    packet              packet              packet            Exit commands
```

---

## 3. TOOLS — BUILT vs MOCKED vs MISSING

### 3.1 Production-Ready (Live Data)

| Tool | File | Data Source |
|------|------|-------------|
| `detect_market_regime` | `tools/ta_tools.py:272` | DuckDB `market_data` (ADX, ST, VIX, spot) |
| `engine_scout_regime` | `trading_desk.py:266` | DuckDB via `_read_live_market_data()` |
| `MonitorPnLGreeksTool` | `tools/risk_tools.py:45` | DuckDB `market_data` + `option_snapshots` |
| `FetchOptionChainTool` | `tools/ta_strategy_tools.py` | DuckDB `option_snapshots` |
| `FetchGreeksTool` | `tools/ta_strategy_tools.py` | DuckDB `market_data` |
| `ResolveContractTool` | `tools/contract_tools.py` | `static_metadata.db` + DuckDB |
| `EnrichTradePlanTool` | `tools/contract_tools.py` | Both databases |
| `query_broker_margin` | `tools/am_tools.py` | Shoonya + Flattrade REST APIs |
| `analyze_wing_margins` | `tools/pm_tools.py` | Shoonya SPAN calculator |
| `token_refresh_status` | `tools/om_tools.py` | Filesystem (cred.yml + tokens.json) |
| `data_capture_health` | `tools/om_tools.py` | DuckDB file stat |
| `disk_usage_check` | `tools/om_tools.py` | os.statvfs |
| `network_connectivity_check` | `tools/om_tools.py` | HTTP requests to broker + Telegram |
| `log_analyzer` daemon | `tools/log_analyzer.py` | syslog, journalctl, log files, systemctl |

### 3.2 Deterministic (Pure Python, No External Data)

| Tool | What It Computes |
|------|-----------------|
| `TSLEngineTool` | SL/TP/TSL levels + EXIT/HOLD/TRAIL decision |
| `TradeCommandHandlerTool` | EXIT/MODIFY/CANCEL command issuance |
| `select_strategy` | Iron Fly vs Credit Spread selection via weighted scoring |
| `calculate_strikes` | Option strikes on 50-pt grid |
| `build_strategy_spec` | Complete strategy spec dict |
| `validate_trade` | 7-field trade validation against PM spec |
| `check_slippage` | Fill slippage vs tolerance |
| `validate_strike_logic` | Grid alignment, wing width adequacy |
| `validate_sl_vs_volatility` | SL covers gamma-driven P&L swing |
| `review_trade` | Trade quality scoring |
| `run_counterfactuals` | What-if entry/exit/SL/TP scenarios |
| `analyze_sl_optimization` | Optimal SL level by simulated P&L |
| All `ceo_tools` | Alignment, aggregation, caps, escalation, authority |
| All `cto_tools` | Risk assessment, signoff, tech scouting, architecture review |
| All `dev_tools` | File read/write/git with auto-rollback |
| All `qa_tools` | Pytest, regression, diff, pass/fail |

### 3.3 Mocked — Needs Production Wiring

| Component | Current Mock | Target | Priority |
|-----------|-------------|--------|----------|
| **Order placement** | Simulated `SIM-{tsym}-{i}` IDs | `BrokerManager.execute_trade()` → Shoonya `place_order` | 🔴 Phase A |
| **Fill prices** | `MOCK_ENTRY = 100.0` | `BrokerManager.get_ltp()` live quotes | 🔴 Phase A |
| **WebSocket feed** | Static mock tick dict | Shoonya WS `event_handler_quote_update` → `on_feed_update` | 🔴 Phase A |
| **Order status WS** | Static `COMPLETE` mock | Shoonya order WS → `on_order_update` | 🔴 Phase A |
| **Live theta** | Hardcoded `theta_current=-2.5` | `MonitorPnLGreeksTool` → DuckDB `greeks` column | 🟡 Phase B |
| **Premium erosion** | `avg_entry * 0.40` (60% assumption) | Live LTP for active tsyms from feed | 🟡 Phase B |
| **Fund balance** | `mock_balance=200000` | `check_capital_limits()` → broker margin API | 🟡 Phase B |
| **Backtester** | Black-Scholes with spot-derived premiums | Real option chain LTP from DuckDB | 🟢 Phase F |
| **Trade sync** | No broker reconciliation | Cross-check `desk.active_*_orders` vs broker open orders | 🟡 Phase E |

### 3.4 Missing Tools

| Tool | What It Would Do | Why Missing |
|------|-----------------|-------------|
| **LiveThetaTool** | Fetches theta per leg from DuckDB for shifter | `MonitorPnLGreeksTool` exists but not wired into `shifter_evaluate()` |
| **BrokerReconTool** | Cross-checks desk state vs broker order book | Not yet implemented |
| **PartialFillHandler** | If 3/4 legs fill, handles the 4th | Not yet implemented |
| **MarketHoursTool** | Checks if market is open (9:15-15:30, Mon-Fri) | Used by capture script but not by trading desk |
| **EODCloser** | Time-based trigger: close all at 15:20 | Not yet implemented |
| **BrokerReconnectTool** | Handles broker disconnection + resume | Not yet implemented |
| **TelegramAlertTool** | Sends trade events (SL hit, TP hit, shift) to Chairman | `log_analyzer.py` has `send_telegram()` but is a daemon, not a crew tool |

---

## 4. SHARED DATA — The Bullettin Board

### 4.1 DeskState Singleton (`desk`)

All agents in the Trading Desk share a single `DeskState` instance:

```
desk (thread-safe singleton)
├── phase: DeskPhase enum          ← gates which agents can run
├── halt: bool                     ← kill switch
├── Forward Flow Packets
│   ├── regime: MarketRegime       ← Scout writes, Researcher reads
│   ├── setup: ProposedSetup       ← Researcher writes, PM reads
│   ├── order: AuthorizedOrder     ← PM writes, Executioner reads
│   └── handoff: HandoffReport     ← Executioner writes, RiskAgent reads
├── Maintenance State
│   ├── positions_open: bool       ← RiskAgent controls
│   ├── session_pnl: float         ← tracked by CFO agent
│   ├── active_sl_orders: dict     ← {leg_name: order_id}
│   ├── active_tp_orders: dict     ← {leg_name: order_id}
│   ├── highest_favorable: float   ← TSL tracking
│   ├── tsl_active: bool
│   └── tsl_level: float
└── Shifter State
    ├── shift_proposals: list      ← LegShifter → Researcher
    └── shift_count: int           ← max 2 per session
```

### 4.2 DuckDB (`varaha_data.duckdb`)

Populated by `data_capture_v3_duckdb.py` every 60 seconds:

```
varaha_data.duckdb (READ_ONLY ATTACH by antariksh)
├── market_data
│   ├── spot, india_vix, futures_price
│   ├── adx, supertrend_direction, supertrend_value
│   ├── delta, gamma, vega, theta (aggregate Greeks)
│   └── pivots_r1, pivots_s1, ... (pivot points)
├── option_snapshots
│   ├── strike, option_type (CE/PE)
│   ├── ltp, bid, ask, volume, oi
│   ├── delta, gamma, vega, theta, iv
│   └── timestamp (1-minute intervals)
└── futures_snapshots
    └── expiry, ltp, volume, oi

static_metadata.db (scrip_master)
└── scrip_master
    ├── token, tsym (trading symbol)
    ├── exch (NFO), pp (lot multiplier)
    ├── ls (lot size), ti (tick size)
    └── expiry (weekly + monthly)
```

### 4.3 Broker APIs

```
Shoonya (primary)                    Flattrade (secondary)
├── get_quotes(exch, token)          ├── get_quotes(exch, token)
├── place_order(...)                 ├── place_order(...)
├── modify_order(order_id, ...)      ├── modify_order(order_id, ...)
├── cancel_order(order_id)           ├── cancel_order(order_id)
├── get_order_book()                 ├── get_order_book()
├── get_positions()                  ├── get_positions()
├── span_calculator(...)             └── span_calculator(...)
├── searchscrip(search_str)
├── get_option_chain(...)
└── WebSocket (quote + order feeds)
```

---

## 5. THE FULL FLOW — Minute by Minute

```
09:14  data_capture_v3_duckdb.py starts (cron)
09:15  ┌─ OM pre-flight check ─────────────────────────┐
       │  token_refresh, code_hash, data_capture,      │
       │  disk_usage, network → GO/NOGO report         │
       └───────────────────────────────────────────────┘
09:16  ┌─ CEO alignment ───────────────────────────────┐
       │  alignment_check, resource caps, authority    │
       └───────────────────────────────────────────────┘
09:17  ┌─ TA: Scout reads DuckDB ──────────────────────┐
       │  detect_market_regime → regime_type           │
       │  validate_strike_logic, validate_sl_vol       │
       │  validate_trade, check_slippage               │
       │  generate_compliance_report                   │
       └───────────────────────────────────────────────┘
09:18  ┌─ PM: Strategy design ─────────────────────────┐
       │  select_strategy (Iron Fly vs Credit Spread)  │
       │  calculate_strikes (50-pt grid)               │
       │  analyze_wing_margins (SPAN calculator)       │
       │  recommend_optimal_wing                       │
       │  build_strategy_spec                          │
       └───────────────────────────────────────────────┘
09:19  ┌─ Trading Desk: PREPARATION ───────────────────┐
       │  Scout → engine_scout_regime()                │
       │  Researcher → engine_research_setup()         │
       └───────────────────────────────────────────────┘
09:20  ┌─ Trading Desk: VALIDATION ────────────────────┐
       │  PM → engine_pm_validate()                    │
       │  Check margin vs 85% of balance               │
       │  Authorize lot count                          │
       └───────────────────────────────────────────────┘
09:21  ┌─ Trading Desk: ACTION ────────────────────────┐
       │  Executioner → engine_execute_basket()        │
       │    1. Resolve contracts via contract_tools    │
       │    2. Place BUY wings first (hedges)          │
       │    3. Place SELL center (straddle)            │
       │  HandoffReport → Risk Agent                   │
       └───────────────────────────────────────────────┘
09:22  ┌─ Trading Desk: MAINTENANCE (→ 15:25) ────────┐
       │                                               │
       │  Risk Agent WebSocket callbacks:              │
       │    on_feed_update(LTP)                        │
       │      ├── LTP < SL? → HOLD                    │
       │      ├── LTP > hard SL? → EXIT all            │
       │      └── LTP > TSL? → MODIFY SL order         │
       │                                               │
       │    on_order_update(status)                    │
       │      ├── TP_COMPLETE → CANCEL all SLs (OCO)  │
       │      └── SL_COMPLETE → CANCEL all TPs (OCO)  │
       │                                               │
       │  Leg Shifter loop (every few minutes):        │
       │    shifter_evaluate() → premium_erosion %     │
       │      ├── < 70% → HOLD                        │
       │      └── > 70% → ShiftProposal                │
       │           → Researcher backtests              │
       │           → RiskAgent directs Executioner      │
       │           → Close old leg, open new           │
       │                                               │
       └───────────────────────────────────────────────┘

15:20  ┌─ EOD close ───────────────────────────────────┐
       │  Time-based trigger: EXIT all positions       │
       │  Cancel all open orders                       │
       └───────────────────────────────────────────────┘
15:25  ┌─ AM: P&L calculation ─────────────────────────┐
       │  track_cumulative_pnl, check_margin limits    │
       │  generate_financial_report → CEO              │
       └───────────────────────────────────────────────┘
15:26  ┌─ PA: Post-mortem ─────────────────────────────┐
       │  review_trade, run_counterfactuals            │
       │  analyze_sl_optimization, analyze_entry_window│
       │  generate_post_mortem_report → PM             │
       └───────────────────────────────────────────────┘
15:27  ┌─ CEO: Board report ───────────────────────────┐
       │  aggregate_crew_performance                   │
       │  generate_board_report                        │
       │  should_escalate?                             │
       └───────────────────────────────────────────────┘
15:30  data_capture_v3_duckdb.py stops (market close)
```

---

## 6. PRODUCTION READINESS — Checklist

```
[✓] DuckDB injection — engine_scout_regime reads live data
[✓] 39/39 integration tests pass — end-to-end conveyor belt
[✓] OCO logic — TP fill cancels SL, SL fill cancels TP
[✓] TSL engine — modifies SL on favorable moves
[✓] Leg Shifter — theta exhaustion detection + backtest gate
[✓] Contract Librarian — symbol resolution, lot sizes, expiry
[✓] All 10 crews defined with agents + tools
[✓] Inter-crew learnings pipeline (orchestrator.py)
[✓] Log analyzer daemon for Telegram alerts
[✓] CTO → Dev → QA engineering pipeline
[✓] Pre-flight GO/NOGO checks (OM crew)

[ ] Real order placement (broker API wired)            ← Phase A
[ ] Real fill prices (LTP from broker)                  ← Phase A
[ ] WebSocket feed callbacks registered                 ← Phase A
[ ] WebSocket order callbacks registered                ← Phase A
[ ] Live theta (DuckDB greeks → shifter)                ← Phase B
[ ] Live premium erosion (LTP feed → shifter)           ← Phase B
[ ] Real fund balance (capital_limits API → PM)         ← Phase B
[ ] LLM-driven crew execution tested (API key needed)   ← Phase C
[ ] EOD time-based close (15:20 trigger)                ← Phase D
[ ] Partial fill handler (3 of 4 legs → reconcile)      ← Phase E
[ ] Trade sync (desk state vs broker order book)        ← Phase E
[ ] Broker disconnect recovery                          ← Phase E
```

---

## 7. CHAIRMAN ORCHESTRATOR — Central Dispatch Hub

**File:** `tools/orchestrator.py` (705 lines)

The Chairman Orchestrator is the central dispatch hub connecting all 10 crews.

### 7.1 Trade Mode Gate

```python
TRADE_MODE = env("TRADE_MODE", "PAPER")  # Dual-gate: both must match
LIVE_KEY   = env("LIVE_KEY", "")           # Secret "antariskh-1ive-2026"
```

Dual-layer safety: both `TRADE_MODE=LIVE` AND correct `LIVE_KEY` required. Default `PAPER`.

### 7.2 Query Routing

Natural-language Chairman queries are keyword-matched against 6 crew domains:

| Crew Key | Keyword Examples | Builder |
|----------|-----------------|---------|
| `am` | "pnl", "margin", "capital", "balance" | `build_am_crew()` |
| `pm` | "strategy", "strike", "iron fly", "lot" | `build_pm_crew()` |
| `ta` | "market", "vix", "adx", "greeks", "regime" | `build_ta_crew()` |
| `om` | "health", "token", "pre-flight", "cron" | `build_om_crew()` |
| `pa` | "review", "counterfactual", "lesson" | `build_pa_crew()` |
| `ceo` | "governance", "escalate", "board" | `build_ceo_crew()` |

Unknown queries fallback to CEO.

### 7.3 Inter-Crew Learnings Pipeline

After every crew execution, findings are extracted via 12 regex patterns and routed to downstream crews via `LEARNING_PIPELINES`:

```
PA findings → PM, AM, CEO
TA findings → PM, AM, PA
OM findings → PM, AM, CEO
AM findings → PM, CEO
PM findings → AM, CEO
CEO directives → PM, AM, OM
```

Injected into the next crew's task description (max 6 findings to avoid context bloat).

---

## 8. RALPH LOOP — PRD-Driven Verification Meta-Layer

**File:** `ralph/ralph_loop.py` (893 lines) | **Daemon:** `ralph/ralph_scheduler_daemon.py`

The Ralph Loop is Antariksh's goal-oriented oversight layer. Invented by Geoffrey Huntley at Vercel Labs.

### 8.1 Core Pattern

```
while not done:
    result = agent.run(task)
    done, feedback = verify(result)
    if not done:
        task += feedback
```

### 8.2 CrewAI Ralph Loop

Each crew's output is evaluated against its **PRD** (Product Requirements Document) — a YAML file defining measurable metrics with targets and floors:

| PRD File | Crew | Metrics |
|----------|------|---------|
| `ralph/prds/om_prd.yaml` | Operations | Uptime, pre-flight pass rate, token freshness, broker cost |
| `ralph/prds/pm_prd.yaml` | Portfolio | Win rate, profit factor, strategy adoption rate |
| `ralph/prds/ta_prd.yaml` | Trading Analyst | Compliance %, validation accuracy, execution patterns |
| `ralph/prds/am_prd.yaml` | Asset Manager | P&L tracking, margin utilization, cost efficiency |
| `ralph/prds/pa_prd.yaml` | Performance Analyst | Recommendation quality, adoption rate |
| `ralph/prds/ceo_prd.yaml` | CEO | Board report timeliness, crew performance, opportunity scouting |

### 8.3 Metric Evaluation

Each metric returns one of: `PASS` (at/above target), `WARNING` (below target, above floor), `FAIL` (below floor), `DATA_IMMATURE` (insufficient samples).

3 consecutive FAILs → escalation pushed to Chairman via Telegram.

### 8.4 Weekend Self-Improvement Cycles

The Ralph scheduler runs the self-improvement mandate on Sat/Sun. Each role has a `better_looks_like` definition (`config/self_improve.yaml`). CEO judges each crew daily: BETTER / SAME / WORSE. 3 SAME or any WORSE → escalate.

---

## 9. CTO → DEV → QA — Engineering Pipeline

**File:** `pipeline_orchestrator.py` (521 lines)

Self-modifying autonomous code pipeline:

```
Change Request → CTO (risk assessment, diff preview, signoff)
                     ↓
                  Dev (apply edit, auto-rollback on syntax error, commit)
                     ↓
                  QA (run test suite, check regression, produce PASS/FAIL)
                     ↓
                  CTO (final signoff or rollback)
```

The pipeline can be invoked deterministically via `process_change_request(change_spec)` — no LLM required for the core workflow. CTO uses LLM only for architecture judgment calls.

### 9.1 CTO Authorities
- Gatekeeps ALL source code changes (blast radius, risk, signoff)
- Scouts new tools/frameworks to reduce cost/maintenance
- Delegates implementation to Dev, validation to QA
- Reports directly to CEO
- CANNOT override Risk Guard halts or modify constitution

---

## 10. LEARNING & FEEDBACK SYSTEMS

Three distinct loops operate at different timescales:

### 10.1 Inter-Crew Learnings (Real-time, per session)
After each crew kickoff, `orchestrator.py` parses output for actionable findings via 12 regex patterns and routes them to downstream crews.

### 10.2 Ralph PRD Verification (Scheduled, 9x per trading day per crew)
Each crew's PRD metrics are evaluated post-execution. FAIL triggers retry with feedback. 3 consecutive FAILs trigger Chairman alert via Telegram.

### 10.3 PA Post-Mortem (End-of-session, per day)
`crews/pa_crew.py` + `tools/pa_tools.py` run after market close. Trade quality review, counterfactuals, pattern detection, SL optimization, entry window analysis. PM is expected to act on PA recommendations (adoption rate tracked by Ralph Loop).

### 10.4 Self-Improvement Mandate (Weekly, weekends)
Every cycle: "be better today than yesterday." CEO judges each crew. Compounding improvements make the system self-sustaining over time.

---

## 11. TEST INFRASTRUCTURE

### 11.1 Test Files

| File | Tests | What |
|------|-------|------|
| `tests/test_integration_end_to_end.py` | 39 assertions | Full conveyor belt: Scout→Researcher→PM→Executioner→RiskAgent (4 phases) |
| `tests/test_orchestration.py` | ORCH-01 → ORCH-20 | Query routing, delegation, mock/real LLM orchestration, 6-crew pipeline |
| `tests/test_ralph_loop.py` | RL-01 → RL-04 | Scheduler, YAML loading, escalation counters, PRD metric status |
| `tests/test_om_crew.py` | 17 tests | OM pre-flight checks, token refresh, health reports |
| `tests/test_ta_crew.py` | Multiple | Trade validation, slippage, duplicate detection |
| `tests/test_pm_crew.py` | Multiple | Strategy selection, strike calculation, wing margins |
| `tests/test_am_crew.py` | Multiple | P&L tracking, margin checks, capital limits |
| `tests/test_pa_crew.py` | Multiple | Trade review, counterfactuals, pattern detection |
| `tests/test_ceo_crew.py` | Multiple | Governance, alignment, escalation |
| `tests/test_agentops.py` | 20 tests | AgentOps observability, 6-crew tracing |
| `tests/test_promptfoo.py` | 22 tests | LLM prompt security eval |
| `tests/test_integration.py` | Additional | Integration coverage |
| `tests/test_risk_sentry.py` | Risk guard | TSL engine, kill switches, OCO logic |
| `tests/test_risk_sentry_mock.py` | Mock broker | Risk sentry with simulated broker |
| `tests/test_closed_loop_executor_sentry.py` | Closed loop | Executor ↔ Sentry feedback loop |
| `tests/test_technical_scout.py` | Regime | Market regime detection |
| `tests/test_strategy_architect.py` | Strategy | Strategy design and leg selection |
| `tests/test_contract_specialist.py` | Contracts | Symbol resolution, expiry, lot sizes |
| `tests/test_execution_specialist.py` | Execution | Order placement and fills |
| `tests/test_chain_librarian_executioner.py` | Chain | Contract resolution → execution |
| `tests/test_architect_iron_condor.py` | Iron Condor | Non-Iron Fly strategy variants |
| `tests/test_delta_neutral_monday.py` | Delta neutral | Delta-neutral strategies |
| `tests/test_vega_positive_atm2.py` | Vega positive | Vega-positive ATM strategies |
| `tests/test_vega_theta_positive.py` | Vega+Theta | Vega+Theta positive strategies |
| `tests/test_scenarios.py` | Scenarios | Scenario runner with fixtures |

**Total: ~150+ tests across 29 test files**

### 11.2 Dry-Run / Mock Mode

All tests and development run via `ANTARIKSH_MOCK_MODE=1`:
- Mock VIX, NIFTY spot, time, event calendar
- Mock P&L simulation
- Mock broker fills (stubbed order IDs)
- No live broker connection needed
- Entry point: `python3 crew_structure.py --mock --vix 18.5 --nifty 24500 --time 10:30`

### 11.3 Trial Run v1 (Live DuckDB + Paper Trading)

New execution mode that reads real market data from DuckDB but keeps orders simulated:

```bash
python3 crew_structure.py --trial     # Full pipeline with live data
python3 crew_test.py --trial          # Test harness version
```

Flow: 6 deterministic tools run sequentially (no LLM needed):
```
scan_market(DuckDB) → generate_trade_plan → check_risk → execute_trade → monitor_positions → log_audit
```

Difference from mock mode:
- Mock: hardcoded VIX=18.5, NIFTY=24500, fake time
- Trial: reads VIX, NIFTY, ADX, SuperTrend from DuckDB `market_data` table, IST system time

Difference from production:
- Trial: `execute_trade` still stubbed (SIM- order IDs), `monitor_positions` still simulated P&L
- Production: real Shoonya `place_order`, live WebSocket P&L

### 11.4 Scenario Runner

**File:** `tests/scenario_runner.py` — programmatic test harness that patches datetime, VIX, NIFTY, and runs crew sessions with assertions.

---

## 12. CONFIG & CONSTITUTION

### 12.1 Rule Files (Immutable — no agent may modify)

| File | Lines | Purpose |
|------|-------|---------|
| `config/antariksh_rules.yaml` | 302 | Capital params, daily envelopes, 3-layer gate, 19 pre-trade sanity checks, LLM provisioning tiers, kill switches, cooldowns |
| `ralph/constitution.yaml` | 57 | Vision ("retire by 50, ₹36L/year"), goals, resource limits per crew, authority chain, board members |
| `config/self_improve.yaml` | 61 | What "better" means for each role, escalation rules |
| `config/agents.json` | — | Role names, goals, and backstories for all agents across all crews |
| `config/event_calendar.json` | — | Market holidays, expiry days |

### 12.2 Authority Chain (from constitution.yaml)

```
Chairman → CEO → {CFO, PM, OM, TA, AM, PA}
Chairman → ALL (absolute override)
CEO → CFO → AM
CEO → PM → {strategist, risk_guard}
CEO → OM → {*infra only*}
CEO → TA → {scanner, executor, sentinel, auditor}
CEO → PA → {*read-only post-mortem*}
```

Risk Guard's HALT is absolute — neither CEO nor Chairman override at runtime (only Chairman via Telegram post-session).

---

## 13. NOTIFICATIONS — Telegram Bridge

**File:** `tools/notifications.py` | Legacy: `telegram_bridge.py`

Dual-channel notification layer:

| Channel | Purpose |
|---------|---------|
| **Direct Telegram Bot API** | Entry gate reports, exit P&L summaries, Board reports |
| **Kubera Queue** (fallback) | Resiliency — messages queue if Telegram unavailable |

Alert types:
- Pre-flight GO/NOGO reports
- Risk Guard halt alerts (SL breached, capital floor breach)
- Ralph escalation alerts (3 consecutive PRD failures)
- CEO board reports
- Session entry/exit summaries (two-message protocol)

---

## 14. QUICK START

```bash
cd /home/trading_ceo/antariksh

# See the full architecture
python3 trading_desk.py --show-flows

# Trial run v1: live DuckDB data, paper trading (no API key needed)
python3 crew_structure.py --trial
python3 crew_test.py --trial

# Dry-run session (no API key needed)
python3 crew_structure.py --mock --vix 18.5 --nifty 24500 --time 10:30

# Run all deterministic tests (no API key needed)
python3 trading_desk.py --test-triggers
python3 trading_desk.py --mock --maintenance-cycle
python3 tests/test_integration_end_to_end.py
python3 tests/test_orchestration.py -v
python3 tests/test_ralph_loop.py -v

# Read live market data from DuckDB
python3 -c "
import os; os.environ.pop('ANTARIKSH_MOCK_MODE','')
from trading_desk import engine_scout_regime
r = engine_scout_regime()
print(f'Live: VIX={r.vix} NIFTY={r.nifty_spot} Regime={r.regime}')
"

# Full session with LLM (requires DEEPSEEK_API_KEY)
export DEEPSEEK_API_KEY="sk-..."
python3 trading_desk.py --mock --full-session --vix 18.5 --nifty 24500

# Run Ralph Loop scheduler (PRD verification)
python3 -m ralph.ralph_loop
```
