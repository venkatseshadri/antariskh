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
