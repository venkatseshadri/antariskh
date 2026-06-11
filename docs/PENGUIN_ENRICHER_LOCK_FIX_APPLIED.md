# PENGUIN Enricher Lock Fix — As Applied (Interim)

**Date:** 2026-06-05 · **Author:** Claude (advisory/validation) · **Status:** Code applied, compiles clean, **NOT yet deployed** (service restart pending board approval)
**Companion:** `PENGUIN_ENRICHER_LOCK_FIX.md` (original proposal + reviewer response)
**Classification:** INTERIM stopgap. The permanent fix is the single-writer merge — see *Strategic* below.

---

## 1. Problem (recap)

`enricher-nifty` crash-loops every ~30s on `sqlite3.OperationalError: database is locked`
(`instrument_enricher.py` `write_enriched`). Consumer + enricher both write the same file
`python-trader/varaha/data/capture_nifty.sqlite`. Result chain:

```
enricher crashes → 0 rows in market_data_enriched today (frozen at prior close)
  → BRAHMAND kickoff LEFT JOIN gets NULL atm_strike
  → e2e_chain.py:115 guard "if not spot or not atm" fires
  → "⚠ No market data — skipping" every 5-min cycle → zero trades
```

**Raw capture was always healthy** (`market_data` fresh to the minute). Only the *enriched* stage was down.

## 2. Root cause of the crash (why WAL + busy_timeout=5000 didn't help)

The old `write_enriched` used Python sqlite3's **implicit deferred transaction** (`INSERT` then
`commit()`). A deferred txn takes the write lock late, at upgrade/commit, where SQLite can return
`SQLITE_BUSY` **without honoring `busy_timeout`** (snapshot conflict, not a wait-able busy). So the
enricher errored out instantly instead of waiting, and systemd restarted it into the same wall.

## 3. The fix

Acquire the write lock **up front** with `BEGIN IMMEDIATE` (where `busy_timeout` *is* honored), wrap
the writes in one explicit transaction, retry with backoff, and **never drop rows** on failure.
Batched so the lock is taken once per flush rather than once per statement.

### Files changed

| File | Change |
|------|--------|
| `config/sqlite_schema.py` | `open_capture_db(instrument, autocommit=False)` — new param sets `isolation_level=None` so callers can run manual `BEGIN IMMEDIATE`/`COMMIT`. **Consumer unchanged** (still implicit-txn). |
| `enrichers/instrument_enricher.py` | `import sqlite3`; buffer state in `__init__`; `write_enriched` now accumulates; new `flush_enriched_batch()` (BEGIN IMMEDIATE + 5-retry backoff, keeps buffer on failure); `run_live`/`run_backfill` open with `autocommit=True`, flush on trigger, drain buffer on exit. |

### Flush policy (`_flush_interval=5.0s`, `_flush_batch_size=5`)

- **Live mode:** bars arrive 60s apart, so the 5s-elapsed trigger fires on **every bar** → enriched
  is written per-bar, never lagging the 5-min kickoff. (Solves reviewer MUST-FIX 3 without
  minute-boundary special-casing.)
- **Backfill mode:** bars replay in milliseconds → the size trigger batches 5 at a time → 5× fewer
  lock acquisitions during the heavy path, which is where batching actually earns its keep.

### Reviewer MUST-FIX items — all incorporated

1. **autocommit for BEGIN IMMEDIATE** — `open_capture_db(..., autocommit=True)`; without it, manual
   `BEGIN` raises "transaction within a transaction".
2. **No silent data loss** — final-retry branch logs and `raise`s with the **buffer intact**;
   systemd restart re-enriches from the `last_enriched_bar_ts` checkpoint. (Original proposal
   `clear()`d the buffer = invisible gaps → intermittent NULL atm_strike.)
3. **Batch latency ≤ kickoff cadence** — `_flush_interval` set to 5s (not 30s); per-bar flush live.

A `self.conn.rollback()` (guarded) precedes each retry so a partial txn can't wedge the next attempt.

## 4. Verification (run after deploy)

```bash
# 1. enriched table tracks raw within ~1 min, today's date present
sqlite3 /home/trading_ceo/python-trader/varaha/data/capture_nifty.sqlite \
  "SELECT 'raw', COUNT(*), MAX(timestamp) FROM market_data WHERE date(timestamp)=date('now')
   UNION ALL
   SELECT 'enriched', COUNT(*), MAX(timestamp) FROM market_data_enriched WHERE date(timestamp)=date('now');"

# 2. atm_strike is non-NULL on the latest enriched row
sqlite3 .../capture_nifty.sqlite \
  "SELECT timestamp, spot, atm_strike, adx, india_vix FROM market_data_enriched ORDER BY timestamp DESC LIMIT 1;"

# 3. restart counter stops climbing (no more crash loop)
systemctl show enricher-nifty.service -p NRestarts

# 4. BRAHMAND kickoff stops rejecting
tail -f /home/trading_ceo/brahmand/logs/kickoff_$(date +%Y%m%d).log   # expect a real decision, not "No market data"
```

**Acceptance:** 30-min run with zero `OperationalError` reaching process exit; `enriched` MAX(timestamp)
within 1 min of `raw`; non-NULL `atm_strike`; enriched-row count == raw-bar count over the session.
Occasional `"Enriched flush locked; retry"` WARN is fine — that's the fix *working* (waiting, not dying).

## 5. Deploy

```bash
sudo systemctl restart enricher-nifty enricher-sensex enricher-mcx
```
(MCX has no enrichment columns consumed by kickoff, but restart for consistency.)

## 6. Rollback

`git checkout antariksh/config/sqlite_schema.py antariksh/enrichers/instrument_enricher.py`
then restart the services. The change is isolated to the enricher write path + one optional
connection flag; the consumer and schema are untouched.

## 7. Strategic — this is a stopgap, delete it when the merge lands

This is the **third** lock-management patch (DuckDB lock → SQLite busy_timeout → this batch+retry).
It makes the lock *survivable*, not *impossible* — two processes still share the file, so under
extreme contention the retries could still exhaust and bounce the service (cleanly, without data
loss now). The permanent fix is the **single-writer merge**: fold the enricher into the consumer so
one process/one connection owns `capture_nifty.sqlite` and contention is structurally impossible.
Confirmed low-risk — the broker block is already best-effort and `atm_strike` is pure arithmetic
(`enrich_bar:459`, no broker). Validate the merge over the weekend via offline replay of the live
slice captured to `brahmand/data/recordings/nifty_20260605_095614/`. **When the merge ships, revert
this file's changes and retire `enricher-nifty.service`.**
