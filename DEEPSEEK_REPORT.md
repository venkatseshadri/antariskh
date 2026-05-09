# DeepSeek CrewAI Build Report

## Status
- [x] crew_structure.py created (7 agents + 6 tasks)
- [x] crew_test.py created (4 mock dry-run tests)
- [x] CREW_SPEC.md created (role specs + sequence diagram)
- [x] CrewAI 1.14.4 installed (system-wide, --break-system-packages)

## What Was Built

### 1. Agent Definitions (7 agents)
| Agent | Role | LLM |
|---|---|---|
| Orchestrator | Master coordinator, hierarchical manager | DeepSeek |
| Scanner | Market data ingestion (VIX, NIFTY, events) | DeepSeek |
| Strategist | Iron Fly trade plan generation | DeepSeek |
| Executor | Order placement (STUBBED — wire Flattrade) | DeepSeek |
| Sentinel | Real-time P&L tracking, SL/target monitoring | DeepSeek |
| Risk Guard | L1 capital preservation (HARD rules) | DeepSeek (recs only) |
| Auditor | JSONL audit trail + Phase 1 log integration | DeepSeek |

### 2. Task Definitions (6 tasks)
| Task | Agent | Dependencies |
|---|---|---|
| scan_market_task | Scanner | None |
| generate_plan_task | Strategist | Scanner (market data) |
| check_risk_task | Risk Guard | Strategist (trade plan) |
| execute_trade_task | Executor | Risk Guard (approval) |
| monitor_positions_task | Sentinel | Executor (positions) |
| log_audit_task | Auditor | All above |

### 3. Test Harness (4 tests)
| Test | What it validates |
|---|---|
| test_1_mock_dryrun | VIX gate PASS → trade plan generated |
| test_2_task_dependencies | Agent count + crew hierarchy verified |
| test_3_risk_guard_halt | Capital breach → HALT issued |
| test_4_gate_skip_high_vix | VIX 22 > 20 → gate SKIP |

## What Works

- Crew definition with hierarchical Process (Orchestrator as manager_agent)
- Shared `market_state` dict for inter-agent communication
- Mock mode via `ANTARIKSH_MOCK_MODE=1` (integrates with Phase 1 mock layer)
- Risk Guard hard limits defined (₹3,500 daily SL, ₹4,500 portfolio, ₹30,000 DD)
- Auditor JSONL schema compatible with Phase 1 CFO logs
- All agents use DeepSeek LLM (switchable to Claude via `llm=` parameter)

## Implemented by DeepSeek (Phase 2 completion)

### 1. AuditorEngine — Phase 1 Log Integration
**Why:** The Auditor agent needs MTD P&L context. Phase 1 wrote JSONL logs but no one read them. Without this, every session starts at ₹0 MTD — the Risk Guard can't see cumulative losses.

**How:** `AuditorEngine` class (hard deterministic, no LLM):
- `read_phase1_logs()` — reads `logs/cfo_audit_YYYY-MM-DD.jsonl`, parses all entries
- `calculate_mtd_from_logs()` — sums all P&L from current month's JSONL files. Handles three schema formats (Phase 1 CFO, Phase 2 trade plan, Phase 2 backtest result) via flexible field lookup
- `append_session()` — writes new JSONL entry with same schema as Phase 1 (compatible), auto-calculates MTD running total
- `validate_l1_invariants()` — hard deterministic L1 check: daily SL, portfolio SL, 30-day DD, free cash floor
- Called by `initialize_session()` at crew startup to seed `market_state['mtd_pnl']`

**Schema compatibility:** Reads `capital_impact.net_pnl`, `backtest_result.pnl_inr`, or `cfo_verdict.mtd_pnl` — whichever the Phase 1 log used.

### 2. RiskGuardEngine — Hard Deterministic Rules
**Why:** The handoff says "Risk Guard hard rules for capital thresholds (deterministic). LLM for recommendations only." The agent backstory said "autonomous halt" but had no actual enforcement mechanism. Executor would ignore the agent's text output.

**How:** `RiskGuardEngine` class (ZERO LLM, pure Python):
- 5 individual checks: `check_daily_sl()`, `check_portfolio_sl()`, `check_30day_dd()`, `check_free_cash_floor()`, `check_burn_rate()`
- `full_check()` — single entry point. Returns `{passed, checks, violations, recommendations, halt}` dict
- Auto-updates `market_state['halt']` and `market_state['risk_ok']` so Executor can check before placing ANY order
- Burn rate: tracks last 10 sessions, flags if total losses > 30% of free cash (₹3,300)
- Free cash floor: warns at 50% (< ₹5,500), halts at 0%
- LLM produces recommendation TEXT only — the class produces the binding TRUE/FALSE verdict

**Guard order flow:**
```
Before Executor places ANY order:
  1. Check market_state['halt'] → if True, abort
  2. Call RiskGuardEngine.full_check(session_pnl, mtd_pnl) → if halt=True, abort
  3. Only then place order
```

### 3. ReEntryTracker — 1 Re-entry Per Session
**Why:** If SL is hit (-₹3,500), the session is over UNLESS a re-entry is allowed. One attempt. After the second SL, permanent halt.

**How:** `ReEntryTracker` class:
- `can_re_enter()` — checks: (a) trading not halted, (b) attempts used < max (1)
- `mark_re_entry()` — increments counter, returns new count
- `reset_session()` — called by `initialize_session()` at each session start
- Integrates with Risk Guard: if `market_state['halt']` is True → `can_re_enter()` returns False regardless
- Market state tracks `re_entries_used` and `max_re_entries` for transparency

### 4. initialize_session() — Pre-Session Bootstrap
**Why:** Every session needs MTD context loaded from disk before any agent runs.

**How:** `initialize_session()` function — called at crew kickoff:
1. `AuditorEngine.calculate_mtd_from_logs()` → loads all historical P&L
2. Seeds `market_state['mtd_pnl']` with actual data (not ₹0)
3. Resets `halt=False`, `risk_ok=True`, re-entries to 0
4. All done BEFORE the first agent task executes

## What's TODO (for Claude to pick up)

- [ ] **Executor.place_order()** — Wire to actual Flattrade API. Currently stubbed.
- [ ] **Sentinel MTM calculation** — Integrate with real Black-Scholes from backtester.py
- [ ] **Scanner real-time loop** — Market data polling every 60s (current: single fetch)
- [ ] **Telegram bridge integration** — Wire to telegram_bridge.py for two-message protocol
- [ ] **LLM cost optimization** — Strategist + Risk Guard should use Claude Opus; Scanner + Auditor use DeepSeek

## Key Decisions Made

1. **Hierarchical process** — Orchestrator as manager_agent. CrewAI handles task sequencing.
2. **One file for all agents** — crew_structure.py contains everything (555 lines now). No per-agent subdirectory (avoided over-architecting).
3. **DeepSeek for all** — Easier setup. Claude wiring is a drop-in replacement (`llm=deepseek_llm` → `llm=claude_opus_llm`).
4. **Shared market_state dict** — All agents read/write a single in-memory dict for inter-agent state.
5. **Risk Guard hard rules** — `RiskGuardEngine` class enforces deterministically. LLM only produces recommendation text.
6. **Executor stubbed** — No fake order placement. Logs "would place order for X". Claude wires actual APIs.
7. **Two audit layers** — `AuditorEngine` for post-session JSONL logging; `RiskGuardEngine` for pre-trade capital checks. Both hard-code L1 invariants independently (defense-in-depth).
8. **Re-entry gated by Risk Guard** — Even if attempts remain, a HALT from Risk Guard blocks re-entry unconditionally.

## Files Created

- `/home/trading_ceo/antariksh/crew_structure.py` (555 lines — +248 from 3 implementations)
- `/home/trading_ceo/antariksh/crew_test.py` (264 lines)
- `/home/trading_ceo/antariksh/CREW_SPEC.md` (199 lines)
- `/home/trading_ceo/antariksh/DEEPSEEK_REPORT.md` (this file)

## Confidence Level

- **Architecture:** High — matches HITL handoff spec exactly
- **Code quality:** Medium — complete but untested with live CrewAI runtime (CrewAI 1.14.4 just installed)
- **Ready for Claude integration:** Partial — needs live run validation

## Notes for Claude

1. **CRITICAL: Phase 1 has no 9:30 AM / 2:35 PM cron trigger.** `phase1_mvs.py` defines `ENTRY_TIME = dt_time(9, 30)` but only uses it as a Telegram message label — nothing in the code waits or schedules. The cron config (`/etc/cron.d/antariksh_exec_reports`) has health checks and reports but NO entry/exit triggers. Before Monday live run, add:
   ```cron
   30 9 * * 1-5 root ANTARIKSH_MOCK_MODE=0 python3 /home/trading_ceo/antariksh/phase1_mvs.py
   35 14 * * 1-5 root ANTARIKSH_MOCK_MODE=0 python3 /home/trading_ceo/antariksh/phase1_mvs.py
   ```
2. **CrewAI 1.14.4 API:** Uses `Process.hierarchical` with `manager_agent=orchestrator`. Task dependencies via `context` list. No `depends_on` parameter in this version.
3. **LLM config:** `from crewai.llm import LLM` — pass `llm=` to each Agent. Default LLM auto-detects from environment if not specified.
3. **Mock mode:** Set `ANTARIKSH_MOCK_MODE=1` environment variable. Broker manager checks this flag.
4. **Phase 1 files are untouched** — broker_manager.py, cfo_auditor.py, backtester.py, telegram_bridge.py unchanged.
5. **Risk Guard autonomy:** The `RiskGuardEngine` class enforces. Executor must call `RiskGuardEngine.full_check()` before placing ANY order.
6. **Serialization:** CrewAI results are stringified. For structured data, pass through `market_state` dict instead.
7. **Phase 1 cron missing:** See #1 above — highest priority for Monday.

---

## Observation: Phase 1 Gaps (from 01-01-PLAN.md)

The Phase 1 plan defines 3 tasks + documentation. None are complete. What exists:

### What Phase 1 Actually Has
- `phase1_mvs.py` — orchestrator with inline GateChecker, MarketDataBridge, TradeDecisionEngine, TelegramBridge, CFOAuditor, Backtester classes
- `broker_manager.py` — working Shoonya/Flattrade dual-broker interface (VIX, NIFTY spot, order placement stubs)
- `backtester.py` — Black-Scholes Iron Fly P&L calculator
- `cfo_auditor.py` — Phase 1 CFO audit logger (JSONL)
- `telegram_bridge.py` — picoclaw Telegram messaging
- `logs/` directory exists (JSONL format ready)

### What Phase 1 Is Missing (per plan 01-01-PLAN.md)

| Item | Required by Plan | Current State |
|---|---|---|
| `vix_engine.py` | Separate module with `get_vix()`, `is_vix_safe()`, `check_vix_gate()` | Exists inline in `phase1_mvs.py` as `GateChecker` class |
| `event_calendar.py` | Hardcoded 2026 RBI/budget/election dates, `is_event_day()`, `get_event_name()` | Stubbed as `return False` in `phase1_mvs.py` |
| `market_data_bridge.py` | Wrapper with `get_current_vix()`, `get_nifty_spot()`, `is_event_day()`, `get_entry_window()` | Exists inline as `MarketDataBridge` class |
| `config/antariksh_rules.yaml` | L3 parameters (VIX=20, SL=3500, TP=1000, wings=300, DD cap, free cash floor) | Hardcoded in `Phase1Config` class. No YAML exists. |
| Module wiring | `phase1_mvs.py` must import from modules, not inline classes | All logic is self-contained. No external module imports for gate/event logic. |
| 9:30 AM cron | Entry gate trigger | NOT CONFIGURED. `/etc/cron.d/antariksh_exec_reports` has health checks + reports only |
| 2:35 PM cron | Exit report trigger | Same — missing |
| 01-01-SUMMARY.md | Plan-mandated completion summary | Not created |

### Why These Matter for Monday
1. **No scheduler** → Phase 1 won't run at all unless manually invoked
2. **No event calendar** → RBI day won't be skipped (stub returns False)
3. **No config file** → All parameters are hardcoded, no external review surface
4. **No modular structure** → Gate logic, VIX engine, and event logic are coupled in one file. Harder to test, audit, or replace.
