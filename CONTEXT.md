# SESSION CONTEXT — Updated 2026-05-17 11:28

Project: Antariksh — CrewAI options trading desk (NIFTY Iron Butterfly)
Branch: `master` | Live data: VIX=18.42, NIFTY=23752.55, Regime=TRENDING_BULL

## Locations
```
/home/trading_ceo/antariksh/              ← Antariksh
/home/trading_ceo/python-trader/varaha/   ← Varaha (DuckDB capture)
/home/trading_ceo/python-trader/Shoonya_oAuthAPI-py/  ← Shoonya API
```
GitHub: `github.com/venkatseshadri/antariskh`

## Last Built
Fixed ta-lib NULL indicators: v3.1 buffer warmup from log + DuckDB reconnect retry + indicators redundancy log; fixed DATA_CAPTURE_V4.md false ta-lib claim

## Priority Queue
verify v3.1 indicators populate correctly on Monday

## What's Where (read on demand)
  `trading_desk.py` (1702 lines)
  `tests/test_integration_end_to_end.py` (263 lines)
  `ARCHITECTURE.md` (697 lines)
  `GAPS_AND_ROADMAP.md` (178 lines)
  `TRADING_DESK_VALIDATION.md` (443 lines)
  `crews/ta_crew.py` (424 lines)
  `crews/pm_crew.py` (167 lines)
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
f19d08f docs: fix DATA_CAPTURE_V4.md — ta-lib IS installed, ADX 78% non-null; May 15 restart cascade caused NULLs
128cf9a docs: add DATA_CAPTURE_V4.md — multi-TF aggregator schema, pipeline, last 10 rows
6f97294 remove sandwich/ — moved to standalone repo github.com/venkatseshadri/sandwich
2554dfd Sandwich: add Claude design analysis + full conversation PDF text
51bad2b Sandwich Step 1: mark complete, add PROGRESS.md
```
