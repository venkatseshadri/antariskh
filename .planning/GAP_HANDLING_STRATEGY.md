# Gap Handling: Which Indicators Survive Overnight Gaps?

**Problem:** Yesterday's bars don't represent today's market if there's a gap.

**Example: Gap Up Scenario**
```
Yesterday's Close: 24980
Today's Open:     25200 (GAP UP +220 pts)

If we naively use yesterday's bars:
├─ ADX calculated on closes [24960, 24970, 24975, ..., 24980]
├─ Then add today's close [25200]
├─ ADX sees a HUGE jump → Might misinterpret as momentum
├─ But is this "real" momentum or just a gap?

If we use yesterday's bars for VWAP:
├─ Yesterday's VWAP: 24950 (based on yesterday's volume)
├─ Today's first bar: 25200
├─ Combined VWAP: nonsensical (cross-day blended)
└─ ❌ VWAP should reset at market open
```

---

## INDICATOR CLASSIFICATION

### **TIER 1: Can Use Yesterday's Data (Trend Indicators)**

These work ACROSS gaps because they measure direction/momentum, not absolute price:

| Indicator | Why Safe | How to Handle Gap |
|-----------|----------|-------------------|
| **ADX(14)** | Measures trend strength, not price level | Use yesterday's bars + today's. Gap is just context. ADX still shows if trend is strong. |
| **RSI(14)** | Relative Strength = ratio of ups/downs. Gaps are already "moves" | Safe to use. RSI will adjust based on gap direction. |
| **EMA** | Exponential smoothing. Gap gets smoothed over time. | Use yesterday's EMA as seed. Today's bars will adjust it. |
| **SuperTrend** | Based on ATR + price direction. Can adapt to gaps. | Use yesterday's ST as reference. Today's ATR will reflect gap volatility. |
| **MACD** | Momentum divergence. Works across gaps. | Use yesterday's MACD as seed. |

**Strategy:** Use yesterday's last 14 bars as-is. Gaps are absorbed naturally.

---

### **TIER 2: Need Gap Adjustment (Volatility Indicators)**

These measure volatility, but gaps inflate it artificially:

| Indicator | Problem | Solution |
|-----------|---------|----------|
| **ATR(14)** | Gap makes ATR huge (gap = extreme true range) | Option A: Use gap-adjusted ATR. Option B: Reset ATR at open. |
| **Bollinger Bands** | Uses ATR/StdDev. Gap invalidates yesterday's bands. | Reset at market open. Calculate on today's bars only. |
| **Std Deviation** | Meaningless across gap. | Reset at open. |

**Strategy:** 
- **ATR**: If gap > 2×yesterday's ATR → Reset. Otherwise use yesterday.
- **Bollinger Bands**: Always reset at open.

---

### **TIER 3: Must Reset at Market Open (Intraday Only)**

These are intraday metrics. Using yesterday breaks them:

| Indicator | Why Reset | Replacement |
|-----------|-----------|-------------|
| **VWAP** | Intraday volume. Gap breaks continuity. | Reset VWAP at 09:15, start fresh. |
| **Open Range High/Low** | Today's open is new anchor. | Calculate from today's 09:15 onwards. |
| **Session High/Low** | Intraday only. | Reset at market open. |
| **Session Volume** | Intraday only. | Reset at market open. |
| **Intraday Pivots** | Based on previous day's close, not cross-session. | Use yesterday's close as base, calculate today's pivots. |
| **Support/Resistance** | Gap invalidates yesterday's levels. | Recalculate from gap-adjusted perspective. |

**Strategy:** Clear reset at 09:15. New VWAP, new volume counter, new highs/lows.

---

## DETECTION: Is There a Gap?

```python
def detect_gap(yesterday_close, today_open, gap_threshold_pct=0.5):
    """Detect if there's a significant gap."""
    gap = today_open - yesterday_close
    gap_pct = abs(gap) / yesterday_close * 100
    
    if gap_pct > gap_threshold_pct:  # Gap > 0.5%
        return {
            "has_gap": True,
            "direction": "UP" if gap > 0 else "DOWN",
            "size_pts": gap,
            "size_pct": gap_pct,
        }
    return {"has_gap": False}


# At market open (09:15):
gap_info = detect_gap(yesterday_close=24980, today_open=25200)
# Returns: {has_gap: True, direction: "UP", size_pts: 220, size_pct: 0.88}
```

---

## INDICATOR HANDLING STRATEGY

### **Scenario 1: No Gap (Normal Day)**

```
Yesterday Close: 24980
Today Open:      25005 (Gap: +25, +0.1%)

Status: ✓ NO SIGNIFICANT GAP

Action:
├─ Load yesterday's last 14 bars ✓
├─ Use for ADX(14), RSI(14), EMA warmup ✓
├─ Use for ATR calculation ✓
├─ Reset: VWAP, volume, high/low only
└─ All indicators valid from 09:15!
```

### **Scenario 2: Gap Up (Moderate)**

```
Yesterday Close: 24980
Today Open:      25100 (Gap: +120, +0.48%)

Status: ⚠️ MODERATE GAP (< 1%)

Action:
├─ Load yesterday's last 14 bars, but...
├─ Mark as "gap-adjusted":
│  ├─ ADX(14) ✓ Use (trend unaffected)
│  ├─ RSI(14) ✓ Use (gap is already a move)
│  ├─ EMA ✓ Use (will adjust)
│  ├─ ATR ⚠️ Use but be cautious
│  │  (Today's ATR might be inflated, but acceptable)
│  └─ SuperTrend ✓ Use (will adapt)
│
├─ Reset:
│  ├─ VWAP (restart at 09:15)
│  ├─ Volume counters
│  └─ Intraday highs/lows
│
└─ Note in PA output: "Day opens +0.48% above yesterday close"
```

### **Scenario 3: Large Gap (>1%)**

```
Yesterday Close: 24980
Today Open:      25300 (Gap: +320, +1.28%)

Status: 🔴 LARGE GAP (> 1%)

Action:
├─ Load yesterday's last 14 bars, BUT:
│  ├─ ADX(14) ⚠️ Use with caution
│  │  (Gap invalidates some trend interpretation)
│  ├─ RSI(14) ✓ Use (but first move is gap-biased)
│  ├─ EMA ✓ Use (exponential decay helps)
│  ├─ ATR ❌ RESET (gap makes it unreliable)
│  │  (Yesterday's ATR was ~50, today's gap is +320)
│  │  (This skews volatility assessment)
│  └─ SuperTrend ❌ RESET (ATR-based, invalid on large gaps)
│
├─ Reset to fresh calculation:
│  ├─ ATR: Start fresh from today's bars
│  ├─ Bollinger Bands: Start fresh
│  ├─ VWAP: Start fresh
│  ├─ Support/Resistance: Recalculate (old levels invalid)
│  └─ Intraday metrics: All new
│
└─ PA Alert: "LARGE GAP UP +1.28%. Indicators reset. Old support/
             resistance invalid. New levels: Support 25250, 
             Resistance 25350."
```

### **Scenario 4: Gap Down**

```
Yesterday Close: 24980
Today Open:      24600 (Gap: -380, -1.52%)

Status: 🔴 LARGE GAP DOWN

Action:
├─ ADX(14) ⚠️ Use with caution (might show strong downtrend)
├─ RSI(14) ✓ Use (gap down is a real move)
├─ ATR ❌ RESET (gap invalidates it)
├─ Bollinger Bands ❌ RESET
├─ VWAP ❌ RESET
└─ Support/Resistance: Recalculate

PA Alert: "LARGE GAP DOWN -1.52%. Yesterday's resistance 
          (24950) now within today's range. New structure."
```

---

## IMPLEMENTATION: Modified Warmup Logic

```python
class IndicatorWarmup:
    """Intelligently handle warmup with gap detection."""
    
    def __init__(self):
        self.yesterday_close = None
        self.today_open = None
        self.gap_info = None
        self.warmup_buffer = []
    
    def startup_load_warmup(self, today_open_price):
        """Run at 09:15 when market opens."""
        
        # 1. Load yesterday's bars
        yesterday = get_previous_trading_day()
        self.warmup_buffer = duckdb.query(f"""
            SELECT * FROM market_data
            WHERE date = '{yesterday}' AND timeframe_min = 1
            ORDER BY timestamp ASC
        """).fetch_all()[-14:]  # Last 14 bars
        
        self.yesterday_close = self.warmup_buffer[-1]['close']
        self.today_open = today_open_price
        
        # 2. Detect gap
        self.gap_info = self.detect_gap()
        
        # 3. Log gap
        if self.gap_info['has_gap']:
            print(f"GAP {self.gap_info['direction']} {self.gap_info['size_pct']:.2f}%")
        
        # 4. Mark which indicators are valid
        self.indicator_validity = self.determine_validity()
    
    def detect_gap(self):
        """Detect gap between yesterday close and today open."""
        gap = self.today_open - self.yesterday_close
        gap_pct = abs(gap) / self.yesterday_close * 100
        
        return {
            "has_gap": gap_pct > 0.5,
            "direction": "UP" if gap > 0 else "DOWN",
            "size_pts": gap,
            "size_pct": gap_pct,
        }
    
    def determine_validity(self):
        """Which indicators use warmup, which reset."""
        validity = {
            "adx": "WARMUP",        # Always use
            "rsi": "WARMUP",        # Always use
            "ema": "WARMUP",        # Always use
            "atr": "RESET" if self.gap_info['size_pct'] > 1.0 else "WARMUP",
            "bollinger": "RESET",   # Intraday only
            "vwap": "RESET",        # Intraday only
            "support_resistance": "RESET" if self.gap_info['size_pct'] > 0.5 else "WARMUP",
            "high_low": "RESET",    # Intraday only
            "volume": "RESET",      # Intraday only
        }
        return validity
    
    def calculate_adx(self, current_close):
        """ADX with warmup (gap-adjusted)."""
        if self.indicator_validity["adx"] == "WARMUP":
            all_closes = [bar['close'] for bar in self.warmup_buffer] + [current_close]
            recent = all_closes[-14:]
            
            adx = calculate_adx_14(recent)
            
            # If large gap, adjust ADX interpretation
            if self.gap_info['size_pct'] > 1.0:
                # Mark as "gap-adjusted ADX" in output
                adx_note = "ADX calculated with gap-adjusted warmup"
            else:
                adx_note = "Normal"
            
            return adx, adx_note
    
    def calculate_atr(self, current_ohlc):
        """ATR handling: reset if large gap, else warmup."""
        if self.indicator_validity["atr"] == "RESET":
            # Start fresh, only use today's bars
            return calculate_atr_14_fresh(current_ohlc)
        else:
            # Use warmup
            return calculate_atr_with_warmup(self.warmup_buffer, current_ohlc)
    
    def calculate_vwap(self, current_bar):
        """VWAP always resets at market open."""
        # Always reset, never use warmup
        # This is the first bar of VWAP for the day
        return calculate_vwap_fresh(current_bar)
    
    def get_support_resistance(self):
        """Support/resistance handling."""
        if self.indicator_validity["support_resistance"] == "RESET":
            # Recalculate from today's price action
            return calculate_sr_fresh(gap_info=self.gap_info)
        else:
            # Use yesterday's levels (but mark as potentially invalid)
            yesterday_sr = get_yesterday_sr()
            return {
                **yesterday_sr,
                "note": "Levels from yesterday, may be invalidated by gap"
            }


# Usage in data_capture:
warmup = IndicatorWarmup()

def on_market_open(today_open_price):
    warmup.startup_load_warmup(today_open_price)
    
    if warmup.gap_info['has_gap']:
        print(f"⚠️  GAP {warmup.gap_info['direction']}")
        print(f"   Size: {warmup.gap_info['size_pct']:.2f}%")
        print(f"   Indicators: {warmup.indicator_validity}")


def on_1min_bar(timestamp, ohlc):
    """Called every minute."""
    
    # ADX uses warmup (always)
    adx, note = warmup.calculate_adx(ohlc['close'])
    
    # ATR depends on gap
    atr = warmup.calculate_atr(ohlc)
    
    # VWAP always resets
    vwap = warmup.calculate_vwap(ohlc)
    
    # Write to DB
    duckdb.insert("market_data", {
        timestamp, timeframe_min=1,
        adx, atr, vwap,
        gap_adjusted=warmup.gap_info['has_gap'],
        ...
    })
```

---

## **PA Crew: How to Handle Gap Info**

```python
# In snapshot_multitf():

def snapshot_multitf(timestamp, index_name="NIFTY"):
    """Get multi-TF status, accounting for gaps."""
    
    # Query the bars
    bars = duckdb.query(...)
    
    # Check if market opened with gap
    market_data_today = duckdb.query("""
        SELECT DISTINCT gap_adjusted, gap_size_pct
        FROM market_data
        WHERE date = TODAY()
        LIMIT 1
    """)
    
    gap_info = market_data_today[0]
    
    # Build response with gap context
    return {
        "timestamp": timestamp,
        "gap": {
            "has_gap": gap_info['gap_adjusted'],
            "size_pct": gap_info['gap_size_pct'],
            "affects_atr": gap_info['gap_size_pct'] > 1.0,
            "affects_support_resistance": gap_info['gap_size_pct'] > 0.5,
        },
        "multitf": [...],
        "note": "Indicators recalculated with gap context" if gap_info['has_gap'] else ""
    }


# PA makes decisions with gap awareness:

if snapshot['gap']['has_gap']:
    if snapshot['gap']['size_pct'] > 1.0:
        print("⚠️  Large gap detected. ATR/Volatility reset at open.")
        print("    Old support/resistance invalidated.")
        print("    Treat first hour as establishment phase.")
    else:
        print("ℹ️  Moderate gap. Indicators adjusted but valid.")
```

---

## **Practical Example: Your UP→PAUSE→REVERSAL Day with Gap**

### **Scenario A: Opens with Gap Up**

```
Yesterday Close: 24980
Today Open:      25100 (Gap +120, +0.48%)

09:15:00 — Market opens
├─ Gap detected: +0.48% (moderate)
├─ ADX(14) ✓ WARMUP: Uses 14-bar history, gap absorbed
├─ ATR(14) ✓ WARMUP: Gap < 1%, ATR still valid (yesterday's ATR ~50)
├─ VWAP ❌ RESET: Starts fresh at 25100
├─ Support: Yesterday's 24950 now +150pts above open (invalid)
│  New Support: 25080-25100 range
├─ Resistance: Yesterday's 25050 now broken (invalid)
│  New Resistance: 25120-25150 range
└─ PA sees: "Morning gap up. Old levels invalidated. 
           New structure: 25080-25150. ADX/ATR normal."

12:30 (CONSOLIDATION):
├─ ADX drops to 28 (valid, gap-aware)
├─ VWAP (started at 25100): Now at 25250 (intraday VWAP)
├─ Support: 25250 (today's VWAP) ← NEW level
├─ Resistance: 25300 (intraday high)
└─ PA Alert: "Consolidation. Support at VWAP (25250). 
             ADX declining (28). Reversal risk increasing."

12:35 (REVERSAL):
├─ Breaks below VWAP (25250)
├─ ADX = 30, RSI = 48, ST = BEARISH ✓ Reversal confirmed
└─ PA Exit: "Below VWAP. Reversal confirmed. EXIT."
```

### **Scenario B: Opens with Large Gap Down**

```
Yesterday Close: 24980
Today Open:      24600 (Gap -380, -1.52%)

09:15:00 — Market opens
├─ Large gap detected: -1.52% (large!)
├─ ADX(14) ⚠️ WARMUP but gap-adjusted
│  (Yesterday's uptrend irrelevant, today's gap shows strength down)
├─ ATR(14) ❌ RESET (gap > 1%, yesterday's ATR invalidated)
│  New ATR calculated from today only, will show high volatility
├─ VWAP ❌ RESET: Starts fresh at 24600
├─ Support: Yesterday's 24950 now WAY above open (completely invalid)
│  New Support: 24550-24600 (around open)
├─ Resistance: Yesterday's resistance gone, recalculate
│  New Resistance: 24650-24700
│
└─ PA Alert: "LARGE GAP DOWN -1.52%. System reset:
             - ATR recalculated (will show elevated volatility)
             - Old support/resistance invalidated
             - VWAP restarted at 24600
             - Today is a NEW market structure"

Risk Management:
├─ Don't trust yesterday's ADX for today (gap inverted bias)
├─ ATR is fresh/elevated due to gap
├─ Treat 09:15-10:00 as "establishment phase"
└─ Wait for market to stabilize before aggressive entry
```

---

## **Summary: Gap Handling Rules**

| Gap Size | ADX | RSI | ATR | VWAP | Support/Resistance |
|----------|-----|-----|-----|------|-------------------|
| None (< 0.3%) | ✓ Warmup | ✓ Warmup | ✓ Warmup | ❌ Reset | ✓ Valid |
| Small (0.3-0.5%) | ✓ Warmup | ✓ Warmup | ✓ Warmup | ❌ Reset | ✓ Valid |
| Moderate (0.5-1.0%) | ✓ Warmup | ✓ Warmup | ✓ Warmup | ❌ Reset | ⚠️ Adjust |
| Large (>1.0%) | ⚠️ Caution | ✓ Warmup | ❌ Reset | ❌ Reset | ❌ Reset |

**Simple Rule:**
- **Trend indicators (ADX, RSI, EMA):** Always use warmup
- **Volatility indicators (ATR, Bollinger):** Reset if gap > 1%
- **Intraday metrics (VWAP, volume, highs/lows):** Always reset at open
- **Support/Resistance:** Reset if gap > 0.5%

Should I integrate this into the implementation?
