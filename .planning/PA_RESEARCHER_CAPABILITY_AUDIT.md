# PA Researcher: Capability Audit for Phase-Based Thinking

**Goal:** Can the PA researcher agent autonomously analyze raw multi-TF OHLC and identify market phases?

---

## WHAT THE RESEARCHER NEEDS

### 1. RAW DATA ACCESS (Tools)

**Needed:**
- ✓ snapshot_multitf(timestamp) → Returns raw OHLC for all TFs at that moment
- ? Calculate pattern characteristics from raw OHLC
  - close_position = (close - low) / (high - low) [0=low, 1=high]
  - range_pct = (high - low) / open * 100
  - body_size = |close - open| / (high - low)
  - wick_ratio = longer_wick / shorter_wick

**Status:**
- snapshot_multitf() → EXISTS (returns {price, trend, momentum, volatility, structure, greeks})
- Pattern calculation → MISSING (no tool to analyze OHLC shape)

---

### 2. KNOWLEDGE (Agent Backstory + System Prompt)

**Needed:**
- ✓ Understanding of OHLC shapes (doji, bull_close, bear_close, consolidation)
- ✓ Understanding of phases (setup, initiation, early_trend, continuation, exhaustion, reversal)
- ✓ Understanding of multi-TF sequences (what it means when 1hr breaks first)
- ✓ Understanding of "what changed from last bar" (momentum, direction flip, rollover)
- ? Decision logic: "If daily is doji AND 1hr breaks AND 30min follows → INITIATION"

**Status:**
- Agent backstory in config/agents.json
- No explicit knowledge about phase detection
- No explicit logic about multi-TF sequences

---

### 3. DECISION FRAMEWORK (What agent should output)

**Needed:**
- ✓ Confidence scoring (already has score_confidence tool)
- ? Phase identification output
- ? Risk assessment based on phase
- ? Exit conditions based on phase

---

## CURRENT TOOLS AVAILABLE TO PA RESEARCHER

```python
Tools in crews/pa_crew.py:

✓ review_trade(trade, spec)
✓ run_counterfactuals(trade, ...)
✓ detect_patterns(trades)
✓ generate_post_mortem_report(...)
✓ analyze_sl_optimization(trades, ...)
✓ analyze_entry_window(trades)
✓ analyze_strategy_selection(trades, market_regime, vix)
✓ write_trade_review_to_rag(trade, review, ...)
✓ query_similar_trades_from_rag(query_text, ...)
✓ load_portfolio_state()
✓ save_session_state(...)
✓ snapshot_indicators(timestamp, index_name)
✓ score_confidence(snapshot, direction)
✓ track_missed_opportunities(trades_taken, ...)
✓ generate_pa_recommendations(trades, ...)

MISSING for phase detection:

? snapshot_multitf(timestamp) — Get multi-TF OHLC at once
  Status: Needs to be built to return clean multi-TF data

? analyze_ohlc_shape(open, high, low, close) 
  → Returns {close_position, range_pct, pattern_name}
  Status: Simple utility, should exist

? compare_bars(bar_n_minus_1, bar_n)
  → Returns {higher_high, lower_low, higher_close, hl_ratio_change}
  Status: Sequence analysis, needed

? detect_multitf_alignment(daily, 4hr, 1hr, 30min, 5min)
  → Returns "all_bull", "all_bear", "mixed", cascade_pattern
  Status: Alignment checker, needed
```

---

## WHAT NEEDS TO BE ADDED

### TOOL 1: snapshot_multitf()
```python
# NEEDS TO EXIST in tools/pa_tools.py

def snapshot_multitf(timestamp: str, index_name: str = "NIFTY") -> Dict:
    """Get multi-TF OHLC snapshot (raw data, no classification)."""
    
    # Query market_data for 5min, 15min, 30min, 60min, 1440min
    # Return clean OHLCV for each
    
    Returns:
    {
        "timestamp": "2026-05-15 12:30:00",
        "index": "NIFTY",
        "multitf": {
            "5min": {
                "open": 25280, "high": 25320, "low": 25275, "close": 25300,
                "volume": 9000,
                "adx": 35, "rsi": 72
            },
            "15min": {
                "open": 25000, "high": 25320, "low": 24995, "close": 25300,
                "volume": 27000,
                "adx": 35, "rsi": 75
            },
            "30min": {...},
            "60min": {...},
            "1440min": {...}
        }
    }
```

**Status:** ✗ MISSING (need to build)
**Effort:** 30 mins (just aggregate + return)

---

### TOOL 2: analyze_ohlc_shape()
```python
# NEEDS TO EXIST in tools/pa_tools.py

def analyze_ohlc_shape(ohlc: Dict) -> Dict:
    """Analyze raw OHLC to extract shape characteristics."""
    
    Input: {open, high, low, close, adx}
    
    Returns:
    {
        "close_position": 0.92,  # 0=low, 1=high
        "range_pct": 0.17,       # (high-low)/open * 100
        "body_pct": 0.70,        # |close-open|/range * 100
        "wick_ratio": 0.3,       # (smaller wick / larger wick)
        "hl_ratio": 43,          # (high - low) in points
        "adx_strength": "STRONG" # ADX > 25 or < 20
    }
    
    # Agent can then reason:
    # - If close_position > 0.7 AND adx > 25 → BULL_CLOSE
    # - If close = open AND range_pct > 1.5 → DOJI
    # - If range_pct < 0.5 → CONSOLIDATION
```

**Status:** ✗ MISSING (simple calculation, but useful)
**Effort:** 20 mins

---

### TOOL 3: compare_ohlc_sequence()
```python
# NEEDS TO EXIST in tools/pa_tools.py

def compare_ohlc_sequence(bars: List[Dict]) -> Dict:
    """Compare sequence of bars to detect momentum, reversals."""
    
    Input: [bar_t-2, bar_t-1, bar_t]
    
    Returns:
    {
        "higher_high": True,      # current high > prev high
        "higher_low": True,       # current low > prev low
        "higher_close": True,     # current close > prev close
        "closes_at_range_top": True,
        "direction_consistent": "UP",  # UP, DOWN, MIXED
        "pattern_type": "BULL_CONTINUATION",  # or BEAR, REVERSAL, etc
        "momentum": "ACCELERATING"  # or DECELERATING, STABLE
    }
```

**Status:** ✗ MISSING (pattern recognition)
**Effort:** 40 mins

---

### TOOL 4: detect_phase()
```python
# THIS IS THE KEY TOOL - Let agent reason about it!
# Don't hard-code phases. Give agent the raw data + knowledge.

# Agent backend: Just provide helper
def analyze_multitf_phases(multitf_snapshot: Dict) -> Dict:
    """
    Provide raw analysis that agent can interpret.
    Don't tell agent "this is INITIATION".
    Just give facts, let agent think.
    """
    
    Returns:
    {
        "daily": {
            "ohlc_shape": analyze_ohlc_shape(daily),
            "adx": daily["adx"],
            "rsi": daily["rsi"],
            "st": daily["st_consensus"]
        },
        "4hr": {
            "ohlc_shape": analyze_ohlc_shape(4hr),
            "adx": 4hr["adx"],
            "comparison_to_daily": "similar_momentum",
            "st": 4hr["st_consensus"]
        },
        "1hr": {
            "ohlc_shape": analyze_ohlc_shape(1hr),
            "adx": 1hr["adx"],
            "comparison_to_4hr": "stronger_than_4hr",
            "st": 1hr["st_consensus"]
        },
        "30min": {...},
        "5min": {...},
        
        "observations": [
            "Daily is doji (open=close, wide wick) → indecision",
            "1-hour ADX is 25+ (just crossed threshold)",
            "1-hour close position is 0.92 (near high)",
            "30-min following the 1-hour move upward",
            "5-min consolidating at new high"
        ]
    }
```

**Status:** ~ PARTIALLY EXISTS (analyze functions exist, but not integrated)
**Effort:** Integration only, 20 mins

---

## KNOWLEDGE AUDIT: What Agent Needs to Know

### Current PA Agent Backstory (config/agents.json):
```json
"reviewer": {
  "role": "Trade Quality Reviewer",
  "goal": "Antariksh is your research lab. Discover what nobody asked...",
  "backstory": "You're not a report generator..."
}
```

**Missing:** No mention of phase detection, multi-TF analysis, OHLC patterns!

### What Should Be Added:
```
"You understand market structure across timeframes:
- Daily timeframe shows the market's daily conviction
- Hourly shows the intraday momentum
- When hourly breaks out while daily is consolidating, that's a
  NEW TREND INITIATING (high risk but early entry)
- When hourly shows higher lows but 30-min shows lower highs,
  that's exhaustion (exit signal)
- When all timeframes show the same direction (bull close across
  all), that's CONTINUATION (safest trade)

Use snapshot_multitf() to get raw OHLC. Analyze each bar's shape:
- Where did it close? (top/middle/bottom of range)
- What was the range? (expansion/contraction)
- Are new highs/lows being made?
- Is momentum accelerating or decelerating?

Detect the phase:
1. SETUP: All TFs consolidating, ADX<20
2. INITIATION: Lower TF just broke, higher TF still up
3. CONTINUATION: All TFs bullish/bearish together
4. EXHAUSTION: Top-down rollover starting
5. REVERSAL: Cascade of flips

Your job is not to classify. Your job is to OBSERVE the raw data
and REASON about what it means."
```

---

## DECISION: What to Build vs What to Teach

### Option A: Pre-compute phases in code (What we initially planned)
```
Pros: Agent doesn't have to think, just reads phase column
Cons: Clouds agent's reasoning, reduces flexibility

Example:
SELECT * WHERE phase = 'INITIATION'
Agent: "It says initiation, so enter"
```

### Option B: Give agent raw data + teach it to think (Your suggestion)
```
Pros: Agent reasons independently, flexible, can find new patterns
Cons: Agent needs more knowledge, might miss something

Example:
SELECT ohlc, adx, rsi WHERE tf IN (5,15,30,60,1440)
Agent thinks: "Daily doji, 1hr broke, 30min following...
             this looks like initiation phase. Enter."
```

**You're saying:** Go with Option B

---

## MINIMAL BUILD CHECKLIST

To enable PA researcher to think about phases:

### Must Build (3 items):
- [ ] **snapshot_multitf(timestamp)** — Raw OHLC across all TFs
- [ ] **analyze_ohlc_shape(ohlc)** — Extract shape characteristics  
- [ ] **compare_ohlc_sequence(bars)** — Pattern momentum detection

### Must Update (1 item):
- [ ] **PA Agent Backstory** in config/agents.json
  - Add knowledge about OHLC patterns
  - Add knowledge about multi-TF phases
  - Add decision framework for phase-based reasoning

### Already Exists:
- ✓ score_confidence() — Confidence scoring
- ✓ snapshot_indicators() — Current bar snapshot
- ✓ query_similar_trades_from_rag() — Pattern library lookup

---

## WHAT THIS ENABLES

Once these tools + knowledge exist:

```
PA researcher analyzes your UP→PAUSE→REVERSAL scenario:

09:15 — Market open
  snapshot_multitf() → Returns daily doji + hourly consolidating
  Agent thinks: "Setup phase. Waiting for breakout."

09:20 — First 5-min aggregation
  snapshot_multitf() → 1hr close at high, 30min following
  Agent thinks: "Initiation! 1hr just broke, rest following."
  Agent decides: "ENTRY WINDOW OPEN"

12:30 — Consolidation hour
  snapshot_multitf() → 5min yellow, 15min yellow, 1hr still green
  analyze_ohlc_sequence() → ADX declining, range shrinking
  Agent thinks: "Exhaustion starting. Top-down rollover."
  Agent decides: "DO NOT ENTER. TAKE PROFIT."

12:35 — Reversal
  snapshot_multitf() → SuperTrend cascade, closes at lows
  Agent thinks: "Reversal confirmed. Cascade in progress."
  Agent decides: "EXIT IMMEDIATELY"

All WITHOUT pre-computed phase column!
All through REASONING about raw data!
```

---

## FINAL RECOMMENDATION

Build 3 simple tools:
1. snapshot_multitf() — 30 mins
2. analyze_ohlc_shape() — 20 mins  
3. compare_ohlc_sequence() — 40 mins

Update 1 config:
4. PA Agent Backstory with phase-detection knowledge — 20 mins

**Total: ~2 hours**

Then the PA researcher will THINK about phases naturally, without pre-computation clouding its reasoning.

Does this match your vision?
