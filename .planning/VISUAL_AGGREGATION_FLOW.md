# Visual Flow: How Data Flows Through the System

## Data Capture Lifecycle (One Day)

```
MARKET OPEN (09:15)
│
├─ 09:15:00 ─── 1-min bar arrives
│  └─> data_capture: calculate 1-min indicators, write to DB
│      DB: [09:15, 1min, close=25005, adx=12, rsi=48, status=YELLOW]
│
├─ 09:16:00 ─── 1-min bar arrives
│  └─> data_capture: write 1-min bar
│      DB: [09:16, 1min, close=25015, adx=14, rsi=52, status=YELLOW]
│
├─ 09:17:00 ─── 1-min bar arrives
│  └─> data_capture: write 1-min bar
│
├─ 09:18:00 ─── 1-min bar arrives
│  └─> data_capture: write 1-min bar
│
├─ 09:19:00 ─── 1-min bar arrives
│  └─> data_capture: write 1-min bar
│
└─ 09:20:00 ─── 1-min bar arrives + 5-MIN MARK HIT! ⭐
   ├─> data_capture: write 1-min bar
   │   DB: [09:20, 1min, close=25035, adx=19, rsi=64, status=GREEN]
   │
   └─> multitf_aggregator: TRIGGERS! 🔴
       ├─ Read last 5 1-min bars (09:15-09:20)
       ├─ Aggregate OHLCV
       ├─ Recalculate ADX, RSI, ST on 5-min OHLC
       ├─ Compute status (GREEN/YELLOW/RED)
       └─ Write 5-min aggregation
           DB: [09:20, 5min, close=25035, adx=32, rsi=72, status=GREEN]
                         ↑ Different from 1-min! (19 vs 32)

(09:21-09:29: 9 more 1-min bars, aggregator idle)

└─ 09:30:00 ─── 1-min bar arrives + 15-MIN MARK HIT! ⭐
   ├─> data_capture: write 1-min bar
   │
   └─> multitf_aggregator: TRIGGERS!
       ├─ Read last 15 1-min bars (09:15-09:30)
       ├─ Recalculate indicators on 15-min OHLC
       └─ Write 15-min aggregation
           DB: [09:30, 15min, close=25115, adx=35, rsi=75, status=GREEN]
                           ↑ Even stronger on 15-min

(09:31-09:44: 14 more 1-min bars, aggregator idle)

└─ 09:45:00 ─── 1-min bar arrives + 5-MIN MARK HIT! ⭐
   └─> multitf_aggregator: 5-min aggregation (09:40-09:45)

(Continue pattern every 5 min, then 15 min, 30 min, 60 min, 240 min, 1440 min)

At 12:30:00 ─── CONSOLIDATION PHASE
│
└─ 12:30:00 ─── 1-min bar arrives + 5-MIN MARK HIT! ⭐
   └─> multitf_aggregator: 
       ADX drops from 35 to 28
       RSI drops from 72 to 58
       Status changes: 🟢 GREEN → 🟡 YELLOW ⚠️

At 12:35:00 ─── REVERSAL BEGINS
│
└─ 12:35:00 ─── 1-min bar arrives + 5-MIN MARK HIT! ⭐
   └─> multitf_aggregator: 
       SuperTrend FLIPS to BEARISH
       RSI crosses below 50
       Status changes: 🟡 YELLOW → 🔴 RED 🚨

At 12:45:00 ─── REVERSAL CONFIRMED
│
└─ 12:45:00 ─── 1-min bar arrives + 30-MIN MARK HIT! ⭐
   └─> multitf_aggregator: 
       30-min aggregation shows same RED status
       CONFIRMS CASCADE (5-min → 30-min following)

MARKET CLOSE (15:30)
│
└─ 15:30:00 ─── 1-min bar arrives + 60-MIN MARK HIT! ⭐
   └─> multitf_aggregator:
       Hour-long aggregation shows full reversal
       Back to open price (25000)
```

---

## Database Growth During Day

```
Time     | 1-min bars | 5-min bars | 15-min | 30-min | 60-min | Total Rows
─────────┼────────────┼────────────┼────────┼────────┼────────┼──────────
09:20    |     6      |     1      |   0    |   0    |   0    |     7
09:30    |    16      |     3      |   1    |   0    |   0    |    20
10:00    |    46      |     9      |   3    |   0    |   0    |    58
12:00    |   166      |    33      |  11    |   5    |   1    |   216
15:30    |   256      |    51      |  17    |   8    |   4    |   336
(+ 1440min: 1 row per day)

Total rows in DB: ~337 rows
Without aggregation: only 256 rows (1-min only)
Storage cost: ~31% more, but infinite value for PA decision-making
```

---

## PA Query Pattern During Market Hours

```
PA Crew (during 09:15-15:30):

Every minute:
  SELECT * FROM market_data 
  WHERE timeframe_min IN (5, 15, 30, 60)
  AND timestamp >= NOW() - INTERVAL 2 HOURS
  ORDER BY timestamp DESC
  
Result: Last 24 bars (every 5-min for 2 hours)

Example at 12:35:
  ┌─────────────┬────┬──────┬─────┬─────┬────────┐
  │ timestamp   │ tf │ close│ adx │ rsi │ status │
  ├─────────────┼────┼──────┼─────┼─────┼────────┤
  │ 12:35:00    │ 5  │25200 │ 30  │ 48  │  RED   │ ← Current
  │ 12:30:00    │ 5  │25280 │ 28  │ 58  │ YELLOW │
  │ 12:25:00    │ 5  │25300 │ 33  │ 69  │ GREEN  │
  │ 12:20:00    │ 5  │25290 │ 35  │ 71  │ GREEN  │
  │ 12:15:00    │ 5  │25300 │ 35  │ 72  │ GREEN  │
  │ 12:15:00    │ 30 │25300 │ 34  │ 70  │ GREEN  │
  │ 12:00:00    │ 5  │25295 │ 34  │ 72  │ GREEN  │
  │ 11:45:00    │ 5  │25285 │ 35  │ 71  │ GREEN  │
  │ 11:30:00    │ 15 │25250 │ 35  │ 71  │ GREEN  │
  └─────────────┴────┴──────┴─────┴─────┴────────┘

PA sees:
  Last 5-min: 🔴 RED (ADX=30, RSI=48)
  Last 15-min: 🟢 GREEN (ADX=35, RSI=71)
  Last 30-min: 🟢 GREEN (ADX=34, RSI=70)
  
  → "Lower TF flipped red, higher TF still green, but 
     lagging. Reversal cascade likely. EXIT NOW!"
```

---

## Code Structure (What Gets Built)

```
Current System:
├─ data_capture_v3_duckdb.py
│  ├─ Read NIFTY spot every minute
│  ├─ Calculate 1-min OHLCV
│  ├─ Calculate indicators (ADX, RSI, ST, EMA, etc)
│  ├─ Compute status (GREEN/YELLOW/RED)
│  └─ INSERT into market_data (timeframe_min=1)
│
└─ [Missing: multi-TF aggregation]

NEW: multitf_aggregator.py
├─ Runs every minute (after data_capture)
├─ Checks if timestamp is mark time:
│  ├─ 09:20 % 5 == 0? → Aggregate 5-min
│  ├─ 09:30 % 15 == 0? → Aggregate 15-min
│  ├─ 09:45 % 30 == 0? → Aggregate 30-min
│  ├─ 10:00 % 60 == 0? → Aggregate 60-min
│  ├─ 13:20 % 240 == 0? → Aggregate 4-hr
│  └─ 16:30 % 1440 == 0? → Aggregate daily
│
├─ For each mark time:
│  ├─ Query last N 1-min bars
│  ├─ Aggregate OHLCV
│  ├─ Recalculate indicators (ADX, RSI, ST, EMA)
│  ├─ Compute status (GREEN/YELLOW/RED)
│  └─ INSERT into market_data (timeframe_min=X)
│
└─ tools/pa_tools.py (NEW TOOL)
   ├─ snapshot_multitf(timestamp)
   │  ├─ Query all TF rows for that timestamp
   │  ├─ Return hierarchical status
   │  └─ Return PA recommendation
   │
   └─ Used by PA Reviewer & Analyst agents
```

---

## Real-Time Decision Making Example

```
📊 PA Dashboard (Live during market hours)

Time: 12:35:00

Query: "What should PM do now?"

PA calls: snapshot_multitf("2026-05-15 12:35:00")

Response:
{
  "timestamp": "2026-05-15 12:35:00",
  "consensus": "REVERSAL",
  "multitf": [
    {"tf": "1min", "status": "RED", "adx": 30, "rsi": 48},
    {"tf": "5min", "status": "RED", "adx": 30, "rsi": 48},
    {"tf": "15min", "status": "YELLOW", "adx": 32, "rsi": 52},
    {"tf": "30min", "status": "YELLOW", "adx": 33, "rsi": 58},
    {"tf": "60min", "status": "GREEN", "adx": 34, "rsi": 62},
    {"tf": "240min", "status": "GREEN", "adx": 32, "rsi": 65},
    {"tf": "1440min", "status": "GREEN", "adx": 30, "rsi": 68},
  ],
  "analysis": "Lower timeframes flipped red (reversal), 
              higher timeframes lagging (will follow). 
              Cascade in progress.",
  "action": "EXIT all long positions immediately",
  "confidence": 85
}

PA Recommendation to PM:
  ✗ Do NOT enter new longs
  ✓ EXIT existing longs (cascade starting)
  ✓ Consider short positions (trend reversed)
  
  Reasoning: "5-min and 1-min already red. 15/30-min 
             yellowing. 60+ still green but lagging.
             This is a cascade, expect 30-min to go red 
             within 10 minutes."

PM executes: EXIT all positions

10 minutes later (12:45): 30-min goes red (as predicted)

This is the power of multi-TF aggregation!
```

---

## Implementation Complexity

```
Lines of code to add:

multitf_aggregator.py:
  ├─ Timestamp checking logic: 20 lines
  ├─ Aggregation (OHLCV sum/min/max): 30 lines
  ├─ Indicator recalculation calls: 40 lines
  ├─ Status computation: 30 lines
  ├─ DuckDB write: 20 lines
  └─ Error handling: 20 lines
  = ~160 lines total (small!)

tools/pa_tools.py additions:
  ├─ snapshot_multitf() function: 50 lines
  └─ Updated crews/pa_crew.py: +1 tool wrapper
  = Simple

Changes to data_capture:
  ├─ Nothing! (it keeps doing 1-min only)
  └─ Just add timeframe_min=1 column
  = Minimal

Total new code: ~200 lines
Complexity: Low
Value: Extremely high

Risk: Very low (aggregator is independent, just reads & writes)
```

---

## Summary: What Happens Every 5 Minutes

```
🕐 At 09:20:00 (5-min mark):

Step 1 (09:20:00.000)
  data_capture writes: 1-min bar 
  multitf_aggregator reads: last 5 bars

Step 2 (09:20:00.010)
  Aggregate: 09:15/16/17/18/19/20 OHLCV
  Calculate: OHLC = [25000, 25038, 24995, 25035]

Step 3 (09:20:00.050)
  Recalculate: ADX(14) on aggregated close series
  Result: ADX = 32 (vs 19 on 1-min) ← KEY DIFFERENCE!

Step 4 (09:20:00.100)
  Compute status: GREEN (ADX>25, ST bullish, EMA cross)
  
Step 5 (09:20:00.150)
  INSERT into market_data:
    timestamp=09:20, tf=5min, close=25035, adx=32, 
    rsi=72, status=GREEN, ...

DONE! Took 150ms.

PA can now query and see 5-min status instantly.

Repeat at 09:25, 09:30, ... every 5 minutes during market hours.
```

This is the complete flow. Should we build it?
