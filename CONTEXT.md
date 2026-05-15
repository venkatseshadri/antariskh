# SESSION CONTEXT — Updated 2026-05-15 09:22

Project: Antariksh — CrewAI options trading desk (NIFTY Iron Butterfly)
Branch: `master` | Live data: VIX=18.49, NIFTY=23719.0, Regime=SIDEWAYS

## Locations
```
/home/trading_ceo/antariksh/              ← Antariksh
/home/trading_ceo/python-trader/varaha/   ← Varaha (DuckDB capture)
/home/trading_ceo/python-trader/Shoonya_oAuthAPI-py/  ← Shoonya API
```
GitHub: `github.com/venkatseshadri/antariskh`

## Last Built
PA crew complete: rolling multi-TF bars + Batch 1 gap-capable indicators (SMA, RSI, ATR, MACD)

## Pipeline Status
- v3.1: 1-min capture (NIFTY/SENSEX) → Redis queue + log file
- v4: Rolling bar aggregation (5/15/30/60/240/1440-min) + Batch 1 indicators → market_data_multitf.duckdb
- PA Researcher: snapshot_multitf() → OHLC + Trend/Momentum/Volatility → phase reasoning (raw data only)

## Indicators Complete ✅

**Batch 1 - Gap-Capable** (work from market open):
✅ SMA 20/50/200 — trend identification
✅ RSI 14 — momentum measurement
✅ ATR 14 — volatility range
✅ MACD 12/26/9 — momentum confirmation

**Batch 2 - Gap-Sensitive** (accumulate intraday):
✅ ADX + DI+/DI- — trend strength & direction
✅ Bollinger Bands — volatility extremes
✅ OBV — on-balance volume
✅ CMF — Chaikin Money Flow (volume quality)
✅ CCI — oscillator for extremes

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
988ac5c feat(pa): add EOD dispatch with Telegram alerts
088469f feat(pa): add SQLite state.db persistence
f44b97d feat(pa): add ChromaDB RAG integration for trade learning
0fc75c2 feat(pa): add strategy selection analysis
8d306fe chore: update context with Brahmand MVP status
```
