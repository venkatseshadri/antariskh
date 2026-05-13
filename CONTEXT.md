# SESSION CONTEXT — Paste into new session

Project: Antariksh — CrewAI options trading desk (NIFTY Iron Butterfly)

## Locations
```
/home/trading_ceo/antariksh/              ← Antariksh
/home/trading_ceo/python-trader/varaha/   ← Varaha (DuckDB capture)
/home/trading_ceo/python-trader/Shoonya_oAuthAPI-py/  ← Shoonya API
```
GitHub: `github.com/venkatseshadri/antariskh` (master, pushed)

## Last Built
`trading_desk.py` (1702 lines) — 6-agent desk with state machine, ListenTriggers (OCO + TSL), Leg Shifter loop. Live DuckDB injection works. `tests/test_integration_end_to_end.py` → 39/39 PASSED.

## What's Where (read on demand)
| File | Contents |
|------|----------|
| `trading_desk.py` | Full desk: agents, engine functions, ListenTriggers, shifter, DESkState, CLI |
| `tests/test_integration_end_to_end.py` | 39 E2E checks (Scout→RiskAgent) |
| `ARCHITECTURE.md` | All 10 crews, 60+ tools, shared data, minute-by-minute flow |
| `GAPS_AND_ROADMAP.md` | 11 mock gaps, 6 phases A→F, test coverage |
| `TRADING_DESK_VALIDATION.md` | Flow diagrams, trigger tables, verification commands |

## Verify State
```bash
cd /home/trading_ceo/antariksh && git log --oneline -3
python3 tests/test_integration_end_to_end.py   # 39/39
python3 trading_desk.py --test-triggers        # 4 trigger tests
python3 -c "import os; os.environ.pop('ANTARIKSH_MOCK_MODE',''); from trading_desk import engine_scout_regime; r=engine_scout_regime(); print(f'Live: VIX={r.vix} Regime={r.regime}')"
```

## Priority Queue
1. Phase A: Wire broker API (order placement, fill prices, WebSocket callbacks)
2. Phase B: Live theta + fund balance from DuckDB/broker
3. Phase C: LLM-driven crew execution (needs `DEEPSEEK_API_KEY`)
