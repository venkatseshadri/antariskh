# Antariksh Data Capture — DuckDB Schema & Indicators

**Date:** 2026-05-16 | **DB:** `python-trader/varaha/data/varaha_data.duckdb`

## Capture Scripts

| Script | DB Table | Status | Frequency |
|--------|----------|--------|-----------|
| `data_capture_v3_duckdb.py` | `market_data`, `option_snapshots` | Baseline (v3) | Every 60s, market hours |
| `data_capture_v3.1_duckdb.py` | `market_data`, `option_snapshots` | Active | Every 60s + Redis queue + log backup |
| `data_capture_v4_queue_aggregator.py` | `market_data_multitf` (separate DB) | Ready | Every 60s, reads Redis queue |
| `data_capture_v4_multitf_aggregator.py` | `market_data_multitf` (same DB) | Standby | Batch, 30-day lookback |

---

## Table: `market_data` (104 columns)

Populated by v3/v3.1 every 60 seconds. One row per capture cycle.

### Identity & Time (6 cols)
| # | Column | Type | Source |
|---|--------|------|--------|
| 1 | `id` | INTEGER PK | Auto-increment |
| 2 | `timestamp` | TEXT | ISO 8601 (datetime.now()) |
| 3 | `date` | TEXT | Derived from timestamp |
| 4 | `time` | TEXT | Derived from timestamp |
| 5 | `trading_day` | INTEGER | 0=Mon..6=Sun |
| 6 | `index_name` | TEXT | NIFTY / SENSEX |

### Price Data — Raw Broker (4 cols)
| # | Column | Type | Source |
|---|--------|------|--------|
| 7 | `spot` | DOUBLE | Shoonya get_spot |
| 8 | `futures` | DOUBLE | Shoonya get_futures |
| 9 | `open_price` | DOUBLE | Shoonya (cached once/day) |
| 10 | `prev_close` | DOUBLE | Shoonya (cached once/day) |

### Expiry Data (6 cols)
| # | Column | Type | Source |
|---|--------|------|--------|
| 11 | `atm_strike` | INTEGER | Computed: round(spot/50)*50 |
| 12 | `expiry_weekly` | TEXT | Shoonya API |
| 13 | `days_to_weekly` | INTEGER | Computed |
| 14 | `expiry_next_weekly` | TEXT | Shoonya API |
| 15 | `days_to_next_weekly` | INTEGER | Computed |
| 16 | `expiry_monthly` | TEXT | Shoonya API |
| 17 | `days_to_monthly` | INTEGER | Computed |

### Trend Indicators — ta-lib (8 cols)
| # | Column | Type | Source |
|---|--------|------|--------|
| 18 | `ema_5` | DOUBLE | ta-lib EMA(5) on close |
| 19 | `ema_20` | DOUBLE | ta-lib EMA(20) |
| 20 | `ema_50` | DOUBLE | ta-lib EMA(50) |
| 21 | `supertrend_value` | DOUBLE | Custom ST(10,3) |
| 22 | `supertrend_direction` | TEXT | bullish/bearish |
| 23 | `st_5min_value` | DOUBLE | Multi-TF SuperTrend 5m |
| 24 | `st_5min_direction` | TEXT | Multi-TF SuperTrend 5m |
| 25 | `st_15min_value` | DOUBLE | Multi-TF SuperTrend 15m |
| 26 | `st_15min_direction` | TEXT | Multi-TF SuperTrend 15m |
| 27 | `st_consensus` | VARCHAR | BULLISH/BEARISH/NEUTRAL |
| 28 | `adx` | DOUBLE | ta-lib ADX(14) |
| 29 | `atr` | DOUBLE | ta-lib ATR(14) |

### Momentum — ta-lib (3 cols)
| # | Column | Type | Source |
|---|--------|------|--------|
| 30 | `rsi` | DOUBLE | ta-lib RSI(14) |
| 31 | `bb_pct_b` | DOUBLE | Bollinger %B (20,2) |
| 32 | `bb_width` | DOUBLE | Bollinger Band width % |

### Volatility & VIX (2 cols)
| # | Column | Type | Source |
|---|--------|------|--------|
| 33 | `india_vix` | DOUBLE | Shoonya (token 26017) |
| 34 | `vwap` | DOUBLE | Cumulative VWAP |
| 35 | `ema20_slope` | DOUBLE | EMA20[-1] - EMA20[-6] |
| 36 | `gap_pct` | DOUBLE | (open - prev_close) / prev_close * 100 |

### Day Range (5 cols)
| # | Column | Type | Source |
|---|--------|------|--------|
| 37 | `prev_day_high` | DOUBLE | DB query or yfinance |
| 38 | `prev_day_low` | DOUBLE | DB query or yfinance |
| 39 | `prev_day_range` | DOUBLE | Computed |
| 40 | `intraday_high` | DOUBLE | max(high) from buffer |
| 41 | `intraday_low` | DOUBLE | min(low) from buffer |

### Pivot Points (7 cols)
| # | Column | Type | Source |
|---|--------|------|--------|
| 42 | `pivot_pp` | DOUBLE | Classic Pivot Point |
| 43 | `pivot_r1` | DOUBLE | Resistance 1 |
| 44 | `pivot_r2` | DOUBLE | R2 |
| 45 | `pivot_r3` | DOUBLE | R3 |
| 46 | `pivot_s1` | DOUBLE | Support 1 |
| 47 | `pivot_s2` | DOUBLE | S2 |
| 48 | `pivot_s3` | DOUBLE | S3 |

### Fibonacci Levels (7 cols)
| # | Column | Type | Source |
|---|--------|------|--------|
| 49 | `fib_0` | DOUBLE | 0.0 (prev_day_low) |
| 50 | `fib_236` | DOUBLE | 23.6% |
| 51 | `fib_382` | DOUBLE | 38.2% |
| 52 | `fib_50` | DOUBLE | 50.0% |
| 53 | `fib_618` | DOUBLE | 61.8% |
| 54 | `fib_786` | DOUBLE | 78.6% |
| 55 | `fib_100` | DOUBLE | 100.0% (prev_day_high) |

### Open Range (2 cols)
| # | Column | Type | Source |
|---|--------|------|--------|
| 56 | `open_range_high` | DOUBLE | First 5 bars max high |
| 57 | `open_range_low` | DOUBLE | First 5 bars min low |

### SMC Indicators (12 cols)
| # | Column | Type | Source |
|---|--------|------|--------|
| 58 | `ob_zone_high` | DOUBLE | Order Block high |
| 59 | `ob_zone_low` | DOUBLE | Order Block low |
| 60 | `ob_strength` | INTEGER | OB strength score |
| 61 | `fvg_high` | DOUBLE | Fair Value Gap high |
| 62 | `fvg_low` | DOUBLE | Fair Value Gap low |
| 63 | `fvg_mitigated` | BOOLEAN | FVG filled? |
| 64 | `swing_high` | DOUBLE | Recent swing high |
| 65 | `swing_low` | DOUBLE | Recent swing low |
| 66 | `liquidity_swept` | BOOLEAN | Liquidity grab? |
| 67 | `structure_type` | VARCHAR | Market structure |
| 68 | `structure_confirmed` | BOOLEAN | Structure break confirmed |
| 69 | `next_target` | DOUBLE | Next SMC target |
| 70 | `smc_strength` | DOUBLE | Overall SMC strength |

### IV & Volatility Regime (9 cols)
| # | Column | Type | Source |
|---|--------|------|--------|
| 71 | `iv_current` | DOUBLE | Current IV |
| 72 | `iv_52w_high` | DOUBLE | 52-week IV high |
| 73 | `iv_52w_low` | DOUBLE | 52-week IV low |
| 74 | `iv_rank` | DOUBLE | IV Rank (0-100) |
| 75 | `iv_regime` | VARCHAR | low/normal/high/extreme |
| 76 | `iv_short` | DOUBLE | Short-term IV avg |
| 77 | `iv_long` | DOUBLE | Long-term IV avg |
| 78 | `iv_slope` | DOUBLE | IV trend slope |
| 79 | `hv_20` | DOUBLE | Historical Vol 20-day |
| 80 | `hv_60` | DOUBLE | Historical Vol 60-day |

### Options Greeks — Aggregate (6 cols)
| # | Column | Type | Source |
|---|--------|------|--------|
| 81 | `agg_delta` | DOUBLE | Composite delta (ATM) |
| 82 | `agg_gamma` | DOUBLE | Composite gamma |
| 83 | `agg_vega` | DOUBLE | Composite vega |
| 84 | `agg_theta` | DOUBLE | Composite theta |
| 85 | `wings_delta` | DOUBLE | Wing legs delta |
| 86 | `body_delta` | DOUBLE | Body/straddle delta |

### Price Clusters (4 cols)
| # | Column | Type | Source |
|---|--------|------|--------|
| 87 | `cluster_support` | DOUBLE | Support cluster level |
| 88 | `cluster_resistance` | DOUBLE | Resistance cluster level |
| 89 | `distance_to_support` | DOUBLE | % distance to support |
| 90 | `distance_to_resistance` | DOUBLE | % distance to resistance |

### Session State (4 cols)
| # | Column | Type | Source |
|---|--------|------|--------|
| 91 | `session_phase` | VARCHAR | early/mid/late |
| 92 | `open_to_current_pct` | DOUBLE | % from open |
| 93 | `distance_to_pivot_pct` | DOUBLE | % to pivot |
| 94 | `distance_to_r1_pct` | DOUBLE | % to R1 |
| 95 | `distance_to_s1_pct` | DOUBLE | % to S1 |

### Options Flow & Sentiment (8 cols)
| # | Column | Type | Source |
|---|--------|------|--------|
| 96 | `pcr_total` | DOUBLE | Put-Call Ratio |
| 97 | `pcr_atm` | DOUBLE | ATM PCR |
| 98 | `sentiment` | VARCHAR | bullish/bearish/neutral |
| 99 | `max_pain_strike` | INTEGER | Max Pain strike |
| 100 | `call_oi_concentration` | DOUBLE | Call OI concentration |
| 101 | `put_oi_concentration` | DOUBLE | Put OI concentration |
| 102 | `oi_skew` | DOUBLE | OI skew ratio |

### Meta (2 cols)
| # | Column | Type | Source |
|---|--------|------|--------|
| 103 | `data_source` | TEXT | broker/yfinance/none |
| 104 | `buffer_bars` | INTEGER | Bars in rolling buffer |

---

## Table: `option_snapshots` (12 columns)

| # | Column | Type | Source |
|---|--------|------|--------|
| 1 | `id` | INTEGER PK | Auto-increment |
| 2 | `timestamp` | TEXT | ISO 8601 |
| 3 | `date` | TEXT | Derived |
| 4 | `expiry_label` | TEXT | weekly/next_weekly/monthly |
| 5 | `expiry_date` | TEXT | Shoonya API |
| 6 | `strike` | INTEGER | Grid builder |
| 7 | `strike_offset` | INTEGER | -5 to +5 offset |
| 8 | `option_type` | TEXT | CE/PE |
| 9 | `tsym` | TEXT | Trading symbol |
| 10 | `ltp` | DOUBLE | Broker LTP |
| 11 | `volume` | BIGINT | Broker volume |
| 12 | `oi` | BIGINT | Broker open interest |
| 13 | `iv` | DOUBLE | **Computed:** Black-Scholes IV |

---

## Table: `market_data_multitf` (v4) — 26 columns

Stored in `market_data_multitf.duckdb` (separate DB). Populated by v4 queue aggregator.

| # | Column | Type | Source |
|---|--------|------|--------|
| 1 | `timestamp` | TEXT PK | Last bar's timestamp in bucket |
| 2 | `index_name` | TEXT PK | NIFTY/SENSEX |
| 3 | `timeframe_min` | INTEGER PK | 5/15/30/60/240/1440 |
| 4 | `open` | FLOAT | First bar open |
| 5 | `high` | FLOAT | Max bar high |
| 6 | `low` | FLOAT | Min bar low |
| 7 | `close` | FLOAT | Last bar close |
| 8 | `volume` | FLOAT | Sum of volumes |
| 9 | `sma20` | FLOAT | SMA(20) — gap-capable |
| 10 | `sma50` | FLOAT | SMA(50) |
| 11 | `sma200` | FLOAT | SMA(200) |
| 12 | `rsi` | FLOAT | RSI(14) Wilder |
| 13 | `atr` | FLOAT | ATR(14) with gaps |
| 14 | `macd` | FLOAT | MACD line (12/26) |
| 15 | `macd_signal` | FLOAT | Signal line (9) |
| 16 | `macd_histogram` | FLOAT | Histogram |
| 17 | `adx` | FLOAT | ADX with +DI/-DI |
| 18 | `di_plus` | FLOAT | +DI |
| 19 | `di_minus` | FLOAT | -DI |
| 20 | `bb_upper` | FLOAT | Bollinger upper (20,2) |
| 21 | `bb_middle` | FLOAT | Bollinger middle |
| 22 | `bb_lower` | FLOAT | Bollinger lower |
| 23 | `obv` | FLOAT | On-Balance Volume |
| 24 | `cmf` | FLOAT | Chaikin Money Flow(20) |
| 25 | `cci` | FLOAT | CCI(20) |
| 26 | `st_consensus` | TEXT | SuperTrend BULLISH/BEARISH |

**Primary Key:** `(timestamp, index_name, timeframe_min)`

---

## Prerequisites

- **ta-lib** — required for ADX, RSI, ATR, EMA, BB in v3 market_data. Not installed = those columns stay NULL.
- **Redis** — required for v4 queue aggregator (reads from `v3_ohlcv_queue`).
- **Shoonya API** — broker for spot, futures, VIX, option chain.
- **yfinance** — fallback for prev_day_high/low.

## Quick Health Check

```bash
# Latest row from market_data
python3 -c "
import duckdb
db = duckdb.connect('python-trader/varaha/data/varaha_data.duckdb', read_only=True)
row = db.execute(\"SELECT timestamp, spot, india_vix, adx, rsi, iv_rank, agg_delta, agg_theta, pcr_total, sentiment, session_phase FROM market_data ORDER BY id DESC LIMIT 1\").fetchone()
for col, val in zip(['ts', 'spot', 'vix', 'adx', 'rsi', 'iv_rank', 'agg_delta', 'agg_theta', 'pcr', 'sentiment', 'phase'], row):
    print(f'{col}: {val}')
"

# Total rows captured today
python3 -c "
import duckdb
db = duckdb.connect('python-trader/varaha/data/varaha_data.duckdb', read_only=True)
print(db.execute(\"SELECT COUNT(*) FROM market_data WHERE date >= CURRENT_DATE\").fetchone()[0], 'rows today')
print(db.execute(\"SELECT COUNT(*) FROM option_snapshots WHERE date >= CURRENT_DATE\").fetchone()[0], 'option snapshots today')
"
```
