# Phase Detection: OHLC Sequence Across Timeframes

**Core Insight:** ADX gives one snapshot. OHLC PATTERN across TFs gives the STORY.

The story reveals: Are we at trend START, CONTINUATION, EXHAUSTION, or REVERSAL?

---

## OHLC SHAPES: What Each Pattern Means

### Pattern 1: Wide Body (BULL_CLOSE)
```
High:  ▲
       │
       │   ▲─ Close (near high)
       │   │
Mid:   ├───┤
       │   │
       │   │─ Open (middle)
Low:   ▼
       └─ (Open and low separated)

Interpretation:
├─ Buyers controlled the period
├─ Opened somewhere, pushed to high
├─ Closed near the high
├─ Wick below = mild selling (rejected)
└─ Signal: BULLISH MOMENTUM
```

### Pattern 2: Wide Body (BEAR_CLOSE)
```
High:  ▲
       │   ▲─ Open (high in range)
       │   │
Mid:   ├───┤
       │   │
       │   │─ Close (near low)
Low:   ▼
       └─ Wick above = mild buying (rejected)

Interpretation:
├─ Sellers controlled the period
├─ Opened high, pushed to low
├─ Closed near the low
└─ Signal: BEARISH MOMENTUM
```

### Pattern 3: Narrow Body (CONSOLIDATION)
```
High:  ▲
       │  ▲─ Close & Open (close together)
       │  │
Mid:   ├──┤ (Small range, no clear direction)
       │  │
       │  │
Low:   ▼

Interpretation:
├─ No clear direction
├─ Buyers and sellers balanced
├─ Low volatility, no conviction
└─ Signal: INDECISION, GATHERING ENERGY
```

### Pattern 4: Doji (INDECISION)
```
High:  ▲
       │   ▲─ Wick (buyers tried, rejected)
       │   │
Mid:   ├───┤ Close & Open (same!)
       │   │
       │   │─ Wick (sellers tried, rejected)
Low:   ▼

Interpretation:
├─ Open = Close (exactly balanced!)
├─ Wide range but neither side won
├─ Classic reversal/exhaustion signal
└─ Signal: INDECISION AT EXTREME (potential reversal)
```

### Pattern 5: Hammer/Inverted Hammer
```
Hammer (Found Support):
       High: close/open
       │   
       │    (small body)
       │    
       └─ Wick down (rejection of low)

Interpretation: Support found, potential bounce

Inverted Hammer (Resistance met):
       ▲ Wick up (rejection of high)
       │    
       │    (small body)
       │    close/open

Interpretation: Resistance met, potential pullback
```

---

## MULTI-TF SEQUENCES: The Stories They Tell

### STORY 1: Trend START (Setup → Initiation)

```
Timeline:
  Day-3  Day-2   Day-1   Day(today) Hour(next) 
  ─────  ────    ────────────────────────────

Daily:
  Consolidation (DOJI)
  High=25200, Low=24800, Close=25000
  Range = 400, but close = open (indecision)
  ADX = 15 (weak)
  Signal: SLEEPING, SETUP PHASE

4-Hourly (end of yesterday):
  Still consolidating
  ADX = 18 (weak)
  Close in middle of range
  Signal: STILL GATHERING

1-Hourly (this hour):
  ▲ BREAKOUT!
  ▼
  Close = 25100 (above resistance 25050)
  ADX = 25+ (trend started!)
  High > yesterday's high
  Signal: INITIATION — Trend has started!
  
  ← This is the KEY MOMENT!
     PA should say: "ENTRY WINDOW OPEN"

30-min (current):
  Higher high (25110), higher low (25080)
  ADX = 28
  Close at high
  Signal: EARLY STAGE, still accelerating

5-min (now):
  Still up, consolidating at high
  ADX = 30
  Close near high
  Signal: READY FOR ACCELERATION

Analysis:
  Daily:   Setup (sleeping, doji)
  4-hr:    Setup (still consolidating)
  1-hr:    ← INITIATION (broke out first!)
  30-min:  Early (following 1-hr break)
  5-min:   Confirmation (consolidating high)
  
  Conclusion: EARLY STAGE TREND (1-2 hours old)
             "Don't miss the move, enter NOW"
             Risk: But only if 1hr maintains above break (25050)
```

### STORY 2: Trend CONTINUATION (All TFs Aligned)

```
Daily:
  BULL_CLOSE (open 24900, close 25200)
  Close near top
  Range = 300, used 80% of it (0→80%)
  ADX = 32 (strong)
  Signal: DAY IS BULLISH

4-hr (last one):
  BULL_CLOSE (higher close)
  Close at or near high
  ADX = 32 (strong)
  Signal: STRONG BULLISH

1-hr (current):
  BULL_CLOSE (continuing up)
  Close 25150, high 25200
  ADX = 35 (strongest)
  Signal: STRONG BULLISH

30-min:
  BULL_CLOSE
  Close near high
  ADX = 33
  Signal: BULLISH

5-min:
  BULL_CLOSE
  Close near high
  ADX = 32
  Signal: BULLISH

Analysis:
  ALL timeframes: BULL_CLOSE + ADX>25 + higher closes
  
  Conclusion: STRONG CONTINUATION TREND
             "All TFs aligned, safe to hold"
             Highest confidence entry
             Risk: Low (trend is confirmed across all levels)
```

### STORY 3: Trend EXHAUSTION (Top-Down Rollover)

```
Timeline: Morning was trending, now afternoon

Daily (full day so far):
  Open: 25000
  High: 25300 (peak earlier)
  Low: 24995 (tested but held)
  Close: 25150 (pulled back from high)
  Range: 305 pts (used 60% - declining)
  ADX: 32 → 28 (declining!)
  Signal: STILL STRONG but WEAKENING

4-hr (hour 5 of session):
  BULL_CLOSE still but…
  Close 25150, high 25200
  ADX: 32 (still strong)
  Signal: STRONG but momentum slowing

1-hr (this hour):
  Close: 25120 (LOWER than last hour's 25150!)
  High: 25200 (but didn't break it)
  ADX: 28 (← ROLLING OVER, was 35 earlier)
  Signal: ⚠️ MOMENTUM DECLINING
  
  ← This is the EXHAUSTION SIGNAL!
     PA should say: "WARNING: Trend losing steam"

30-min (current):
  Close: 25100 (LOWER again!)
  High: 25120 (not going higher)
  Range: shrinking
  ADX: 22 (← Continuing to roll)
  Signal: ⚠️ EXHAUSTION CONFIRMED
  
  ← PA says: "DO NOT ENTER NEW LONGS"

5-min (now):
  Close: 25090 (still lower)
  Cannot make new highs
  ADX: 18 (← Broke below 20)
  Signal: 🔴 ROLL-OVER COMPLETE
  
  ← PA says: "EXIT or PREPARE TO EXIT"

Analysis:
  Daily:   Still up (ADX=28, but declining)
  4-hr:    Up but weakening (ADX=32)
  1-hr:    ← FIRST ROLLOVER (ADX=28, lower close)
  30-min:  Confirmed rollover (ADX=22, lower close)
  5-min:   Cascade complete (ADX=18, selling)
  
  Pattern: "TOP-DOWN ROLLOVER" (higher TFs roll first, lower follow)
           Trend exhaustion in progress
           
  Conclusion: TREND EXHAUSTION
             "Trend losing momentum from top down"
             "Exit, don't buy dips"
             Risk: This is the reversal setup!
```

### STORY 4: REVERSAL (Cascade Down)

```
Timeline: Trend was up, now cascading down

Daily:
  Open: 25300 (peak from yesterday)
  High: 25320 (barely went higher)
  Low: 25000 (back to yesterday's open!)
  Close: 25010 (near low)
  Pattern: BEAR_CLOSE (opened high, closed low, huge wick below)
  ADX: 28 (directional but confused)
  Signal: ⚠️ REVERSAL DAY (worst case for bulls)

4-hr (hour 6 of session):
  BEAR_CLOSE
  Close: 25050
  High: 25100 (couldn't extend)
  ADX: 30 (BUT trend direction flipped!)
  ST: BEARISH (← FLIPPED)
  Signal: DIRECTION REVERSED

1-hr (this hour):
  BEAR_CLOSE
  Close: 25000 (near low)
  High: 25080 (rejected)
  ADX: 30 (strong DOWN!)
  Signal: REVERSAL CONFIRMED

30-min:
  BEAR_CLOSE
  Close: 24990
  ADX: 32
  ST: BEARISH
  Signal: REVERSAL ACCELERATING

5-min (now):
  BEAR_CLOSE
  Close: 24950
  High: 24980 (small range)
  ADX: 30 (consistent)
  Signal: 🔴 REVERSAL IN FULL EFFECT

Analysis:
  Daily:   Reversal day (BEAR_CLOSE, huge wick)
  4-hr:    ← FIRST TO FLIP (ST went BEARISH)
  1-hr:    Confirmed flip (close at low)
  30-min:  Cascade continuing (ADX still strong but down)
  5-min:   Cascade complete (fully red)
  
  Pattern: "BOTTOM-UP CASCADE" (lower TFs flip, upper follow)
           NOT a temporary pullback
           
  Conclusion: FULL REVERSAL
             "Trend has reversed, sell any longs"
             "Shorts now favored"
             Risk: Medium (reversal could bounce, not guaranteed to extend)
```

---

## THE PHASES: What Each Story Reveals

| Phase | Daily Pattern | 4hr Status | 1hr Status | 30min Status | 5min Status | Signal | Risk |
|-------|---|---|---|---|---|---|---|
| **Setup/Accumulation** | Doji, narrow | ADX<20 | ADX<20 | Consolidating | Consolidating | Energy gathering, breakout coming | Low (tight stops possible) |
| **Initiation** | Still narrow | ADX~18 | ADX>25 ← FIRST | Emerging up | Consolidating high | ENTRY WINDOW OPEN | High (early, could fail) |
| **Early Trend** | Starting to break | ADX>20 | ADX>30 | Higher high/low | Aligned up | Safe entry, trend confirmed | Medium (still young) |
| **Continuation** | Bull/bear close | ADX>25 | ADX>25 | Bull/bear close | Bull/bear close | All aligned, hold | Low (trend mature) |
| **Exhaustion** | Still up, ADX↓ | ADX declining | ADX↓ ← FIRST | ADX<25 | ADX<20 | Take profit, don't buy dips | Medium (reversal forming) |
| **Reversal** | Bear close, wick | ST flips | ST flips | BEAR_CLOSE | BEAR_CLOSE | EXIT longs, setup short | High (violent unwind) |

---

## HOW THIS CHANGES PA/TA DECISIONS

### OLD WAY (ADX Only):
```
PA queries: SELECT adx FROM market_data WHERE tf=5
Result: adx = 28
Decision: "ADX=28, strong trend, BUY"

Problem: Doesn't know if trend is:
├─ Starting (safe entry)
├─ Continuing (good entry)
├─ Exhausting (bad entry!)
├─ Reversing (terrible entry!)
└─ All look the same to ADX!
```

### NEW WAY (OHLC Sequences):
```
PA queries:
├─ Daily OHLC: doji (open=close, wide wick)
├─ 4hr OHLC: consolidating (narrow body, middle close)
├─ 1hr OHLC: bull_close (close at high)
├─ 30min OHLC: higher_high, close near high
└─ 5min OHLC: consolidating at resistance

Analysis:
├─ Daily + 4hr: Setup phase (doji + consolidation)
├─ 1hr: ← Initiation (first to break out)
├─ 30min: Following the break
├─ 5min: Building support at new level

Conclusion: EARLY STAGE TREND (hour old)
            "Enter NOW while setup to continuation"
            Confidence: 85% (1hr confirmed, lower TFs following)

This tells PA: Entry risk is LOW (trend just started)
              Exit risk is MEDIUM (only 1hr of data)
              Hold target: Until 1hr closes below support
```

---

## THE DATA STRUCTURE YOU NEED

Not just ADX value. Store OHLC + Pattern Classification:

```sql
CREATE TABLE market_multitf_ohlc (
  timestamp TEXT,
  timeframe_min INTEGER,
  
  -- OHLCV
  open FLOAT,
  high FLOAT,
  low FLOAT,
  close FLOAT,
  volume FLOAT,
  
  -- Indicators (for reference)
  adx FLOAT,
  atr FLOAT,
  
  -- NEW: Pattern Classifications
  pattern TEXT,  -- BULL_CLOSE, BEAR_CLOSE, DOJI, CONSOLIDATION, HAMMER
  close_position FLOAT,  -- 0.0 = near low, 1.0 = near high
  range_pct FLOAT,  -- (high-low)/open * 100
  body_size_pct FLOAT,  -- |(close-open)|/range * 100
  
  -- Status for that TF
  status TEXT,  -- GREEN, YELLOW, RED
  
  PRIMARY KEY (timestamp, timeframe_min)
);
```

Example data:
```
09:15, 1day, open=25000, high=25200, low=24800, close=25000
       pattern='DOJI'
       close_position=0.5 (at midpoint)
       range_pct=1.6
       adx=15
       status=YELLOW (indecision)

09:20, 5min, open=25000, high=25038, low=24995, close=25035
       pattern='BULL_CLOSE'
       close_position=0.92 (near high!)
       range_pct=0.17
       body_size_pct=90
       adx=32
       status=GREEN (bullish)
```

---

## PHASE DETECTION ALGORITHM

```python
class PhaseDetector:
    """Detect trend PHASE from multi-TF OHLC sequences."""
    
    def detect_phase(self):
        """Analyze OHLC patterns across TFs to find phase."""
        
        # Get aggregated bars
        daily = self.get_bar(timeframe=1440)      # 1-day
        four_hr = self.get_bar(timeframe=240)     # 4-hour
        one_hr = self.get_bar(timeframe=60)       # 1-hour
        thirty_min = self.get_bar(timeframe=30)   # 30-min
        five_min = self.get_bar(timeframe=5)      # 5-min
        
        # Classify each TF's pattern
        daily_pattern = daily['pattern']           # DOJI, BULL_CLOSE, etc
        hr1_pattern = one_hr['pattern']
        min30_pattern = thirty_min['pattern']
        min5_pattern = five_min['pattern']
        
        # Detect phase sequence
        if self.is_setup(daily, four_hr, one_hr):
            return "SETUP_PHASE"
        elif self.is_initiation(daily, four_hr, one_hr, thirty_min):
            return "INITIATION_PHASE"  # ← Entry opportunity
        elif self.is_early_trend(one_hr, thirty_min, five_min):
            return "EARLY_TREND_PHASE"
        elif self.is_continuation(daily, four_hr, one_hr, thirty_min):
            return "CONTINUATION_PHASE"  # ← Safe to hold
        elif self.is_exhaustion(daily, four_hr, one_hr, thirty_min, five_min):
            return "EXHAUSTION_PHASE"  # ← Exit warning
        elif self.is_reversal(daily, four_hr, one_hr, thirty_min, five_min):
            return "REVERSAL_PHASE"  # ← Exit immediately
        else:
            return "UNKNOWN"
    
    def is_setup(self, daily, four_hr, one_hr):
        """Setup: Daily doji, all TFs consolidating."""
        return (
            daily['pattern'] == 'DOJI' and
            daily['adx'] < 20 and
            four_hr['pattern'] in ['CONSOLIDATION', 'DOJI'] and
            four_hr['adx'] < 20 and
            one_hr['adx'] < 20
        )
    
    def is_initiation(self, daily, four_hr, one_hr, thirty_min):
        """Initiation: 1hr breaks out first, rest follow."""
        return (
            daily['pattern'] in ['DOJI', 'CONSOLIDATION'] and
            four_hr['adx'] < 22 and
            one_hr['adx'] > 25 and  # ← 1hr just broke out!
            one_hr['close_position'] > 0.7 and  # ← Close at high
            thirty_min['adx'] > 20  # ← Following
        )
    
    def is_continuation(self, daily, four_hr, one_hr, thirty_min):
        """Continuation: All TFs aligned, bull/bear closes."""
        directions = [
            daily['pattern'],
            four_hr['pattern'],
            one_hr['pattern'],
            thirty_min['pattern']
        ]
        # All should be BULL_CLOSE or all BEAR_CLOSE
        return (
            all(p == 'BULL_CLOSE' for p in directions) or
            all(p == 'BEAR_CLOSE' for p in directions)
        ) and all(bar['adx'] > 25 for bar in [daily, four_hr, one_hr, thirty_min])
    
    def is_exhaustion(self, daily, four_hr, one_hr, thirty_min, five_min):
        """Exhaustion: Higher TFs still up but rolling over."""
        return (
            daily['adx'] > 20 and  # Still trending
            four_hr['adx'] > 20 and
            one_hr['adx'] > 22 and  # Still strong
            thirty_min['adx'] < 22 and  # ← Rolling over
            five_min['adx'] < 20 and  # ← Already rolled
            one_hr['close_position'] < 0.5  # ← Lower close
        )
    
    def is_reversal(self, daily, four_hr, one_hr, thirty_min, five_min):
        """Reversal: Pattern flip cascade."""
        return (
            daily['pattern'] == 'BEAR_CLOSE' and
            four_hr['st'] == 'BEARISH' and  # ← Flipped
            one_hr['st'] == 'BEARISH' and  # ← Cascading
            thirty_min['st'] == 'BEARISH' and
            five_min['st'] == 'BEARISH'
        )
```

---

## OUTPUT TO PA: Phase-Based Decisions

```python
def get_pa_recommendation(phase, one_hr_adx, five_min_status):
    """Make decision based on detected phase."""
    
    recommendations = {
        "SETUP_PHASE": {
            "action": "WAIT",
            "reason": "Setup forming, breakout coming",
            "risk": "Low (tight stops possible)",
            "confidence": 40  # Not actionable yet
        },
        "INITIATION_PHASE": {
            "action": "ENTRY_WINDOW_OPEN",
            "reason": "1hr just broke out, early trend confirmed",
            "risk": "High (still young, could fail)",
            "confidence": 65  # Good entry, but early
        },
        "EARLY_TREND_PHASE": {
            "action": "SAFE_ENTRY",
            "reason": "Trend 1-2 hours old, lower TFs following",
            "risk": "Medium (trend confirmed but young)",
            "confidence": 75  # Good entry
        },
        "CONTINUATION_PHASE": {
            "action": "HOLD / SAFE_ENTRY",
            "reason": "All TFs aligned, mature trend",
            "risk": "Low (trend confirmed across all TFs)",
            "confidence": 85  # Best entry
        },
        "EXHAUSTION_PHASE": {
            "action": "TAKE_PROFIT / DO_NOT_ENTER",
            "reason": "Trend rolling over from top TFs down",
            "risk": "High (reversal likely within hour)",
            "confidence": 75  # Exit high confidence
        },
        "REVERSAL_PHASE": {
            "action": "EXIT_IMMEDIATELY",
            "reason": "Reversal confirmed across all TFs",
            "risk": "Critical (swift move likely)",
            "confidence": 90  # Exit with conviction
        }
    }
    
    return recommendations[phase]
```

---

## SUMMARY: Why This Matters

| Metric | ADX Only | OHLC Sequence |
|--------|----------|---------------|
| **Detects trending?** | ✓ Yes (ADX>25) | ✓ Yes (all BULL_CLOSE) |
| **Detects sideways?** | ✓ Yes (ADX<20) | ✓ Yes (doji, consolidation) |
| **Detects TREND START?** | ✗ No (just says trending) | ✓ YES (1hr broke first!) |
| **Detects EARLY vs LATE entry?** | ✗ No | ✓ YES (phase reveals timing) |
| **Detects EXHAUSTION?** | ✗ No (ADX still high!) | ✓ YES (top-down rollover) |
| **Detects REVERSAL cascade?** | ✗ No | ✓ YES (pattern flip sequence) |
| **Tells you CONFIDENCE level?** | ✗ No | ✓ YES (phase-based) |

**ADX = Current state**
**OHLC Sequence = Direction + Stage + Timing**

This is the missing piece that makes PA truly intelligent about market phases.
