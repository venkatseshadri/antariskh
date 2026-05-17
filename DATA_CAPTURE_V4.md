# Antariksh Data Capture v4 — Multi-TF Aggregator

**Date:** 2026-05-17 | **DB:** `python-trader/varaha/data/market_data_multitf.duckdb`

## Pipeline Architecture

```
┌────────────────────────────────┐
│  v3.1 1-min capture (2 instances) │
│  NIFTY → varaha_data.duckdb     │
│  SENSEX → varaha_data_sensex.duckdb │
│  ↓ pushes OHLCV to:              │
│  Redis queue: v3_ohlcv_queue     │
│  Log file: v3_ohlcv_{INDEX}.log  │
└────────────┬───────────────────┘
             │
     ┌───────▼───────────┐
     │  v4 Queue Aggregator │
     │  Reads Redis (primary) │
     │  Falls back to log file │
     │  ↓ aggregates to:       │
     │  5, 15, 30, 60, 240, 1440 min │
     │  ↓ writes to:           │
     │  market_data_multitf.duckdb │
     └──────────────────────┘
```

Both are started by the master wrapper: `run_data_capture_with_v4.sh`, which:
- Launches 3 processes (v3.1 NIFTY, v3.1 SENSEX, v4 aggregator)
- Monitors child health every 30s, auto-restarts if any die
- Shuts down after market close (15:31)
- Runs during market hours only (Mon–Fri, 9:15–15:30)

## Capture Scripts

| Script | Location | DB Target | Status |
|--------|----------|-----------|--------|
| `data_capture_v3.1_duckdb.py` | `python-trader/varaha/` | `varaha_data.duckdb` | Active — 1-min raw + Redis push |
| `data_capture_v4_queue_aggregator.py` | `antariksh/` | `market_data_multitf.duckdb` | Active — reads Redis, aggregates |
| `run_data_capture_with_v4.sh` | `python-trader/varaha/` | — | Master wrapper (starts both) |

## Data Flow: v3.1 → Redis → v4

1. **v3.1** captures 1-min OHLCV bars every 60s
2. Each bar is pushed to **Redis list** `v3_ohlcv_queue` and appended to **log file** `v3_ohlcv_{INDEX}.log`
3. **v4** reads bars from Redis (primary) or log file (fallback if queue has < 5 bars)
4. v4 aggregates raw 1-min bars into 6 timeframes
5. v4 writes to separate DuckDB (`market_data_multitf.duckdb`) — no locking conflict with v3

## Table: `market_data_multitf` (26 columns)

**Primary Key:** `(timestamp, index_name, timeframe_min)`

### OHLCV (6 cols)

| # | Column | Type | Description |
|---|--------|------|-------------|
| 1 | `timestamp` | TEXT PK | Last bar's timestamp in bucket (ISO 8601) |
| 2 | `index_name` | TEXT PK | NIFTY / SENSEX |
| 3 | `timeframe_min` | INTEGER PK | 5 / 15 / 30 / 60 / 240 / 1440 |
| 4 | `open` | FLOAT | First bar open in bucket |
| 5 | `high` | FLOAT | Max bar high in bucket |
| 6 | `low` | FLOAT | Min bar low in bucket |
| 7 | `close` | FLOAT | Last bar close in bucket |
| 8 | `volume` | FLOAT | Sum of volumes |

### Batch 1: Gap-Capable Indicators (8 cols)

Computed from all accumulated 1-min bars. Handle overnight gaps naturally.

| # | Column | Type | Description |
|---|--------|------|-------------|
| 9 | `sma20` | FLOAT | SMA(20) on close |
| 10 | `sma50` | FLOAT | SMA(50) on close |
| 11 | `sma200` | FLOAT | SMA(200) on close |
| 12 | `rsi` | FLOAT | RSI(14) Wilder, custom implementation |
| 13 | `atr` | FLOAT | ATR(14) with gap-aware True Range |
| 14 | `macd` | FLOAT | MACD line (12/26 EMA) |
| 15 | `macd_signal` | FLOAT | Signal line (9-period EMA of MACD) |
| 16 | `macd_histogram` | FLOAT | MACD − Signal |

### Batch 2: Gap-Sensitive Indicators (9 cols)

Computed from recent bars only. Return `NULL` if insufficient bars for lookback.

| # | Column | Type | Description |
|---|--------|------|-------------|
| 17 | `adx` | FLOAT | ADX with +DI/−DI (14-period) |
| 18 | `di_plus` | FLOAT | +DI (positive directional indicator) |
| 19 | `di_minus` | FLOAT | −DI (negative directional indicator) |
| 20 | `bb_upper` | FLOAT | Bollinger Upper (20, 2σ) |
| 21 | `bb_middle` | FLOAT | Bollinger Middle = SMA(20) |
| 22 | `bb_lower` | FLOAT | Bollinger Lower (20, 2σ) |
| 23 | `obv` | FLOAT | On-Balance Volume (cumulative) |
| 24 | `cmf` | FLOAT | Chaikin Money Flow (20-period) |
| 25 | `cci` | FLOAT | Commodity Channel Index (20) |

### Legacy (1 col)

| # | Column | Type | Description |
|---|--------|------|-------------|
| 26 | `st_consensus` | TEXT | Placeholder — always "NEUTRAL" |

## Indicator Implementation Notes

- **All indicators are custom Python implementations** — no ta-lib dependency for v4
- **Upsert behavior:** INSERT with ON CONFLICT (timestamp, index_name, timeframe_min) DO UPDATE — each 60s run updates the same bucket rows with latest close/H/L
- **Rolling windows:** Each timeframe bucket accumulates bars throughout the hour/day. The same bucket row is updated every 60s as new 1-min bars arrive.
- **MACD signal line** is a simplified approximation (equaled to MACD line) — properly requires tracking MACD history across runs

## Live Data Snapshot

Data captured May 15, 2026 — single trading day.

| Timeframe | Bar Count |
|-----------|-----------|
| 5 min | 82 |
| 15 min | 29 |
| 30 min | 17 |
| 60 min | 9 |
| 240 min | 4 |
| 1440 (daily) | 2 |
| **Total** | **143** |

### Last 10 Bars (May 15, 2026 15:15–15:25)

| Index | TF | Timestamp | Open | High | Low | Close | ADX | RSI |
|-------|----|-----------|------|------|-----|-------|-----|-----|
| NIFTY | 5 | 15:25:35 | 23651.9 | 23651.9 | 23628.1 | 23628.1 | — | 50.0 |
| SENSEX | 5 | 15:25:00 | 75305.3 | 75305.3 | 75197.2 | 75203.3 | — | 50.0 |
| SENSEX | 5 | 15:20:35 | 75209.0 | 75245.6 | 75209.0 | 75231.2 | — | 50.0 |
| NIFTY | 5 | 15:20:00 | 23632.3 | 23640.2 | 23628.8 | 23637.2 | — | 50.0 |
| NIFTY | 5/15/30 | 15:15:00 | varies | 23651.9 | 23618.6 | 23644.1 | 8.18 | 45.9 |
| SENSEX | 5/15/30 | 15:15:00 | varies | 75305.3 | 75147.6 | 75229.6 | 22.07 | 39.0 |

> Many indicators show NaN/NULL because a single trading day provides insufficient bars for lookback periods (SMA200 needs 200 bars, SMA50 needs 50, etc.). Values fill in as more trading days accumulate.

### Last 10 Rows — v4 `market_data_multitf`

```
2026-05-15T15:25:35 | NIFTY  |    5min | O=23651.9  H=23651.9  L=23628.1  C=23628.1  | RSI=50.0 ADX=-
2026-05-15T15:25:00 | SENSEX |    5min | O=75305.3  H=75305.3  L=75197.2  C=75203.3  | RSI=50.0 ADX=-
2026-05-15T15:20:35 | SENSEX |    5min | O=75209.0  H=75245.6  L=75209.0  C=75231.2  | RSI=50.0 ADX=-
2026-05-15T15:20:00 | NIFTY  |    5min | O=23632.3  H=23640.2  L=23628.8  C=23637.2  | RSI=50.0 ADX=-
2026-05-15T15:15:00 | NIFTY  |    5min | O=23635.0  H=23644.1  L=23618.6  C=23644.1  | RSI=45.9 ADX=8.2
2026-05-15T15:15:00 | NIFTY  |   15min | O=23651.9  H=23651.9  L=23618.6  C=23644.1  | RSI=45.9 ADX=8.2
2026-05-15T15:15:00 | NIFTY  |   30min | O=23651.9  H=23651.9  L=23618.6  C=23644.1  | RSI=45.9 ADX=8.2
2026-05-15T15:15:00 | SENSEX |    5min | O=75195.3  H=75229.6  L=75147.6  C=75229.6  | RSI=39.0 ADX=22.1
2026-05-15T15:15:00 | SENSEX |   15min | O=75305.3  H=75305.3  L=75147.6  C=75229.6  | RSI=39.0 ADX=22.1
2026-05-15T15:15:00 | SENSEX |   30min | O=75305.3  H=75305.3  L=75147.6  C=75229.6  | RSI=39.0 ADX=22.1
```

### Last 10 Rows — v3.1 `market_data` (104 cols, subset shown)

```
2026-05-15T15:29:35 | spot=23651.9 | vix=18.80 | ADX=-    | RSI=-  | IV_rank=93.9 | delta=+0.144 | theta=-171.9 | PCR=1.087 | bearish | late | gap=0.18%
2026-05-15T15:29:00 | spot=23650.5 | vix=18.76 | ADX=-    | RSI=-  | IV_rank=92.6 | delta=+0.135 | theta=-171.5 | PCR=1.086 | bearish | late | gap=0.18%
2026-05-15T15:28:35 | spot=23648.5 | vix=18.76 | ADX=-    | RSI=-  | IV_rank=92.6 | delta=+0.123 | theta=-171.5 | PCR=1.086 | bearish | late | gap=0.18%
2026-05-15T15:28:00 | spot=23646.6 | vix=18.78 | ADX=-    | RSI=-  | IV_rank=93.3 | delta=+0.111 | theta=-171.6 | PCR=1.086 | bearish | late | gap=0.18%
2026-05-15T15:27:31 | spot=23646.9 | vix=18.81 | ADX=-    | RSI=-  | IV_rank=94.2 | delta=+0.113 | theta=-172.0 | PCR=1.086 | bearish | late | gap=0.18%
2026-05-15T15:27:00 | spot=23644.2 | vix=18.86 | ADX=-    | RSI=-  | IV_rank=95.8 | delta=+0.095 | theta=-172.4 | PCR=1.086 | bearish | late | gap=0.18%
2026-05-15T15:26:35 | spot=23642.9 | vix=18.90 | ADX=-    | RSI=-  | IV_rank=97.1 | delta=+0.087 | theta=-172.8 | PCR=1.086 | bearish | late | gap=0.18%
2026-05-15T15:26:00 | spot=23628.0 | vix=18.90 | ADX=-    | RSI=-  | IV_rank=97.1 | delta=-0.007 | theta=-172.4 | PCR=1.086 | bearish | late | gap=0.18%
2026-05-15T15:25:35 | spot=23628.1 | vix=18.89 | ADX=-    | RSI=-  | IV_rank=96.8 | delta=-0.006 | theta=-172.3 | PCR=1.086 | bearish | late | gap=0.18%
2026-05-15T15:25:00 | spot=23632.9 | vix=18.90 | ADX=-    | RSI=-  | IV_rank=97.1 | delta=+0.024 | theta=-172.6 | PCR=1.086 | bearish | late | gap=0.18%
```

> v3.1: 3,039 rows total, 104 columns. ADX/RSI/ATR NULL because ta-lib not installed. Other indicators (IV_rank, Greeks, PCR, sentiment, SMC levels) populate fine.

## Prerequisites

| Component | Required | Status |
|-----------|----------|--------|
| **Redis** | Yes — queue between v3.1 and v4 | Running on localhost:6379 |
| **DuckDB** | Yes — stores aggregated bars | `market_data_multitf.duckdb` |
| **Python 3** | Yes — both scripts | ✅ |
| **ta-lib** | No — v4 uses custom Python indicators | Not needed |
| **Shoonya API** | No (v4 reads from Redis, not broker) | N/A |
| **v3.1 running** | Yes — feeds data into Redis | Co-managed by wrapper |

## Cron / Scheduling

The master wrapper is intended to be scheduled via cron at market open:

```bash
# Market open (9:14 AM) — starts all 3 processes, runs until 15:31
14 9 * * 1-5 /home/trading_ceo/python-trader/varaha/run_data_capture_with_v4.sh >> /tmp/data_capture_master.log 2>&1
```

The wrapper self-terminates after market close. No separate cron for exit is needed.

## Quick Health Check

```bash
# Last 10 aggregated bars across all timeframes
python3 -c "
import duckdb
db = duckdb.connect('python-trader/varaha/data/market_data_multitf.duckdb', read_only=True)
for row in db.execute(\"SELECT timestamp, index_name, timeframe_min, close, rsi, adx FROM market_data_multitf ORDER BY timestamp DESC LIMIT 10\").fetchall():
    print(f'{row[0][:19]} | {row[1]:6s} | {row[2]:4d}min | close={row[3]:.1f} | RSI={row[4]} | ADX={row[5]}')
"

# Row count per timeframe
python3 -c "
import duckdb
db = duckdb.connect('python-trader/varaha/data/market_data_multitf.duckdb', read_only=True)
for row in db.execute(\"SELECT timeframe_min, COUNT(*) FROM market_data_multitf GROUP BY timeframe_min ORDER BY timeframe_min\").fetchall():
    print(f'{row[0]:4d}min: {row[1]} bars')
print('Total:', db.execute('SELECT COUNT(*) FROM market_data_multitf').fetchone()[0])
"

# Check if v3.1 is feeding v4 (Redis queue depth)
redis-cli LLEN v3_ohlcv_queue
```

## Relationship to Sandwich

Sandwich POC explicitly **excludes v4 multi-TF data** (per Sandwich spec). Sandwich uses only v3.1 1-min data from `varaha_data.duckdb`. The v4 aggregator is infrastructure for future multi-timeframe strategies.
