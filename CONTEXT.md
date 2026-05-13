# ANTARIKSH SESSION CONTEXT — Paste into new Claude session

## PROJECT LOCATIONS
```
/home/trading_ceo/antariksh/              ← Antariksh (CrewAI trading desk)
/home/trading_ceo/python-trader/varaha/   ← Varaha (data capture, DuckDB)
/home/trading_ceo/python-trader/Shoonya_oAuthAPI-py/ ← Shoonya broker API
```

Project: Antariksh (/home/trading_ceo/antariksh)
GitHub: github.com/venkatseshadri/antariskh (master, fully pushed)
Type: CrewAI role-based options trading system (NIFTY Iron Butterfly)
Broker: Shoonya (primary) + Flattrade (secondary)

Dependency: Varaha (/home/trading_ceo/python-trader/varaha/)
  data_capture_v3_duckdb.py — 1-min REST poll loop → varaha_data.duckdb
  run_data_capture.sh / watchdog_capture.sh — cron-managed
  varaha_auth.py — Shoonya + Flattrade authentication (VarahaConnect)

## LAST SESSION BUILT
trading_desk.py (1702 lines) — full multi-agent options trading desk:
  6 agents: Scout→Researcher→PM→Executioner→RiskSentry→LegShifter
  State machine: PREPARATION→VALIDATION→ACTION→MAINTENANCE→CLOSED
  5 typed data packets: MarketRegime, ProposedSetup, AuthorizedOrder, HandoffReport, ShiftProposal
  ListenTriggers class: on_order_update (OCO), on_feed_update (SL/TSL), on_risk_command
  Leg Shifter loop: theta exhaustion >70% → propose shift → Researcher backtests → Risk directs Exec
  LIVE DuckDB injection: engine_scout_regime() reads varaha_data.duckdb for real VIX/NIFTY/ADX/ST
  Engine functions (testable): engine_scout_regime, engine_research_setup, engine_pm_validate, engine_execute_basket
  @tool wrappers for CrewAI hierarchical mode

Integration test: tests/test_integration_end_to_end.py (263 lines) — 39/39 PASSED

## FULL SYSTEM (10 crews, 24 agents, 60+ tools)
- TA (4): Scout, Validator, Analyst, Compliance → reads DuckDB
- PM (2): Strategist, Reporter → strategy selection, strike calc, SPAN margins
- AM (2): P&L tracker, Reporter → broker margin APIs
- CEO (2): Guardian, Reporter → governance, escalation
- OM (3): Pre-flight, Cron, Reporter → token/code/network/disk health → GO/NOGO
- PA (2): Reviewer, Analyst → post-mortem, counterfactuals, SL optimization
- CTO→Dev→QA (3): engineering pipeline, self-modifying code
- Trading Desk (6): above

## DATA SOURCES
- varaha_data.duckdb (populated by data_capture_v3_duckdb.py, 1-min REST poll)
  → market_data: adx, supertrend_direction, india_vix, spot, greeks
  → option_snapshots: strike, CE/PE, ltp, bid, ask, greeks per option
- static_metadata.db: scrip_master (token, tsym, lot size, expiry)
- Shoonya REST API: get_quotes, place_order, modify_order, cancel_order, span_calculator
- Shoonya WebSocket: quote feed (tk,lp) + order feed (noid,status)

## WHAT'S MOCKED → NEEDS PRODUCTION WIRING (Phase A priority)
1. Order placement: simulated IDs → wire BrokerManager.execute_trade()
2. Fill prices: MOCK_ENTRY=100.0 → wire BrokerManager.get_ltp()
3. WebSocket feed: static tick data → register on_feed_update as WS callback
4. WebSocket orders: static COMPLETE → register on_order_update as WS callback
5. Live theta: hardcoded -2.5 → wire MonitorPnLGreeksTool into shifter_evaluate()
6. Fund balance: mock_balance=200000 → wire check_capital_limits() into engine_pm_validate

## VERIFICATION COMMANDS
python3 trading_desk.py --show-flows           # Architecture diagram
python3 trading_desk.py --test-triggers        # 4 listen trigger tests
python3 trading_desk.py --mock --maintenance-cycle  # One maintenance cycle
python3 tests/test_integration_end_to_end.py   # 39/39 E2E conveyor belt tests

# Read LIVE market data from DuckDB (no mock):
python3 -c "import os; os.environ.pop('ANTARIKSH_MOCK_MODE',''); from trading_desk import engine_scout_regime; r=engine_scout_regime(); print(f'Live: VIX={r.vix} NIFTY={r.nifty_spot} Regime={r.regime}')"

## KEY DOCS ON DISK
ARCHITECTURE.md         — 10 crews, 60+ tools, data flow, minute-by-minute timeline
GAPS_AND_ROADMAP.md     — 11 mock gaps, 6 phases A→F, test coverage, decisions log
TRADING_DESK_VALIDATION.md — architecture diagrams, flow tables, verification commands

## GIT
Last 2 commits on master: 187aa31 (docs) + f9c0abf (trading_desk feat)
Working tree clean, fully pushed.
