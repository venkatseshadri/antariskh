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
