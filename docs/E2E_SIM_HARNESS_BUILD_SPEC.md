# E2E Simulation Harness — Build Spec (DeepSeek Handoff)

**Date:** 2026-06-05 · **Author:** Claude (design/validation) · **Builder:** DeepSeek · **Status:** Ready to build, Phase 0 first
**Read first:** `E2E_SIM_HARNESS_DESIGN.md` (architecture + Board decisions). This doc is the
implementation contract — written assuming **no prior context**. Build phases in order; each phase has a
Definition of Done (DoD) that must pass before the next.

> **Validation split:** DeepSeek builds. Claude owns the gates — especially the Phase-0 `assert_sandboxed()`
> leakage guard (the #1 risk: a test run writing into production data). Do not skip it.

---

## 0. What this is, in one paragraph

The live trading pipeline is `feed.py (Shoonya websocket) → consumer → enricher → kickoff → order →
monitor → risk/exit`. Everything below `feed.py` is production code we do NOT change. We build a **mock
feed** that writes ticks into a **separate test Redis** in the *exact same key shape* the real feed uses,
and we redirect every stateful path to a **sim root** directory. Then the real pipeline runs end-to-end,
offline, against fake data — so we validate the whole system without touching live.

---

## 1. The production contracts you must reproduce EXACTLY

The mock feed is only correct if downstream code cannot tell it from `feed.py`. These are the contracts
(verified in source 2026-06-05). **Do not change them — reproduce them.**

### 1.1 Redis keys written by the real feed (`feed.py`)
| Key | Type | Written by | Read by | Shape |
|-----|------|-----------|---------|-------|
| `feed:{INST}` | LIST (LPUSH, LTRIM 0..7000) | feed | consumer `lrange` | bar JSON (below) |
| `feed:{INST}:options:ltp` | HASH (field=tsym) | feed | consumer `hgetall` | option JSON (below) |
| `feed:{INST}:options:window` | STRING | feed | consumer | JSON list of valid strikes (ints) |
| `prev_close_{INST}` | STRING | feed | enricher/kickoff | float as string |
| `feed:{INST}:heartbeat` | STRING (ex=120) | feed | health | ISO-8601 ts |
| `bars:{INST}:{tf}` | PUB/SUB channel | **consumer** | enricher (`bars:{INST}:1`) | completed bar/bucket JSON |

`{INST}` ∈ `NIFTY`, `SENSEX`, `MCX` (MCX = 7 contracts: GOLD, SILVERMIC, CRUDEOILM, NATGASMINI, ZINCMINI,
LEADMINI, ALUMINI; feed key per contract `feed:{CONTRACT}`).

**Bar JSON** (consumer `lrange` → `json.loads`, fields it reads):
```json
{"timestamp":"2026-06-05T10:18:00","instrument":"NIFTY","open":23490.0,"high":23495.0,
 "low":23488.0,"close":23492.0,"volume":0,"ltp":23492.0}
```
**Option JSON** (consumer `hgetall` values → `json.loads`):
```json
{"tsym":"NIFTY09JUN26C23500","strike":23500,"option_type":"CE","ltp":82.5,
 "oi":6750445.0,"volume":12082265.0,"timestamp":"2026-06-05T10:18:00+05:30"}
```
Note: real option feed has **no IV** field — IV/greeks come from the broker, which is best-effort and
absent in sim (those enriched columns stay NULL — that is correct and expected).

### 1.2 SQLite tables (consumer + enricher write these in `capture_{inst}.sqlite`)
- consumer → `market_data`, `market_data_multitf`, `option_prices`, `consumer_state(last_ts:{INST})`
- enricher → `market_data_enriched`, `consumer_state(last_enriched_bar_ts:{INST})`
- Schemas: `config/sqlite_schema.py` (`init_schemas`, `init_enriched_schema`). Reuse — do not redefine.

---

## 2. Phase 0 — Isolation plumbing (FOUNDATION — build first, nothing works without it)

### 2.1 The single env contract
```
SIM_MODE=1                        # turns the whole stack into sandbox mode
SIM_ROOT=/home/trading_ceo/antariksh/sim/run_<scenario>_<YYYYMMDD_HHMMSS>/
SIM_REDIS_PORT=6380               # separate redis-server (own dir, FLUSHALL-safe)
```
`SIM_ROOT/` layout: `data/` (capture_*.sqlite, *.duckdb), `state/` (ledger.json, brahmand_kickoff.json,
trade_execution.duckdb), `logs/`, `redis/` (dump.rdb + redis.conf).

### 2.2 New file: `sim/sim_env.py` (single source of truth for isolation)
```python
# Pseudocode contract — implement exactly this surface.
import os
from pathlib import Path

def sim_active() -> bool: return os.environ.get("SIM_MODE") == "1"

def sim_root() -> Path:
    r = os.environ.get("SIM_ROOT")
    if sim_active() and not r: raise RuntimeError("SIM_MODE=1 but SIM_ROOT unset")
    return Path(r) if r else None

def redis_kwargs() -> dict:
    port = int(os.environ.get("SIM_REDIS_PORT", "6379"))
    return {"host": "localhost", "port": port, "db": 0, "decode_responses": True}

def capture_path(instrument: str) -> Path:
    base = sim_root() / "data" if sim_active() else Path("/home/trading_ceo/python-trader/varaha/data")
    return base / f"capture_{instrument.lower()}.sqlite"

def log_dir() -> Path: ...

def assert_sandboxed(path) -> None:
    """HARD GUARD. If SIM_MODE=1, every resolved write path MUST live under SIM_ROOT.
    Raise RuntimeError otherwise. Call before any file/db open in sim-aware code."""
    if sim_active() and sim_root() not in Path(path).resolve().parents and Path(path).resolve() != sim_root():
        raise RuntimeError(f"SANDBOX LEAK: {path} is outside SIM_ROOT {sim_root()}")
```

### 2.3 Make these production paths sim-aware (verified hardcoded gaps, 2026-06-05)
| File:loc | Current | Change |
|----------|---------|--------|
| `config/sqlite_schema.py:get_sqlite_capture_path` | `_DATA_DIR / capture_{inst}.sqlite` (hardcoded) | delegate to `sim_env.capture_path()`; call `assert_sandboxed()` |
| `consumers/instrument_consumer.py:152-158` | hardcoded `python-trader/varaha/data/...` db_path | use `sim_env.capture_path(instrument)` |
| `feed.py:321` | `redis.Redis(host,port=6379,db=0)` | `redis.Redis(**sim_env.redis_kwargs())` |
| `consumers/instrument_consumer.py` redis | `port=6379` | `sim_env.redis_kwargs()` |
| `enrichers/instrument_enricher.py` redis | `port=6379` | `sim_env.redis_kwargs()` |
| loggers (feed/consumer/enricher) | stdout/prod logs | file handler → `sim_env.log_dir()` when sim |

Keep production behavior **identical** when `SIM_MODE` unset (defaults = current values). This is a pure
add-a-branch change; no prod path moves.

### 2.4 New file: `sim/start_test_redis.sh`
Boot a dedicated redis-server on `SIM_REDIS_PORT` with `dir=SIM_ROOT/redis`, `save ""` (no persistence
needed), `--daemonize no` (managed by the orchestrator). Teardown kills it by pidfile.

### **Phase 0 DoD**
- `SIM_MODE=1 SIM_ROOT=... SIM_REDIS_PORT=6380` set → consumer/enricher/feed resolve every path under
  `SIM_ROOT` and connect to redis:6380.
- `assert_sandboxed()` raises if any path escapes `SIM_ROOT`. Unit test proves it (feed a prod path → expect raise).
- With `SIM_MODE` unset, production is byte-for-byte unchanged (run existing 39/39 suite — must stay green).

---

## 3. Phase 1 — Mock feed producer (THE KEYSTONE)

### New file: `sim/mock_feed.py` — drop-in replacement for `feed.py`
CLI: `python3 -m sim.mock_feed --instrument NIFTY --source replay|synth --clock realtime|fast [--speed N]`

One `FeedDriver` interface, two implementations:

**`ReplayDriver`** — reads recorded real data and emits it:
- bars: from `market_data` history (a copied capture DB) and/or `brahmand/data/recordings/<dir>/`
  (today's live slice: `capture_nifty_snapshot.sqlite` + `option_timeseries.jsonl`).
- options: replay `option_timeseries.jsonl` snapshots (HSET into `feed:{INST}:options:ltp`).
- Emits in timestamp order; `--clock realtime` sleeps to real cadence (REQUIRED to reproduce timing races
  like the enricher lock), `--clock fast` compresses time.

**`SynthDriver`** — generates ticks + injects faults (Board: erroneous-data validation):
- base: random-walk spot around a seed; derive option chain.
- fault flags (each independently togglable): `--fault lp-zero` (lp-less ticks → must not clobber last good
  ltp), `--fault gap` (skip minutes), `--fault stale-ts`, `--fault dup-ts`, `--fault vol-spike`,
  `--fault missing-strikes`, `--fault lock-stress` (spawn a concurrent writer hammering the capture DB).

Both write the **exact** keys from §1.1 via `sim_env.redis_kwargs()`. Set heartbeats. Nothing else in the
pipeline knows it isn't `feed.py`.

### **Phase 1 DoD**
- `mock_feed --source replay` → real `instrument_consumer` (SIM_MODE) → `market_data` in
  `SIM_ROOT/data/capture_nifty.sqlite` populates with the replayed bars (row count == emitted bars).
- `option_prices` populates from replayed option snapshots.
- Zero writes outside `SIM_ROOT` (verify via `assert_sandboxed` + inspect prod DB mtime unchanged).

---

## 4. Phases 2–4 — layer the real pipeline (point existing code at the sim stack)

| Phase | Wire up | DoD (assertions) |
|-------|---------|------------------|
| **2 — through entry** | enricher + kickoff/e2e_chain under SIM_MODE | `market_data_enriched` MAX(ts) tracks `market_data` MAX(ts) within 1 min; `atm_strike` non-NULL; kickoff produces an entry signal (not "No market data"); **enricher NRestarts==0** over the run → validates the lock fix + future merge |
| **3 — full lifecycle** | order_agent (paper), position_manager, TSL/morph monitor, risk_agent (LLM), exit, EOD square-off | order written to `SIM_ROOT/state` ledger AND trade_execution.duckdb consistently (no split-brain); monitor advances; exit/square-off runs; EOD state flat |
| **4 — fault library + runner** | `sim/run_scenario.py` orchestrator + `sim/scenarios/*.yaml` + assertion lib + teardown | each scenario boots redis→launches components→runs→asserts→tears down, exit code 0/1 |

### LLM sub-modes (Phase 3) — required by non-determinism + token cost
- `--llm real`: true risk/exit agent. Assertions tolerance-based ("acted sensibly, no fabricated P&L"),
  for full validation runs.
- `--llm stub`: deterministic canned decisions, for fast CI / path coverage without DeepSeek spend.
- The risk agent stays LLM in production — the stub is **test-only** (do not modularize the live agent).

---

## 5. Scenario library (Phase 4 seed set)
| File | Source | Asserts |
|------|--------|---------|
| `happy_path.yaml` | replay 2026-06-05 | 1 entry → monitored → clean exit/square-off |
| `ltp_zero_storm.yaml` | synth `--fault lp-zero` | last-good ltp never clobbered |
| `lock_stress.yaml` | synth `--fault lock-stress` realtime | enriched no gaps, enricher NRestarts==0 |
| `broker_down.yaml` | replay, broker stub off | IV/greeks NULL, atm_strike + entry still produced |
| `stale_snapshot.yaml` | synth `--fault stale-ts` | freshness guard rejects entry |
| `eod_squareoff.yaml` | replay to 15:30 | all positions closed, ledger flat |

---

## 6. Gotchas (read before coding)
1. **Sandbox leak is the top risk.** `assert_sandboxed()` is mandatory at every write site in sim-aware
   code. A single missed hardcoded path corrupts production data. Claude gates this.
2. **Races need `--clock realtime` + real separate processes.** Fast/inline replay will NOT surface the
   enricher lock or feed clobber bugs. Launch components as the orchestrator would in prod.
3. **Tick fidelity:** `market_data` is 1-min bars; the live WS is sub-second. Historical replay is
   bar-as-tick (one tick/bar) — fine for logic/lock validation, not micro-timing. Today's captured slice
   has finer option granularity — prefer it for fidelity.
4. **Don't touch production defaults.** Every change is `if sim_env.sim_active(): <sandbox> else <current>`.
5. **Reuse, don't reinvent:** schemas (`config/sqlite_schema.py`), and the existing `BRAHMAND_SANDBOX`
   redirections (REPLAY_GUIDE.md §"Env var overrides") — extend that map, don't duplicate it.

## 7. Definition of Done (whole harness)
`python3 -m sim.run_scenario sim/scenarios/happy_path.yaml` boots an isolated stack, drives the **real**
pipeline feed→exit with the mock feed, asserts a full clean trade, tears down, exits 0 — and the
production Redis (6379) and prod capture DBs are provably untouched (mtime unchanged). All six seed
scenarios pass. Existing 39/39 integration suite still green with `SIM_MODE` unset.

## 8. Build order (do not reorder)
P0 plumbing + `assert_sandboxed` test → P1 mock feed (replay) → P2 through entry → P1b synth+faults →
P3 full lifecycle + LLM → P4 orchestrator + scenarios. P0–P2 (~1.5–2 days) already validates the enricher
lock fix and the single-writer merge offline — the weekend goal.
