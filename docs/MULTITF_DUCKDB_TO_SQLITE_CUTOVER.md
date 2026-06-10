# Multi-TF: DuckDB → SQLite consolidation (retire the lock class)

**Why:** the v4 aggregator writes `market_data_multitf_<index>.duckdb`; DuckDB allows
only ONE writer *process*, so a transient lock crashes it and NIFTY trend goes stale
(2026-06-10). SQLite serializes writers (BEGIN IMMEDIATE + busy_timeout + retry) and
the Penguin capture is already on SQLite. Moving multi-TF indicators into the SQLite
`market_data_multitf` table (which already has the columns) eliminates the lock class
and the two-table split. See [[position_research_cache_architecture]] context only;
core memory: `multitf_duckdb_to_sqlite_consolidation`.

## State
- ✅ **Interim safety shipped** (`f1fcd4ca`): `_connect_write` retry + supervisor cron
  so today's DuckDB path self-heals. Disaster risk mitigated NOW.
- ✅ **Core built + verified** (`f86a72e`): `enrichers/multitf_enricher.py` fills SQLite
  indicator columns reusing the aggregator's exact compute (parity test 8/8). `--backfill`
  works; the lock-prone DuckDB is NOT yet removed.

## Cutover sequence (deliberate — NOT during a live session, NOT at session-tail)
1. **Live mode for the enricher** — subscribe to `bars:{inst}:{tf}` (already published by
   the consumer) and `enrich_day`-style write on each closed bar. Run as a Penguin systemd
   unit (`multitf-enricher@.service`) alongside the 1-min enricher. *(Code: add the live
   loop in `multitf_enricher.py`, mirror `instrument_enricher`.)*
2. **Shadow-run a full session** — enricher writes SQLite indicators while the DuckDB
   aggregator still runs. Compare SQLite `market_data_multitf.st_consensus` vs the DuckDB
   per-index file across the day (a parity cron / PORCUPINE assertion). Must match.
3. **Repoint the reader** — `tools/entry_tools.query_trend` + `agents/entry/toolkit` read
   `market_data_multitf` from the **capture SQLite** instead of `market_data_multitf_<index>.duckdb`.
   Gate behind a flag (`MULTITF_SOURCE=sqlite|duckdb`) so it's a reversible flip.
4. **Retire DuckDB** — stop `data_capture_v4_queue_aggregator`, remove its supervisor cron,
   archive the `.duckdb` files. Delete the aggregator after a clean week.

## Safety invariants
- SQLite remains single *file*, many writers serialized — never the DuckDB
  single-writer-process trap.
- Reader flip is flag-gated and reversible; DuckDB stays warm until SQLite is proven live.
- Every step verified in PORCUPINE before the live flip.

## Don't
- Don't flip the reader or stop the aggregator mid-market or at the tail of a long session.
- Don't add a second DuckDB writer "to be safe" — that's the exact trap we're removing.
