# Multi-Timeframe Aggregation: Minute-by-Minute Walkthrough

**Scenario:** Market opens at 09:15, trending UP until 12:15, then PAUSE, then REVERSAL.

---

## MINUTE 1: 09:15 — MARKET OPEN

### What Happens:
```
09:15:00 — First 1-min bar closes
┌──────────────────────────────────────────┐
│ 1-MIN BAR ARRIVES                         │
├──────────────────────────────────────────┤
│ timestamp: 09:15:00                      │
│ timeframe_min: 1                         │
│ ohlc: [25000, 25010, 24995, 25005]       │
│ volume: 1250 contracts                   │
│ adx: 12 (weak)                           │
│ rsi: 48 (neutral)                        │
│ st_consensus: NEUTRAL                    │
│ status: YELLOW (weak signals)            │
└──────────────────────────────────────────┘

Action: data_capture writes to market_data
  INSERT INTO market_data VALUES (
    timestamp='09:15:00',
    timeframe_min=1,
    open=25000, high=25010, low=24995, close=25005,
    volume=1250,
    adx=12, rsi=48, st_consensus='NEUTRAL',
    status='YELLOW'
  )

PA can query: No decision yet (need more bars)
```

---

## MINUTE 2: 09:16 — Aggregator Idle

```
09:16:00 — Second 1-min bar arrives
┌──────────────────────────────────────────┐
│ 1-MIN BAR ARRIVES                         │
├──────────────────────────────────────────┤
│ timestamp: 09:16:00                      │
│ open: 25005, high: 25020, low: 25000     │
│ close: 25015                             │
│ volume: 1320                             │
│ adx: 14 (still weak)                     │
│ rsi: 52 (neutral, slightly up)           │
│ status: YELLOW                           │
└──────────────────────────────────────────┘

Action: data_capture writes 1-min bar
  INSERT market_data (timeframe_min=1, ...)

Multitf_aggregator: IDLE (not a mark time yet)

DB state:
  09:15:00, 1min: 25005 close, YELLOW
  09:16:00, 1min: 25015 close, YELLOW
```

---

## MINUTE 3: 09:17 — Aggregator Still Idle

```
09:17:00 — Third 1-min bar
│ open: 25015, high: 25025, low: 25010
│ close: 25020
│ volume: 1400
│ adx: 15
│ rsi: 54
│ status: YELLOW

Action: Write 1-min bar only
```

---

## MINUTE 4: 09:18 — Aggregator Still Idle

```
09:18:00 — Fourth 1-min bar
│ open: 25020, high: 25030, low: 25015
│ close: 25028
│ volume: 1450
│ adx: 16
│ rsi: 58
│ status: YELLOW → GREEN (starting to trend)

Action: Write 1-min bar only
```

---

## MINUTE 5: 09:19 — Aggregator Still Idle

```
09:19:00 — Fifth 1-min bar
│ open: 25028, high: 25035, low: 25025
│ close: 25032
│ volume: 1500
│ adx: 18
│ rsi: 61
│ status: GREEN (momentum building)

Action: Write 1-min bar only
```

---

## ⭐ MINUTE 6: 09:20 — AGGREGATOR TRIGGER (5-MIN MARK)

### This is where the magic happens!

```
09:20:00 — Sixth 1-min bar + AGGREGATOR RUNS
┌──────────────────────────────────────────────────────────┐
│ STEP 1: New 1-min bar arrives                            │
├──────────────────────────────────────────────────────────┤
│ timestamp: 09:20:00                                      │
│ open: 25032, high: 25038, low: 25030                     │
│ close: 25035                                             │
│ volume: 1550                                             │
│ adx: 19                                                  │
│ rsi: 64                                                  │
│ status: GREEN                                            │
│                                                          │
│ Action: Write 1-min bar to DB ✓                          │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│ STEP 2: MULTITF_AGGREGATOR DETECTS 5-MIN MARK (09:20)   │
├──────────────────────────────────────────────────────────┤
│ Condition: timestamp % 5 == 0 ✓                          │
│ Action: Aggregate last 5 bars (09:15-09:20)             │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│ STEP 3: AGGREGATION (5 1-min bars → 1 5-min bar)        │
├──────────────────────────────────────────────────────────┤
│ Last 5 bars in DB:                                       │
│   09:15:00  open=25000, close=25005                      │
│   09:16:00  open=25005, close=25015                      │
│   09:17:00  open=25015, close=25020                      │
│   09:18:00  open=25020, close=25028                      │
│   09:19:00  open=25028, close=25032                      │
│ (new 1-min just written)                                 │
│   09:20:00  open=25032, close=25035                      │
│                                                          │
│ Aggregated 5-min OHLC:                                   │
│   open:  25000 (first bar's open)                        │
│   high:  25038 (max of all highs)                        │
│   low:   24995 (min of all lows)                         │
│   close: 25035 (last bar's close)                        │
│   volume: 1250+1320+1400+1450+1500+1550 = 8470           │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│ STEP 4: RECALCULATE INDICATORS ON 5-MIN OHLC           │
├──────────────────────────────────────────────────────────┤
│ Input: Close series (09:15-09:20)                        │
│   [25005, 25015, 25020, 25028, 25032, 25035]            │
│                                                          │
│ COMPARE 1-min vs 5-min indicators:                       │
│                                                          │
│ ADX (14-period):                                         │
│   1-min (on 1-min closes): 19 ← weak                    │
│   5-min (on 5-min OHLC):   32 ← STRONG! ✓               │
│                                                          │
│ RSI (14-period):                                         │
│   1-min: 64 ← overbought but recent                     │
│   5-min: 72 ← MORE overbought (longer view)             │
│                                                          │
│ SuperTrend:                                              │
│   1-min: BULLISH (up trend)                              │
│   5-min: BULLISH (confirmed on 5-min)                   │
│                                                          │
│ EMA (5, 20, 50):                                         │
│   1-min: 5>20 (bullish crossover) ✓                     │
│   5-min: 5>20 (same, more confirmed)                    │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│ STEP 5: COMPUTE 5-MIN STATUS                             │
├──────────────────────────────────────────────────────────┤
│ Decision Logic:                                          │
│   ADX=32 (>25) ✓ STRONG TREND                           │
│   RSI=72 ✓ BULLISH (but overbought)                     │
│   ST=BULLISH ✓                                           │
│   EMA=BULLISH ✓                                          │
│   VIX=18 ✓ LOW (risk-on)                                │
│                                                          │
│ Status: 🟢 GREEN (Strong uptrend confirmed)             │
│ Trend_strength: 88%                                      │
│ Momentum: BULLISH                                        │
│ Recommendation: BUY (confidence 75%+)                    │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│ STEP 6: WRITE 5-MIN AGGREGATION TO DB                    │
├──────────────────────────────────────────────────────────┤
│ INSERT INTO market_data VALUES (                         │
│   timestamp='09:20:00',          ← bar CLOSE time       │
│   timeframe_min=5,               ← this is a 5-min bar   │
│   open=25000,                    ← 09:15 open           │
│   high=25038,                    ← max of 5 bars        │
│   low=24995,                     ← min of 5 bars        │
│   close=25035,                   ← 09:20 close          │
│   volume=8470,                   ← sum of 5 bars        │
│   adx=32,                        ← recalculated on 5-min │
│   rsi=72,                        ← recalculated on 5-min │
│   st_consensus='BULLISH',        ← recalculated         │
│   status='GREEN',                ← computed from above   │
│   trend_strength=88,             ← confidence           │
│   momentum='BULLISH'              ← final judgment       │
│ )                                                        │
└──────────────────────────────────────────────────────────┘

DB after 09:20:
  ✓ Six 1-min bars (09:15, 09:16, 09:17, 09:18, 09:19, 09:20)
  ✓ One 5-min bar (09:20, aggregated from 09:15-09:20)

🔍 PA Can Query NOW:
  "What's the current 5-min status?"
  SELECT * FROM market_data 
  WHERE timeframe_min=5 
  ORDER BY timestamp DESC LIMIT 1
  
  Result: 09:20, 5min, status=GREEN, adx=32, rsi=72
  
  PA Decision: "Entry signal confirmed on 5-min. ADX=32, 
               EMA bullish. Safe to BUY Iron Fly."
```

---

## MINUTE 7: 09:21 — Back to 1-Min Only

```
09:21:00 — New 1-min bar
│ open: 25035, high: 25042, low: 25033
│ close: 25040
│ volume: 1600
│ adx: 20
│ rsi: 67
│ status: GREEN

Action: Write 1-min bar only (not a mark time)

Aggregator: IDLE
```

---

## MINUTES 8-24: Regular 1-Min Bars

```
09:22:00 — 1-min bar
09:23:00 — 1-min bar
09:24:00 — 1-min bar
... (no aggregation)
```

---

## ⭐ MINUTE 25: 09:30 — NEXT AGGREGATOR TRIGGER (15-MIN MARK)

```
09:30:00 — New 1-min bar PLUS aggregator trigger
┌──────────────────────────────────────────────────────────┐
│ STEP 1: Write new 1-min bar (09:30)                      │
├──────────────────────────────────────────────────────────┤
│ timestamp: 09:30:00                                      │
│ close: 25115 (market up 115 pts from open)              │
│ adx: 28                                                  │
│ rsi: 68                                                  │
│ status: GREEN                                            │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│ STEP 2: Detect 15-min mark (09:30 % 15 == 0)            │
├──────────────────────────────────────────────────────────┤
│ Aggregate: Last 15 1-min bars (09:15-09:30)             │
│                                                          │
│ Sum of 15 closes: [25005, 25015, 25020, 25028, 25032,   │
│                    25035, 25040, 25045, 25055, 25065,   │
│                    25075, 25085, 25095, 25105, 25115]   │
│                                                          │
│ Aggregated 15-min OHLC:                                  │
│   open: 25000 (09:15 open)                              │
│   high: 25150 (max of all)                              │
│   low: 24995 (min of all)                               │
│   close: 25115 (09:30 close)                            │
│   volume: sum = 22500 contracts                          │
│                                                          │
│ RECALCULATED INDICATORS:                                 │
│   adx: 35 (even stronger on 15-min) ← KEY POINT!       │
│   rsi: 75 (more overbought on longer period)            │
│   st_consensus: BULLISH (confirmed)                      │
│   ema_5/20: BULLISH CROSS confirmed                      │
│                                                          │
│ Status: 🟢 GREEN (Very strong uptrend)                  │
│ Trend_strength: 92%                                      │
│ Recommendation: STRONG_BUY                               │
└──────────────────────────────────────────────────────────┘

INSERT INTO market_data VALUES (
  timestamp='09:30:00',
  timeframe_min=15,
  open=25000,
  high=25150,
  low=24995,
  close=25115,
  volume=22500,
  adx=35,
  rsi=75,
  st_consensus='BULLISH',
  status='GREEN',
  trend_strength=92,
  recommendation='STRONG_BUY'
)

PA Now Sees:
  5-min (09:20): GREEN, ADX=32, RSI=72
  5-min (09:25): GREEN, ADX=33, RSI=73
  5-min (09:30): GREEN, ADX=34, RSI=74
  15-min (09:30): GREEN, ADX=35, RSI=75 ← STRONG!
  
  PA thinks: "All timeframes green, ADX climbing, RSI elevated.
             Market in strong uptrend. Good entry window."
```

---

## CONTINUING THROUGH THE DAY...

### 12:15 — PEAK (3 hours of UP trend)

```
12:15:00 — 5-min mark aggregation
┌──────────────────────────────────────────────────────────┐
│ Market: 25300 (up 300 from open)                         │
│                                                          │
│ 5-min OHLC:                                              │
│   open: 25280, high: 25320, low: 25275, close: 25300   │
│   volume: 9000                                           │
│                                                          │
│ RECALCULATED 5-min Indicators:                           │
│   adx: 35 (STRONG, peak of uptrend)                     │
│   rsi: 72 (OVERBOUGHT! ⚠️)                              │
│   st_consensus: BULLISH (still)                          │
│   vix: 16.5 (compressed)                                │
│                                                          │
│ Status: 🟢 GREEN (but with warning)                     │
│ Warning: "RSI overbought, consider taking profit"       │
└──────────────────────────────────────────────────────────┘

PA Decision:
  "5-min: RSI=72 overbought signal. Strong trend (ADX=35)
   but extreme momentum. TAKE_PROFIT now or scale back."
```

### 12:20 — 5-MIN AGGREGATION

```
12:20:00
│ 5-min close: 25290
│ adx: 35
│ rsi: 71 (cooling slightly)
│ status: GREEN

PA: "RSI still high but cooling. Still in uptrend."
```

### ⭐ 12:30 — 5-MIN AGGREGATION (TROUBLE SIGNAL)

```
12:30:00
┌──────────────────────────────────────────────────────────┐
│ Market: 25280 (DECLINING from 25300 peak)               │
│                                                          │
│ 5-min close: 25280                                       │
│ 5-min high: 25305 (inside yesterday's range)            │
│ 5-min low: 25270 (approaching support)                  │
│                                                          │
│ RECALCULATED 5-min Indicators:                           │
│   adx: 28 ← DECLINING! (from 35)                        │
│   rsi: 58 ← COOLING FAST! (from 72)                     │
│   st_consensus: BULLISH (still, but weakening)          │
│                                                          │
│ Status: 🟡 YELLOW (consolidation!)                      │
│ Interpretation: "Trend losing momentum. Consolidation   │
│                 phase. Risk: possible reversal next."    │
└──────────────────────────────────────────────────────────┘

PA Critical Decision:
  "🟡 Status flipped to YELLOW. ADX declining (35→28),
   RSI cooling (72→58). DO NOT ENTER new positions.
   Wait for next 5-min bar:
   - If 🟢 GREEN again: continuation
   - If 🔴 RED: reversal confirmed, EXIT all longs"
```

### ⭐ 12:35 — 5-MIN AGGREGATION (REVERSAL STARTS)

```
12:35:00
┌──────────────────────────────────────────────────────────┐
│ Market: 25200 (DOWN 100 from 12:30 close)              │
│                                                          │
│ 5-min close: 25200                                       │
│ 5-min high: 25285 (last bar's high)                     │
│ 5-min low: 25190 ← BREAKING SUPPORT                     │
│                                                          │
│ RECALCULATED 5-min Indicators:                           │
│   adx: 30 (momentum growing — downward!)                │
│   rsi: 48 ← CROSSED BELOW 50! (momentum flip)          │
│   st_consensus: BEARISH ← FLIPPED!                      │
│   ema_5 < ema_20: BEARISH CROSS                         │
│                                                          │
│ Status: 🔴 RED (Reversal confirmed!)                    │
│ Strength: 75% ← AS CONFIDENT AS UPTREND WAS             │
│ Recommendation: STRONG_SELL                              │
└──────────────────────────────────────────────────────────┘

PA EMERGENCY DECISION:
  "🔴 REVERSAL CONFIRMED!
   - SuperTrend flipped to BEARISH
   - RSI broke below 50 (momentum flip)
   - EMA crossover broken
   - ADX=30 (strong move downward)
   
   ACTION: EXIT ALL LONG POSITIONS IMMEDIATELY!
   This is a CASCADE — 15min/30min/1hr will follow."
```

### 12:45 — 30-MIN AGGREGATION MOMENT

```
12:45:00 (30-min mark)
┌──────────────────────────────────────────────────────────┐
│ Aggregating last 30 1-min bars (12:15-12:45)            │
│                                                          │
│ 30-min OHLC:                                             │
│   open: 25300 (12:15 open)                              │
│   high: 25320 (peak during first part)                  │
│   low: 25180 (lowest in last 15 min)                    │
│   close: 25190 (current)                                │
│                                                          │
│ RECALCULATED 30-min Indicators:                          │
│   adx: 32 (strong move, currently downward)             │
│   rsi: 42 (moved below 50, back to oversold risk)       │
│   st_consensus: BEARISH (flipped)                        │
│   ema_cross: BEARISH                                     │
│                                                          │
│ Status: 🔴 RED (Downtrend confirmed on 30-min)          │
│ Strength: 80%                                            │
│ Pattern: "Market peaked at 25300, now in -110pt reversal"
└──────────────────────────────────────────────────────────┘

CRITICAL: 30-min confirms what 5-min saw — not a blip, it's real!

PA sees progression:
  5-min (12:35):  🔴 RED, ADX=30, RSI=48
  5-min (12:40):  🔴 RED, ADX=31, RSI=45
  5-min (12:45):  🔴 RED, ADX=31, RSI=42
  30-min (12:45): 🔴 RED, ADX=32, RSI=42 ← CONFIRMS CASCADE
  
  Conclusion: "This is NOT a pullback. Full reversal underway."
```

### 15:30 — END OF DAY (1-HOUR MARK)

```
15:30:00 (60-min mark)
┌──────────────────────────────────────────────────────────┐
│ Aggregating 60 1-min bars (14:30-15:30)                 │
│                                                          │
│ 60-min OHLC:                                             │
│   open: 25000 (14:30)                                   │
│   high: 25200                                            │
│   low: 25000 ← BACK TO OPEN!                            │
│   close: 25000 (end of session)                          │
│                                                          │
│ RECALCULATED 60-min Indicators:                          │
│   adx: 28 (strong move, but cooling)                    │
│   rsi: 32 (oversold)                                    │
│   st_consensus: BEARISH                                 │
│   ema_cross: BEARISH                                    │
│                                                          │
│ Status: 🔴 RED (reversal confirmed on hourly)           │
│ Pattern: "Full reversal to open completed"              │
└──────────────────────────────────────────────────────────┘

FULL DAY VIEW (PA Summary):
  
  ⏰ 09:20 (5min):   🟢 GREEN  ADX=32  RSI=72  → "BUY signal"
  ⏰ 09:30 (15min):  🟢 GREEN  ADX=35  RSI=75  → "STRONG BUY"
  ⏰ 12:15 (5min):   🟢 GREEN  ADX=35  RSI=72  → "PEAK, take profit"
  ⏰ 12:30 (5min):   🟡 YELLOW ADX=28  RSI=58  → "⚠️  PAUSE WARNING"
  ⏰ 12:35 (5min):   🔴 RED    ADX=30  RSI=48  → "🚨 REVERSAL, EXIT!"
  ⏰ 12:45 (30min):  🔴 RED    ADX=32  RSI=42  → "Confirmed, cascade"
  ⏰ 15:30 (60min):  🔴 RED    ADX=28  RSI=32  → "Back to open, done"
```

---

## KEY INSIGHTS FROM THIS WALKTHROUGH

### 1. **Why Recalculate Indicators?**
```
1-min ADX at 12:30:  18 (weak) ← MISLEADING
5-min ADX at 12:30:  28 (strong) ← ACCURATE

If PA used 1-min ADX, it would think trend is weak (ADX=18).
But 5-min ADX shows strong momentum (ADX=28), which is correct.

The reversal is a STRONG move down (ADX=28), not a weak one.
1-min would hide this. 5-min reveals it.
```

### 2. **Aggregation Timing is Critical**
```
12:15 — 1-min bar: Market at 25300 (looks strong)
12:20 — 1-min bar: Market at 25290 (slight dip)
12:25 — 1-min bar: Market at 25280 (more dip)
12:30 — 5-min agg:  SHOWS CONSOLIDATION (average of 5 bars)
        Indicators recalculated show: ADX declining, RSI cooling
        PA gets EARLY WARNING before full reversal at 12:35
```

### 3. **Cascade Confirmation**
```
Reversal starts at 5-min (12:35)
Confirmed at 15-min (12:35)
Confirmed at 30-min (12:45)
Confirmed at 60-min (15:30)

If PA sees 🔴 RED at 5min + 15min, it KNOWS the 30min and 60min
will follow. Can exit before they confirm. That's the power.
```

### 4. **Real-Time Decision Making**
```
During market hours, PA queries:
  SELECT * FROM market_data 
  WHERE timeframe_min IN (5, 15, 30, 60)
  ORDER BY timestamp DESC LIMIT 4
  
Gets instant answer: All green? All red? Mixed?

Makes decision RIGHT THEN at that 5-min mark, not at EOD.
```

---

## DATABASE VIEW AT 12:45

```
market_data table (selected rows):

timestamp    | tf  | close  | adx | rsi | status | recommendation
─────────────┼─────┼────────┼─────┼─────┼────────┼──────────────────
09:15:00     | 1   | 25005  | 12  | 48  | YELLOW | HOLD
09:16:00     | 1   | 25015  | 14  | 52  | YELLOW | HOLD
...
09:20:00     | 1   | 25035  | 19  | 64  | GREEN  | BUY
09:20:00     | 5   | 25035  | 32  | 72  | GREEN  | BUY         ← Aggregated!
09:21:00     | 1   | 25040  | 20  | 67  | GREEN  | BUY
...
09:30:00     | 1   | 25115  | 28  | 68  | GREEN  | BUY
09:30:00     | 15  | 25115  | 35  | 75  | GREEN  | STRONG_BUY  ← Aggregated!
...
12:15:00     | 1   | 25300  | 32  | 72  | GREEN  | BUY
12:15:00     | 5   | 25300  | 35  | 72  | GREEN  | BUY
12:20:00     | 5   | 25290  | 35  | 71  | GREEN  | BUY
12:30:00     | 5   | 25280  | 28  | 58  | YELLOW | HOLD        ← Status flipped!
12:35:00     | 5   | 25200  | 30  | 48  | RED    | STRONG_SELL ← Reversal!
12:40:00     | 5   | 25180  | 31  | 45  | RED    | STRONG_SELL
12:45:00     | 30  | 25190  | 32  | 42  | RED    | STRONG_SELL ← Confirmed!
```

---

## SUMMARY: What PA Sees During Market Hours

**09:15-09:20:** "Weak signals, wait"
**09:20-12:15:** "All green, strong buy. Perfect entry window 10:30-11:30"
**12:15-12:30:** "Peak reached, RSI overbought, take profit"
**12:30-12:35:** "🟡 Status yellow, consolidation warning"
**12:35-12:45:** "🔴 Reversal confirmed, exit all longs"
**12:45-15:30:** "Downtrend continues, stay out"

All in real-time, reading aggregated multi-TF data!
