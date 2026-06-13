# PRD — Path to Go-Live (L0 → L1)

> **Owner:** Chairman (Venkat) · **Author/Director:** Claude (Narasimha) · **Implementer:** DeepSeek
> **Created:** 2026-06-13 · **Status:** DRAFT for Board approval
> **Scope:** Get the Varaha options trading system from "L0 paper, optimistic" to **a real, evidence-backed L0→L1 go-live** — without lighting real capital on a strategy that has not been proven to have positive expectancy.

This is the **single source of truth for the build backlog.** Each story below maps 1:1 to a
GitHub issue. DeepSeek implements one story per ralph-loop iteration. Claude (Director)
**raises and validates only** — DeepSeek implements all fixes (Board rule, 2026-06-12).

Companion docs:
- `ABOUTME.md` — the *why* (human, goals, personality). North star. Frozen narrative.
- `TRADING_SYSTEM.md` — the *what* (architecture, components, data flow). Spec of record.
- `CODE_AUDIT_LOOP.md` — the scheduled propose-only file-conformance reviewer (feeds E5).

---

## 0. The Honest Status (read this before anything else)

`TRADING_SYSTEM.md §10` says *"Ready for L0→L1."* That is **plumbing-readiness, not
strategy-readiness.** Two facts the architecture doc does not state:

1. **The canonical strategy as currently configured tested NEGATIVE expectancy.**
   Memory `sherpa_phase2_verdict`: SHERPA-as-configured = **−13%/month on full-2024**.
   The old "₹287k profit / 2,055 trades" backtest that justified this build is **invalid**
   (wrong NOT_UP/NOT_DOWN logic, wrong TP/SL params, broken `combine_entry_scores`).
   **Verdict on record: no paper trade until the harness is recalibrated.**

2. **Config contradicts itself.** Free-cash floor is ₹50,000 in `risk_config.py` but
   ₹11,000 in `ralph/constitution.yaml`. SL/TP appear at three different values across
   `ABOUTME.md`. A system whose own rule files disagree cannot be called go-live ready.

**Therefore go-live order is: prove the edge (E1) before polishing the pipeline.** Plumbing
without a positive-expectancy strategy is a well-built machine that loses money reliably.

---

## 1. Reconciliation — ABOUTME.md vs TRADING_SYSTEM.md

Both docs stay separate (Board decision 2026-06-13). Contradictions below are resolved to a
**canonical value**; each unresolved one becomes a story in E0.

| Parameter | ABOUTME.md says | TRADING_SYSTEM.md / code says | Canonical (resolved) | Action |
|---|---|---|---|---|
| Per-trade SL | ₹2,500 (§2) **and** ₹3,500 (§4) | ₹3,500 (`risk_config.daily_sl`, constitution) | **₹3,500** | Fix ABOUTME §2 → S0.1 |
| Take-profit / lock | +₹5,000 lock (§2) **and** ₹1,000 (§4) | ₹1,000 target | **₹1,000 TP** (₹5,000 was a stale "profit-lock" concept) | Fix ABOUTME §2 → S0.1 |
| Session window | 9:20–15:05 (§1); entry 10:30 (§4); decisions 09:15–15:30 (§5) | decisions until 15:05; force-exit 15:25 | **Decisions 09:15–15:05; force-exit 15:25; first-entry window per strategy** | Clarify ABOUTME → S0.1 |
| NIFTY lot size | unspecified | 65 (`risk_config`, constitution) | **65, max_lots 2** (⚠️ old backtest used 75 — note only) | none |
| Free-cash floor | unspecified | **₹50,000** (`risk_config`) vs **₹11,000** (`constitution.yaml`) | **UNRESOLVED — live config conflict** | S0.2 (blocker) |
| Win-rate target | 60%+ structural | — | 60% structural (to be *proven*, not assumed) | E1 |
| Session-end message | 2:35 PM | 14:35 | consistent | none |

**Principle reaffirmed (both docs agree):** *Code enforces. LLMs explain. Never reverse.*
Every story below must preserve this — no story may move a risk gate from Python into LLM judgment.

---

## 2. Backlog Structure

```
E0  Truth & Reconciliation        (config single-source)      ← do first, fast, unblocks all
E1  Strategy Validity Gate        (prove the edge)            ← THE go-live blocker
E2  Paper Session Reliability     (10 clean sessions)         ← go-live
E3  Two-Message Protocol          (comms discipline)          ← go-live
E4  Code Conformance Audit Loop   (the scheduled reviewer)    ← runs in parallel, feeds E5
E5  Cleanup & Scalability         (dead code, consolidations) ← DEFERRED, documented
```

Priority legend: **P0** = go-live blocker · **P1** = go-live required · **P2** = deferred.
Each story: **Goal · Context · Acceptance/Test · Repo · Depends-on.** A story is "done" only
when its Test conditions pass — green test count alone is not safety (`planner_altitude`).

---

## E0 — Truth & Reconciliation  `P0`

Goal of epic: the system's own rule files must agree before anything trades. Cheap, fast,
removes ambiguity that would otherwise corrupt E1's measurements.

### S0.1 — Reconcile ABOUTME.md parameter values
- **Goal:** ABOUTME.md states the *same* SL/TP/session-window values as `risk_config.py`.
- **Context:** ABOUTME §2 says SL ₹2,500 / lock ₹5,000; §4 says SL ₹3,500 / TP ₹1,000. The
  canonical values live in `risk_config.py` (₹3,500 / ₹1,000).
- **Acceptance/Test:**
  - ABOUTME §2 SL/TP numbers replaced with ₹3,500 / ₹1,000 and a one-line note "values
    enforced by `risk_config.py`, not this doc."
  - `grep -nE '2,?500|5,?000' ABOUTME.md` returns no SL/TP usages.
  - No code change; doc-only.
- **Repo:** root (`ABOUTME.md`). **Depends-on:** none.

### S0.2 — Resolve free-cash-floor conflict (₹50,000 vs ₹11,000)  `P0 blocker`
- **Goal:** Exactly one free-cash-floor value across the whole system.
- **Context:** `risk_config.py CAPITAL.free_cash_floor = 50_000`; `ralph/constitution.yaml
  capital_floor = 11000` and `session_buffer = 11_000`. `TRADING_SYSTEM.md §7.3` claims this
  was already unified to 50,000 — it was not. A kill-switch ("Free cash < floor → scale down")
  firing at the wrong threshold either never protects (11k) or blocks every trade (50k).
- **Acceptance/Test:**
  - Chairman decides the canonical value (Director recommendation: **₹50,000** for a ₹2L
    margin / ₹5L pool — 11,000 gives almost no buffer). Record decision in the story.
  - All readers import from `risk_config.py`; `constitution.yaml` either matches or references it.
  - `grep -rnw 11000 --include=*.py --include=*.yaml` shows no free-cash-floor usage (other
    contexts e.g. `session_buffer` documented if kept).
  - A unit test asserts `RISK`/`CAPITAL` floor == constitution floor (single-source proof).
- **Repo:** antariksh. **Depends-on:** none.

### S0.3 — Config single-source audit (no scattered magic numbers)
- **Goal:** Every risk/sizing constant resolves to `risk_config.py` (and DB paths to
  `config/db_paths.py`), matching the claim in `TRADING_SYSTEM.md §7.3`.
- **Context:** Doc claims "was 7 scattered copies" / "8 hardcoded duplicates" already fixed.
  Verify the claim is true *now*, not aspirational.
- **Acceptance/Test:**
  - A test `tests/test_config_single_source.py` greps the tree for the literal values
    (`3500`, `4500`, `30000`, lot `65`, floor value) and asserts they appear **only** in
    `risk_config.py` (allow-list for tests/docs).
  - Any violation found is listed (not auto-fixed) for a follow-up story.
- **Repo:** antariksh. **Depends-on:** S0.2.

---

## E1 — Strategy Validity Gate  `P0` (THE blocker)

Goal of epic: **prove the canonical strategy has non-negative expectancy on out-of-sample
data before any paper-or-live go-live.** Until E1 passes, E2/E3 produce a reliable money-loser.
This epic directly serves ABOUTME §2 ("Evidence over narrative — kill strategies with bad data").

### S1.1 — Reproduce the −13%/mo finding on a clean harness  `P0`
- **Goal:** Independently reproduce (or refute) `sherpa_phase2_verdict` using PORCUPINE.
- **Context:** Memory says canonical-as-configured = −13%/mo full-2024; old ₹287k backtest
  invalid. We must stand on a harness we trust, not a number in a memory file.
- **Acceptance/Test:**
  - PORCUPINE runs the *current* `canonical_strategy` config over full-2024 NIFTY with real
    captured bars (no synthetic fills, no look-ahead).
  - Output: monthly expectancy %, WR, EV/trade, max DD, trade count — written to
    `brahmand/backtest/results/canonical_2024_<date>.json`.
  - Result cross-checked against the three known-bad spots (NOT_UP/NOT_DOWN logic, TP/SL
    params, `combine_entry_scores`) — each confirmed correct in the harness path.
  - **Gate:** if expectancy ≤ 0, E2/E3 stay blocked and S1.2 opens.
- **Repo:** brahmand (+antariksh sim). **Depends-on:** E0.

### S1.2 — Parameter / logic recalibration to positive expectancy  `P0`
- **Goal:** Find a configuration (entry weights, score thresholds ±3, VIX gate, TP/SL) with
  **EV/trade > 0 and monthly expectancy ≥ +1%** on out-of-sample data, or formally kill the
  strategy and escalate to Chairman.
- **Context:** Per ABOUTME, the deliverable is *evidence of an edge*, not P&L. 60% WR with
  defined risk is the thesis — S1.2 tests whether the thesis survives contact with data.
- **Acceptance/Test:**
  - Walk-forward: calibrate on 2024 H1, validate on 2024 H2 (no peeking). Report both.
  - Candidate config must beat a do-nothing baseline AND a naive always-sell-straddle baseline.
  - All parameter changes land in `entry_weights.json` / `antariksh_rules.yaml` via the
    **24h-cooldown + git-commit** path (ABOUTME §8.8) — not hot-edited.
  - If no positive config found after N candidates: write `STRATEGY_KILL_REPORT.md`, stop.
- **Repo:** brahmand/antariksh. **Depends-on:** S1.1.

### S1.3 — Lock the validated config + freeze
- **Goal:** The proven config is the only one that can reach paper/live.
- **Acceptance/Test:**
  - `entry_weights.json` + rules hash recorded; session-end message reports the hash
    (ABOUTME §4 "Rules file hash: a1b2c3 verified").
  - A test asserts the live-loaded config hash == the validated hash.
- **Repo:** antariksh. **Depends-on:** S1.2.

---

## E2 — Paper Session Reliability (10 clean sessions)  `P1`

Goal of epic: 10 consecutive paper sessions with zero API errors, zero lost trades, correct
EOD square-off — the L0 exit criterion. Stories are the **verified-open** items from session
memory, not speculation.

### S2.1 — EOD square-off in run_bridge
- **Goal:** Every paper position is force-closed by 15:25 IST even when only `run_bridge`
  runs (no separate orchestrator).
- **Context:** `entry_path_and_stale_trade_blocker`: run_bridge has no EOD square-off; a stale
  EOD cleanup cron was bolted on. Make square-off a first-class path, not a cron afterthought.
- **Acceptance/Test:**
  - PORCUPINE scenario: open position at 14:00, advance clock to 15:25 → position closed,
    `trade_outcomes` written, P&L booked. Assert no position survives past 15:25.
  - Idempotent: running square-off twice does not double-book.
- **Repo:** brahmand. **Depends-on:** none.

### S2.2 — Resolve JSON↔DuckDB split-brain ledger
- **Goal:** One authoritative trade ledger. `order_ledger.json` and the execution DB never
  disagree about open positions.
- **Context:** `entry_path_and_stale_trade_blocker` + `paper_trade_never_completed_rootcause`:
  split-brain ledger + dead-DB readers were the real reason paper trades never completed.
- **Acceptance/Test:**
  - Define the single writer + reconciliation rule (doc in story).
  - Test: simulate a crash between JSON write and DB write → on restart, exactly one
    consistent view of open positions; no phantom and no orphan.
- **Repo:** brahmand. **Depends-on:** none.

### S2.3 — Demonstrate T23 split-brain recovery live
- **Goal:** Prove the `_LAST_BUILT_TRADE` cache recovery (TRADING_SYSTEM §5.4) works in a
  real session, not just unit tests.
- **Acceptance/Test:**
  - PORCUPINE fault-driver forces `tasks_output=None` after `place_entry_orders()` → chain
    reconciles from cache within 60s staleness cap → PM picks up the trade → normal exit.
  - Decision-trace shows one GO row, no phantom ₹0 P&L (regression for bug #5).
- **Repo:** brahmand. **Depends-on:** S2.2.

### S2.4 — Dual-chain subscription (NIFTY 1DTE) at 09:00
- **Goal:** Both index chains subscribed at session open without REST fallback.
- **Context:** TRADING_SYSTEM §10.3 open item "Dual-chain subscription Mon 09:00 NIFTY 1DTE".
- **Acceptance/Test:**
  - At 09:00 both chains have live option_prices rows; 0 REST calls during session
    (matches §10.2 stat).
  - Stale-fill guard (`_read_live_ltp`) confirmed active: an LTP=0 tick never clobbers last-good.
- **Repo:** antariksh. **Depends-on:** none.

### S2.5 — 10-session clean-run evidence ledger
- **Goal:** Machine-checkable proof of the L0 exit criterion.
- **Acceptance/Test:**
  - A `docs/L0_SESSION_LEDGER.md` (auto-appended) records per session: date, bars captured,
    API errors, GO/SKIP, trades opened/closed, EOD square-off OK, P&L, rules hash.
  - L0→L1 promotion requires 10 rows all green. No manual edits.
- **Repo:** antariksh. **Depends-on:** S2.1–S2.4.

---

## E3 — Two-Message Protocol  `P1`

Goal of epic: enforce ABOUTME §4 / TRADING_SYSTEM §8.1 exactly — **two Telegram messages per
session, nothing in between.** This is a discipline gate, not a feature: it removes the
session-brain's override window.

### S3.1 — Session-start verdict message (09:30)
- **Goal:** One message at gate-decision time: PASS (strategy, lots, SL, TP) or SKIP (reason).
- **Acceptance/Test:**
  - Verify whether this exists today; if partial, complete it.
  - PORCUPINE: a SKIP (VIX≥20) emits exactly the SKIP string; a GO emits exactly the PASS
    string with real strikes/SL/TP. Asserted by string match.
  - No second message before session end except hard errors.
- **Repo:** antariksh/brahmand. **Depends-on:** none.

### S3.2 — Session-end P&L message (14:35)
- **Goal:** One message: P&L, MTD, WR, EV/trade, max DD, kill-switch status, rules hash.
- **Acceptance/Test:**
  - All fields populated from real outcome tables (no placeholders, no fabricated P&L —
    `claude_hallucination_incident_may24`).
  - If a field is unavailable, message says so explicitly (fail-loud, not fake-zero).
- **Repo:** antariksh/brahmand. **Depends-on:** S2.5.

### S3.3 — No-streaming guard
- **Goal:** Architecturally forbid intra-session MTM messages.
- **Acceptance/Test:**
  - Test asserts that across a full simulated session exactly 2 broadcast calls fire
    (start + end), barring exceptions which use a distinct error channel.
- **Repo:** antariksh. **Depends-on:** S3.1, S3.2.

---

## E4 — Code Conformance Audit Loop  `P1` (the scheduled reviewer)

Goal of epic: stand up the **propose-only** scheduled reviewer that walks every Python file
and judges it against `TRADING_SYSTEM.md` — purpose, conformance, dead-code candidacy. It
**never edits or deletes**; it writes a findings ledger that becomes the E5 backlog. Full
design in `CODE_AUDIT_LOOP.md`.

### S4.1 — Wire + schedule the audit loop
- **Goal:** `ralph/code_audit_loop.py` runs on cron, incremental + nightly full sweep,
  writes `docs/REVIEW_FINDINGS.md` + `data/code_audit.jsonl`.
- **Acceptance/Test:**
  - Dry-run over antariksh+brahmand produces a findings file with one record per reviewed
    file: `{path, verdict, reason, conformance, remove_candidate, severity}`.
  - Loop touches nothing (assert `git status` clean after a run except the findings files).
  - Cron entry installed (work-hours incremental + nightly full). See CODE_AUDIT_LOOP.md.
- **Repo:** antariksh. **Depends-on:** none.

### S4.2 — Findings → triage workflow
- **Goal:** A human/DS-gated step converts `remove_candidate`/defect findings into E5 stories.
- **Acceptance/Test:**
  - `ralph/triage_findings.py --since <ts>` lists new findings grouped by severity; emits a
    ready-to-file issue body per finding (does not auto-create — propose only).
  - No file is removed without a Chairman-approved E5 story referencing the finding id.
- **Repo:** antariksh. **Depends-on:** S4.1.

---

## E5 — Cleanup & Scalability  `P2` (DEFERRED, documented)

Goal of epic: shrink to a clean, scalable tree — but only after E1–E3. Seeded by E4 findings.
Known items already on record:

### S5.1 — Retire v4 DuckDB multi-TF aggregator → SQLite
- **Context:** `multitf_duckdb_to_sqlite_consolidation` — cross-process DuckDB lock = disaster;
  core built+verified 2026-06-10, cutover staged. **Acceptance:** all readers on SQLite
  multi-TF; v4 DuckDB files archived; per-index split preserved (`v4_per_index_db_split` —
  NEVER merge). **Repo:** antariksh. **Depends-on:** E2.

### S5.2 — Remove confirmed-dead files from audit findings
- **Context:** E4 produces `remove_candidate` list. **Acceptance:** each removal is its own
  commit referencing the finding id; PORCUPINE + integration tests stay green
  (`test_integration_end_to_end.py` 39/39). **Repo:** both. **Depends-on:** S4.2.

### S5.3 — pyflakes/undefined-name gate in CI
- **Context:** `dambuilder_live_validation_20260612` — 3 prod-dead paths were all
  undefined-name class; a pyflakes gate was proposed. **Acceptance:** pre-commit + CI fail on
  undefined names across both repos. **Repo:** both. **Depends-on:** none (can pull earlier
  if E2 keeps hitting undefined-name bugs).

---

## 3. The Two Ralph Loops (how this backlog gets executed)

```
┌─────────────────────────────────────────────────────────────────┐
│  BUILD LOOP  (Track A — go-live)                                 │
│  GH issues (E0→E1→E2→E3) → DeepSeek implements one → tests →     │
│  Director validates → close → next issue. Human-gated merges.    │
└─────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────┐
│  AUDIT LOOP  (Track B — cleanliness, parallel)                   │
│  cron → code_audit_loop.py walks py files vs TRADING_SYSTEM.md → │
│  REVIEW_FINDINGS.md (propose only) → triage → E5 stories.        │
│  NEVER edits or deletes. Director/Chairman gate every removal.   │
└─────────────────────────────────────────────────────────────────┘
```

Build Loop drives the system *up*. Audit Loop keeps it *clean*. They never block each other.

## 4. Definition of "Go-Live Ready" (the only checklist that matters)

- [ ] E0 done — config single-source, no contradictions.
- [ ] **E1 done — proven positive expectancy on out-of-sample data, config frozen + hashed.**
- [ ] E2 done — 10 clean paper sessions in the auto-ledger.
- [ ] E3 done — exactly two messages per session, no fabricated fields.
- [ ] Audit loop (E4) running; no P0/P1 conformance findings open.

Until **all five** are checked, the system stays paper. ABOUTME §2: the pressure is on the
system's correctness, not the P&L.

---

## 5. Collaboration Workflow — GitHub Label State Machine

Every story is a GitHub issue on `venkatseshadri/antariskh`. Work flows between three actors
via **mutually-exclusive workflow labels** — the actor who finishes a stage removes their
label and adds the next. A glance at the label tells you whose court the ball is in.

```
        ┌──────────────┐  DeepSeek picks the next ready issue
        │  ds:ready    │  ◄──────────────────────────────┐
        └──────┬───────┘                                 │
               │ DeepSeek implements + tests             │ Claude/Chairman
               ▼                                         │ bounce back
        ┌──────────────┐                          ┌──────────────────┐
        │   ds:done    │  awaiting review         │ changes:requested│
        └──────┬───────┘                          └────────▲─────────┘
               │ Claude picks it up                        │
               ▼                                           │ review FAILS
        ┌──────────────┐  Claude reviews diff vs ──────────┘
        │ claude:review│  story Test conditions
        └──────┬───────┘
               │ review PASSES
               ▼
        ┌──────────────────┐  Chairman gives final yes
        │ chairman:approve │ ──────────────►  issue closed / merged
        └──────────────────┘
```

| Label | Color | Whose turn | Meaning |
|---|---|---|---|
| `ds:ready` | magenta | **DeepSeek** | Picked up next. Deps clear. Implement per the story's Acceptance/Test. |
| `ds:done` | yellow | DeepSeek → idle | Implemented + tests pass. Awaiting Claude review. |
| `claude:review` | blue | **Claude** | Claude is reviewing the diff against the story's Test conditions. |
| `changes:requested` | orange | DeepSeek | Review failed. Comment lists what to fix. Goes back to `ds:ready`. |
| `chairman:approve` | green | **Venkat** | Passed Claude review. Awaiting your final approval to close. |

**Rules of the machine:**
1. Exactly **one** workflow label per issue at any time. The acting party swaps it.
2. DeepSeek only ever pulls `ds:ready`. It never self-approves — it moves to `ds:done` and stops.
3. Claude only reviews `ds:done`; on pickup it sets `claude:review`. Claude **does not fix** —
   on failure it sets `changes:requested` with a comment; on pass it sets `chairman:approve`.
4. Only the Chairman moves `chairman:approve` → closed.
5. A dependent story stays **without** `ds:ready` until its predecessor is `chairman:approve`d.

**Structural labels (always present, never swapped):** `epic:E0`…`epic:E5`, `P0`/`P1`/`P2`.

The audit loop's removal candidates (E5) enter this same machine: a finding becomes a
`ds:ready` issue only after the Chairman approves the E5 story that references its finding id.
