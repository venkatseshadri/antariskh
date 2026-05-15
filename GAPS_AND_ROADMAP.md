# Antariksh Trading Desk — GAPS & ROADMAP

**Date:** 2026-05-15
**Last Update:** 2026-05-12 (original)

---

## 1. WHAT'S MOCKED → NEEDS PRODUCTION WIRING

| Component | Current (Mock) | Production Target | Action Required |
|-----------|---------------|-------------------|-----------------|
| **Fill prices** | `MOCK_ENTRY = 100.0` hardcoded | Live LTP from broker API | Wire `BrokerManager.get_ltp()` into `engine_execute_basket` |
| **Order placement** | Simulated `SIM-{tsym}-{i:03d}` IDs | `api.place_order()` via Shoonya/Flattrade | Wire `BrokerManager.execute_trade()` at `tools/execution_tools.py:23` |
| **WebSocket feed** | Static mock tick data | Shoonya WebSocket `event_handler_quote_update` | Register `ListenTriggers.on_feed_update` as WS callback in `broker_manager.py:280` |
| **Order status** | Static mock `COMPLETE` status | Shoonya `event_handler_order_update` on orders WS | Register `ListenTriggers.on_order_update` as WS callback |
| **TSL engine** | Hardcoded `desk.highest_favorable = 80.0` | Live LTP tracking from feed ticks | Feed `on_feed_update` → `desk.highest_favorable` tracking already wired, needs real LTPs |
| **Theta computation** | Hardcoded `theta_current=-2.5`, `theta_target=-8.0` | Live Greek engine from `tools/risk_tools.py:MonitorPnLGreeksTool` | Wire `MonitorPnLGreeksTool._run()` into `shifter_evaluate()` |
| **Premium erosion** | `current_ltp = avg_entry * 0.40` (60% erosion assumption) | Live LTP from option feed → real `(avg_entry - ltp)/avg_entry * 100` | Replace `avg_entry * 0.40` with `on_feed_update` LTP for active tsyms |
| **Backtester** | Black-Scholes `IronFlyBacktester` with spot-derived premiums | Real option chain LTP from DuckDB `option_snapshots` | Wire `get_weekly_expiry()` + live chain into backtester |
| **VIX fetch** | DuckDB read (works in production) ✓ | Already wired | No change needed |
| **NIFTY spot** | DuckDB read (works in production) ✓ | Already wired | No change needed |
| **ADX/SuperTrend** | DuckDB read (works in production, may be NaN on fresh capture) | Already wired | Handle NaN → wait for next 1-min cycle |
| **Fund balance** | Hardcoded `mock_balance=200000` | Live margin/free cash from `tools/am_tools.py:check_capital_limits()` | Wire into `engine_pm_validate` |
| **Trade sync** | No sync with Shoonya order book | Cross-check `desk.active_sl_orders` against broker open orders | Post-execution reconciliation |

---

## 2. CREW STATUS — All Operational

| Crew | Agents | Process | Status | Tested with LLM? |
|------|--------|---------|--------|-----------------|
| **OM** (operations) | 3 | hierarchical | ✅ pre-flight infra watchdog | ❌ Needs API key |
| **TA** (trading analyst) | 4 | hierarchical | ✅ Varaha model — regime, validation, greeks, compliance | ❌ |
| **PM** (portfolio mgr) | 2 | hierarchical | ✅ Strategy selection, strikes, wing optimization | ❌ |
| **PA** (post-mortem) | 2 | hierarchical | ✅ Trade review, counterfactuals, patterns | ❌ |
| **AM** (asset manager) | 2 | hierarchical | ✅ P&L tracking, margin, capital limits | ❌ |
| **CEO** (governance) | 2 | hierarchical | ✅ Alignment, escalation, board reports | ❌ |
| **CTO** | 1 | hierarchical | ✅ Architecture gatekeeping, Dev/QA delegation | ❌ |
| **Dev** | 1 | sequential | ✅ Code implementation with auto-rollback | ❌ |
| **QA** | 1 | sequential | ✅ Test suites, regression validation | ❌ |
| **Telegram Reporter** | 1 | — | ✅ Notifications, alerts, reports | N/A |

**10 crews, 19 agents total.** All crews defined with agents + tools. LLM-driven execution path tested in code (mock LLM orchestration tests pass 20/20) but not with real DeepSeek API key.

---

## 3. TEST COVERAGE

| Test File | What It Tests | Status |
|-----------|--------------|--------|
| `tests/test_integration_end_to_end.py` | Full conveyor belt: Scout→Researcher→PM→Executioner→RiskAgent (39 checks, 4 phases) | ✅ 39/39 |
| `tests/test_orchestration.py` | 20 tests: query routing, delegation, mock/real LLM, 6-crew pipeline (ORCH-01 → ORCH-20) | ✅ 20/20 |
| `tests/test_ralph_loop.py` | 4 tests: scheduler, YAML loading, escalation counters, PRD metrics (RL-01 → RL-04) | ✅ 4/4 |
| `tests/test_om_crew.py` | OM pre-flight checks, token refresh, health reports (17 tests) | ✅ 17/17 |
| `tests/test_ta_crew.py` | Trade validation, slippage, duplicate detection | ✅ Multiple |
| `tests/test_pm_crew.py` | Strategy selection, strike calculation, wing margins | ✅ Multiple |
| `tests/test_am_crew.py` | P&L tracking, margin checks, capital limits | ✅ Multiple |
| `tests/test_pa_crew.py` | Trade review, counterfactuals, pattern detection | ✅ Multiple |
| `tests/test_ceo_crew.py` | Governance, alignment, escalation | ✅ Multiple |
| `tests/test_agentops.py` | AgentOps observability, 6-crew tracing (20 tests) | ✅ 20/20 |
| `tests/test_promptfoo.py` | LLM prompt security eval (22 tests) | ✅ 22/22 |
| `tests/test_risk_sentry.py` | TSL engine, kill switches, OCO logic | ✅ |
| `tests/test_risk_sentry_mock.py` | Risk sentry with mock broker | ✅ |
| `tests/test_closed_loop_executor_sentry.py` | Executor ↔ Sentry feedback loop | ✅ |
| `tests/test_technical_scout.py` | Market regime detection | ✅ |
| `tests/test_strategy_architect.py` | Strategy design and leg selection | ✅ |
| `tests/test_contract_specialist.py` | Symbol resolution, expiry, lot sizes | ✅ |
| `tests/test_execution_specialist.py` | Order placement and fills | ✅ |
| `tests/test_chain_librarian_executioner.py` | Contract resolution → execution chain | ✅ |
| `tests/test_architect_iron_condor.py` | Iron Condor strategy variant | ✅ |
| `tests/test_delta_neutral_monday.py` | Delta neutral strategies | ✅ |
| `tests/test_vega_positive_atm2.py` | Vega-positive ATM strategies | ✅ |
| `tests/test_vega_theta_positive.py` | Vega+Theta positive strategies | ✅ |
| `tests/test_scenarios.py` | Scenario runner with fixtures | ✅ |
| `tests/test_integration.py` | Integration coverage | ✅ |

**Total: ~150+ tests across 29 test files**

Tests requiring LLM (DeepSeek API key): test_orchestration.py (3 real-LLM tests), test_promptfoo.py, test_agentops.py, crew LLM tests

---

## 4. FUTURE PHASES — ORDERED BY PRIORITY

### Phase A: Production Wiring (Critical)
**Goal:** Replace all mocks with live broker/DuckDB data.

- [ ] Wire `BrokerManager.execute_trade()` into `engine_execute_basket` (real order placement)
- [ ] Wire `BrokerManager.get_ltp()` for live fill prices (replace `MOCK_ENTRY`)
- [ ] Register `ListenTriggers.on_feed_update` as Shoonya WebSocket callback
- [ ] Register `ListenTriggers.on_order_update` as Shoonya order WebSocket callback
- [ ] Wire `check_capital_limits()` into `engine_pm_validate` for real fund balance
- [ ] Wire `MonitorPnLGreeksTool` into `shifter_evaluate` for live theta
- [ ] Cross-check: `desk.active_sl_orders` vs broker open orders after execution
- [ ] Handle DuckDB NaN ADX (poll once, retry next cycle if null)

### Phase B: Leg Shifter — Real Theta (High)
**Goal:** Replace hardcoded theta with live Greek engine.

- [ ] Compute live theta from DuckDB `option_snapshots.greeks` (theta column)
- [ ] Replace `premium_erosion_pct` with live `(entry - current_ltp) / entry * 100`
- [ ] Shifter test: simulate premium erosion over time, confirm shift fires at 70%+
- [ ] Backtest shift proposal against live option chain before executing

### Phase C: CrewAI LLM Integration (Medium)
**Goal:** Test the hierarchical LLM-driven execution path.

- [ ] Set `DEEPSEEK_API_KEY` and run `python3 trading_desk.py --mock --full-session`
- [ ] Verify LLM correctly sequences agent calls (Scout → Researcher → PM → Exec)
- [ ] Verify LLM does NOT overrule deterministic tools (risk decisions stay in code)
- [ ] Tune prompt constraints to enforce "never fabricate readings"

### Phase D: Multi-Shift EOD Close (Medium)
**Goal:** Guarantee all positions are squared off by 15:20.

- [ ] Add time-based trigger: `if time > "15:20" and positions_open → EXIT_ALL`
- [ ] Close all open SL/TP orders, then square all positions
- [ ] Report final P&L to CFO agent

### Phase E: Error Recovery & Alerting (Medium)
**Goal:** System survives partial fills and broker disconnections.

- [ ] Partial fill handler: if 3 of 4 legs fill, place the 4th or cancel all
- [ ] Broker disconnect: pause → reconnect → resume monitoring
- [ ] Telegram alerts for SL hits, TP hits, shift actions, EOD closings
- [ ] Duplicate order prevention: check `desk.completed_orders` before re-placing

### Phase F: Strategy Expansion (Low)
**Goal:** Beyond Iron Butterfly — add Credit Spread, Iron Condor, Ratio Spread.

- [ ] Credit Spread: `engine_research_setup` selects CS when VIX > 20
- [ ] Iron Condor: wider body (sell 2 OTM strikes, buy 2 farther OTM)
- [ ] Ratio Spread: buy 1 ATM, sell 2 OTM (for trending markets)
- [ ] Strategy scoring: `tools/ta_strategy_tools.py` strategy_score tool

---

## 5. QUICK PRODUCTION READINESS CHECKLIST

```bash
# Run these to verify production readiness:

# 1. DuckDB is being populated
ls -la /home/trading_ceo/python-trader/varaha/data/varaha_data.duckdb
python3 -c "import duckdb; c=duckdb.connect('.../varaha_data.duckdb', read_only=True); print(c.execute('SELECT COUNT(*) FROM market_data').fetchone())"

# 2. Data capture script is running
ps aux | grep data_capture_v3

# 3. All existing tests pass
cd /home/trading_ceo/antariksh
python3 tests/test_integration_end_to_end.py

# 4. Production data flows
python3 -c "
import os; os.environ.pop('ANTARIKSH_MOCK_MODE','')
from trading_desk import engine_scout_regime
r = engine_scout_regime()
print(f'Live: VIX={r.vix} NIFTY={r.nifty_spot} Regime={r.regime}')
"

# 5. Broker API available
python3 -c "from broker_manager import BrokerManager; bm=BrokerManager(); print('Quotes:', bm.get_nifty_spot())"
```

---

## 6. ARCHITECTURE DECISIONS LOG

| Decision | Rationale |
|----------|-----------|
| CREWAI `@tool` wrappers call engine functions | Test harness uses engine functions directly (parameterized, typed returns); CrewAI uses tool wrappers (global state, JSON returns). No code duplication. |
| Risk decisions are deterministic code, not LLM | `ListenTriggers.on_order_update/on_feed_update` uses pure Python comparisons. LLM cannot override SL/TP logic. |
| Wings-first execution (BUY hedges before SELL straddle) | SELL legs consume margin. BUY legs unlock it. Sequencing matters. |
| DuckDB ATTACH READ_ONLY pattern | Avoids lock contention with `data_capture_v3_duckdb.py` writer process. |
| Max 2 shifts/session | Prevents infinite theta-chasing when VIX spikes mid-day. |
| Backtest-gated shifts | ShiftProposal must show positive P&L before Executioner acts. |
| Enum state machine for phases | Each phase gates tool availability. Executioner blocked unless phase=VALIDATION→ACTION. |
