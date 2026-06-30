# TICKET: Penguin stale option premiums (frozen 06-12 → 06-30)

**Status:** FIXED 2026-06-30 (live)
**Severity:** Critical — every option-premium reader served ~19-day-old prices + expired strikes.
**Files:** `consumers/instrument_consumer.py` (fix), `feed.py` (diagnostics)

## Symptom
`option_prices` in `capture_nifty.sqlite` / `capture_sensex.sqlite` frozen at:
- NIFTY max ts `2026-06-12T15:29`, SENSEX `2026-06-12T14:37`
- Strikes topped out 23600 / 74700 vs live spot 23895 / 76627 (expired 16JUN/09JUN chains)

`market_data` (1-min bars) was fresh the whole time — only options were stale.

## Root cause
The 06-11 Redis purge (`37b7e24`, `a41700f`) moved option-LTP persistence into `feed.py`,
which now writes `option_prices` directly to SQLite each minute
(`_persist_bar_and_options`). It stopped publishing the
`feed:{inst}:options:ltp` hash and `:options:window` key.

But `instrument_consumer.py` was **not** updated. Its option block ran every loop
iteration (every ~5s, ungated by the now-empty bar queue) and did:

1. `DELETE FROM option_prices WHERE strike NOT IN (<window>)` — window key frozen at
   `[23000..23500]`, so it deleted feed.py's fresh ATM (~23950) rows.
2. `INSERT OR REPLACE` from the frozen `:options:ltp` hash (last written 06-11 11:53,
   the moment the `hset` was deleted) — restoring the stale 06-11/06-12 snapshot.

Net: feed.py wrote ~22/44 fresh rows each minute; the consumer wiped them within ~20s
and restored the 06-12 snapshot. Confirmed by live watch:
```
11:49:02 today=22  maxts=2026-06-30T11:48:00   ← feed.py wrote
11:49:22 today=0   maxts=2026-06-12T15:29:00   ← consumer wiped + restored
```

## Diagnosis trail (for next time)
- feed.py subscribes the current chain fine (log: `Option feed [NIFTY]: ATM=… expiry=2026-06-30`, ATM rebalancing).
- Added `OPTDIAG` line to `_persist_bar_and_options`: `total=22 priced=22 ticks=5886 lp_folds=2893`
  proved ticks arrive, LTP folds, all strikes priced → inserts DO run, no failure.
- Insert verified to land against the real schema in isolation.
- So rows were inserted then deleted → watched the live count across a bar boundary → caught the consumer.

## Fix
Removed the dead option block from `instrument_consumer.py`. feed.py is the **sole**
`option_prices` writer. Consumer no longer touches the table.

`feed.py` keeps a per-minute `OPTDIAG` health line (option tick/fold/priced counts) so
this silent failure mode is visible next time.

## Follow-ups (not blocking)
- `opt_count` in the consumer's "Bars: … Options: N" log line is now always 0 — cosmetic; drop it.
- Orphaned Redis keys `feed:{inst}:options:ltp` and `:options:window` are never written in
  prod now (only `sim/mock_feed.py` sets window). The old `tests/test_option_feed_publish.py`
  asserts the hash is published by feed.py — now stale; update or delete.
- Consumer's bar path also reads a Redis queue feed.py no longer fills — the whole consumer
  may be retire-able; out of scope here.
- Backfill: option_prices has a ~19-day hole (06-13 → 06-30 AM). Live capture resumes now;
  historical gap unrecoverable from this path.
