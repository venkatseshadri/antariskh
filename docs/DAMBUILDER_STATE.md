# DAMBUILDER — Live State & Continuity Handoff

**Updated:** 2026-06-11 ~08:35 IST · **Read this first if continuing the build (Claude post-compaction OR DeepSeek cold start).**
Single source of truth for *where DAMBUILDER is*. Companion: `DATA_CAPTURE_REFACTOR_PLAN.md`
(the why + architecture + §7 reviewer analysis). Update THIS file at the end of every work
iteration — that is the continuity protocol; progress lives in git + this doc, never in any
agent's context.

## 0. Operating protocol (why this doc exists)
- Every iteration: code → test → **git commit** → update this doc. An agent dying mid-task
  loses at most one uncommitted step.
- Tasks in §4 are written DeepSeek-implementable: exact files, exact acceptance command.
  Claude (or any reviewer) validates against the acceptance line, never against memory.
- Board (user) gates anything touching live capture or readers. Shadow-only work is pre-approved.

## 1. What DAMBUILDER is (one paragraph)
Capture refactor: ONE truth store (Penguin `capture_{index}.sqlite`: 1-min bars + option
LTP), ONE derive pass (multi-TF enricher fills all indicator columns in
`market_data_multitf` in the SAME SQLite — no DuckDB writers anywhere), readers repointed
behind a flag, v4 per-index DuckDB aggregator then retired (the lock class dies). Research
reads the same SQLite via DuckDB ATTACH / nightly parquet; LLM indicator research requires
outcome tables + out-of-sample discipline (SHERPA method). Full rationale + Board Q&A:
`DATA_CAPTURE_REFACTOR_PLAN.md` §1-7.

## 2. STATUS (2026-06-11)
| Step | What | State |
|---|---|---|
| A0 | Core enricher (`enrichers/multitf_enricher.py` --backfill), parity-of-math with v4 aggregator (8/8) | ✅ done earlier (commit `f86a72e`) |
| A1 | `--live` mode: subscribe `bars:{inst}:{tf}` ×6, idempotent per-TF day re-enrich, heartbeat `multitf_enricher:{inst}:heartbeat` | ✅ built + hermetic test PASS (`tests/test_multitf_live.py`) — commit `19c3e7d` |
| A2 | Shadow deploy kit: `deploy/multitf-enricher-{nifty,sensex}.{service,timer}` + `deploy/install_multitf_enricher.sh` (refuses during session) + `enrichers/multitf_parity_check.py` | ✅ built — **NOT installed** |
| A3 | Install shadow units (post-close) + first shadow session + parity report | ⏳ NEXT — install after 15:35 IST, parity after close |
| B | Recompute-from-raw + drift diff + heal pre-06-09 low=0 history | ⬜ |
| C | Reader migration: 8 `query_*` fns in `tools/entry_tools.py` (3 backends → 1 SQLite), flag-gated | ⬜ |
| D | Research surface: nightly parquet + outcome tables (decision_trace, trade_outcomes — schema in plan §7.5) | ⬜ |
| E | Retire v4 aggregator + DuckDBs + EMA-state updater (after 5 clean parallel sessions) | ⬜ |

**Board answers locked 2026-06-11** (plan §7.7): parallel-build ✓; wide-table-per-TF ✓;
Greeks = separate batch layer (NOT per-bar in enricher); traffic_light keeps Redis for now,
migrates LAST; heal history by recompute+interpolation; enums strict / floats tol 0.5;
parquet-only research MVP.

## 3. Verified commands (rerun anytime)
```bash
cd /home/trading_ceo/antariksh
python3 tests/test_multitf_live.py                      # hermetic live-mode gate (PASS)
python3 enrichers/multitf_enricher.py --instrument NIFTY --backfill 2026-06-10   # backfill mode
# after a shadow session:
python3 enrichers/multitf_parity_check.py --date <YYYY-MM-DD> --instrument NIFTY
# install (REFUSES during market hours):
bash deploy/install_multitf_enricher.sh
```

## 4. TASK QUEUE (DeepSeek-implementable; do top-down)

### T1 — Install shadow units + first parity report (HUMAN/ops step, gated post-close)
Run `bash deploy/install_multitf_enricher.sh` after 15:35 IST. Next session, after close:
run the parity check for both instruments; paste output into §5 below.
**Accept:** parity output exists for 1 full session; no `WRITE FAIL` lines in
`logs/multitf_enricher_*.log`; enricher heartbeat fresh during session (redis key).

### T2 — data_health invariant for the new enricher (code)
File: `brahmand/data_health.py`. Add to `check_porcupine()` (or a new `check_dambuilder()`
wired into `run_all`): during market hours, redis `multitf_enricher:{NIFTY,SENSEX}:heartbeat`
must be < 10 min old once T1 units are live; WARN if missing/stale.
**Accept:** `python3 data_health.py` off-hours prints nothing new; with a stale fake
heartbeat key + market hours mocked, prints the warning. Commit to brahmand.

### T3 — Phase B recompute-from-raw (code)
New: `antariksh/enrichers/multitf_recompute.py`. Input: `market_data` 1-min bars for a
date range; re-aggregate to 6 TFs (same bucket math as consumer); for low<=0 bars
interpolate low := min(open, close, prev_low) and mark count; then call the SAME
`compute_row_indicators` and DIFF against stored `market_data_multitf` (write nothing
unless `--heal` passed). Thresholds: enums exact, floats |Δ|≤0.5.
**Accept:** `python3 enrichers/multitf_recompute.py --instrument NIFTY --date 2026-06-10`
prints per-TF per-column PASS/DRIFT and exits 0 on a clean post-06-09 day. `--heal`
rewrites rows and a re-run is clean.

### T4 — Phase C reader migration, flag-gated (code, NO default flip)
File: `antariksh/tools/entry_tools.py`. Env flag `MULTITF_SOURCE=sqlite|duckdb`
(default duckdb). When sqlite: `query_trend/momentum/volatility/volume/macro` read
`market_data_multitf` from the capture SQLite (same shapes out). traffic_light stays
Redis. options/flow stay on their current source until the Greeks batch layer exists.
**Accept:** with `MULTITF_SOURCE=sqlite` on a shadow-enriched day, each migrated
`query_*` returns the same signal fields as duckdb mode (write
`antariksh/tests/test_multitf_source_flag.py` asserting shape + st_consensus equality
on a fixture day). Default behavior unchanged (flag unset == duckdb).

### T5 — Phase D outcome tables MVP (code)
Schema from plan §7.5 (`decision_trace`, `trade_outcomes`) created in the capture SQLite;
brahmand `e2e_chain.py` writes one decision_trace row per gate decision (source, conf,
vix); `position_manager` writes trade_outcomes on close (reuse the trade dict it already
books). Nightly parquet export script `antariksh/research/export_parquet.py`
(per plan §7.5 D2 Option A layout).
**Accept:** one kickoff in sandbox (`BRAHMAND_SANDBOX`) inserts a decision_trace row;
seeded lifecycle close inserts trade_outcomes; export produces parquet readable by pandas.

### T6 — Phase E retirement (HUMAN-gated, last)
After 5 clean parallel sessions + T4 flipped by Board: stop/disable v4 aggregator units
+ supervisor cron, archive `.duckdb` files, grep-guard test that no live-path file
imports the v4 DuckDB paths.
**Accept:** grep-guard test green; one full session healthy on SQLite-only.

## 5. Shadow-session parity log (append results here)
*(empty — first shadow session pending T1)*

## 6. Don'ts (carry from cutover doc + plan)
- No capture changes / installs / reader flips during a live session (09:00–15:35 IST).
- Never add a DuckDB writer. DuckDB = read-only research engine.
- traffic_light Redis path migrates LAST (proven; latency-sensitive).
- A green unit test ≠ session-proven: every step needs one real shadow session before the
  next step trusts it.
