# SESSION CONTEXT — Updated 2026-06-09 23:59

Project: Antariksh — CrewAI options trading desk (NIFTY Iron Butterfly)
Branch: `master` | Live data: VIX=15.56, NIFTY=23257.75, Regime=TRENDING_BEAR

## Locations
```
/home/trading_ceo/antariksh/              ← Antariksh
/home/trading_ceo/python-trader/varaha/   ← Varaha (DuckDB capture)
/home/trading_ceo/python-trader/Shoonya_oAuthAPI-py/  ← Shoonya API
```
GitHub: `github.com/venkatseshadri/antariskh`

## Last Built
Built cached position-research (UNICORN pattern for position manager): position_research_cache + position_research.py + cron; run_bridge applies cached morph/roll/tighten, protective floor/SL/TP/EOD stay live; fixed broken risk_agent_crew sync call. Tests 10/10 + position_cache sim PASS

## Priority Queue
RISK-PATH: run_bridge rewire re-activates deterministic morph/roll/tighten+floor+resting-SL/TP at next position-manager cron start (market open) — Board review before deploy. 15-min research cron NOT installed (cache activation = separate step)

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
35bc890 porcupine: position_cache scenario — proves cached-research hot path (real position_manager)
1aa70ae chore: auto-update session context
0d43821 docs(porcupine): v4 aggregator wired into sim (bug #3b E2E guard)
65a4e69 porcupine: wire v4 aggregator into the sim — bug #3b end-to-end guard
ed409cd chore: auto-update session context
```
