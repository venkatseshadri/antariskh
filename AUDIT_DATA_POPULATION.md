# Data Population Audit — Pre R3-Multi

**Date:** 2026-05-17 | **Source:** Live DuckDB queries

## v3.1 `market_data` — NIFTY (3,039 rows)

```
Total rows:        3,039

ta-lib (buffer-dependent):
  rsi                    2,386  (78.5%)
  adx                    2,386  (78.5%)
  atr                    2,386  (78.5%)
  ema_5                  2,580  (84.9%)
  ema_20                 2,308  (75.9%)
  ema_50                 2,045  (67.3%)
  supertrend_direction   2,308  (75.9%)
  supertrend_value       2,308  (75.9%)
  bb_pct_b               2,308  (75.9%)
  bb_width               2,308  (75.9%)
  ema20_slope            2,308  (75.9%)
  vwap                   2,226  (73.2%)

SMC indicators:
  swing_high             2,226  (73.2%)
  swing_low              2,226  (73.2%)
  structure_type         2,226  (73.2%)
  smc_strength           2,226  (73.2%)
  next_target            2,226  (73.2%)
  fvg_high               1,986  (65.4%)
  fvg_low                1,986  (65.4%)
  ob_zone_high             392  (12.9%)  ⚠️ CRITICAL
  ob_zone_low              392  (12.9%)  ⚠️ CRITICAL

SMC booleans (interestingly populated — NOT zone-dependent):
  ob_strength            2,675  (88.0%)
  fvg_mitigated          2,675  (88.0%)
  structure_confirmed    2,675  (88.0%)
  liquidity_swept        2,675  (88.0%)

Multi-TF consensus:
  st_consensus           1,735  (57.1%)  needs st_5min + st_15min both warm

Broker-computed (no buffer needed):
  iv_rank                2,675  (88.0%)
  iv_current             2,675  (88.0%)
  iv_regime              2,675  (88.0%)
  pcr_atm                2,673  (88.0%)
  pcr_total              2,673  (88.0%)
  session_phase          2,675  (88.0%)
  agg_delta              2,660  (87.5%)
  agg_theta              2,660  (87.5%)
  agg_gamma              2,660  (87.5%)
  agg_vega               2,660  (87.5%)
  sentiment              2,673  (88.0%)

Infra (partially broker-dependent):
  prev_day_high          2,300  (75.7%)
  prev_day_low           2,300  (75.7%)
  open_price             2,238  (73.6%)
  pivot_pp               2,300  (75.7%)

DEAD columns (0.0%):
  cluster_support            0  (0.0%)
  cluster_resistance         0  (0.0%)
  distance_to_support        0  (0.0%)
  distance_to_resistance     0  (0.0%)
```

## v4 `market_data_multitf` — NIFTY (82 bars total across 6 TFs)

```
                   bars   RSI    ADX    SMA20  MACD   BB     OBV
5 min              42     100%    95%    93%    88%    93%    100%
15 min             15     100%   100%    93%    93%    93%    100%
30 min              9     100%   100%    89%    89%    89%    100%
60 min              5     100%   100%   100%   100%   100%   100%
240 min             2     100%   100%   100%   100%   100%   100%
1440 min (daily)    1     100%   100%   100%   100%   100%   100%

Date range: 2026-05-15 11:37:36 → 15:25:35 (single day, late start)

SMA200:    0% all TFs (needs 200 bars, max available = 42)
st_consensus: always "NEUTRAL" (legacy placeholder)
cmf:       58-100% populated per TF
cci:       82-100% populated per TF
```

## Summary for R3-Multi spec

| Gap | Severity | Detail |
|-----|----------|--------|
| ob_zone_high/low @ 12.9% | **BLOCKER** | Order block detection fails for 87% of rows. OB zones are the SMC foundation. But ob_strength/fvg_mitigated at 88% suggest the bools are computed from something else — needs code audit. |
| cluster_support/resistance @ 0% | **DEAD** | Price cluster detection never populated. Remove from spec or fix. |
| v4 has 1 day | **SEVERE** | SMA50/SMA200 impossible for weeks. MACD/Bollinger/ADX compute fine from ~20 bars. |
| st_consensus @ 57% | **MODERATE** | Multi-TF SuperTrend needs both 5m and 15m ST — buffer warmup will fix. |
| EMA_50 @ 67%, ADX @ 78% | **MODERATE** | Fixed by today's buffer warmup patch. Will normalize to ~88% (matching IV/Greeks ceiling). |
| SENSEX v4 | Mirror of NIFTY | 40/14/8/4/2/1 bars per TF. Same gaps. |
