# SESSION CONTEXT — Updated 2026-05-28 00:07

Project: Antariksh — CrewAI options trading desk (NIFTY Iron Butterfly)
Branch: `master` | Live data: DuckDB: check manually

## Locations
```
/home/trading_ceo/antariksh/              ← Antariksh
/home/trading_ceo/python-trader/varaha/   ← Varaha (DuckDB capture)
/home/trading_ceo/python-trader/Shoonya_oAuthAPI-py/  ← Shoonya API
```
GitHub: `github.com/venkatseshadri/antariskh`

## Last Built
Fixed root-cause data-capture outage (check_market_open ExecCondition inversion); added stale/expired-expiry entry guard in brahmand e2e_chain; fixed Flattrade token refresh (Selenium Manager) + exec_report cron path/arg

## Priority Queue
Verify 09:14 combined capture populates option_snapshots + entry guard holds (Thu 28-May); fix execution_tools _build_tsym Thursday->Tuesday before live mode; session_orchestrator still deferred Phase 1

## What's Where (read on demand)
  `trading_desk.py` (1929 lines)
  `tests/test_integration_end_to_end.py` (263 lines)
  `ARCHITECTURE.md` (698 lines)
  `GAPS_AND_ROADMAP.md` (209 lines)
  `TRADING_DESK_VALIDATION.md` (443 lines)
  `crews/ta_crew.py` (428 lines)
  `crews/pm_crew.py` (170 lines)
  `tools/risk_tools.py` (606 lines)
  `tools/execution_tools.py` (621 lines)
  `tools/contract_tools.py` (533 lines)

## Verify State
```bash
cd /home/trading_ceo/antariksh
git log --oneline -3
python3 tests/test_integration_end_to_end.py   # integration suite
python3 trading_desk.py --test-triggers        # 4 trigger tests
python3 -c "import os; os.environ.pop('ANTARIKSH_MOCK_MODE',''); from trading_desk import engine_scout_regime; r=engine_scout_regime(); print(f'Live: VIX={r.vix} Regime={r.regime}')"
```

## Recent Commits
```
cf67e58 fix: correct check_market_open.sh ExecCondition exit codes
f2c9cb9 chore: daily margin snapshot + fix malformed ralph imports
831afef feat: per-index DB paths, sandbox env var overrides, Redis tap tool
1b691b2 fix: v4 aggregator — per-index queues, EMA dedup, queue preservation
5476d2c fix: fall back to v3_ohlcv_queue if per-index key empty
```
