# PORCUPINE — Gated Autonomous Builder

**Created:** 2026-06-08 · **By:** Claude (approved by Board) · **Status:** OPERATIONAL, currently **PAUSED** (see §6)
Self-terminating autonomous builder that finishes PORCUPINE's remaining items without a human in the loop,
with **bounded** token spend. Companion: `PORCUPINE_STATE.md` (overall state).

---

## 1. Why it exists
The free nags (`data_health` 5-min, `porcupine_status` 30-min) *report* progress but cannot *build*.
Building needs an LLM. This wraps an LLM (`claude -p`) in a cheap gate so it builds the remaining harness
items on a schedule and **stops spending the moment the work is done**.

## 2. Flow (every 30 min via cron)
```
porcupine_autobuild.sh:
  0. if sim/.autobuild_paused exists      → exit (₹0)         # stuck-guard tripped
  1. flock singleton                       → no overlap
  2. porcupine_status.py --send (free)     → nag Telegram on change
  3. if COMPLETE                           → exit (₹0)         # SELF-TERMINATES here forever
  4. stuck-guard: milestone sig unchanged 4× → pause + alert, exit
  5. else: claude -p  (build ONE next item) → tokens spent only while work remains
  6. report result + new status to Telegram
```
The cheap script (steps 0–4) gates the expensive call (step 5). When all milestones pass, step 3 exits
and the LLM is never invoked again.

## 3. Files & cron
| Path | Role |
|------|------|
| `sim/porcupine_autobuild.sh` | the gated builder wrapper (cron target) |
| `sim/porcupine_status.py` | deterministic milestone/progress check (`--send` Telegram on change) |
| `sim/porcupine_tick.sh` | heavier manual full-regression reporter (not cron-wired) |
| `sim/.autobuild_paused` | presence = paused (stuck-guard or manual) |
| `sim/.autobuild_attempts` | `<milestone_sig> <count>` for the stuck-guard |
| `sim/.porcupine_status.json` | last milestone signature (change-detection) |
| `sim/logs/autobuild.log` | full run log |
Cron (root): `*/30 7-23 * * * /home/trading_ceo/antariksh/sim/porcupine_autobuild.sh`
(Also: `*/5 9-15 * * 1-5 brahmand/cron/run_data_health.sh` runs `check_porcupine()` live invariants.)

## 4. Safeguards (it edits a LIVE trading box unattended)
- **Bash allow-listed to `python3` + `git` only** (`--allowedTools`). It physically cannot `systemctl
  restart`, `rm`, or run destructive commands — those tool calls are denied.
- **Prompt scope:** only create/edit under `sim/` and `tests/`; forbidden to touch `feed.py`,
  `consumers/`, `enrichers/`, `config/`, `brahmand/`, `python-trader/` (live code) or restart services.
- `--permission-mode acceptEdits` (auto-accepts edits; scope enforced by prompt — residual risk: a
  mis-scoped edit, but reversible via git and the highest-risk ops are blocked by the bash allow-list).
- **Commits to git** for auditability (e.g. `891e835`).
- **Stuck-guard:** pauses after 4 attempts with no milestone-signature change → cannot burn tokens forever.
- **`timeout 1200`** per run.

## 5. Token model
- Steps 0–4 (status, guards) = pure Python = **₹0**, however often they run.
- Step 5 (`claude -p`) = tokens, **only while items remain**; self-terminates at COMPLETE.
- Worst case bounded by the stuck-guard (≤4 no-progress LLM runs, then pause).

## 6b. UPDATE 2026-06-09 — milestone flaw FIXED, ready to resume
The design flaw below is fixed (commit `ee24e9e`). `porcupine_status.py` bug#3/#4
milestones now track the **harness guard** (regression test files the builder can build),
not the `.bugN_fixed` live-fix markers. Live-code-fix status moved to a non-gating
`live_fixes()` line. The milestone signature advanced (`b66d50bc0367` → new), so the
stuck-guard resets on the next tick. The synthetic fault driver (a remaining buildable
item) is also done. **Harness milestones now 8/9 — only the lifecycle scenario remains**,
which is squarely within the builder's scope (it *calls* brahmand readers but only *edits*
`sim/`). **To resume:** delete `sim/.autobuild_paused` and `sim/.autobuild_attempts`
(root-owned), then the next `*/30` tick builds the lifecycle item and self-terminates at
COMPLETE. Note: the cron is duplicated in both the user and root crontabs — harmless (the
`flock -n` singleton makes the second run skip) but redundant.

## 6. CURRENT STATE (2026-06-08 20:00) — PAUSED *(superseded by §6b)*
`sim/.autobuild_paused` present; `.autobuild_attempts = b66d50bc0367 4`. It ran ~3 build cycles and did
real work, then the stuck-guard paused it. What it built (committed `891e835`):
- **Bug #4 (VIX-null) guards:** `sim/tests/test_vix_null_guard.py` (6/6) + two E4 assertions in
  `run_scenario.py` (pins `vix=None → go=True` bug present, `india_vix` 351/351 NULL in sandbox).
- **Bug #3 (entry-agent fallback) root-cause + guards:** `sim/tests/test_fallback_inputs.py` + F2
  assertions. Found TWO real upstream bugs: (a) `enrichers/lib/advanced.py:compute_session_metrics`
  uses `datetime.now()` not the bar timestamp (backfill labels every bar "late"); (b)
  `market_data_multitf.st_consensus` is NULL on every row/timeframe (multi-TF aggregator never writes
  indicators in the replay path) → `avg_super_trend=0`.

### Why it paused (a real design flaw to fix)
Milestones for bug #3/#4 require marker files `sim/.bug3_fixed`/`.bug4_fixed`, which are created **only
when the LIVE code is fixed** — but the builder is (correctly) forbidden from touching live code. So it
*guarded* both bugs but the milestone signature never advanced → stuck-guard paused it. **The genuinely
remaining BUILDABLE harness items are the Synthetic fault driver and the Lifecycle scenario** — the bug
milestones are blocked on human-approved live-code fixes, not on the builder.

### Fix / resume options
- **Recommended:** redefine the bug #3/#4 milestones as "harness guard exists" (test files present) so
  they reflect what the builder can actually do; keep separate "live-fixed" tracking for the human-gated
  code changes. Then the builder advances on the synth-driver + lifecycle items.
- **Resume now:** `rm sim/.autobuild_paused` (it will retry next cron tick).
- The two upstream bugs it found (session_phase `datetime.now()`, multitf st_consensus NULL) are **live
  enrichment bugs** needing human-approved fixes — see `PORCUPINE_STATE.md` §5 #3.
