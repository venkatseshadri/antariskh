# Antariksh E2E Simulation Harness — Design

**Date:** 2026-06-05 · **Author:** Claude (advisory/validation) · **Status:** Design — awaiting Board approval to build
**Purpose:** Validate the **entire** trading pipeline offline against a fully isolated stack driven by a
**mock websocket feed**, so we stop firefighting on the live system. Permanent regression harness, built
mock-feed-first.

---

## 1. Core principle — one substitution point

Everything from the consumer down is **already production code**. The live Shoonya websocket is the *only*
thing we replace. Swap it for a mock producer that writes ticks into a **test Redis** in the exact same
key shape, point every component's paths at a **sim root**, and the real pipeline runs unchanged:

```
            ┌─────────────── PRODUCTION (untouched) ───────────────┐
 MOCK FEED → consumer → enricher → kickoff/e2e_chain → order_agent → position_manager → risk_agent(LLM) → exit/EOD
   ▲              │           │            │                │              │                  │
   │          test Redis  test SQLite   test DuckDB     test ledger     test logs        test state
   └─ replay real ticks  (sim_root/)    (sim_root/)     (sim_root/)     (sim_root/)       (sim_root/)
      OR synth + faults
```

The mock feed is not a *component* of the harness — it is the **driver** the whole harness hangs off.
That is why it is built first (Board direction 2026-06-05).

## 2. Confirmed scope (Board, 2026-06-05)

| Dimension | Decision |
|-----------|----------|
| Goal | **Permanent regression harness**, built incrementally, mock-WS feed first |
| Feed data | **Both** — replay recorded **real** ticks (real scenarios) **and** a synthetic generator (erroneous-data / fault injection) |
| Pipeline depth | **Full lifecycle incl. the LLM risk agent** (entry → paper order → monitor → risk/exit → EOD square-off) |
| Isolation | **Fully separate stack** — own Redis instance (port 6380), own file paths, own logs, own processes |

## 3. Isolation model — `SIM_ROOT` + test Redis

A single env contract drives all isolation. One knob to flip the whole stack into the sandbox:

```
SIM_ROOT=/home/trading_ceo/antariksh/sim/run_<scenario>_<ts>/
SIM_REDIS_PORT=6380          # separate redis-server, own dir/config, FLUSHALL-safe
SIM_MODE=1                   # components assert they're sandboxed before writing
```

`SIM_ROOT/` holds: `data/` (capture_*.sqlite, *.duckdb), `state/` (ledger, kickoff json, trade_execution),
`logs/`, `redis/` (test redis dump + config). Production paths are NEVER touched — a guard in each
component refuses to start if `SIM_MODE=1` but a resolved path points outside `SIM_ROOT`.

### Reuse what exists
The REPLAY harness already redirects ~12 modules via `BRAHMAND_SANDBOX` (ema_aggregator, kickoff,
trade_execution_db, duckdb_tool, order_agent, entry_tools, toolkit…). We extend that pattern; we do
**not** reinvent it.

## 4. Phase 0 — path-isolation plumbing (FOUNDATION, must come first)

Nothing runs isolated until every stateful path honors `SIM_ROOT`. **Audited gaps (verified 2026-06-05):**

| Gap | Location | Fix |
|-----|----------|-----|
| SQLite capture path hardcoded | `config/sqlite_schema.py:get_sqlite_capture_path` (no env check) | honor `SIM_ROOT`/`BRAHMAND_SANDBOX` |
| Consumer db path hardcoded | `consumers/instrument_consumer.py:152-158` (`python-trader/varaha/data/...`) | route through `get_sqlite_capture_path` |
| Redis host/port hardcoded | `feed.py:321`, `consumers/*`, `enrichers/*` (`port=6379`) | read `SIM_REDIS_PORT` (default 6379) |
| Log dir | enricher/consumer/feed loggers | `SIM_ROOT/logs` when `SIM_MODE` |

**Deliverable:** a `sim/sim_env.py` helper (mirrors `tools/replay_env.py`) that every entrypoint imports to
resolve redis + paths + logs from one place, plus a **leakage guard** (`assert_sandboxed()`).

## 5. Phase 1 — Mock websocket feed producer (the keystone)

`sim/mock_feed.py` — drop-in replacement for `feed.py`. Emits the **exact** production key contract so
downstream code can't tell the difference:

- `LPUSH feed:{instrument}` — normalized 1-min/tick bars (shape per `feed.py:normalize`/`bucket_minute`)
- `HSET feed:{instrument}:options:ltp {tsym} {json}` — per-strike `ltp/oi/volume/strike/option_type/timestamp`
- `SET feed:{instrument}:options:window`, `prev_close_{instrument}`, `feed:{instrument}:heartbeat`

Two source drivers behind one interface:

| Driver | Source | Use |
|--------|--------|-----|
| `replay` | recorded slice (`brahmand/data/recordings/…`) + `market_data` history reconstructed to ticks | **real scenarios** — deterministic, faithful |
| `synth` | programmatic generator | **erroneous-data** — inject: lp-less ticks (ltp=0 clobber), gaps, stale/duplicate timestamps, vol spikes, missing strikes, **write-lock stress** (concurrent writer) |

Clock modes: `--realtime` (reproduces timing-dependent races like the enricher lock — required to validate
the lock fix) and `--fast` (compressed, for quick deterministic CI once races are ruled out).

**Phase-1 exit check:** mock feed → real consumer → `market_data` populates in `SIM_ROOT` test DB. Proves
the keystone drives the real pipeline.

## 6. Phases 2–4 — layer the pipeline

| Phase | Adds | Key assertions |
|-------|------|----------------|
| **2 — through entry** | enricher + kickoff/e2e_chain | `market_data_enriched` tracks raw within 1 min; `atm_strike` non-NULL; entry signal produced; **no enricher crash loop** (validates the lock fix + the single-writer merge) |
| **3 — full lifecycle** | order_agent (paper), position_manager, TSL/morph monitor, **LLM risk agent**, exit, EOD square-off | order recorded in test ledger+duckdb (no split-brain); exit/square-off runs; clean EOD state |
| **4 — fault library + CI** | synthetic scenarios + assertion runner + teardown | each fault scenario asserts the system degrades correctly, not silently |

## 7. Scenario library (grows over time)

| Scenario | Feed | Asserts |
|----------|------|---------|
| Happy path | replay 2026-06-05 | 1 clean entry → monitored → exit/square-off |
| ltp=0 tick storm | synth | last-good ltp never clobbered (regression on the known feed bug) |
| Two-writer lock stress | synth + concurrent writer | enriched has **no gaps**, no crash loop (validates lock fix) |
| Broker down | replay, broker stubbed off | enriched best-effort (IV/greeks NULL), kickoff still produces atm_strike & entry |
| Stale snapshot | synth (yesterday's ts) | freshness guard rejects entry (e2e_chain stale-snapshot path) |
| EOD square-off | replay to 15:30 | all positions closed, ledger flat |

## 8. LLM in the loop — two sub-modes (non-determinism + token cost)

Full pipeline includes the real risk agent, which is non-deterministic and burns DeepSeek tokens.
So the runner supports:
- `--llm real` — true risk/exit agent; assertions are **tolerance-based** ("acted sensibly / no hallucinated P&L"), used for full validation runs.
- `--llm stub` — deterministic canned risk decisions, for fast CI / path coverage without token spend.

(Keeps the [[feedback_risk_agent_stays_llm]] rule intact — the agent stays LLM; the stub is test-only.)

## 9. Effort & sequencing

| Phase | Effort | Gives |
|-------|--------|-------|
| 0 — path plumbing + guard | ~0.5–1 day | isolation foundation |
| 1 — mock feed (replay) | ~0.5 day | keystone; drives real consumer |
| 2 — through entry | ~0.5 day | **validates today's lock fix + the merge this weekend** |
| 3 — full lifecycle + LLM | ~1–1.5 days | end-to-end trade in sandbox |
| 4 — fault library + CI runner | ~1 day | repeatable regression suite |

**Total ~3.5–4.5 days.** Phases 0–2 (~1.5–2 days) already deliver the weekend goal: prove the
enricher fix and the single-writer merge end-to-end without touching live.

## 10. Risks & gotchas

- **Path-leakage is the #1 risk** — any missed hardcoded prod path writes into real data. Phase 0's
  `assert_sandboxed()` guard is mandatory, not optional.
- **Tick fidelity for past days** — `market_data` is 1-min bars; the live WS is sub-second. Historical
  replay is bar-as-tick (one tick/bar) — fine for logic/lock validation, not micro-timing. Today's
  captured slice has finer option granularity.
- **Race reproduction needs `--realtime`** — fast-replay won't surface the lock race; the harness must
  run components as real separate processes at real cadence to reproduce/validate it.
- **LLM cost/variance** — default CI to `--llm stub`; reserve `--llm real` for full validation runs.

## 11. Relationship to existing REPLAY harness

REPLAY (`brahmand/tools/replay_session.py`) is **not** this — it replays the old DuckDB path, never runs
the consumer/enricher, and is broker-less, so it can't validate the SQLite capture/enrich path. This
harness supersedes it for capture-path validation; REPLAY remains useful for indicator/kickoff-logic
diffing. Do not conflate them.
