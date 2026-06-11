# PORCUPINE — Live State & Continuity Handoff

**Updated:** 2026-06-05 ~21:30 IST · **By:** Claude · **Read this first if continuing the build (incl. DeepSeek cold start).**
This is the single source of truth for *where PORCUPINE is*. Companion docs:
`E2E_SIM_HARNESS_DESIGN.md` (architecture), `E2E_SIM_HARNESS_BUILD_SPEC.md` (full spec),
`PORCUPINE_SCENARIO_CATALOGUE.md` (the bug-catching backlog).

---

## 1. What PORCUPINE is (one paragraph)
An offline end-to-end test harness. It boots a **fully isolated stack** (test Redis on **6380**, all
files under a **`SIM_ROOT`** sandbox) and drives the **real production pipeline** (feed→consumer→enricher
→kickoff/CrewAI→…) with a **mock feed** that replays real recorded data. Purpose: catch bugs before
09:15 Monday instead of firefighting live. **The harness is worth only the bugs it catches.**

## 2. STATUS — what is built & working (2026-06-05)
| Phase | What | State |
|-------|------|-------|
| P0 | Isolation foundation (`sim_env`, leak guard, redis/path redirection) | ✅ built, **4/4 gate passing** |
| P1 | Mock feed (replay from capture DB) → real consumer → sandbox DB | ✅ verified (375 bars flowed) |
| P2 | + real enricher (concurrent two-writer) | ✅ verified, **0 lock crashes** |
| P3 | + real CrewAI kickoff against sandbox enriched data | ✅ **agents ran** (regime agent produced real decision) |
| P4 | Orchestrator `run_scenario.py` + scenario automation | ✅ built |
| P5 | Synthetic fault driver (`mock_feed --fault`) | ✅ built 2026-06-09 (6 fault classes, 11/11 unit tests) |
| P6 | Lifecycle in sim (order→monitor→exit) | ✅ built 2026-06-09 — `run_scenario lifecycle` drives REAL `position_manager.run_bridge()` hermetically; deterministic SL_HIT closes a seeded paper trade, books to trade_history (no LLM, no broker, 0 prod leak). |
| P6b | All lifecycle EXIT branches | ✅ 2026-06-10 — `lifecycle`(SL), `tp_hit`, `eod`, `floor`, `morph` (LLM-stub). Caught bug #5 (CLOSE_ALL phantom ₹0). |
| P7 | **Path stack** — time-evolving scenarios | ✅ 2026-06-10 — `option_pricer` (toy spot→LTP, 6/6) + `path_driver` (multi-cycle run_bridge over a scripted spot path, re-marks each step) + `path_scenarios` (DATA + `expect` assertion-DSL). `path:ramp_then_fade` (theta→fade→EOD) & `path:spike_breaches_floor` both PASS. |
| P8 | **Fault→assertion binding** | ✅ 2026-06-10 — `run_scenario fault:<class>` replays a real day with `mock_feed --fault` through the real pipeline + asserts the class invariant. `fault:zero`(A1) & `fault:dup`(A4) PASS; caught bug #6 (consumer had no zero-OHLC guard). `fault:outlier` (A8) RED = open finding (no outlier clamp — Board call). |

**ENGINE STATUS: 14/14 milestones — DEVELOPMENT COMPLETE (2026-06-10).** PORCUPINE is the testing *engine*; the scenario *library* is project MONGOOSE. The path scenarios + lifecycle specs currently in `sim/` are MONGOOSE seed rows that will migrate; the engine (sim_env, mock_feed, option_pricer, path_driver, run_scenario, the `expect` DSL) stays.

**Honest engine gap (deferred):** H1–H3 (process-level resilience: silent producer death, OOM, cron-env) need a systemd/heartbeat sim, not data replay — a separate phase, not part of the data-replay engine.

## 3. Files built (all under `antariksh/sim/`)
| File | Purpose |
|------|---------|
| `sim/sim_env.py` | **Core.** `sim_active/ sim_root/ redis_kwargs/ capture_path/ log_dir/ assert_sandboxed`. Single isolation contract. Prod-safe: no-op when `SIM_MODE` unset. |
| `sim/mock_feed.py` | Replay driver. Reads `market_data`+`option_prices` from a source capture sqlite, LPUSHes `feed:{INST}` + HSETs option hash into test Redis in exact prod key shape. Refuses to run unless `SIM_MODE=1`. |
| `sim/start_test_redis.sh` | `start|stop <SIM_ROOT> [port]` — isolated redis-server (own dir, no persistence). |
| `sim/tests/test_isolation.py` | Phase-0 gate (4 tests): prod defaults unchanged, SIM redirects, leak guard raises, SIM_MODE-without-ROOT raises. |

## 4. Production code changed today (REVIEW THESE — they affect live)
| File | Change | Why |
|------|--------|-----|
| `antariksh/config/sqlite_schema.py` | `get_sqlite_capture_path`→`sim_env.capture_path`; `assert_sandboxed()` in `open_capture_db`; `autocommit` param; busy_timeout 30s | sim redirection + enricher lock fix |
| `antariksh/enrichers/instrument_enricher.py` | `write_enriched` batched via `flush_enriched_batch` (BEGIN IMMEDIATE + retry, **no row drop**); redis via `redis_kwargs()` | **lock-fix (deployed live 10:18, NRestarts=0)** + sim |
| `antariksh/consumers/instrument_consumer.py` | db_path via `get_sqlite_capture_path`; redis via `redis_kwargs()` | sim |
| `antariksh/feed.py` | redis via `redis_kwargs()` | sim |
| `brahmand/market_data.py` | `get_latest_market_snapshot`: **LEFT JOIN → INNER JOIN** on enriched | **PROD BUG FIX** — latest-raw-join returned NULL atm → "No market data" |

> ⚠️ `brahmand/market_data.py` is a **live entry-path reader**. The INNER-JOIN fix is correct (snapshot
> must have enriched fields) but should be watched on Monday's first live kickoffs.

## 5. Bugs PORCUPINE caught today
1. **Latest-raw-join NULL atm** → "No market data" even with enriched data. **FIXED** (market_data.py LEFT→INNER JOIN). Independent of the lock fix; would intermittently block live entries.
2. **★ `low=0` on 87.5% of ALL captured bars (1423/1626)** — systemic capture corruption. Root cause: `feed.bucket_minute` folded lp-less (ltp=0) ticks into the bar; `low=min(0,·)` locks at 0 forever (high=max recovers, low never does). **Poisoned every low-based indicator (ATR/SuperTrend/pivots/Bollinger).** Same class as the option ltp=0 clobber bug but in the *index bar path*. **FIXED** (`feed.py` drops ltp≤0 ticks) + regression test `sim/tests/test_feed_bar_integrity.py` (2/2). Note: only fixes FUTURE capture; the 1423 historical bars stay corrupted.
3. **Entry agents → `deterministic_fallback`** (`avg_super_trend=0.00`, `session=""`). **FIXED 2026-06-09** (Board-approved "fix it the correct way"). Two LIVE causes — note the original 3(b) diagnosis below was WRONG on specifics: **(a) session_phase** — `enrichers/lib/advanced.py::compute_session_metrics` used `datetime.now()`, so a backfill at 21:30 stamped every bar "late". **FIXED**: now takes a `bar_ts` arg and derives the phase from the bar's own timestamp (falls back to `now()` only when `bar_ts` is None). **(b) st_consensus** — the original note ("`market_data_multitf.st_consensus` 100% NULL; aggregator never writes indicators in the replay") measured the **WRONG table**: the consumer's *SQLite* `market_data_multitf` is **OHLCV-only by design**. The trend agent actually reads `st_consensus` from the **v4 per-index DuckDB** (`market_data_multitf_<index>.duckdb`), which the v4 queue aggregator populated but **HARDCODED to `"NEUTRAL"`** (a `# Legacy` stub; SuperTrend was never wired) — so `trend.timeframes[*].st_consensus → "NEUTRAL" → avg≈0`. **FIXED**: `data_capture_v4_queue_aggregator` now computes a proper ATR-band SuperTrend (takes effect at the aggregator's next start; affects only the LLM-down fallback path). Guards: `sim/tests/test_supertrend_consensus.py` (7/7), `test_fallback_inputs.py` (4/4), corrected F2 assertion in `run_scenario.py`. Marker `sim/.bug3_fixed` created.
4. **VIX null → regime defaults to "enter".** The *auto-enter on null VIX* logic in `brahmand/unicorn_debate._deterministic_fallback`. **FIXED 2026-06-09**: collapsed `vix is None or (isinstance(vix,(int,float)) and vix<20)` → `isinstance(vix,(int,float)) and vix<20` in both gate branches, so an unknown VIX fails closed. Guard: `sim/tests/test_vix_null_guard.py` (6/6, flipped to assert fail-closed). Marker `sim/.bug4_fixed` created.

5. **★ EOD/floor `CLOSE_ALL` books P&L at entry fill, not live LTP (phantom ₹0).** Caught 2026-06-10 by the new `floor` lifecycle scenario: a deep-underwater position (mtm −2925) squared off by the cumulative-P&L floor reported `final_pnl=0.0`. Root cause: `position_manager.execute_action`'s `CLOSE_ALL` branch called `_square_off` **without** first marking legs to live LTP — `_square_off` books from `leg['ltp']` else the entry fill, so unmarked legs book 0. The SL/TP path was unaffected (it marks via `_close_side`→`_mark_legs_to_ltp`), but EOD and floor reach `CLOSE_ALL` straight from `run_bridge` with unmarked legs. **FIXED**: `CLOSE_ALL` now `_mark_legs_to_ltp(legs)` before square-off (`brahmand/position_manager.py`). Floor now books the real −45.0 loss. Guard: `floor` scenario asserts `pnl<0`.

6. **★ Consumer had no zero/invalid-OHLC guard (corrupt bars via the queue reach raw).** Caught 2026-06-10 by `fault:zero`: injecting zero-price bars (`mock_feed --fault zero`) put 5 bad bars into raw `market_data`. Root cause: the lp-less/zero filter lived **only in `feed.py`** (the WS tick path); `instrument_consumer` treats each queued bar as pre-aggregated and INSERTs it directly with **no validation**, so any zero/invalid bar arriving via the queue reaches raw and poisons low-based indicators (same class as #2, sibling write path). **FIXED**: `consumers/instrument_consumer.py` now skips bars with any OHLC ≤ 0 before the `market_data` INSERT (checkpoint still advances on later good bars). `fault:zero` now PASS. ⚠️ live capture-code change — Board review.

   **Open finding (NOT fixed — Board call):** `fault:outlier` (A8) stays RED — a 10× fat-finger spike survives into raw (no outlier clamp). A clamp is heuristic (could reject real gap moves), so it's deferred to the Board, not fixed reflexively.

### Lifecycle scenarios — the §7 "remaining lifecycle extensions" are now DONE (2026-06-10)
`sim/lifecycle_driver.py` is now mode-driven (`LIFECYCLE_MODE` env) and seeds the sandbox option_prices itself (via the real `get_sqlite_capture_path`, the same SQLite `_check_sl_tp` reads). `run_scenario.run_lifecycle(scenario)` sets `SIM_NOW` (so the real-wall-clock EOD branch can't spuriously fire in non-EOD modes) and runs per-mode assertions. Five scenarios, all PASS, each pinning a **distinct** `run_bridge` exit branch:
- `lifecycle` (SL_HIT) — deterministic SL square-off, pnl<0
- `tp_hit` (G3) — deterministic TP square-off, pnl>0
- `eod` (G2) — `SIM_NOW≥15:30`, no SL/TP → hard EOD `CLOSE_ALL`, reason MARKET_CLOSE
- `floor` (P6) — mtm≤FLOOR, no SL → cumulative-P&L `CLOSE_ALL`, reason FLOOR, pnl<0
- `morph` (F5/G4) — cached NEUTRAL→BULLISH assessment (the deterministic **LLM stub**) → discretionary morph closes the CE side (legs 4→2), trade stays ACTIVE

> Note (not fixed — existing behaviour, out of scope): TP exits are classified `SL_HIT` in `trade_history.close_reason` (`_norm_close_reason` collapses `SL_TP_EXIT`→`SL_HIT`); the `tp_hit` scenario discriminates on `pnl>0`, not the reason label.

Orchestrator `sim/run_scenario.py` now built (P4): `python3 -m sim.run_scenario happy_path --date 2026-06-05` → per-assertion PASS/FAIL + exit code. A1 (zero/invalid OHLC in raw) correctly goes RED until clean data flows.

## 6. HOW TO RUN (verified commands)

### Phase-0 gate
```bash
cd /home/trading_ceo/antariksh && python3 -m sim.tests.test_isolation   # expect 4/4
```

### Full replay + enrich + CrewAI kickoff (the P1→P3 chain)
```bash
cd /home/trading_ceo/antariksh
SIM_ROOT=/home/trading_ceo/antariksh/sim/run_$(date +%s); mkdir -p "$SIM_ROOT"/{data,logs,redis}
PROD_DB=/home/trading_ceo/python-trader/varaha/data/capture_nifty.sqlite; TODAY=$(date +%F)
bash sim/start_test_redis.sh start "$SIM_ROOT" 6380
export SIM_MODE=1 SIM_ROOT="$SIM_ROOT" SIM_REDIS_PORT=6380

# 1) replay real bars → consumer → sandbox market_data
timeout 30 python3 -m consumers.instrument_consumer --instrument NIFTY > "$SIM_ROOT/logs/consumer.out" 2>&1 &
python3 -m sim.mock_feed --instrument NIFTY --source-db "$PROD_DB" --date "$TODAY" --interval 0.02
wait
# 2) backfill-enrich the whole day (full coverage)
timeout 60 python3 -m enrichers.instrument_enricher --instrument NIFTY --backfill "$TODAY:$TODAY" > "$SIM_ROOT/logs/enr.out" 2>&1
sqlite3 "$SIM_ROOT/data/capture_nifty.sqlite" "SELECT 'raw',COUNT(*) FROM market_data UNION ALL SELECT 'enr',COUNT(*) FROM market_data_enriched;"
bash sim/start_test_redis.sh stop "$SIM_ROOT" 6380

# 3) real CrewAI kickoff against the sandbox (needs brahmand/.env DEEPSEEK_API_KEY)
cd /home/trading_ceo/brahmand
BRAHMAND_SANDBOX="$SIM_ROOT/data" python3 -c "from kickoff import run_entry_pipeline; print(run_entry_pipeline('15:25'))"
```
Key env contract: `SIM_MODE=1`, `SIM_ROOT=<dir>`, `SIM_REDIS_PORT=6380` (antariksh side);
`BRAHMAND_SANDBOX=$SIM_ROOT/data` (brahmand readers, already honored by `market_data.py`).

## 7. NEXT (priority order) — for whoever continues
1. ~~`sim/run_scenario.py` orchestrator~~ ✅ done (P4)
2. ~~Scenario A1 (zero-tick filter)~~ ✅ done — `feed.py` drops lp-less ticks; regression in `sim/tests/test_feed_bar_integrity.py`; A1 assertion live in `run_scenario.py` (stays RED on historical capture, will go GREEN with clean re-capture).
3. ~~Root-cause F2~~ ✅ root-caused + guarded (2026-06-08) — see §5 bug #3. Live-code fix still pending (cannot be done from the sim/ sandbox): (i) `enrichers/lib/advanced.py::compute_session_metrics` must take the bar's timestamp instead of `datetime.now()`, and (ii) the multi-TF aggregator must actually populate indicator columns in `market_data_multitf` (currently 100% NULL in the replay path). Once both land in live code, the F2 scenario assertions in `run_scenario.py` will flip GREEN and the `sim/.bug3_fixed` marker can be created.
4. ~~Bug #4 (VIX-null auto-enter guard)~~ **harness-side done (2026-06-08)**. Regression `sim/tests/test_vix_null_guard.py` (6/6) probes `brahmand/unicorn_debate._deterministic_fallback` directly and pins the bug shape: `vix=None` currently returns `go=True` (same as `vix=15`); `vix=25` blocks. Two new assertions in `sim/run_scenario.py` stay RED until the live fix lands: **(a)** `india_vix populated in sandbox (E4)` — today 351/351 NULL because no broker/option-chain stub is wired into the replay path; **(b)** `vix=None gate fails-closed (E4)` — calls the live gate with `vix=None` and asserts `go is False`. Live-code fix (cannot be done from sim/): collapse `vix is None or vix<20` → `isinstance(vix,(int,float)) and vix<20` in both `NOT_UP` and `NOT_DOWN` branches of `_deterministic_fallback`. Marker `sim/.bug4_fixed` deliberately NOT created — bug remains open until live-code fix lands.
5. ~~Lifecycle G1–G3 + ledger D1~~ ✅ **done 2026-06-09.** `python3 -m sim.run_scenario lifecycle` seeds the sandbox option_prices sqlite so a sold CE leg has breached SL, then `sim/lifecycle_driver.py` (runs cwd=brahmand under `SIM_MODE`+`BRAHMAND_SANDBOX`) seeds a paper trade via the real `trade_execution_db` and calls the real `position_manager.run_bridge()`. The deterministic SL/TP path fires (skips the LLM), squares off the side (paper fill, no broker), closes in both sandbox stores. Asserts ACTIVE→closed + booked to `trade_history`. **3/3 PASS; 0 SIM rows leaked into the live trade DB.** Remaining lifecycle extensions (catalogue, not blocking COMPLETE): EOD square-off branch (needs a clock injection — `run_bridge` gates on real `now_str()>=15:30`), TP_HIT and FLOOR/CLOSE_ALL paths, and an `--llm stub` for the morph/shift branch.
5c. ~~Wire v4 aggregator into the sim (bug #3b E2E)~~ ✅ **done 2026-06-09.** `python3 -m sim.run_scenario multitf_trend` feeds real 1-min bars → test Redis queue → the REAL `data_capture_v4_queue_aggregator` → a SANDBOX per-index DuckDB, and asserts `st_consensus` is **computed, not hardcoded NEUTRAL**. The aggregator is now sandbox-aware (`sim_env.redis_kwargs()`/`log_dir()`, import-guarded, prod-safe). Verified 375 bars → 118 directional bars; hermetic (live v4 DuckDB + EMA state untouched). Driver: `sim/v4_aggregator_driver.py`.
6. ~~Synthetic fault driver~~ ✅ **done 2026-06-09.** `mock_feed --fault {none,gap,freeze,dup,zero,outlier} [--fault-pct]` via pure, unit-testable `_inject_faults` (reproduces A2/A3/A5/A8 classes). Regression: `sim/tests/test_fault_driver.py` (11/11). Still TODO: wire fault scenarios into `run_scenario.py` with expected-failure assertions (catalogue work).
7. Work the `PORCUPINE_SCENARIO_CATALOGUE.md` backlog top-down.

> **2026-06-09 milestone-design fix (unblocks the autobuilder):** `porcupine_status.py`
> bug#3/#4 milestones now track the *harness guard* (the regression test files the builder
> CAN produce) instead of `.bugN_fixed` live-fix markers. Live-code-fix status moved to a
> separate **non-gating** `live_fixes()` informational line. Before this, the builder could
> never reach COMPLETE (markers need human-gated live-code edits it's forbidden to make) →
> it paused. Harness milestones now **8/9**; only the lifecycle scenario remains.
> Also: previously-uncommitted bootstrap code (`sim_env.py`, `porcupine_autobuild.sh`,
> `start_test_redis.sh`, P0/feed tests) is now tracked; `.gitignore` keeps run-sandbox
> sqlites/locks out of git. Commit `ee24e9e`.

## 7b. Live monitoring (tagged onto existing health cron — 2026-06-08)
PORCUPINE invariants now ride the existing `data_health` cron (`*/5 9-15 * * 1-5
brahmand/cron/run_data_health.sh`) via `check_porcupine()` in `brahmand/data_health.py` — added to
`run_all()`, so a regression alerts through the same Telegram path. No new cron. Guards: low<=0
regression (feed lp-less filter), enricher heartbeat freshness (lock-fix crash-loop), enriched-vs-raw lag.
Also fixed a latent bug in `check_penguin` (`WHERE date=` → `date(timestamp)=`; it had been erroring
every run → penguin DB-freshness was NOT actually being monitored). `sim/porcupine_tick.sh` exists for a
heavier manual full-regression run (not wired to cron).

## 7c. Gated autonomous builder (2026-06-08) — see `PORCUPINE_AUTOBUILDER.md`
`sim/porcupine_autobuild.sh` (cron `*/30 7-23 * * *`) finishes remaining items unattended: free status
gate → `claude -p` only while work remains → self-terminates at COMPLETE; stuck-guard pauses after 4
no-progress attempts; Bash allow-listed to python3/git, scoped to `sim/`+`tests/`. **Currently PAUSED**
(`sim/.autobuild_paused`) — it guarded bugs #3/#4 (new tests + F2/E4 assertions, commit `891e835`) but
their milestones need `.bugN_fixed` markers that only a human-approved live fix creates, so the signature
never advanced. Genuinely-remaining buildable items: synthetic fault driver, lifecycle scenario. Resume:
`rm sim/.autobuild_paused`. Full detail + the milestone-redefinition fix in `PORCUPINE_AUTOBUILDER.md`.

## 8. Operating rule (do not break)
Every future production incident: **write the failing scenario in the harness first**, then fix, then it
stays as a permanent regression. The catalogue only grows. Isolation guard (`assert_sandboxed`) is
mandatory — a sim run must NEVER write outside `SIM_ROOT` or touch redis 6379.
