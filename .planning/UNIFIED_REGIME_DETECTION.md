# Unified Regime Detection: Single Source of Truth

**Problem:** Currently:
- PA crew calculates indicators independently
- TA crew (technical_scout) calculates regime independently
- Both reading same DuckDB data, computing same things twice
- Risk: They disagree (different ADX calculation, different interpretation)

**Solution:** Single multi-TF aggregation table, all crews query it.

---

## HOW ADX IS CALCULATED (The Key Insight)

ADX is NOT a separate "special" indicator. It's derived from OHLC range:

```
ADX Calculation Steps:
├─ 1. Calculate True Range (TR):
│     TR = max(high - low, |high - prev_close|, |low - prev_close|)
│     This captures the RANGE including gaps
│
├─ 2. Calculate Directional Movements:
│     +DM = high - prev_high (if > 0, else 0)    [up movement]
│     -DM = prev_low - low   (if > 0, else 0)    [down movement]
│     These come from OHLC range
│
├─ 3. Calculate DI (Directional Indicators):
│     +DI = (+DM / TR) × 100  [bullish bias from range]
│     -DI = (-DM / TR) × 100  [bearish bias from range]
│
└─ 4. Calculate ADX:
      ADX = average of DI difference over 14 periods
      ADX HIGH (>25) = Range is biased in one direction = TRENDING
      ADX LOW  (<20) = Range swings both ways = SIDEWAYS

KEY INSIGHT: ADX = "What does the OHLC range tell us about direction?"
```

---

## WHAT DIFFERENT VIEWS OF SAME DATA TELL US

```
Example: Market 25000-25200 range during 09:15-10:15

Raw OHLC View:
├─ Open:  25000
├─ High:  25200
├─ Low:   24995
├─ Close: 25100
├─ Range: 200 pts

Interpretation 1 — Range Analysis:
├─ Range = 200 pts (measured from low to high)
├─ Typical daily range = 300-400 pts
├─ So 200 pts in first hour = "Small range" ← CONSOLIDATING
└─ Signal: Market is quiet, not trending yet

Interpretation 2 — ADX View:
├─ Calculate TR, +DM, -DM
├─ +DM = mostly positive (high kept going up)
├─ -DM = mostly negative (low didn't go lower)
├─ Result: ADX = 35 ← STRONG UPTREND
└─ Signal: Market is trending UP (despite "small range")

Interpretation 3 — Pattern View:
├─ Pivot point at 25050
├─ Stayed mostly above pivot
├─ Volume concentrated in upper half
└─ Signal: Bullish bias within consolidation

Interpretation 4 — VWAP View:
├─ VWAP = 25080
├─ Price oscillating around VWAP
├─ Up, down, up, down
└─ Signal: Fair value is 25080, buyers/sellers balanced

ALL ARE TRUE AT SAME TIME!
They're different perspectives on the same 200-pt range.

Which does TA crew care about?
├─ Trending? → ADX (35 = YES, trending up)
├─ Sideways? → ADX (35 = NO, not sideways) + Range (relative to history)
├─ Fair value? → VWAP (25080)
├─ Bias direction? → Pattern (above pivot = bullish)
```

---

## THE REAL QUESTION: Sideways = What?

```
A market is SIDEWAYS when:

Option A: "ADX < 20" (technical definition)
├─ DI+ ≈ DI-
├─ Directional movements are balanced
└─ This is what ADX measures

Option B: "Price oscillating within narrow range"
├─ High - Low is small relative to history
├─ Price bouncing off support/resistance
└─ Range contraction

Option C: "Price around same level for extended time"
├─ Open ≈ Close over N periods
├─ True range small but DI still biased
└─ Could be trending sideways (up direction, small range)

Which is correct?
Answer: ALL OF THEM ARE VALID SIGNALS, DIFFERENT ANGLES

Example:
  Market: 25000-25050 range, all day
  └─ ADX: 8 (no direction, DI+ ≈ DI-)          ← SIDEWAYS (ADX view)
  └─ Range: 50 pts (tiny)                       ← CONSOLIDATING (range view)
  └─ Pattern: Bouncing off pivot                ← BALANCED (pattern view)
  └─ Signal: SIDEWAYS ✓ (all agree)

Example 2:
  Market: 25000-25200, trending up
  └─ ADX: 35 (strong bias)                      ← TRENDING (ADX view)
  └─ Range: 200 pts (decent)                    ← Active (range view)
  └─ Pattern: Above pivot, higher lows          ← BULLISH (pattern view)
  └─ Signal: TRENDING UP ✓ (all agree)

Example 3 (Tricky):
  Market: 25000 close but 24900-25200 range (huge daily range)
  └─ ADX: 22 (borderline, slight bias)          ← Borderline sideways
  └─ Range: 300 pts (large range)               ← Active swings
  └─ Pattern: Open = close despite big range    ← Indecisive
  └─ Signal: SIDEWAYS within HIGH VOLATILITY (different profile!)
```

---

## CURRENT ARCHITECTURE (Duplicated Work)

```
DuckDB market_data table:
├─ spot, futures, open, high, low, close, volume
└─ Stored in one place

TA Crew queries market_data:
├─ "Give me last 14 closes"
├─ Calculates ADX from scratch
├─ Calculates SuperTrend from scratch
├─ Makes regime decision: "TRENDING"

PA Crew queries market_data:
├─ "Give me last 14 closes"
├─ Calculates ADX from scratch (AGAIN!)
├─ Calculates RSI from scratch (AGAIN!)
├─ Makes trade decision based on its own ADX

PM Crew has own logic for strategy selection

PROBLEM:
├─ Same calculation done 3 times
├─ Risk: Different implementations give different ADX
├─ TA says "TRENDING" but PA sees "weak momentum"
└─ Conflicting signals to PM
```

---

## PROPOSED: UNIFIED MULTI-TF AGGREGATION

```
DuckDB market_data table (NEW structure):
├─ Row 1: timestamp=09:15, tf=1min, close=25005, adx=12, rsi=48, st=NEUTRAL
├─ Row 2: timestamp=09:16, tf=1min, close=25015, adx=14, rsi=52, st=NEUTRAL
├─ ...
├─ Row 6: timestamp=09:20, tf=1min, close=25035, adx=19, rsi=64, st=BULLISH
├─ Row 7: timestamp=09:20, tf=5min,  close=25035, adx=32, rsi=72, st=BULLISH ← Aggregated once
├─ ...
├─ Row 31: timestamp=09:30, tf=15min, close=25115, adx=35, rsi=75, st=BULLISH ← Aggregated once
└─ (All pre-calculated, stored, ready to read)

TA Crew queries:
├─ SELECT * FROM market_data 
│  WHERE tf IN (5, 15, 30, 60, 1440)
│  ORDER BY timestamp DESC LIMIT 10
├─ Gets: [15min, 1hr, 4hr, daily] status already calculated ✓
├─ Decision: "Daily shows BULLISH (ADX=30), 1hr shows GREEN (ADX=32)"
└─ Regime: "TRENDING UP across all major TFs"

PA Crew queries:
├─ SELECT * FROM market_data
│  WHERE tf IN (5, 15)
│  ORDER BY timestamp DESC LIMIT 20
├─ Gets: [5min, 15min] status already calculated ✓
├─ Decision: "5min YELLOW (consolidation), 15min GREEN (trend)"
└─ Action: "HOLD, don't enter new"

PM Crew queries:
├─ SELECT * FROM market_data
│  WHERE tf IN (1, 5)
│  ORDER BY timestamp DESC LIMIT 5
├─ Gets: [1min, 5min] status ready ✓
└─ Chooses strategy: "IRON_FLY (trending conditions)"

BENEFIT:
├─ ADX calculated ONCE per timeframe
├─ All crews use SAME indicators
├─ Consistent decisions
├─ No recalculation overhead
└─ ✓ Single source of truth
```

---

## REGIME DETECTOR: SHOULD USE DAILY TF DATA

```
Current TA technical_scout (probably):
├─ Query 1-min bars
├─ Calculate ADX (14) on 1-min
├─ If ADX > 25: "TRENDING"
├─ If ADX < 20: "SIDEWAYS"

PROBLEM:
├─ 1-min ADX is noisy
├─ Detects intraday vibration, not actual regime
├─ Example: 1-min ADX = 18 (looks sideways)
│           But 15-min ADX = 32 (actually trending)
└─ Wrong regime detected!

PROPOSED: Use Daily + Hourly TF
├─ Query: SELECT * FROM market_data 
│         WHERE tf IN (60, 1440)
│         ORDER BY timestamp DESC LIMIT 2
├─ Gets: Yesterday's daily + today's hourly
├─ Daily OHLC tells us:
│  ├─ Yesterday was SIDEWAYS (ADX < 20)
│  ├─ Yesterday's high = 25100, low = 24900, close = 25000
│  └─ No new highs, no new lows = choppy day
├─ Today's hourly (so far):
│  ├─ Hourly ADX = 32 (strong)
│  ├─ Hourly high = 25200, low = 24995
│  └─ Making new highs = breakout potential
│
└─ Regime Decision:
   "Yesterday SIDEWAYS. Today BREAKOUT forming.
    Regime = TRANSITIONING FROM SIDEWAYS TO TRENDING"
```

---

## BETTER: Regime Based on Daily Pattern

```
Instead of just "ADX value", use DAILY OHLC pattern:

Daily OHLC Views (from aggregated daily bar):

Pattern 1: NARROW RANGE DAY (Sideways)
├─ Open = 25000, High = 25050, Low = 24950, Close = 25025
├─ Range = 100 pts (small relative to history)
├─ Close inside middle of range
├─ ADX = 15 (weak)
└─ Regime: SIDEWAYS

Pattern 2: TRENDING UP DAY
├─ Open = 25000, High = 25300, Low = 24995, Close = 25250
├─ Range = 305 pts
├─ Close near top (25250 vs high 25300)
├─ Open near bottom (25000 vs low 24995)
├─ ADX = 35 (strong)
└─ Regime: TRENDING UP

Pattern 3: REVERSAL DAY (Key for today's scenario!)
├─ Open = 25300 (high from yesterday)
├─ High = 25320 (barely above open)
├─ Low = 25000 (back to yesterday's open!)
├─ Close = 25010
├─ ADX = 28 (directional but confused)
└─ Regime: REVERSAL / Strong selling pressure

Pattern 4: INSIDE DAY (Consolidation before breakout)
├─ Open = 25100, High = 25180, Low = 25020, Close = 25150
├─ Range = 160 pts (less than yesterday)
├─ Close in middle (not pushed to either extreme)
├─ ADX = 22 (borderline)
├─ Volume = lower than yesterday
└─ Regime: CONSOLIDATION (breakout coming)

Pattern 5: DOJI (Indecision, reversal risk)
├─ Open = 25000, High = 25200, Low = 24800, Close = 25010
├─ Huge range but close near open
├─ Wick ratio = 4:1 (tails long, body tiny)
├─ ADX = 18 (despite huge range!)
└─ Regime: INDECISION + high volatility
```

---

## UNIFIED REGIME DETECTION LOGIC

```python
class RegimeDetector:
    """
    Determine market regime from multi-TF data.
    NOT recalculating ADX—reading pre-calculated aggregations.
    """
    
    def detect_regime(self):
        """
        Query market_data for daily + hourly aggregations.
        Use OHLC pattern + ADX to determine regime.
        """
        
        # Get yesterday's daily bar
        yesterday_daily = duckdb.query("""
            SELECT open, high, low, close, adx, volume
            FROM market_data
            WHERE timeframe_min = 1440
            AND date = YESTERDAY()
            LIMIT 1
        """).fetchone()
        
        # Get today's hourly bars (last hour)
        today_hourly = duckdb.query("""
            SELECT timestamp, open, high, low, close, adx, volume
            FROM market_data
            WHERE timeframe_min = 60
            AND date = TODAY()
            ORDER BY timestamp DESC
            LIMIT 1
        """).fetchone()
        
        # Analyze patterns
        yesterday_pattern = self.analyze_ohlc_pattern(yesterday_daily)
        today_pattern = self.analyze_ohlc_pattern(today_hourly)
        
        # Determine regime
        regime = self.determine_regime(
            yesterday_pattern, 
            today_pattern,
            yesterday_daily['adx'],
            today_hourly['adx']
        )
        
        return regime
    
    def analyze_ohlc_pattern(self, ohlc):
        """Analyze OHLC to detect pattern."""
        
        open_price = ohlc['open']
        high = ohlc['high']
        low = ohlc['low']
        close = ohlc['close']
        
        range_pts = high - low
        range_pct = (range_pts / open_price) * 100
        
        close_position = (close - low) / range_pts  # 0 = near low, 1 = near high
        
        # Categorize
        if range_pct < 0.5:
            pattern = "NARROW_RANGE"
        elif close_position < 0.3:
            pattern = "SELLING_PRESSURE"  # Close near low
        elif close_position > 0.7:
            pattern = "BUYING_PRESSURE"   # Close near high
        elif 0.3 <= close_position <= 0.7:
            pattern = "BALANCED"
        else:
            pattern = "UNKNOWN"
        
        return {
            "pattern": pattern,
            "range_pct": range_pct,
            "close_position": close_position,
            "hl_ratio": range_pts,
        }
    
    def determine_regime(self, yesterday_pattern, today_pattern, 
                        yesterday_adx, today_adx):
        """Combine patterns + ADX to determine regime."""
        
        # Regime rules
        if today_adx > 25:
            if today_pattern['pattern'] in ['BUYING_PRESSURE', 'NARROW_RANGE']:
                return "TRENDING_UP"
            elif today_pattern['pattern'] in ['SELLING_PRESSURE']:
                return "TRENDING_DOWN"
        else:  # ADX < 20
            if today_pattern['range_pct'] < 0.7:
                return "SIDEWAYS"
            else:
                return "CONSOLIDATION"
        
        # Transition detection
        if yesterday_adx < 20 and today_adx > 25:
            return "BREAKOUT_FORMING"
        
        if yesterday_pattern['pattern'] == 'BUYING_PRESSURE' and \
           today_pattern['pattern'] == 'SELLING_PRESSURE':
            return "REVERSAL_LIKELY"
        
        return "NEUTRAL"
    
    def explain(self, regime):
        """Provide reasoning for regime."""
        explanations = {
            "TRENDING_UP": "ADX >25, higher lows, close at high",
            "TRENDING_DOWN": "ADX >25, lower highs, close at low",
            "SIDEWAYS": "ADX <20, balanced OHLC, no new extremes",
            "CONSOLIDATION": "ADX 20-25, narrow range, indecision",
            "BREAKOUT_FORMING": "Yesterday sideways, today strong ADX",
            "REVERSAL_LIKELY": "Yesterday buying, today selling pressure",
        }
        return explanations.get(regime, "Unknown regime")


# Usage
detector = RegimeDetector()
regime = detector.detect_regime()

print(f"Regime: {regime}")
print(f"Reason: {detector.explain(regime)}")
```

---

## HOW IT APPLIES TO YOUR SCENARIO

```
Day: UP 3hrs → PAUSE 0.5hrs → REVERSAL by EOD

09:20 — First 5-min aggregation:
├─ Yesterday's daily: TRENDING (from previous session)
├─ Today's 5min: ADX=32, close near high
├─ TA regime: "Continuation of yesterday's trend"
├─ PA sees: "BUY signal, ADX confirmed"
└─ Decision: Entry OK

12:30 — Consolidation hour:
├─ Hourly aggregation: ADX dropping (35→28)
├─ Daily OHLC forming: Open at 25300, high at 25320, low at 25280
├─ Pattern: Narrow range (40 pts) despite big daily move
├─ TA regime: "CONSOLIDATION after strong move"
├─ PA sees: "Status YELLOW, consolidation warning"
└─ Decision: Don't enter new, watch for break

13:45 — Reversal hour:
├─ Hourly aggregation: ADX=30, but ST=BEARISH
├─ OHLC pattern: Huge range (25200-25150), closing low
├─ Pattern: Selling pressure (close near low of hour)
├─ TA regime: "REVERSAL. Yesterday's highs broken. New regime: DOWN"
├─ PA sees: "5min RED, 15min YELLOW, cascade starting"
└─ Decision: EXIT immediately, short setup forming

15:30 — End of day:
├─ Daily OHLC complete: Open 25300, high 25320, low 25000, close 25010
├─ Pattern: REVERSAL DAY (huge range, close near low relative to open)
├─ Daily ADX: 28 (directional but confused, daily view)
├─ TA regime: "REVERSAL DAY completed. Tomorrow: test support or bounce?"
└─ Lesson: "Reversal days don't repeat immediately. Monday: wait for confirmation"
```

---

## SUMMARY: Single Source of Truth

```
BEFORE (Independent calculations):
├─ TA crew: Calculates ADX on 1-min
├─ PA crew: Calculates ADX on 1-min (different code, same data)
├─ PM crew: Uses heuristics
└─ Risk: Inconsistent signals

AFTER (Unified multi-TF aggregation):
├─ Data Capture: 1-min OHLCV → writes 1-min bars
├─ MultiTF Aggregator: Aggregates to 5/15/30/60/240/1440-min
│  ├─ Calculates ADX ONCE per TF
│  ├─ Calculates RSI ONCE per TF
│  ├─ Stores with gap-aware flags
│  └─ All in market_data table
│
├─ TA Regime Detector: Queries 60-min + 1440-min
│  ├─ Reads pre-calculated ADX (no recalculation)
│  ├─ Analyzes OHLC pattern from aggregated bars
│  ├─ Makes regime call (TRENDING/SIDEWAYS/REVERSAL)
│  └─ Sends to PM: "Market is TRENDING UP"
│
├─ PA Analyzer: Queries 5-min + 15-min
│  ├─ Reads pre-calculated status (GREEN/YELLOW/RED)
│  ├─ Detects reversals, consolidations
│  └─ Sends to PM: "Take profit now, reversal forming"
│
└─ PM Decision: Receives consistent signals from both crews
   ├─ TA: "Market trending, ADX=35"
   ├─ PA: "Status green, confidence 75%"
   └─ PM: "Enter now"
```

---

## WHAT TO BUILD

```
Phase 1: Multi-TF Aggregator (done once daily)
├─ Reads: 1-min bars from data_capture
├─ Aggregates: to 5, 15, 30, 60, 240, 1440-min
├─ Recalculates: ADX, RSI, ST, EMA (on each TF's OHLC)
├─ Gap-detects: resets ATR, VWAP if needed
└─ Writes: All to market_data with timeframe_min column

Phase 2: Regime Detector (TA crew upgrade)
├─ Queries: market_data WHERE tf IN (60, 1440)
├─ Analyzes: OHLC pattern + ADX from aggregation
├─ Determines: Regime (TRENDING/SIDEWAYS/REVERSAL/etc)
└─ Reports: To PM + PA crews

Phase 3: PA Multi-TF Analysis (PA crew upgrade)
├─ Queries: market_data WHERE tf IN (5, 15, 30)
├─ Reads: Pre-calculated status (GREEN/YELLOW/RED)
├─ No recalculation: Just interprets aggregated data
└─ Detects: Reversals, consolidations, patterns

Phase 4: PM Strategy Selection (PM crew upgrade)
├─ Receives: Regime from TA + status from PA
├─ Chooses: Strategy (Iron Fly for TRENDING, Credit Spread for SIDEWAYS)
└─ Executes: With confidence from multiple crews
```

This is the **unified architecture** where all crews read the same source of truth.

Should I build Phase 1 (MultiTF Aggregator) that feeds all the others?
