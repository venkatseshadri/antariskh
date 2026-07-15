# SESSION CONTEXT — Updated 2026-07-15 20:32

Project: Antariksh — CrewAI options trading desk (NIFTY Iron Butterfly)
Branch: `feat/ouroboros-lld-gap` | Live data: VIX=13.26, NIFTY=24073.45, Regime=SIDEWAYS

## Locations
```
/home/trading_ceo/antariksh/              ← Antariksh
/home/trading_ceo/python-trader/varaha/   ← Varaha (DuckDB capture)
/home/trading_ceo/python-trader/Shoonya_oAuthAPI-py/  ← Shoonya API
```
GitHub: `github.com/venkatseshadri/antariskh`

## Last Built
Built NUCLEUS capital-orchestration layer: dynamic tier ceilings (T1 ATOM/T3 HYDROGEN real, T2 PROTON/T4 NEUTRON simulated) swept off live Shoonya margin, wired into ATOM's risk gate + HYDROGEN's entry gate

## Priority Queue
Watch first live NUCLEUS cron cycles; HYDROGEN's own check_account_margin() has the same collat/col field-name bug nucleus.py just fixed — flagged, not fixed (out of scope, DRY_RUN today)

## What's Where (read on demand)
  `trading_desk.py` (1928 lines)
  `tests/test_integration_end_to_end.py` (263 lines)
  `ARCHITECTURE.md` (698 lines)
  `GAPS_AND_ROADMAP.md` (209 lines)
  `TRADING_DESK_VALIDATION.md` (443 lines)
  `crews/ta_crew.py` (428 lines)
  `crews/pm_crew.py` (170 lines)
  `tools/risk_tools.py` (606 lines)
  `tools/execution_tools.py` (621 lines)
  `tools/contract_tools.py` (526 lines)

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
5c876bc fix: scrip_master was never refreshed + built from fake demo data (T25)
a0edb4a Suppress PENGUIN health report on weekends/holidays
6bc1eae Fix structure_type forcing HH/LL on genuinely ambiguous bars
4b7f047 Fix SuperTrend consensus tie-break + VWAP always-None for NIFTY/SENSEX
cc91353 fix: broker token refresh timing out — bump login subprocess timeout 120s→300s
```
