# PENGUIN Enricher — SQLite Lock Fix

**Problem**: `instrument_enricher.py` crashes every ~50s with `sqlite3.OperationalError: database is locked`. Consumer writes to `market_data`/`market_data_multitf`/`option_prices` every 1–2s; enricher writes `market_data_enriched` once per minute. Despite WAL + 5000ms busy_timeout, write windows collide.

**Impact**: 0 enriched rows today → `atm_strike` NULL → BRAHMAND `"No market data — skipping"` → zero trades.

---

## Fix: Batch-flush enriched writes

**Current (broken)**:
```
pub/sub bar → enrich_bar() → write_enriched(row) → INSERT → commit  💥 1 commit/bar
```

**Proposed**:
```
pub/sub bar → enrich_bar() → append to buffer[]
                              ↓ (every 5 bars OR 30s)
                    flush_batch() → BEGIN IMMEDIATE → INSERT all → COMMIT  ✅ 1 commit/batch
```

5× reduction in write contention. Combined with retry logic in flush_batch, the enricher stops crashing.

---

## Implementation

### 1. `Enricher.__init__` — add buffer + flush tracking

```python
def __init__(self, instrument: str, conn, broker: Optional[BrokerSession] = None):
    # ... existing init ...
    self._write_buffer: List[Dict] = []
    self._last_flush = time.time()
    self._flush_interval = 30.0       # seconds
    self._flush_batch_size = 5         # bars
```

### 2. `Enricher.write_enriched` — accumulate, don't write

```python
def write_enriched(self, row: Dict):
    self._write_buffer.append(row)

def flush_enriched_batch(self):
    if not self._write_buffer:
        return
    max_retries = 5
    for attempt in range(max_retries):
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            placeholders = ", ".join(["?"] * len(ENRICHED_COLUMNS))
            cols = ", ".join(ENRICHED_COLUMNS)
            for row in self._write_buffer:
                values = [row.get(c) for c in ENRICHED_COLUMNS]
                self.conn.execute(
                    f"INSERT OR REPLACE INTO market_data_enriched ({cols}) VALUES ({placeholders})",
                    values,
                )
            last_bar = self._write_buffer[-1]
            self.conn.execute(
                "INSERT OR REPLACE INTO consumer_state (key, value) VALUES (?, ?)",
                (f"last_enriched_bar_ts:{self.instrument}", last_bar["timestamp"]),
            )
            self.conn.commit()
            self._write_buffer.clear()
            self._last_flush = time.time()
            return
        except sqlite3.OperationalError:
            if attempt < max_retries - 1:
                backoff = 0.5 * (2 ** attempt)
                log.warning(f"Flush locked, retry {attempt+1}/{max_retries} in {backoff:.1f}s")
                time.sleep(backoff)
            else:
                log.error(f"Flush failed after {max_retries} retries — dropping {len(self._write_buffer)} rows")
                self._write_buffer.clear()
                self._last_flush = time.time()
                raise
```

### 3. `run_live` — wire flush trigger

In `run_live()`, after `enricher.enrich_bar(bar)`:

```python
# AFTER: row = enricher.enrich_bar(bar)   (line 680)
if row:
    enricher.write_enriched(row)           # accumulate, NO DB write
    bar_count += 1
    last_ts = row["timestamp"]

    # INSERT: flush trigger after Redis bridge push (line 705-708 area)
    should_flush = (
        len(enricher._write_buffer) >= enricher._flush_batch_size
        or (time.time() - enricher._last_flush) >= enricher._flush_interval
    )
    if should_flush:
        enricher.flush_enriched_batch()
```

Also in `finally:`:

```python
finally:
    enricher.flush_enriched_batch()  # drain buffer
    conn.close()
    log.info(f"Enricher stopped — {bar_count} bars enriched")
```

---

## Verification

1. Restart enricher services: `sudo systemctl restart enricher-nifty enricher-sensex enricher-mcx`
2. After 2–3 bars (~3 min): check `market_data_enriched` has today's rows:
   ```bash
   sqlite3 data/capture_nifty.sqlite "SELECT COUNT(*), MAX(timestamp) FROM market_data_enriched"
   ```
3. Check BRAHMAND kickoff log for "ENTERED" instead of "No market data — skipping"
4. Monitor enricher logs for "Flush locked" warnings — should be 0 under normal operation

---

## Reviewer Response — Claude (validation role) · 2026-06-05

**Verdict: APPROVED AS INTERIM ONLY, with 3 mandatory corrections. Not the permanent fix.**
One core idea here is correct and probably *is* the crash cure; the batching is secondary;
and three concrete defects must be fixed before this ships. Root cause (two processes writing
one file) is NOT removed by this — see "Strategic" at the end.

### Why the crash actually happens (confirms the right primitive)
Current `write_enriched` uses Python sqlite3's *implicit deferred* transaction (plain `INSERT`
then `commit()`). A deferred txn acquires the write lock late, at upgrade/commit — and in that
path SQLite can return `SQLITE_BUSY` **without honoring `busy_timeout`** (snapshot conflict, not
a wait-able busy). That is the most likely reason WAL + `busy_timeout=5000` is already set yet it
still dies within 5s. `BEGIN IMMEDIATE` takes the write lock **up front**, where `busy_timeout`
applies → the writer waits instead of crashing. **This single change is the real fix. The
batching is optional contention-reduction, not the cure.**

### MUST-FIX 1 — `BEGIN IMMEDIATE` needs autocommit mode
As written, `self.conn.execute("BEGIN IMMEDIATE")` on a default connection (isolation_level `""`)
collides with the module's auto-`BEGIN` and can raise
`OperationalError: cannot start a transaction within a transaction`. In `open_capture_db()` set:
```python
conn.isolation_level = None      # autocommit; we manage BEGIN/COMMIT manually
conn.execute("PRAGMA busy_timeout=5000")   # keep — now it is actually honored
```
Verify this does not break the **consumer's** commit pattern (it relies on implicit txns today —
either set autocommit there too and wrap its cycle in `BEGIN IMMEDIATE`/`COMMIT`, or keep the
consumer as-is and only change the enricher connection).

### MUST-FIX 2 — never silently drop rows
The failure branch does `self._write_buffer.clear()` **then** `raise` → it loses up to 5 enriched
rows AND crashes. Silent gaps in `market_data_enriched` cause intermittent NULL `atm_strike` →
kickoff erratically rejects/half-fires. **Do not clear on failure.** Keep the buffer, let it
raise (systemd restarts; the buffer is rebuilt from pub/sub + warmup), OR re-queue:
```python
else:
    log.error(f"Flush failed after {max_retries} retries — keeping {len(self._write_buffer)} rows for retry")
    raise        # do NOT clear(); restart will re-enrich from last_enriched_bar_ts checkpoint
```

### MUST-FIX 3 — batch latency must not outlive the kickoff cadence
Flush "every 5 bars OR 30s" lets an enriched row sit ~5 min in the buffer; kickoff runs every
5 min and can read a stale/missing row — a milder rerun of today's bug. Required:
- drop `_flush_interval` to **≤ 5s** (not 30s), and
- **force a flush at the top of every minute boundary** before kickoff can read, e.g.
  `if row["timestamp"].endswith(":00"): enricher.flush_enriched_batch()`.
At 1 bar/min the batch buys almost nothing anyway — correctness > the 5× commit reduction.

### Acceptance criteria (add to Verification)
- 30 min continuous run, **zero** `OperationalError` escaping to process exit (restart counter stops climbing).
- `market_data_enriched` MAX(timestamp) tracks `market_data` MAX(timestamp) within **1 minute**.
- A kickoff cycle logs a real regime/decision (non-NULL `atm_strike`), not "No market data".
- Zero rows dropped: enriched row count over the session == raw bar count (minus warmup).

### Strategic — this is a stopgap, log it as such
This is the **third** lock-management patch (DuckDB lock → SQLite busy_timeout → batch+retry).
It lowers collision probability but two writers still share `capture_nifty.sqlite`; under open-bell
volatility / more strikes / a slow broker cycle it will recur. The permanent fix is the
**single-writer merge**: fold the enricher into the consumer so one process/one connection owns the
file — contention becomes structurally impossible. Confirmed low-risk because the broker block is
already best-effort (`enrich_bar` guards on `self.broker.connected`) and `atm_strike` is pure
arithmetic (`enrich_bar:459`, no broker). Track the merge separately; ship this only to unblock
near-term, and delete it when the merge lands.
