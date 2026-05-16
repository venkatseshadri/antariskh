# Sandwich — Design Analysis from Claude Conversation

**Date:** 2026-05-16 | **Source:** Claude.ai shared snapshot (88 pages)

## What You're Really Building

A **post-mortem pattern miner** that discovers entry rules from paper trade outcomes against captured multi-TF + option chain data. NOT a live trading system yet — the learning loop comes first.

## Architecture: 3-Layer System

```
Layer 1: Feature Extractor (deterministic Python)
  └─ For each paper trade: snapshot ALL indicators at T-5, T, T+entry
  └─ Multi-TF state, option chain, greeks, outcome metrics

Layer 2: Statistical Pattern Finder (scipy/stats)
  └─ Group trades by outcome bucket
  └─ Compute P(big_win | feature_combination) 
  └─ Only pass statistically-flagged patterns (N≥30, lift>1.5x) to Layer 3

Layer 3: LLM Hypothesis Researcher (CrewAI/LangGraph)
  └─ Receives: stat-backed patterns + example trades
  └─ Outputs: hypothesis with mechanism, rule DSL, failure modes, sample size
  └─ Validator backtests on held-out window
```

## Key Design Principles

1. **LLM never sees raw OHLC.** It sees patterns that statistics already found.
2. **7 indicator families** (not 40 overlapping indicators):
   - Trend: EMA20 + EMA50 per TF (not EMA5,9,20 all stacked)
   - Momentum: RSI(14) per TF
   - Volatility: ATR(14) + ATR percentile
   - Volume: VWAP + volume/avg ratio
   - Options: OI×Price matrix + IV percentile + PCR change
   - Flow: FII index futures net position (5-day change)
   - Macro: India VIX + GIFT premium + Bank Nifty/Nifty ratio
3. **Bull/Bear debate** — skeptic agent argues why each pattern is spurious before acceptance
4. **Decision log** — each closed trade generates reflection paragraph injected into future prompts
5. **Walk-forward validation** — rules tested on held-out time windows before deployment

## CrewAI Layout (batch, runs overnight)

| Agent | Type | Role |
|-------|------|------|
| Hypothesis Researcher | LLM | Takes flagged patterns → writes thesis + rule DSL |
| Hypothesis Validator | LLM + tool | Backtests rule on held-out window → pass/fail |
| Strategy Librarian | LLM | Maintains validated rule library, flags stale rules |

## Tools Needed

- `get_trade_with_context(trade_id)` — full feature snapshot + outcome
- `query_pattern(filter_dict)` — conditional probability calc
- `backtest_rule(rule_dsl, date_range)` — apply rule to historical data
- `list/save/update_hypothesis()` — library CRUD

## Status

Step 1 (Connect & Inspect): ✅ Done
Step 2: Layer 1 Feature Extractor — pending specification
Step 3: Layer 2 Statistical Pattern Finder — pending
Step 4: Layer 3 LLM Researcher — pending
