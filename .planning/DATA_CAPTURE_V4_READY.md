# Data Capture v4: Multi-TF Aggregator Ready

**Status:** ✅ READY TO RUN
**Date:** 2026-05-15
**Design:** Parallel with v3, separate table, later migration

---

## ARCHITECTURE

```
data_capture_v3_duckdb.py (Running)
        ↓
    Captures 1-min OHLCV
        ↓
    market_data table (v3)
    (timeframe_min = 1 only)
        ↓
data_capture_v4_multitf_aggregator.py (NEW)
        ↓
    Reads 1-min bars from v3
    Aggregates to 5/15/30/60/240/1440-min
    Recalculates ADX, RSI, ST per timeframe
        ↓
    market_data_multitf table (NEW, separate)
        ↓
    PA Researcher queries → snapshot_multitf()
    (auto-detects v4 table, falls back to v3)
```

---

## WHAT v4 DOES

### Input
- Reads 1-min bars from `market_data` table (v3 output)
- Looks back N days (configurable, default 30)

### Processing
- **Aggregation:** Groups 1-min bars into 5/15/30/60/240/1440-min buckets
  - Open: first bar's open
  - High: max of all bars in bucket
  - Low: min of all bars in bucket
  - Close: last bar's close
  - Volume: sum of all bars

- **Indicator Recalculation:** For each timeframe's aggregated close series
  - ADX(14): Trend strength (simplified calculation)
  - RSI(14): Momentum (gain/loss ratio)
  - ST Consensus: BULLISH/BEARISH/NEUTRAL

- **Gap Handling:** (Current: basic, can enhance)
  - Detects large gaps (future: resets ATR, VWAP)

### Output
- New table: `market_data_multitf`
- Columns: timestamp, index_name, timeframe_min, open, high, low, close, volume, adx, rsi, st_consensus

---

## HOW TO RUN

### Option 1: One-Time Aggregation (Historical Backfill)
```bash
python3 data_capture_v4_multitf_aggregator.py
```
Aggregates last 30 days for NIFTY into market_data_multitf table.

### Option 2: Continuous Aggregation (Real-Time)
```bash
# Add to crontab to run every 5 minutes
*/5 * * * * cd /home/trading_ceo/antariksh && python3 -c "from data_capture_v4_multitf_aggregator import MultiTFAggregator; MultiTFAggregator().run_all_timeframes()"
```

### Option 3: Production (Later)
Replace v3 with v4 when ready:
- Migrate data from market_data → market_data_multitf
- Update all queries to use market_data_multitf
- Retire v3

---

## TESTING & VERIFICATION

### Current State
✅ All PA crew tests pass (17/17)
✅ All integration tests pass (25/25)
✅ snapshot_multitf() auto-detects v4 table
✅ Falls back to v3 if v4 doesn't exist

### To Test v4
```python
from data_capture_v4_multitf_aggregator import MultiTFAggregator

agg = MultiTFAggregator(verbose=True)
agg.run_all_timeframes(index_name="NIFTY", lookback_days=5)

# Then query:
from tools.pa_tools import snapshot_multitf

result = snapshot_multitf("2026-05-15 12:30:00", "NIFTY")
print(result)  # Should show multitf data
```

---

## NEXT STEPS

### Immediate (This Session)
- [ ] Run v4 aggregator to create market_data_multitf table
- [ ] Verify PA researcher can query it via snapshot_multitf()
- [ ] Test PA crew decision-making with real multi-TF data

### Near Future
- [ ] Enhance gap handling (detect 1%+ gaps, reset ATR/VWAP)
- [ ] Improve indicator calculations (full ADX algorithm, not simplified)
- [ ] Add to cron for continuous real-time aggregation
- [ ] Test PA crew in live scenarios

### Later
- [ ] Migrate all queries from market_data to market_data_multitf
- [ ] Retire v3 (or keep as backup)
- [ ] Update TA crew to use v4 data
- [ ] Update PM crew to use v4 data

---

## WHY THIS DESIGN

✅ **Safe:** v3 keeps running, v4 doesn't break it
✅ **Testable:** Can run v4 independently, verify in parallel
✅ **Flexible:** Fallback logic in snapshot_multitf()
✅ **Migratable:** When ready, just update table name
✅ **Reversible:** Keep both tables until migration complete

---

## FILES CREATED

1. **data_capture_v4_multitf_aggregator.py** (new)
   - MultiTFAggregator class
   - main() for running historical backfill
   - Can be scheduled or run manually

2. **tools/pa_tools.py** (updated)
   - snapshot_multitf() now auto-detects v4 table
   - Falls back to v3 if v4 not available

3. **crews/pa_crew.py** (already updated)
   - Agents ready to use snapshot_multitf()

---

## READY TO SHIP

PA Researcher + v4 Aggregator = Complete research pipeline

```
Raw Market Data (v3) → Aggregated Multi-TF (v4) → PA Researcher (thinking) → PM Decisions
```

Should we run the aggregator now to populate market_data_multitf?
