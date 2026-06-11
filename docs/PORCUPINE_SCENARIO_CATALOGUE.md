# PORCUPINE — Scenario Catalogue (the bug-catching backlog)

**Date:** 2026-06-05 · **Owner:** Claude (design/validation) · **Status:** living document
**Principle (Board):** *the harness is worth only the bugs it catches before 09:15.* A scenario that
only proves the happy path is theater. Every scenario below maps to a **real failure mode** — most to an
incident this system has actually had. When a new bug escapes to live, it gets added here as a regression
that must fail-then-pass. "Why wasn't this in the harness?" should always be answerable with a row number.

Legend — **caught**: harness already reproduced it · **planned**: scenario specced, not yet automated ·
**infra**: needs process/systemd-level sim (harder).

---

## A. Data integrity (the feed/capture layer)

| # | Scenario | Real incident | Trigger (feed driver) | Assertion |
|---|----------|---------------|-----------------------|-----------|
| A1 | **Zero/invalid tick** — spot/low/close = 0 | spot=0.0 on 15:29 bar (caught 2026-06-05) | `synth --fault zero-tick` / replay a bad close bar | no bar with spot≤0 reaches enriched or agents; bad ticks filtered |
| A2 | **lp-less option tick clobbers last-good LTP** | feed.py on_tick ltp=0 clobber ([[sensex_option_capture_zero_ltp]]) | `synth --fault lp-zero` | last good option ltp preserved; `_apply_option_tick` guard holds |
| A3 | **Stale snapshot** — yesterday's data served as today | 26-MAY expired-weekly trade ([[entry_path_and_stale_trade_blocker]]) | `synth --fault stale-ts` (prior day) | freshness guard rejects entry; never trades an expired expiry |
| A4 | **Duplicate / sub-minute timestamps** | capture polling dup ts (REPLAY_GUIDE) | `synth --fault dup-ts` | dedup; one row per (ts,instrument); no double-count volume |
| A5 | **Gap in bars** (minutes missing) | feed silent death gaps | `synth --fault gap` | indicators don't NaN-cascade; gap logged, not silently zero-filled |
| A6 | **Enrichment lags raw by ≥1 bar** | latest-raw-join NULL atm (caught 2026-06-05, FIXED) | replay full day, read snapshot | snapshot = latest *enriched* bar; atm_strike never NULL when enriched exists |
| A7 | **SENSEX option symbol format** | wrong SENSEX symbol ([[fix_sensex_option_symbols]]) | replay SENSEX | option tsyms match `SENSEX50[YY][MMM][DD][STRIKE][CE/PE]` |
| A8 | **Out-of-range / spike values** (fat-finger print) | — (preventive) | `synth --fault vol-spike` | spike rejected or clamped; ATR/BB don't explode |

## B. Concurrency & persistence

| # | Scenario | Real incident | Trigger | Assertion |
|---|----------|---------------|---------|-----------|
| B1 | **Two writers → SQLite lock crash-loop** | enricher lock (caught+fixed 2026-06-05, [[enricher_lock_rootcause_and_fix]]) | consumer+enricher concurrent, realtime | 0 `database is locked` exits; enriched has no gaps |
| B2 | **Duplicate DB writers** | duplicate DuckDB writers crash ([[data_pipeline_instability_blocker]]) | spawn 2 writers same file | single-writer guard holds / no corruption |
| B3 | **DB locked by capture during read** | duckdb_tool 30-retry | reader during write burst | reader retries, never crashes the cycle |
| B4 | **WAL not checkpointing / bloat** | — (preventive) | long run | WAL size bounded; reads see latest |

## C. Scheduling, timing & market hours

| # | Scenario | Real incident | Trigger | Assertion |
|---|----------|---------------|---------|-----------|
| C1 | **Entry window correctness** | entry-time dup 9:15 vs 9:30 ([[cpu_load_leak_and_claudemem_disable]]) | replay across entry marks | exactly one entry attempt per intended window |
| C2 | **Off-hours / holiday gate** | check_market_hours / RuntimeMaxSec bounce ([[penguin_runtimemaxsec_bounce_fix]]) | feed outside window | no entry/capture outside session; clean stop at close |
| C3 | **Timer re-arm** *(infra)* | Penguin timer Requires bug ([[penguin_timer_requires_bug]]) | systemd-level | timers re-arm daily |
| C4 | **Singleton guard** (no pile-up) | run_kickoff CPU pileup ([[cpu_load_leak_and_claudemem_disable]]) | launch 2 kickoffs | second bails via pgrep guard |

## D. State, ledger & idempotency

| # | Scenario | Real incident | Trigger | Assertion |
|---|----------|---------------|---------|-----------|
| D1 | **JSON ↔ DuckDB split-brain** | ledger split-brain ([[paper_trade_never_completed_rootcause]]) | place order in sim | order_ledger.json and trade_execution.duckdb agree |
| D2 | **Stale ACTIVE trades block entry** | 8 stale ACTIVE trades ([[entry_path_and_stale_trade_blocker]]) | seed stale ACTIVE trade | entry handles/cleans stale state, not blocked forever |
| D3 | **Re-processing idempotency** | INSERT OR REPLACE design | replay same bar twice | no dup rows, no double trade |
| D4 | **Checkpoint resume after restart** | enricher last_enriched_bar_ts | kill+restart mid-run | resumes without gap or dup |

## E. Market-data correctness for decisions

| # | Scenario | Real incident | Trigger | Assertion |
|---|----------|---------------|---------|-----------|
| E1 | **ATM strike correctness** | atm NULL/again | replay | atm = round(spot/50)*50; matches strikes present |
| E2 | **Expiry calendar** (weekly/next/monthly) | expired-weekly trade | replay across expiry day | days_to_weekly ≥0; never trades past expiry |
| E3 | **Missing OI/IV (no broker source)** | option OI/IV Penguin gap ([[capture_canonical_penguin_only]]) | broker stub off | agents degrade explicitly, don't fabricate; flagged not silent |
| E4 | **VIX null → regime default** | caught 2026-06-05 | broker stub off | null-VIX must NOT silently auto-enter; needs explicit guard |

## F. Agents / LLM (CrewAI)

| # | Scenario | Real incident | Trigger | Assertion |
|---|----------|---------------|---------|-----------|
| F1 | **Agent runs on garbage input** | spot=0 reached regime agent (caught 2026-06-05) | feed bad tick | agents reject/flag impossible inputs (spot≤0, vix≤0) |
| F2 | **Deterministic fallback path** | entry agents fallback `avg_super_trend=0, session=""` (caught) | sandbox/missing multi-TF | fallback inputs are valid, not zero/empty; fallback logged |
| F3 | **Fabricated P&L / hallucination** | Claude fake-backtest incident ([[claude_hallucination_incident_may24]]) | replay | every number traces to a tool result; no invented fills |
| F4 | **Entry-score logic** | NOT_UP/NOT_DOWN, combine_entry_scores ([[deepseek_nifty_backtest_validation]]) | replay known regimes | NOT_UP/NOT_DOWN + combine produce expected signal on labelled bars |
| F5 | **LLM non-determinism / cost** | — | `--llm stub` vs `--llm real` | stub deterministic for CI; real run asserts tolerance-based |

## G. Trade lifecycle (entry → monitor → exit → EOD)

| # | Scenario | Real incident | Trigger | Assertion |
|---|----------|---------------|---------|-----------|
| G1 | **Full happy path** | — | replay trending day | 1 entry → monitored → exit, ledger consistent |
| G2 | **EOD square-off** | run_bridge no square-off ([[entry_path_and_stale_trade_blocker]]) | replay to 15:30 | all positions closed by EOD; ledger flat |
| G3 | **Exit actually runs** | exit never runs ([[paper_trade_never_completed_rootcause]]) | open trade + SL hit | exit path fires; trade closed |
| G4 | **TSL / morph / shift transitions** | TSL threshold ([[monitoring_phase_logging_added]]) | replay move past TSL activation | TSL activates at threshold; morph stages logged |
| G5 | **Re-entry rules** | iron-fly 2 re-entries ([[iron_fly_strategy_rules]]) | replay SL+recenter | ≤2 re-entries; single position invariant |

## H. Infra / process resilience *(infra — process-level sim)*

| # | Scenario | Real incident | Assertion |
|---|----------|---------------|-----------|
| H1 | **Silent producer death** (systemd "active", thread dead) | feed WS callback death ([[feed_producer_silent_crash_loop]]) | heartbeat staleness detected; not "active+dead" |
| H2 | **Resource leak / OOM** | CPU/log-analyzer OOM ([[cpu_load_leak_and_claudemem_disable]]) | bounded memory/CPU over a full-day run |
| H3 | **Cron wrapper env** | v4 cron leak ([[feedback_cron_shell_wrappers]]) | wrapper sets cd/env/guard |

---

## Coverage status (2026-06-10)
- **Built + caught:** A6, B1, F1, F2, E4 (2026-06-05). A1/A2 via synth fault driver.
- **Lifecycle now automated (2026-06-10):** G1 (`lifecycle` SL_HIT), G2 (`eod`), G3 (`tp_hit`),
  P6 floor (`floor`), F5/G4 morph (`morph`, deterministic LLM stub). The `floor` scenario caught a
  real bug: EOD/floor `CLOSE_ALL` booked P&L at entry fill, not live LTP (phantom ₹0) — FIXED
  (`position_manager.execute_action` CLOSE_ALL now marks legs first). See PORCUPINE_STATE §5 bug #5.
- **Fault→assertion binding (2026-06-10):** `run_scenario fault:<class>` wires `mock_feed --fault` through
  the real pipeline. `fault:zero`(A1) & `fault:dup`(A4) PASS. `fault:zero` caught bug #6 — the consumer had
  no zero-OHLC guard (only feed.py did); FIXED. `fault:outlier`(A8) RED = open finding (no outlier clamp).
- **Path stack (2026-06-10):** time-evolving narratives now possible — `path:ramp_then_fade` (theta→fade→EOD),
  `path:spike_breaches_floor` (FLOOR preempts per-leg SL at 65-lot). Engine = option_pricer + path_driver +
  `expect` DSL; scenarios are DATA (the seam to MONGOOSE).
- **Next automation priority:** D1 (ledger consistency), G5 (re-entry), A8 outlier clamp (Board), fault:gap/freeze
  assertions.
- **Honest gaps:** H1–H3 need process-level sim (systemd/heartbeat), not just data replay — phase later.

## Rule of operation
Every production incident from here on opens with: **write the failing scenario first** (it must
reproduce the bug in the harness), then fix, then it stays as a permanent regression. The catalogue only
grows. That is how "why wasn't this caught?" stops being a question.
