# SESSION CONTEXT — Updated 2026-05-18 22:00

Project: Antariksh — Autonomous options trading desk (NIFTY Credit Spreads + Iron Butterfly)
Branch: `master` | 2 paper trades today | Deploying morphing PM + margin capture tomorrow (May 19, 0 DTE)

## Locations
```
/home/trading_ceo/antariksh/              ← Antariksh (orchestrator, agents, tools, config)
/home/trading_ceo/brahmand/               ← Brahmand (5-agent chain, kickoff, PM, margin capture)
/home/trading_ceo/python-trader/varaha/   ← Varaha (DuckDB + Redis capture v3.1+v4)
/home/trading_ceo/python-trader/Shoonya_oAuthAPI-py/  ← Shoonya broker API
```
GitHub: `github.com/venkatseshadri/antariskh` + `github.com/venkatseshadri/brahmand`

## Last Built (May 18 — All deployed)

**Entry Gate (Redis-only, 0 LLM, 0 DuckDB, ~100ms)**
- `antariksh/tools/entry_tools.py` — 9 family tools + deterministic scorers (score_trend_redis, score_traffic_light_redis, combine_entry_scores) + RL weight learner
- `antariksh/agents/entry/entry_check.py` — confidence-weighted fusion → signal-driven strategy
- `antariksh/config/entry_weights.json` — tunable TF weights, ADX thresholds, pattern scores
- v3.1 data capture pushes 15 indicator fields to Redis (ema, rsi, adx, st_direction, bb)

**Position Manager (single owner, no conflict)**
- `brahmand/position_manager.py` — 7-priority checks: decay→roll, hedge→tighten, signal→morph, SL, TP, floor, market close
- Integrated into `brahmand/kickoff.py` → monitor_trade() with legacy fallback
- `brahmand/e2e_chain.py` — signal-driven: BULLISH→PUT_SPREAD, BEARISH→CALL_SPREAD, NEUTRAL→BUTTERFLY

**Margin Capture + Wing Optimizer**
- `brahmand/margin_capture.py` — Shoonya span_calculator every 5 min, PE/CE margins ATM ±5 strikes
- `brahmand/wing_optimizer.py` — risk/reward scoring per wing, NIFTY lot=65, ROI% + R/R

**Paper trade mode:** max 99 trades/day, 5min cooldown, no TIME_EXIT

## Tomorrow's Cron
```
09:14  Data capture (v3.1+v4) starts
09:30  Kickoff every 5 min: Entry Gate → Position Manager → Margin-optimized spreads
09:30  Margin capture every 5 min: Shoonya span calc → wing_optimizer
14:35  Session orchestrator exit (Telegram P&L)
15:30  Market close → Post-Mortem + RL weight update
```

## Priority Queue
- Morphing position manager live test (0 DTE)
- RL weight learner: post-session LLM analyzes P&L, adjusts entry_weights.json
- Option LTP to Redis for PM (currently reads DuckDB)
- Wing optimizer integration into entry gate (auto-select wing at entry time)

## What's Where (read on demand)
  `MORPHING_POSITION_MANAGER.md` (full architecture docs)
  `brahmand/position_manager.py`
  `brahmand/kickoff.py`
  `brahmand/e2e_chain.py`
  `brahmand/margin_capture.py`
  `brahmand/wing_optimizer.py`
  `antariksh/tools/entry_tools.py`
  `antariksh/agents/entry/entry_check.py`
  `antariksh/config/entry_weights.json`

## Data Capture v3.1 + v4: COMPLETE & VALIDATED (May 19)

### Status: ✅ PRODUCTION READY — ZERO DATA LOSS

**v3.1 (1-min DuckDB + Redis):**
- 104 columns captured per bar
- 3,774 1-min bars in database
- 5 critical indicators pushed to Redis (ema, rsi, adx, st_direction, bb_pct_b)

**v4 (Multi-TF Aggregator):**
- 6 timeframes aggregated: 5/15/30/60/240/1440-min
- 331 aggregated bars (201 5-min, 67 15-min, 35 30-min, 19 60-min, 6 240-min, 3 1440-min)
- **DATA LOSS: ZERO** — All 1,522 source bars accounted for per timeframe

**Validation:**
- `validate_data_capture_complete.py` — comprehensive validation (10 checks)
- `check_data_capture_status.sh` — quick health check

**Critical Values Present:**
- ✓ OHLCV, Greeks (Δ, Γ, Θ), EMA, RSI, ADX, SuperTrend, VIX, Pivots, Support/Resistance, SMC structure, IV metrics

**How to Verify:**
```bash
# Quick check
./check_data_capture_status.sh

# Comprehensive validation
python3 validate_data_capture_complete.py

# Run v4 aggregator
python3 data_capture_v4_multitf_aggregator.py

# View detailed report
cat DATA_CAPTURE_VALIDATION_REPORT.md
```

**Files:**
- `data_capture_v4_multitf_aggregator.py` — v4 aggregator with zero-loss validation
- `validate_data_capture_complete.py` — comprehensive v3.1 + v4 validation
- `check_data_capture_status.sh` — quick health check
- `DATA_CAPTURE_VALIDATION_REPORT.md` — full technical report

**Next:**
1. Add v4 to cron (every 5 min during market hours)
2. Wire v4 into PA researcher for multi-TF pattern detection
3. Update entry gate to use multi-TF confluence signals
