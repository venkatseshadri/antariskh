# CODE AUDIT LOOP — Scheduled, Propose-Only File Conformance Reviewer

> **Companion to:** `PRD_GOLIVE.md` (epic E4) · **Spec of record:** `TRADING_SYSTEM.md`
> **Authority:** PROPOSE ONLY. Never edits, never deletes. Every action it suggests is
> human/Chairman-gated. This is the Director's *validation apparatus* — it raises, DeepSeek
> implements (Board rule 2026-06-12).

## 1. What it does

`ralph/code_audit_loop.py` walks **every project file** — not just Python: `.py`, `.md`,
`.json`, `.yaml/.yml`, `.sh`, `.toml/.cfg/.ini`, `.sql`, **and cron tables** (antariksh,
brahmand, python-trader; venv/site-packages/archives/logs/recordings excluded) — and judges
each against the spec + the 9-dimension rubric, per file type:

- **Python** — orphan (imported anywhere / entrypoint / cron-referenced? else
  `REMOVE_CANDIDATE`), test coverage, docstrings, long functions (>60 LOC), god-files
  (>500 LOC), SRP smell, weak identifiers.
- **Shell + cron** — valid shebang, **dead path references / stale jobs** (a job pointing at
  a script that no longer exists), references to `.disabled` units, malformed cron lines.
- **JSON / YAML** — parse validity (a config that doesn't parse is `high` severity).
- **Markdown** — dead local links (points to a missing file).
- **All types** — conformance (dir appears in `TRADING_SYSTEM.md` repo map?), TODO/FIXME density.

Output (the only things it writes):
- `docs/REVIEW_FINDINGS.md` — human-readable latest sweep, sorted by severity.
- `data/code_audit.jsonl` — append-only ledger, one record per reviewed file.
- `data/code_audit_state.json` — cursor (last commit per repo + rolling window position).

It asserts its own safety: after a run, `git status` is clean **except** those three files.

## 2. Backends

| Backend | Needs | Use |
|---|---|---|
| `heuristic` (default) | nothing | Deterministic structural signals. Runs today, every cycle. |
| `llm` | `$CODE_AUDIT_LLM_CMD` (prompt on stdin → JSON on stdout) | Semantic conformance verdict vs the spec. Wired by DeepSeek in story **S4.1**. Falls back to heuristic if the command is unset or errors. |

The `llm` backend is model-agnostic on purpose — point `CODE_AUDIT_LLM_CMD` at DeepSeek,
Claude-via-bridge, or any client. Example:
```bash
export CODE_AUDIT_LLM_CMD='python3 tools/ds_review_client.py'   # reads stdin, prints JSON
```

## 3. Continuous loop — per-file review state (not a one-shot sweep)

This is a **ralph loop**, not a single pass. A manifest `data/code_audit_manifest.json` tracks
every file: `{hash, last_reviewed, verdict, severity}`. On each run the loop classifies files:

- **new** — never reviewed → review now.
- **changed** — content hash differs from the manifest → re-review.
- **stale** — last reviewed > `STALE_DAYS` (14) ago → re-review.
- **reviewed** — hash matches and fresh → **skip** (already covered).

So once a file is reviewed it is *marked reviewed* and left alone until it changes or goes
stale. You always know coverage: "N/Total files up-to-date reviewed", shown in
`REVIEW_FINDINGS.md` and via `--status`.

```bash
python -m ralph.code_audit_loop --status              # coverage report, reviews nothing
python -m ralph.code_audit_loop --mode incremental    # review up to REVIEW_BATCH (60) needing review
python -m ralph.code_audit_loop --mode full           # review ALL that need it (new+changed+stale)
python -m ralph.code_audit_loop --mode full --force    # re-review everything, ignore manifest
python -m ralph.code_audit_loop --mode full --backend llm
```

`incremental` clears 60 files per run, so a fresh tree (~1,600 files) reaches full coverage
over ~27 runs, then steady-state only changed/stale files resurface — cheap and continuous.
Tune `REVIEW_BATCH` / `STALE_DAYS` at the top of `code_audit_loop.py`.

## 4. Schedule (cron)

Reviewer runs only need to be frequent enough to catch changes — code doesn't change every
minute, so a tight loop wastes cycles. Recommended (`/etc/cron.d/antariksh-code-audit`):

```cron
# Incremental review every 20 min, every day — chips through the backlog 60 files/run,
# re-reviews anything changed/stale. Manifest tracks per-file review state.
*/20 * * * *  trading_ceo  cd /home/trading_ceo/antariksh && \
    /usr/bin/python3 -m ralph.code_audit_loop --mode incremental \
    >> logs/code_audit.log 2>&1

# Full nightly review of everything that needs it (semantic LLM backend if CODE_AUDIT_LLM_CMD set)
30 1 * * *  trading_ceo  cd /home/trading_ceo/antariksh && \
    /usr/bin/python3 -m ralph.code_audit_loop --mode full \
    >> logs/code_audit.log 2>&1
```

> Cron must call via the repo dir + a wrapper that sets env/pgrep-guards if the LLM backend
> is heavy (`feedback_cron_shell_wrappers`). For the heuristic backend the inline form above
> is fine.

## 5. From findings to fixes — the gated flow

```
code_audit_loop.py  ──►  REVIEW_FINDINGS.md + code_audit.jsonl   (PROPOSE)
        │
        ▼
triage_findings.py (S4.2) ──► groups new findings, emits issue-ready bodies   (PROPOSE)
        │
        ▼   Chairman/Director gate — nothing auto-removed
   E5 story / GH issue ──► DeepSeek implements removal or fix ──► Claude reviews ──► approve
```

No file is ever removed by the loop. A `REMOVE_CANDIDATE` only becomes real deletion through
an E5 story that a human approved — and that deletion must keep
`tests/test_integration_end_to_end.py` at 39/39 and PORCUPINE green.

## 6. First sweep result (2026-06-13, heuristic)

843 files reviewed, **52 removal candidates**, plus god-file/TODO flags. Notable orphans:
`agents/entry/toolkit.py`, `crews/telegram_reporter.py`, `deploy/antariskh_watchdog.py`,
`enrichers/lib/sentiment.py`, `sim/synth_option_chain.py`. These are *candidates only* — some
may be entrypoints the heuristic missed (the LLM backend + human triage resolve that). Do not
delete from this list directly; route through §5.
