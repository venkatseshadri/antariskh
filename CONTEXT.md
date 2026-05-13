# SESSION CONTEXT — Updated 2026-05-13 09:16

Project: Antariksh — CrewAI options trading desk (NIFTY Iron Butterfly)
Branch: `master` | Live data: VIX=18.64, NIFTY=23625.1, Regime=SIDEWAYS

## Locations
```
/home/trading_ceo/antariksh/              ← Antariksh
/home/trading_ceo/python-trader/varaha/   ← Varaha (DuckDB capture)
/home/trading_ceo/python-trader/Shoonya_oAuthAPI-py/  ← Shoonya API
```
GitHub: `github.com/venkatseshadri/antariskh`

## Last Built
Created auto-update script + CLAUDE.md session rules

## Priority Queue
Phase A: Wire broker API into engine_execute_basket

## What's Where (read on demand)
  `trading_desk.py` (1702 lines)
  `tests/test_integration_end_to_end.py` (263 lines)
  `ARCHITECTURE.md` (416 lines)
  `GAPS_AND_ROADMAP.md` (169 lines)
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
919dafd docs: slim CONTEXT to lightweight index
08548ef docs: add project file paths for Antariksh + Varaha + Shoonya
854618c docs: session context for fast resume
187aa31 docs: master architecture + gaps/roadmap for Antariksh trading desk
f9c0abf feat(trading_desk): unified multi-agent options trading system
```
