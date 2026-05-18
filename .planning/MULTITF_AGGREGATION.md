# Multi-Timeframe Aggregation Strategy for PA Crew

**Problem:** PA analyzing 60+ indicators on 1-min data = noise. Can't see forest for trees.

**Solution:** Add multi-timeframe summarization to data_capture. Each timeframe gets a simple status:
- 🟢 **GREEN** = Trending (all indicators aligned in direction)
- 🟡 **YELLOW** = Consolidating (mixed signals, not confirmed)
- 🔴 **RED** = Reversing (indicators flipping, momentum broken)

---

## PROPOSED DATA STRUCTURE

### Current Data Capture (1-min bars)
```
market_data table:
├── timestamp (1-min bars: 09:15, 09:16, 09:17, ...)
├── spot, futures, atm_strike
├── trend indicators (ST, ADX)
├── momentum (RSI, EMA)
├── volatility (ATR, VIX, IV)
├── structure (support, resistance, pivots)
├── energy (BB, VWAP)
└── greeks (delta, gamma, vega)
```

### NEW: Multi-TF Aggregation Table
```
market_data_multitf table:
├── timestamp (aligned to end of timeframe)
├── timeframe (1min, 5min, 15min, 30min, 1hr, 4hr, 1day)
├── status (GREEN, YELLOW, RED)
├── indicators_aligned (list of confirmed indicators)
├── indicators_conflicting (list of misaligned indicators)
├── trend_strength (0-100, how strong is the trend)
├── momentum_state (BULLISH, NEUTRAL, BEARISH)
├── ohlcv (open, high, low, close, volume for the period)
├── adx, rsi, ema_signal, st_signal
└── recommendation (STRONG_BUY, BUY, HOLD, SELL, STRONG_SELL)
```

---

## TIMELINE VIEW FOR YOUR SCENARIO

### Scenario: UP 3hrs → PAUSE 0.5hrs → REVERSAL by EOD

**09:15-12:15 (TREND UP)**
```
Timestamp: 12:15 (end of period)
┌─────────────────────────────────────────┐
│ TF    │ Status │ Momentum │ Trend_Str │ │
├───────┼────────┼──────────┼───────────┤ │
│ 1min  │   🟢   │ BULLISH  │    85%    │ │
│ 5min  │   🟢   │ BULLISH  │    88%    │ │
│ 15min │   🟢   │ BULLISH  │    90%    │ │
│ 30min │   🟢   │ BULLISH  │    92%    │ │
│ 1hr   │   🟢   │ BULLISH  │    95%    │ │
│ 4hr   │   🟢   │ BULLISH  │    85%    │ │
│ 1day  │   🟢   │ BULLISH  │    65%    │ │
└─────────────────────────────────────────┘

CONSENSUS: ALL GREEN ✓
ACTION: STRONG_BUY (high confidence entry)
```

**12:15-12:45 (PAUSE/CONSOLIDATION)**
```
Timestamp: 12:45
┌─────────────────────────────────────────┐
│ TF    │ Status │ Momentum │ Trend_Str │ │
├───────┼────────┼──────────┼───────────┤ │
│ 1min  │   🟡   │ NEUTRAL  │    55%    │ │
│ 5min  │   🟡   │ NEUTRAL  │    60%    │ │
│ 15min │   🟢   │ BULLISH  │    80%    │ │
│ 30min │   🟢   │ BULLISH  │    88%    │ │
│ 1hr   │   🟢   │ BULLISH  │    92%    │ │
│ 4hr   │   🟢   │ BULLISH  │    85%    │ │
│ 1day  │   🟢   │ BULLISH  │    65%    │ │
└─────────────────────────────────────────┘

CONSENSUS: Lower TFs cooling, higher TFs still strong
ACTION: HOLD (pullback in uptrend, not reversal yet)
WAIT: Don't enter new longs. Possible reversal forming.
```

**13:45 (REVERSAL BEGINS)**
```
Timestamp: 13:45
┌─────────────────────────────────────────┐
│ TF    │ Status │ Momentum │ Trend_Str │ │
├───────┼────────┼──────────┼───────────┤ │
│ 1min  │   🔴   │ BEARISH  │    72%    │ │
│ 5min  │   🔴   │ BEARISH  │    75%    │ │
│ 15min │   🟡   │ NEUTRAL  │    50%    │ │
│ 30min │   🟡   │ NEUTRAL  │    55%    │ │
│ 1hr   │   🟢   │ BULLISH  │    75%    │ │
│ 4hr   │   🟢   │ BULLISH  │    82%    │ │
│ 1day  │   🟢   │ BULLISH  │    65%    │ │
└─────────────────────────────────────────┘

CONSENSUS: Lower TFs flipping red, higher TFs lagging
ACTION: EXIT (reversal confirmed on lower TFs, likely cascade)
RISK: 1hr will follow within 30min, 4hr within 2hrs
```

**15:30 (FULL REVERSAL COMPLETE)**
```
Timestamp: 15:30
┌─────────────────────────────────────────┐
│ TF    │ Status │ Momentum │ Trend_Str │ │
├───────┼────────┼──────────┼───────────┤ │
│ 1min  │   🔴   │ BEARISH  │    80%    │ │
│ 5min  │   🔴   │ BEARISH  │    82%    │ │
│ 15min │   🔴   │ BEARISH  │    78%    │ │
│ 30min │   🔴   │ BEARISH  │    75%    │ │
│ 1hr   │   🔴   │ BEARISH  │    72%    │ │
│ 4hr   │   🟡   │ NEUTRAL  │    60%    │ │
│ 1day  │   🟢   │ BULLISH  │    65%    │ │
└─────────────────────────────────────────┘

CONSENSUS: All lower TFs red, 4hr neutral, 1day still bullish
ACTION: STRONG_SELL (short term reversal, but daily still up)
INTERPRETATION: Day's reversal is temporary, not structural
```

---

## IMPLEMENTATION PLAN

### 1. Add to `data_capture_v3_duckdb.py`

Every minute, after computing 1-min indicators:
```python
def compute_multitf_status(index_name="NIFTY", current_bar_timestamp=None):
    """Compute multi-TF status for all 6 timeframes."""
    
    timeframes = [5, 15, 30, 60, 240, 1440]  # min
    results = {}
    
    for tf_min in timeframes:
        # Get last N bars for this TF
        bars = duckdb.query(f"""
            SELECT timestamp, close, rsi, adx, st_consensus, ema_5/ema_20 as ema_ratio
            FROM market_data
            WHERE index_name = ? AND timestamp < ?
            ORDER BY timestamp DESC
            LIMIT {tf_min // 1}  -- Last N minutes
        """, (index_name, current_bar_timestamp))
        
        # Aggregate indicators
        status = classify_status(bars)  # GREEN/YELLOW/RED
        results[tf_min] = status
    
    return results
```

### 2. New DuckDB Table: `market_multitf_status`

```sql
CREATE TABLE market_multitf_status (
    timestamp TEXT,
    index_name TEXT,
    timeframe_min INTEGER,  -- 5, 15, 30, 60, 240, 1440
    status TEXT,            -- GREEN, YELLOW, RED
    trend_strength FLOAT,   -- 0-100
    momentum TEXT,          -- BULLISH, NEUTRAL, BEARISH
    indicators_aligned TEXT,    -- comma-separated list
    indicators_conflicting TEXT,
    recommendation TEXT,    -- STRONG_BUY, BUY, HOLD, SELL, STRONG_SELL
    PRIMARY KEY (timestamp, index_name, timeframe_min)
);
```

### 3. New PA Tool: `snapshot_multitf()`

Instead of 60 indicators on 1-min, PA sees one clean table:

```python
def snapshot_multitf(timestamp: str, index_name: str = "NIFTY") -> Dict:
    """Get multi-TF consensus at a moment in time.
    
    Returns clean status for all 6 timeframes.
    
    Example:
        {
            "timestamp": "2026-05-15 12:45:00",
            "index": "NIFTY",
            "consensus": "HOLD_PULLBACK",
            "multitf": [
                {"tf": "1min", "status": "YELLOW", "trend_strength": 55, "momentum": "NEUTRAL"},
                {"tf": "5min", "status": "YELLOW", "trend_strength": 60, "momentum": "NEUTRAL"},
                {"tf": "15min", "status": "GREEN", "trend_strength": 80, "momentum": "BULLISH"},
                {"tf": "30min", "status": "GREEN", "trend_strength": 88, "momentum": "BULLISH"},
                {"tf": "1hr", "status": "GREEN", "trend_strength": 92, "momentum": "BULLISH"},
                {"tf": "4hr", "status": "GREEN", "trend_strength": 85, "momentum": "BULLISH"},
                {"tf": "1day", "status": "GREEN", "trend_strength": 65, "momentum": "BULLISH"},
            ],
            "interpretation": "Lower TFs cooling, higher TFs bullish. Consolidation, not reversal."
        }
    """
    # Query market_multitf_status for all TFs at timestamp
    # Return hierarchical view
```

### 4. PA Analysis with Multi-TF

**Old way (hard):**
```python
snapshot = snapshot_indicators("2026-05-15 12:45:00")
# Parse 60+ indicators, try to find consensus
conf = score_confidence(snapshot)  # Noisy
```

**New way (clear):**
```python
multitf = snapshot_multitf("2026-05-15 12:45:00")
if all(tf["status"] == "GREEN" for tf in multitf if tf["tf"] in ["1min", "5min", "15min"]):
    action = "ENTRY_CONFIRMED"
elif any(tf["status"] == "RED" for tf in multitf if tf["tf"] in ["1min", "5min"]):
    and all(tf["status"] == "GREEN" for tf in multitf if tf["tf"] in ["30min", "1hr"]):
    action = "PULLBACK_HOLD"
else:
    action = "REVERSAL_EXIT"
```

---

## BENEFITS

✅ **PA sees big picture instantly** — Look at 7 rows, not 60 indicators
✅ **Hierarchical understanding** — Know which TF level is strongest
✅ **Cascade prediction** — If 1min red but 1hr green → expect cascade in 30min
✅ **Pullback vs Reversal** — Clear distinction (lower TF red, higher green = pullback)
✅ **Entry confidence** — All TFs green = safe entry; all red = safe exit
✅ **Simplified logic** — No complex indicator scoring, just status matrix

---

## WHEN TO IMPLEMENT

**Option A: Add now to data_capture (Best)**
- Modify `data_capture_v3_duckdb.py` to compute multi-TF status every minute
- New table in DuckDB: `market_multitf_status`
- PA crew uses new `snapshot_multitf()` tool
- ~2-3 hours dev work

**Option B: Compute on-demand (Deferred)**
- Add `snapshot_multitf()` tool that aggregates 1-min data on query
- Works immediately, no data_capture changes
- Slower queries, but proves concept
- Can migrate to pre-computed later

**Option C: Hybrid (Recommended for now)**
- Use Option B first (quick proof)
- Migrate to Option A after validating the approach

---

## EXAMPLE: PA USING MULTI-TF FOR ENTRY DECISION

```
PA receives PM request: "Should we enter IRON_FLY at market now?"

Current time: 2026-05-15 12:45:00

PA queries: multitf = snapshot_multitf("2026-05-15 12:45:00", "NIFTY")

PA analysis:
├─ 1min:  🟡 YELLOW (RSI cooling, no clear momentum)
├─ 5min:  🟡 YELLOW (indecisive)
├─ 15min: 🟢 GREEN  (still trending up)
├─ 30min: 🟢 GREEN  (strong up)
├─ 1hr:   🟢 GREEN  (very strong up)
├─ 4hr:   🟢 GREEN  (up)
└─ 1day:  🟢 GREEN  (up)

Pattern: Lower TFs yellow/consolidating, higher TFs green/trending

PA Recommendation:
  ✗ NOT NOW (lower TFs cooling, possible reversal)
  ✓ WAIT 15-30 min for either:
    a) Lower TFs confirm GREEN again (continuation)
    b) Lower TFs flip to RED (reversal, exit any longs)
  
  "Entry premature. Wait for consolidation resolution.
   Risk: If 1hr flips red in next 30min, cascade likely."
```

---

## WHICH DO YOU PREFER?

**Option 1:** Start with on-demand computation (quick, proves concept)
**Option 2:** Jump to pre-computed multi-TF in data_capture (permanent solution)

Both are good. What matters is PA can see the hierarchy and make decisions fast.
