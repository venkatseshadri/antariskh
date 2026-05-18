# Post-Mortem (PA) Crew — Comprehensive Roadmap

**Date:** 2026-05-15  
**Status:** 2 agents + 17 tools built. Ready for next phase.

---

## WHAT'S BUILT ✅

### Agents (2)
- **Reviewer** — Trade quality assessment, counterfactual analysis
- **Analyst** — Pattern detection, recommendations, learning

### Tools (17) — All in `tools/pa_tools.py` + `crews/pa_crew.py`

#### Core Analysis (3 tools - BUILT)
- ✅ `review_trade(trade, spec)` — Quality score + issues list
- ✅ `run_counterfactuals(trade, peak_pnl, better_exit, better_sl, better_tp, hypothetical_entry)` — What-if scenarios
- ✅ `detect_patterns(trades)` — Recurring issue detection

#### Indicator Snapshot & Confidence (3 tools - BUILT)
- ✅ `snapshot_indicators(timestamp, index_name="NIFTY")` — Captures 40+ indicators at a moment (price, trend, momentum, vol, structure, Greeks)
- ✅ `score_confidence(snapshot, direction="UP")` — Scores indicator alignment (0-100%)
- ✅ `track_missed_opportunities(trades_taken, potential_setups)` — Identifies high-confidence setups not executed

#### Strategy Learning (6 tools - BUILT)
- ✅ `analyze_sl_optimization(trades, sl_range=None, step=250)` — Simulates SL levels, finds optimal
- ✅ `analyze_entry_window(trades)` — Best 30-min entry window by win rate
- ✅ `analyze_strategy_selection(trades, market_regime="UNKNOWN", current_vix=18.0)` — Iron Fly vs Credit Spread recommendation
- ✅ `write_trade_review_to_rag(trade, review, market_regime="UNKNOWN")` — Store to ChromaDB for learning
- ✅ `query_similar_trades_from_rag(query_text, strategy_filter=None, n_results=5)` — Semantic search past trades
- ✅ `generate_pa_recommendations(trades, total_margin_available=0, total_margin_used=0)` — Aggregated analysis + top N recommendations

#### Portfolio & Session State (2 tools - BUILT)
- ✅ `load_portfolio_state()` — Current capital, margin, active trades from SQLite
- ✅ `save_session_state(portfolio_value, daily_pnl, session_pnl, margin_available, margin_used)` — Persist state

#### Report Generation (2 tools - BUILT)
- ✅ `generate_post_mortem_report(reviews, counterfactuals, patterns, session)` — Full PM report with recommendations
- ✅ (implied via Reviewer/Analyst agents) Trade quality assessment

**Test Status:** 17/17 PA crew tests ✅ | 25/25 integration tests ✅

---

## WHAT'S PENDING — PRIORITY ORDER

### Phase 1: BREAKOUT ANALYSIS (High Priority — Foundation for entry logic)

Goals:
- Detect support/resistance from price history
- Spot actual breakout events
- Find historical pattern matches for similar breakouts

**Tools to build:**

1. **`detect_range(trades_history, lookback_bars=20, threshold_pct=1.5)`** — Identify support/resistance
   - Input: price history (from DuckDB market_data)
   - Output: `{support_levels: [...], resistance_levels: [...], price_strength: "strong/weak"}`
   - Algorithm: Find local minima/maxima, cluster near levels, measure bounces
   - Used by: Entry signal generation, breakout validation
   - Test: 3 scenarios (narrow range, wide range, no clear structure)

2. **`spot_breakout(current_price, range_levels, direction="UP", confirmation_bars=2)`** — Detect breakout event
   - Input: current price, support/resistance, direction (UP/DOWN)
   - Output: `{is_breakout: bool, strength: 0-100, breakout_level: float}`
   - Algorithm: Check if price crossed level + confirmation (N consecutive closes beyond level)
   - Used by: PM for entry timing confirmation
   - Test: 4 scenarios (clean break, false break, gap breakout, gradual cross)

3. **`find_similar_breakouts(current_pattern, market_regime, min_match_score=0.70)`** — Historical pattern search
   - Input: breakout pattern (levels, direction, VIX, regime), lookback N days
   - Output: `{matches: [{date, price, win_rate, avg_pnl, strategy_works: bool}], success_rate: 0-100}`
   - Algorithm: Query DuckDB trade history + indicator snapshots, match regime/VIX/structure, score by similarity
   - Used by: Confidence scoring, strategy recommendation
   - Test: 3 scenarios (found patterns, no patterns, cross-regime patterns)

**Implementation Notes:**
- All 3 require DuckDB read access (already wired)
- Detector pattern: `snapshot_indicators()` → `detect_range()` → `spot_breakout()` → `find_similar_breakouts()`
- Chain into Reviewer: breakout confirmation before trade entry

---

### Phase 2: EXIT LOGIC (High Priority — Critical for P&L management)

Goals:
- Distinguish pullback from trend reversal (hold vs exit)
- Identify exit signals (time, P&L, technical, risk)
- Resistance zone analysis for profit-taking

**Tools to build:**

4. **`detect_pullback_vs_reversal(active_trade, recent_price_action, market_context)`** — Hold or exit decision
   - Input: trade entry, current price, recent bars (5/10/20 closes), volume, RSI, support/resistance
   - Output: `{signal: "HOLD_PULLBACK" | "EXIT_REVERSAL", confidence: 0-100, reason: str}`
   - Algorithm: 
     - Pullback: retraces <50% of recent move, stays above entry, volume drying
     - Reversal: breaks support, ADX < 20, RSI extremes flip, volume spikes
   - Used by: Risk sentry for position holding vs closing
   - Test: 4 scenarios (pullback in uptrend, reversal in uptrend, sideways chop, ranging market)

5. **`identify_exit_signals(active_trade, market_state, thresholds: dict)`** — When to exit
   - Input: trade details, current price/Greeks/time, exit rules (time_limit=30min, target_pnl=70%, exit_at=15:30)
   - Output: `{exit_signals: [{"signal": "TIME_LIMIT", "confidence": 1.0}, ...], primary_signal: str}`
   - Algorithm: Check all exit conditions (time, P&L target, technical stops, market close, SL/TP)
   - Used by: Executor for EOD position closure + opportunistic exits
   - Test: 5 scenarios (hit target, hit time limit, market close, SL trigger, multi-signal)

6. **`analyze_resistance_zones(trade_context, support_resistance_levels, current_price)`** — Should we exit at resistance?
   - Input: trade entry/current price, support/resistance levels, premium decay status
   - Output: `{zones: [{level, distance_pct, exit_action: "TAKE_PROFIT" | "HOLD", confidence: 0-100}], recommendation: str}`
   - Algorithm: Score distance to resistance, theta decay rate, Greeks risk at each zone
   - Used by: Shifter for exit level selection
   - Test: 3 scenarios (near resistance, far from resistance, multi-zone analysis)

---

### Phase 3: LEARNING LOOP (Medium Priority — Feedback system)

Goals:
- Auto-build pattern library from closed trades
- Track strategy effectiveness by regime
- Update recommendations based on recent wins/losses

**Tools to build:**

7. **`build_pattern_library(completed_trades, market_regime, lookback_days=30)`** — Create reusable patterns
   - Input: closed trades, regime label
   - Output: `{patterns: [{name, setup_conditions, success_rate, avg_pnl, recommendation: str}], top_3_patterns: [...]}`
   - Algorithm: Group trades by similar entry conditions, calculate aggregate stats
   - Stores in: ChromaDB (RAG learning)
   - Test: 2 scenarios (clear pattern emerges, random trades)

8. **`track_strategy_effectiveness(strategy_name, market_regime, n_trades=50)`** — Is strategy still working?
   - Input: strategy name, regime, lookback period
   - Output: `{win_rate: 0-100, profit_factor, trades_analyzed, recommendation: "KEEP" | "PAUSE" | "RETIRE"}`
   - Algorithm: Query past N trades by strategy + regime, calculate aggregate metrics
   - Stores in: SQLite state for PM
   - Test: 2 scenarios (strategy working, strategy broken)

9. **`analyze_counterfactual_patterns(completed_trades)`** — What could we have done better?
   - Input: closed trades with entry/exit/peak_pnl
   - Output: `{biggest_miss: {trade_id, potential_gain, reason}, systematic_issues: [{issue, frequency, avg_cost}]}`
   - Algorithm: For each trade, score alternative exits (peak_pnl vs actual_pnl), cluster reasons
   - Used by: PM to improve strategy design
   - Test: 2 scenarios (good exits vs missed exits, systematic biases)

---

### Phase 4: INTEGRATION (Medium Priority — Wire PA → PM + TA)

Goals:
- PA findings drive PM strategy decisions
- PA market regime data feeds TA
- Daily recommendations actionable by PM

**Tools to build:**

10. **`rank_pa_recommendations(all_recommendations, portfolio_state, priority_metric="risk_adjusted_return")`** — Prioritize for PM
    - Input: PA recommendations, current capital/positions, priority criteria
    - Output: `{ranked_list: [{rank, tool, action, confidence, impact_pnl: float}]}`
    - Algorithm: Score by confidence × expected_impact, sort by priority_metric
    - Used by: Executor for action ordering
    - Test: 2 scenarios (conflicting recs, aligned recs)

11. **`export_pa_findings_to_pm(pa_session_summary)`** — Daily brief for PM
    - Input: PA analysis results
    - Output: JSON struct with: strategy recommendation, entry windows, SL/TP levels, expected patterns
    - Used by: PM crew `strategist` agent input
    - Test: 1 scenario (full daily summary)

12. **`export_pa_regime_to_ta(market_observations)`** — Market regime consensus for TA
    - Input: PA indicator snapshots + pattern analysis
    - Output: `{regime: "TRENDING_UP" | "TRENDING_DOWN" | "SIDEWAYS", confidence: 0-100, next_support, next_resistance}`
    - Used by: TA crew `technical_scout` agent validation
    - Test: 1 scenario (regime confirmation)

---

### Phase 5: ADVANCED ANALYSIS (Low Priority — Polish & optimization)

Goals:
- Multi-timeframe breakout confirmation
- Greeks-aware exit optimization
- Drawdown recovery strategies

**Tools to build:**

13. **`confirm_breakout_multi_timeframe(trade_setup, tf_list=[1, 5, 15])`** — Are all timeframes aligned?
    - Input: breakout on 1-min, check 5-min and 15-min confirmation
    - Output: `{all_aligned: bool, alignment_score: 0-100}`
    - Used by: High-confidence entry filter
    - Test: 2 scenarios (aligned breakout, misaligned)

14. **`optimize_exit_by_greeks(active_trade, current_greeks, target_greeks)`** — Exit when Greeks reach target
    - Input: trade Greeks (delta, gamma, theta, vega), target levels
    - Output: `{exit_price: float, expected_premium: float, greeks_at_exit: dict}`
    - Used by: Shifter for smart exit pricing
    - Test: 2 scenarios (gamma exit, vega exit)

15. **`analyze_recovery_opportunities(drawdown_period, capital_available)`** — How to recover from losses
    - Input: recent losing trades, capital available
    - Output: `{recovery_strategy: str, recommended_position_size: float, expected_timeline: "N days"}`
    - Used by: PM for comeback trading
    - Test: 1 scenario (recovery after bad day)

---

## BUILD ORDER (Recommended)

**Sprint 1 (Days 1-2):** Breakout Analysis
1. `detect_range()` 
2. `spot_breakout()`
3. `find_similar_breakouts()`

**Sprint 2 (Days 3-4):** Exit Logic
4. `detect_pullback_vs_reversal()`
5. `identify_exit_signals()`
6. `analyze_resistance_zones()`

**Sprint 3 (Days 5-6):** Learning Loop
7. `build_pattern_library()`
8. `track_strategy_effectiveness()`
9. `analyze_counterfactual_patterns()`

**Sprint 4 (Days 7-8):** Integration
10. `rank_pa_recommendations()`
11. `export_pa_findings_to_pm()`
12. `export_pa_regime_to_ta()`

**Sprint 5+ (Ongoing):** Polish
13-15. Advanced analysis tools as bandwidth allows

---

## TESTING CHECKLIST

For each tool:
- [ ] Unit tests pass (tool works in isolation)
- [ ] DuckDB queries validated (handles NaN, null, empty result sets)
- [ ] Integrated into crew (wrapped as @tool, added to agent)
- [ ] Integration tests updated (INT-XX tests if cross-crew)
- [ ] Edge cases covered (empty inputs, extremes, boundaries)

---

## SUCCESS CRITERIA

**Phase 1 Complete:** PA can explain "why NIFTY 25000-25200 range breakout at 10:45 was tradeable" (with historical pattern matches)

**Phase 2 Complete:** PA can recommend "hold pullback" or "exit reversal" for active positions with 75%+ accuracy on backtest

**Phase 3 Complete:** PA library shows "Credit Spread in SIDEWAYS works 8/10 times; Iron Fly works 6/10" — actionable patterns

**Phase 4 Complete:** PM receives ranked daily actions; TA receives regime confirmation; system runs closed-loop learning

---

## NOTES FOR NEXT SESSION

- All 17 existing PA tests continue to pass ✅
- DuckDB reads are wired and working ✅
- ChromaDB RAG storage is implemented ✅
- State persistence (SQLite) is implemented ✅
- No blockers to starting Phase 1 tools immediately
- User preference: **iterate daily, ship working code, don't over-design**
