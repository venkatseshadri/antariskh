# SESSION CONTEXT — Updated 2026-06-09 10:03

Project: Antariksh — CrewAI options trading desk (NIFTY Iron Butterfly)
Branch: `master` | Live data: VIX=16.01, NIFTY=23186.2, Regime=TRENDING_BEAR

## Locations
```
/home/trading_ceo/antariksh/              ← Antariksh
/home/trading_ceo/python-trader/varaha/   ← Varaha (DuckDB capture)
/home/trading_ceo/python-trader/Shoonya_oAuthAPI-py/  ← Shoonya API
```
GitHub: `github.com/venkatseshadri/antariskh`

## Last Built
PORCUPINE: built synthetic fault driver (--fault, 6 classes, 11/11 tests); fixed milestone design flaw that paused the autobuilder; tracked uncommitted sim bootstrap code

## Priority Queue
Resume autobuilder (rm sim/.autobuild_paused) → it builds the last item: lifecycle scenario (order→monitor→exit/EOD)

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
  `tools/contract_tools.py` (534 lines)

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
029fa74 docs(porcupine): record fault driver, milestone unblock, resume steps
ee24e9e porcupine: synthetic fault driver + milestone unblock + track bootstrap code
891e835 porcupine: VIX-null auto-enter guard (bug #4)
9b6df5a porcupine: F2 root-cause + permanent regression guards (bug #3)
45c71c6 fix: enricher varaha_auth path fix, prev_day lazy-init, completion_by_tf, CrewAI imports
```
