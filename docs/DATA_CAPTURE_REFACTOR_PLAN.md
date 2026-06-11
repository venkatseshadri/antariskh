# Project DAMBUILDER — Data Capture Refactor Plan

**Date:** 2026-06-11 · **Status:** Proposed (Board to approve) · **Owner:** capture/enrichment layer
**Relation to SHERPA:** SHERPA validates strategy edge; DAMBUILDER fixes the data layer.
They converge at Layer 3 — SHERPA's replay engine becomes the recompute/verification tool.

---

## 1. Where the pain came from (history, honestly)

Design intent was sound: capture everything across 7 indicator families so LLM research
can discover what works. Execution accreted SIX derived stores around one truth stream:

| Store | Why it exists | Bug class it spawned |
|---|---|---|
| varaha_data.duckdb (dead) | original capture | dead readers after Penguin cutover |
| capture_{index}.sqlite | Penguin raw + enriched 1-min | low=0 poisoning (stored, still wrong historically) |
| v4 per-index DuckDB multitf | multi-TF indicators | cross-process locks, RuntimeMaxSec bounces, st_consensus hardcoded NEUTRAL |
| SQLite market_data_multitf | OHLCV-only sibling | two-table confusion (the 06-09 gotcha) |
| EMA state JSON files | trend scorer input | fourth independent indicator computer |
| Redis (queue + hash) | live fan-out | fine — but also used as a de-facto store by entry_tools (TL shape bug 06-11) |

**Root disease: indicator computation scattered across 4 code paths with no shared
contract; derived data stored without a recompute path, so rot is permanent.**

## 2. Principles

1. **Only bars are ground truth.** Ticks → 1-min bars + option LTP snapshots. Everything else is derived = cache.
2. **A stored derived value must be reproducible by one command** (`recompute --from-raw`). No recompute path → don't store it.
3. **One writer per SQLite file** (WAL + busy_timeout — already proven by the enricher lock fix). DuckDB is a READ-ONLY query engine for research (ATTACH sqlite / parquet), never a second write path.
4. **Every stored indicator family ships with a data_health invariant** (PORCUPINE style). Verification surface, not bytes, is the cost of storage.
5. **Research needs outcomes joined to indicators** — decision trace + trade results keyed to the same timestamps. Indicator dumps alone are unqueryable for "what works".

## 3. Target architecture

```
Layer 0  TRUTH    WS → feed.py → 1-min bars + option LTP → capture_{index}.sqlite
                  (Penguin, exists — keep; Redis stays for live fan-out only)

Layer 1  DERIVE   ONE enricher process per index:
                  - on each 1-min bar close: update in-memory TF aggregates
                    (5/15/30/60/240/1440 — resample in process, NO Redis hop,
                    NO second DB)
                  - compute all 7 families per closed TF bar
                  - write to indicators_{tf} tables in the SAME capture sqlite
                  - single writer; batched BEGIN IMMEDIATE (existing lock fix)

Layer 2  CONSUME  entry system: SELECT latest row per TF (one query per decision)
                  LLM research: DuckDB ATTACH (read-only) or nightly parquet
                  export to research/ + outcome tables (decision trace, trades)

Layer 3  VERIFY   sherpa-replay recompute-from-raw + diff vs stored (drift alarm)
                  per-family invariant checks riding the data_health cron
```

**Retired:** v4 queue aggregator + per-index DuckDBs (the lock class dies with it),
EMA state JSON files, the multitf Redis hop, dual-write research capture.
**Kept:** feed/consumer, capture sqlite, Redis live fan-out, data_health.

## 4. Phases

| Phase | Work | Exit gate |
|---|---|---|
| **A** | Finish the staged multi-TF SQLite consolidation (core built+verified 2026-06-10) → becomes Layer 1. All 7 families × 6 TFs computed in the single enricher. | parallel-run: SQLite values vs v4 DuckDB agree (where v4 isn't known-buggy) for 3 sessions |
| **B** | `recompute --from-raw` (adapt SHERPA replay engine) + drift-diff test. Heal pre-06-09 poisoned history by recomputation. | recompute(raw) == stored for a clean day; poisoned days re-derived |
| **C** | Migrate entry_tools reads: EMA files → SQLite trend columns; candle colors/completion → precomputed columns (kills the 4th on-the-fly computer; fixes the bug-class behind the TL shape + now()-coupling issues). One regression test per family. | canonical_strategy decisions identical before/after on a replay day (SHERPA llm_down-style A/B) |
| **D** | Research surface: nightly parquet export + outcome tables (decision trace per point, trade results). LLM indicator research happens HERE, with SHERPA's train/validate discipline mandatory. | first honest "indicator X adds edge / doesn't" report produced from this surface |
| **E** | Retire v4 DuckDBs + aggregator units + EMA updater after 5 clean parallel sessions. | systemd units removed; readers grep-guarded (no v4 imports on live path) |

## 5. Explicit Board challenges (answered or open)

- **"Do we need all 7×6 stored?"** Only with Phase B in place (reproducibility makes
  storage safe) and one invariant per family. Otherwise compute-on-read beats
  stored-and-rotting. Recommendation: store them — bars/day are tiny — but B and the
  invariants are non-negotiable prerequisites.
- **Tick-level capture loss:** accepted for indicators. Option microstructure (slippage
  calibration, IV dynamics) may later want 1-sec option snapshots — out of scope; note
  the door.
- **SQLite scale:** 6 TFs × ~375 bars × 2 indices × wide rows/day = trivial. WAL handles
  many readers + one writer. Proven in production since the lock fix.
- **DuckDB's role shrinks to query engine.** If research later outgrows ATTACH,
  promote the parquet export, never a second writer.
- **SHERPA Phase 2b context:** the directional core has no edge — so indicator
  research (Phase D) is not decoration, it's the path to a core that does. But the
  research only means something against outcomes, out-of-sample.

## 6. Open for Board

1. Approve direction (Layers 0-3, retire list).
2. Phase A first or pause for SHERPA Phase 2c (iron-fly thesis test)? They don't
   conflict — A is capture-side, 2c runs on the replay engine.
3. Pre-06-09 poisoned history: heal by recompute (Phase B) or truncate and accept
   the shorter clean window?

---

## 7. Technical Implementation Analysis (Reviewer: Claude)

### 7.1 Current state mapping: what reads what

Before touching code, I traced every `query_*` function in `antariksh/tools/entry_tools.py` to understand the data source maze:

| Family | Function | Reads from | Also reads |
|---|---|---|---|
| trend | `query_trend` | v4 DuckDB (`market_data_multitf`) | v3.1 DuckDB for 1m EMA |
| momentum | `query_momentum` | v4 DuckDB | v3.1 for RSI |
| volatility | `query_volatility` | v4 DuckDB | v3.1 for BB/ATR |
| volume | `query_volume` | v4 DuckDB | — |
| options | `query_options` | v3.1 DuckDB (`option_snapshots`) | — |
| flow | `query_flow` | v3.1 DuckDB (`option_snapshots`) | — |
| macro | `query_macro` | v4 DuckDB + v3.1 DuckDB | — |
| traffic_light | `query_traffic_light` | **Redis** (v3_ohlcv_queue) | — |

**Eight source functions, three database backends (v4 DuckDB, v3.1 DuckDB, Redis).**
Target: all 8 → **one source** (Penguin SQLite `market_data_enriched` + `indicators_{tf}`).

---

### 7.2 Phase A — Detailed design decisions (need Board answer)

**A1. Enricher strategy: modify or parallel-build?**

The current enricher (`antariksh/data_capture_v4_queue_aggregator.py`) writes to the v4 DuckDB. It has known bugs:
- `st_consensus` hardcoded to "NEUTRAL" (the real ST calculation is elsewhere)
- Cross-process lock contention with entry pipeline readers
- `RuntimeMaxSec` bounces from systemd (process killed mid-write)

**Option 1: Refactor the existing enricher** to write to SQLite instead of DuckDB, and fix the ST bug in-place. Risk: we break the live capture mid-session during the refactor. Safer but slower.

**Option 2: Build a new enricher (`antariksh/penguin_enricher_v2.py`)** that runs alongside the old one. Both receive the same 1-min bars. The new one writes to SQLite `indicators_{tf}` tables. Old one continues writing to DuckDB. After 3 sessions of parallel-run agreement, flip the entry pipeline to read SQLite, then retire the old one. Risk: double computation during parallel-run, CPU/memory cost is trivial (~2ms per bar).

**My recommendation: Option 2 (parallel-build).** The old enricher keeps the live system running while the new one proves itself. The cost is negligible — the enricher is I/O bound on SQLite writes, not CPU bound.

**A2. SQLite schema for Layer 1 — one wide table per TF, or one table per family?**

The current `market_data_multitf` stores one row per TF bar with 26 columns (OHLCV + indicators mixed). The enriched table has ~100 columns. For the new design:

**Option A: One wide table per TF**
```sql
CREATE TABLE indicators_5m (
    timestamp TEXT PRIMARY KEY,
    index_name TEXT,
    -- OHLCV
    open REAL, high REAL, low REAL, close REAL, volume REAL,
    -- Trend
    sma20 REAL, sma50 REAL, sma200 REAL,
    ema5 REAL, ema20 REAL, ema50 REAL,
    st_consensus TEXT, adx REAL, di_plus REAL, di_minus REAL,
    -- Momentum
    rsi REAL, macd REAL, macd_signal REAL, macd_histogram REAL, cci REAL,
    -- Volatility
    atr REAL, bb_upper REAL, bb_middle REAL, bb_lower REAL,
    -- Volume
    obv REAL, cmf REAL, volume_ratio REAL,
    -- Options
    iv_current REAL, pcr_total REAL, pcr_atm REAL,
    max_pain INTEGER, call_oi_concentration REAL, put_oi_concentration REAL,
    -- Flow
    agg_delta REAL, agg_gamma REAL, agg_vega REAL, agg_theta REAL,
    -- Macro
    india_vix REAL, spot REAL, gap_pct REAL, session_phase TEXT,
    -- Computed
    candle_color TEXT, ema_position TEXT, sma_position TEXT
);
```
**Benefit:** One query per TF, no joins. Matches how the entry pipeline reads (by TF).
**Cost:** Schema duplication across 6 tables → 6× the column definitions.

**Option B: One table per family + one OHLCV table**
```sql
CREATE TABLE bars_5m (ts, index, open, high, low, close, volume);
CREATE TABLE trend_5m (ts, index, sma20, sma50, ..., st_consensus);
CREATE TABLE momentum_5m (ts, index, rsi, macd, ...);
```
**Benefit:** Clean separation. Families can be added/removed independently.
**Cost:** Entry pipeline needs up to 7 JOINs per TF. LLM Advocate/Skeptic needs separate queries.

**My recommendation: Option A (wide table per TF).** The entry pipeline only needs "latest bar per TF" — one SELECT, no joins. The LLM research path uses DuckDB ATTACH which handles 100-column wide tables fine. Schema duplication is a maintenance concern but SQLite migrations are simple (ALTER TABLE ADD COLUMN).

**A3. Tagging: which 7 families × which indicators go into each TF table?**

From the `unicorn_raw_query` and `entry_tools` code, here's the definitive list of indicators per family that the entry pipeline actually uses:

| Family | Must include | Nice to have |
|---|---|---|
| Trend | sma20, sma50, sma_position, candle, st_consensus, adx, di_plus, di_minus | sma200, ema5/20/50, ema_position |
| Momentum | rsi, macd, macd_signal, macd_histogram | cci, stoch_k, stoch_d |
| Volatility | atr, bb_upper, bb_middle, bb_lower | bb_width, bb_pct_b |
| Volume | obv, cmf | volume_ratio, volume_avg_5, volume_avg_20 |
| Options | iv_current, pcr_total, pcr_atm, max_pain, call_oi_concentration, put_oi_concentration | oi_skew, iv_rank |
| Flow | agg_delta, agg_gamma, agg_vega, agg_theta | wings_delta, body_delta |
| Macro | india_vix, spot, futures, prev_close, gap_pct, session_phase | intraday_high/low, open_to_current_pct, expiry fields |

Total: ~8-10 columns per TF from the enricher (just OHLCV + computed trends), plus the enriched columns that depend on existing `market_data_enriched` computation (IV, Greeks, OI).

**Key question:** Should the enricher also compute option Greeks (IV, delta, gamma, vega, theta from option_prices)? Currently these are computed in `market_data_enriched` by the Penguin feed consumer, not by the enricher. The enricher currently only does multi-TF OHLCV aggregation.

---

### 7.3 Phase B — Recompute engine design

**B1. Recompute input = 1-min bars from `market_data` table, or from raw tick SQLite?**

The 1-min bars are already in `capture_nifty.sqlite.market_data`. Recomputing multi-TF indicators from 1-min bars is straightforward:
```
1-min bars → resample to 5/15/30/60/240/1440 → compute indicators → compare with stored
```

**But:** the 1-min bars themselves might have been corrupted (low=0 bug). So we need to:
1. Identify which 1-min bars have `low=0` → mark as poisoned
2. Decide: skip those bars, or interpolate (use prev close as low)
3. Recompute multi-TF from cleaned 1-min bars

**Question:** Accept interpolation for poisoned 1-min bars (simpler, ~5 bars affected per day) or require a full tick replay for those minutes?

**B2. Drift alarm contract — what threshold triggers an alert?**

The recompute diff should produce:
```
indicators_5m:
  sma20:     max drift +0.02 → PASS
  st_consensus: 3 mismatches out of 375 → WARN
  rsi:       max drift +0.15 → PASS
```

Floating-point indicators (SMA, RSI) will have sub-cent drift due to bar alignment. Enum indicators (st_consensus, candle_color) should match exactly. What threshold:
- **Strict:** float indicators must match within 0.01, enums must match 100%
- **Relaxed:** float indicators within 0.5, enums ≥99% match

---

### 7.4 Phase C — Entry tools migration

**C1. The 7 `query_*` functions need to switch from DuckDB+Redis to SQLite.**

Current code path:
```python
# antariksh/tools/entry_tools.py
def query_trend(index):
    v4 = _open_db(_v4_db_path(index))      # → DuckDB
    v31 = _open_db(_v31_db_path(index))    # → DuckDB v3.1
    # query both, merge results
```

Target code path:
```python
def query_trend(index):
    db = _open_sqlite(_capture_path(index))  # → Penguin SQLite
    # query indicators_5m, indicators_15m, etc. (one table per TF)
```

**Migration strategy (safe):**
1. Add a config flag `USE_SQLITE_INDICATORS = False` in `entry_tools.py`
2. Write the new SQLite-based `query_*` functions
3. When `USE_SQLITE_INDICATORS = True`, use the new read path
4. After 3 days of parallel-run agreement, flip the default to True
5. After 5 days, delete the old DuckDB read paths

**C2. The `traffic_light` family reads from Redis (live 1-min bars).**

This is the trickiest migration. The traffic light scoring needs live 1-min candle data as bars close. Currently it goes through Redis because Redis has the latest bar before it's committed to SQLite. After migration:
- Option A: READ from SQLite (latest bar already committed by the time entry cron runs)
- Option B: Keep Redis for traffic_light only (it's fast and already correct)

**Question:** Is the 1-2 second latency between bar close → SQLite commit acceptable for traffic_light, or does Redis remain necessary for this family?

---

### 7.5 Phase D — Research surface

**D1. Outcome table schema — what needs to be captured for the "what works" analysis?**

For indicator research to produce meaningful edge analysis, we need:
```sql
CREATE TABLE decision_trace (
    timestamp TEXT,
    index_name TEXT,
    decision_id TEXT,        -- links NOT_UP + NOT_DOWN + outcome
    gate_type TEXT,          -- NOT_UP or NOT_DOWN
    decision_source TEXT,    -- "canonical", "unicorn_cache", "llm_debate"
    signal TEXT,             -- GO / NO-GO
    confidence REAL,
    regime_at_time TEXT,
    vix_at_time REAL
);

CREATE TABLE trade_outcomes (
    trade_id TEXT,
    entry_time TEXT,
    exit_time TEXT,
    strategy TEXT,
    wing_width INTEGER,
    entry_pnl REAL,
    final_pnl REAL,
    duration_mins INTEGER,
    close_reason TEXT,       -- SL_HIT, TP_HIT, EOD, FLOOR, MANUAL
    -- snapshot of indicators at entry:
    trend_at_entry JSON,
    momentum_at_entry JSON,
    volatility_at_entry JSON,
    options_at_entry JSON,
    flow_at_entry JSON
);
```

**D2. Parquet export granularity: one file per day per TF, or one file per day with partitions?**

- Option A: `research/nifty/2026-06-10/indicators_5m.parquet`, `indicators_15m.parquet`, etc.
- Option B: `research/nifty/2026-06-10.parquet` with `timeframe_min` partition column

Option B is simpler for pandas (one file per index per day) but larger files.

---

### 7.6 Risks and timing estimates

| Phase | Estimated effort | Key risk | Mitigation |
|---|---|---|---|
| A — Enricher + SQLite schema | 2-3 days | Getting st_consensus computation correct; the current code has it hardcoded NEUTRAL. Need to port the real ST logic from the old v3.1 code. | Parallel-run with v4; diff output for first session before trusting |
| B — Recompute + drift-diff | 1-2 days | 1-min bar low=0 poisoning may cause false positives in drift detection | Add a "known_poisoned" flag to the recompute; skip or interpolate |
| C — Entry tools migration | 1-2 days | Redis → SQLite latency for traffic_light family | Keep Redis for traffic_light if latency proves critical |
| D — Research surface | 1 day | Outcome tables need data that doesn't exist yet (decision traces are not logged today) | Backfill from existing kickoff logs; move forward with logging going forward |
| E — Retire old stores | 0.5 day | Something might depend on the old DuckDB paths that we missed | grep-guard as specified; one week of parallel-run first |

**Total estimated: 6-9 days**

---

### 7.7 Questions for Board (needs Claude review)

1. **Enricher strategy:** Modify the existing enricher in-place (risk: live disruption) or build a new one alongside (safe, double compute)?
   - *My answer: New enricher alongside (Option 2).*

2. **SQLite schema for indicators:** One wide table per TF (single SELECT, no joins) or one table per family per TF (clean separation, needs JOINs)?
   - *My answer: Wide table per TF (Option A).*

3. **Indicator computation in enricher:** Should the enricher compute ALL 7 families (including option Greeks from `option_prices`), or only the OHLCV-derived ones (trend, momentum, volatility, volume) and leave options/flow/macro to the existing `market_data_enriched` computation?
   - *Need Board answer: the options/flow families depend on full option chain data (`option_prices` table), not just price bars. Computing Greeks in the enricher means loading 241K option snapshots per bar — expensive. These might be better as a separate enriched layer that writes to the same SQLite.*

4. **Traffic light source for Phase C:** Can traffic_light scoring switch to SQLite (latest bar commit latency = 1-2s), or does it need to keep Redis for sub-second freshness?
   - *My hunch: 1-2s is fine for a 5-min cron cycle. But the existing Redis code is simple and reliable — low risk to keep it.*

5. **Poisoned history:** Heal pre-June-9 by recompute with interpolation, or truncate and accept shorter clean window?
   - *My answer: Recompute with interpolation for low=0 bars. It's ~5 bars per day affected, we can interpolate from adjacent bars. This preserves the full 189-day daily bar history.*

6. **Drift threshold for Phase B verification:** Strict (float drift < 0.01, enums 100%) or relaxed (float < 0.5, enums ≥99%)?
   - *My answer: Strict for enums, relaxed for floats. ST consensus needs exact match; SMA/RSI will have floating-point drift from rounding.*

7. **Research surface MVP:** Nightly parquet export only (start analyzing in notebooks) or full DuckDB with pre-built views?
   - *My answer: Nightly parquet. Build the views later when someone actually does the research.*

8. **Option Greeks computation:** Move into the enricher (compute per closed bar) or keep as a separate post-processing step on the enriched table?
   - *My hunch: Separate step. Greeks need the full option chain — that's a batch job, not a per-bar computation. Keep them in `market_data_enriched` but write to the same `indicators_{tf}` tables.*
