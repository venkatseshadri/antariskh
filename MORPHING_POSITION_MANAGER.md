# Position Manager & Morphing Iron Butterfly

**Date:** 2026-05-18  
**Status:** Built, tested, deploying tomorrow (May 19)

## Overview

Entry gate (Trend + Traffic Light, 0 LLM, Redis-only) determines direction.  
Position manager dynamically adjusts open positions — rolling, hedging, morphing.  
Margin capture + wing optimizer select optimal spread width per market conditions.  
One system, one owner. No conflict between risk manager and position manager.

## New: Margin Capture & Wing Optimizer

**Source:** `brahmand/margin_capture.py`, `brahmand/wing_optimizer.py`

Every 5 minutes, Shoonya's `span_calculator` API captures margin requirements for PE and CE credit spreads at ATM ±5 strikes. The wing optimizer computes risk/reward per wing width.

### Formulas (NIFTY lot = 65)
```
Net Credit = premium_sell − premium_buy                     (per share)
Max Profit = Net Credit × 65                                 (per lot, both OTM at expiry)
Max Loss   = (strike_diff − Net Credit) × 65                 (per lot, both ITM at expiry)
ROI%       = (Net Credit × 65) / margin × 100
R/R        = Net Credit / (strike_diff − Net Credit)
```

### Capital Efficiency (PE Spread, 0 DTE)
| Wing | Margin | Net Cr/Lot | Max Loss/Lot | ROI% | R/R |
|------|--------|-----------|-------------|------|-----|
| 50pt | ₹114,986 | ₹1,424 | ₹1,826 | 1.2% | 0.78 |
| 100pt | ₹117,514 | ₹2,613 | ₹3,887 | 2.2% | 0.67 |
| 150pt | ₹120,094 | ₹3,542 | ₹6,208 | 3.0% | 0.57 |
| 200pt | ₹122,685 | ₹4,284 | ₹8,716 | 3.5% | 0.49 |
| 250pt | ₹125,286 | ₹4,852 | ₹11,398 | 3.9% | 0.43 |

**50→100pt gives the best marginal efficiency** (+₹470 credit per ₹1K added margin).
Marginal returns diminish sharply after 150pt. Default wing: 100pt.

### Cron
```
*/5 9-15 * * 1-5  cd /home/trading_ceo/brahmand && /usr/bin/python3 margin_capture.py >> logs/margin_capture.log
```

---

## Architecture

```
Every 5 min (kickoff.py cron: */5 9-15 * * 1-5)

  ├─ No active trade:
  │   ├─ check_entry()          — Redis-only, 0 LLM, ~100ms
  │   │   ├─ score_trend_redis()       — TF-weighted SMA/ADX/ST
  │   │   ├─ score_traffic_light_redis() — candle pattern matching
  │   │   └─ combine_entry_scores()    — confidence-weighted fusion
  │   │
  │   └─ if GO → run_full_chain(signal, confidence)
  │       ├─ BULLISH  → PUT_CREDIT_SPREAD  (sell PE@ATM, buy PE@OTM)
  │       ├─ BEARISH  → CALL_CREDIT_SPREAD (sell CE@ATM, buy CE@OTM)
  │       └─ NEUTRAL  → IRON_BUTTERFLY     (both sides)
  │
  └─ Active trade:
      monitor_trade() → position_manager.run() — 7 checks:

        P1  Theta decay ≥37.5% on sold leg    → ROLL to ATM
        P2  Hedge >150pt from sold strike     → TIGHTEN hedge
        P3  Entry gate signal changed          → MORPH (add/remove side)
        P4  SL hit (LTP ≥ fill × 1.50)        → CLOSE that side
        P5  TP hit (LTP ≤ fill × 0.50)        → CLOSE that side
        P6  Cumulative P&L ≤ -₹500            → CLOSE ALL
        P7  Market close (15:30 IST)          → CLOSE ALL
```

## Entry Gate (Redis-only, 0 DuckDB, 0 LLM)

Source: `antariksh/agents/entry/entry_check.py`

### Data Sources
- **Redis** `v3_ohlcv_queue` — live 1-min OHLCV + indicators (ema5, ema20, ema50, rsi, atr, adx, st_direction, bb_pct_b)
- **v3.1 data capture** pushes 15 fields to Redis every 60s
- **0 DuckDB calls** — avoids lock contention from capture writers

### Trend Scoring (`score_trend_redis`)
TF-weighted SMA/EMA scoring with ADX gates:
```
Each TF: SMA20 > SMA50 → bullish; < → bearish
Weights: daily=0.20, 4h=0.20, 1h=0.20, 30m=0.15, 15m=0.15, 5m=0.10
ADX gate: <10=noise(×0), <20=weak(×0.5), ≥25=normal(×1), ≥35=strong(×1.3)
ST boost: SuperTrend confirms direction → +2
Signal:  score > 3=BULLISH, < -3=BEARISH, else NEUTRAL
```

### Traffic Light Scoring (`score_traffic_light_redis`)
Candle color pattern matching across 6 TFs:
```
GREEN = close > open, RED = close < open
Patterns (priority order):
  MOMENTUM_PEAK           all 6 GREEN    → NEUTRAL (exhaustion risk)
  STRONG_BEAR_CONTINUATION all 6 RED     → BEARISH
  BULLISH_PULLBACK_RESUMING D=GREEN,4H=RED,1H=GREEN → BULLISH
  BULLISH_MILD_PULLBACK    D=GREEN,4H=GREEN,1H=RED  → BULLISH
  DEAD_CAT_BOUNCE          D=RED,1H=GREEN,15m=GREEN → BEARISH
  CHOPPY_INDECISION        3+3 split    → NEUTRAL
```

### Combined Decision (`combine_entry_scores`)
Confidence-weighted average — low-confidence families contribute less:
```
confidence = (c1² + c2²) / (c1 + c2) × multiplier
```
Example: Trend 5% + TL 80% → weighted = 75% (TL dominates, Trend's "I don't know" is ignored)

### Strategy Mapping
| Trend | TL | Signal | Strategy | Wing |
|-------|----|--------|----------|------|
| BULLISH | BULLISH | BULLISH | PUT_CREDIT_SPREAD | 150pt |
| BEARISH | BEARISH | BEARISH | CALL_CREDIT_SPREAD | 150pt |
| NEUTRAL | NEUTRAL | NEUTRAL | IRON_BUTTERFLY | 200pt |
| BULLISH | BEARISH | — | NO-GO (conflict) | — |
| Any < 35% conf | — | NO-GO | — |

---

## Position Manager

Source: `brahmand/position_manager.py`  
Integration: `brahmand/kickoff.py` → `monitor_trade()`

### Defaults (configurable)
```python
DECAY_PCT = 0.375       # 37.5% theta decay → roll trigger
HEDGE_GAP = 150         # pts from sold strike → tighten hedge
SL_PCT = 0.50           # 50% above entry → SL
TP_PCT = 0.50           # 50% below entry → TP
FLOOR = -500            # cumulative P&L floor
MAX_MORPHS = 3          # max morphs per day
WING_SPREAD = 150       # wing for credit spreads
WING_BUTTERFLY = 200    # wing for iron butterfly
```

### P1: Theta Decay → ROLL
When a sold leg decays 37.5% from entry:
1. Close sold leg at current LTP → book profit
2. Open new sold leg at current ATM → fresh theta
3. Recalculate SL/TP for the new leg
4. Benefiting from ₹5/order Shoonya brokerage

### P2: Hedge Gap → TIGHTEN
When hedge is >150pt from nearest sold strike:
1. Close old hedge
2. Open new hedge at sold_strike ± WING_SPREAD
3. Maintains protection without over-insuring

### P3: Signal Change → MORPH
When entry gate signal changes:
```
BULLISH → NEUTRAL  =  ADD call side     → Iron Butterfly
NEUTRAL → RED      =  CLOSE put side    → Call Credit Spread
RED → NEUTRAL      =  ADD put side      → Iron Butterfly
```
Max 3 morphs/day to prevent over-trading.

### P4-P5: SL/TP
- SL = fill × 1.50 (50% above entry)
- TP = fill × 0.50 (50% below entry)
- Position manager owns SL/TP. After ROLL, new SL/TP are set automatically.

### P6-P7: Exit Conditions
- Cumulative P&L ≤ -₹500 → close everything
- Market close (15:30 IST) → close everything

---

## State Tracking

File: `/tmp/brahmand_kickoff.json`
```json
{
  "date": "20260518",
  "trades_today": 2,
  "active_trade": {
    "entry_time": "15:20",
    "strategy_type": "IRON_BUTTERFLY",
    "legs": [...],
    "sl": {"ce": 171.6, "pe": 203.5},
    "tp": {"ce": 57.2, "pe": 67.8},
    "cumulative_pnl": 0,
    "morph_count": 0,
    "entry_scores": {
      "entry_combined_signal": "BULLISH",
      "entry_combined_confidence": 75
    }
  },
  "all_trades": [...],
  "post_mortem_done": true
}
```

---

## RL Weight Learning (Post-Session)

Source: `antariksh/tools/entry_tools.py` → `rl_update_weights()`

After market close, the post-mortem agent analyzes trades. Then `rl_update_weights()`:
1. Reads today's trade ledger with entry scores + P&L
2. Calls 1 LLM (DeepSeek) to analyze which weights produced good/bad decisions
3. Proposes weight adjustments to `config/entry_weights.json`
4. Applies small adjustments only (max ±15% per TF weight)

LLM is used ONLY for post-session learning. Runtime: 0 LLM calls.

---

## Files (May 18 changes)

| File | Role | New/Modified |
|------|------|-------------|
| `antariksh/tools/entry_tools.py` | 9 Redis-based tools + deterministic scorers + RL learner | Modified |
| `antariksh/agents/entry/entry_check.py` | Redis-only entry gate, 0 LLM | Modified |
| `antariksh/config/entry_weights.json` | Configurable TF weights, ADX thresholds, pattern scores | New |
| `brahmand/position_manager.py` | 7-trigger position manager, single owner | New |
| `brahmand/kickoff.py` | Integrated PM, removed trade limits, legacy fallback | Modified |
| `brahmand/e2e_chain.py` | Signal-driven strategy selection (PUT/CALL/BUTTERFLY) | Modified |
| `python-trader/varaha/data_capture_v3.1_duckdb.py` | Redis push now includes 15 indicator fields | Modified |
| `brahmand/config/agents_registry.yaml` | 9 entry agents registered | Modified |
| `brahmand/config/tools_registry.yaml` | Entry analysis tools registered | Modified |

## Cron (tomorrow's schedule)

```
09:14  Data capture + v4 aggregator starts
09:30  Market opens — kickoff fires every 5 min:
         Entry gate → Redis → GO/NO-GO → Position Manager
14:35  Session orchestrator exit (Telegram P&L report)
15:30  Market close → Position manager P7 close-all
15:35  EOD cleanup
16:00  Post-mortem + RL weight update
```
