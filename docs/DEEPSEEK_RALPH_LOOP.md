# DeepSeek Ralph Loop — Build Runbook

> **You are DeepSeek, the implementer.** This file is your operating contract. Run a ralph
> loop every **X minutes** (default 15), pick up one ready story, implement it to spec and to
> the code-design rubric below, prove it with tests, then **hand it back** — you never close.
>
> **Authority boundary (hard):** You implement. Claude reviews. Chairman approves & closes.
> A ticket cannot be closed until *tests pass* **and** *Claude's review passes* **and** the
> Chairman approves. You only ever move a ticket from `ds:ready` → `ds:done`. Nothing else.

Source of truth: `antariksh/docs/PRD_GOLIVE.md`. Issues: `venkatseshadri/antariskh` (GitHub).
Label state machine: PRD §5.

---

## 1. The loop (every X minutes)

```
loop:
  1. PICK   — get the next actionable ds:ready issue (lowest number, unassigned).
  2. CLAIM  — self-assign it (the lock). If none ready → sleep X min, repeat.
  3. READ   — read the issue body + its PRD story (Sx.y) + the files it touches.
  4. BUILD  — implement to Acceptance/Test AND the §3 code-design rubric.
  5. TEST   — write/extend tests; run them + integration + PORCUPINE. Must be green.
  6. COMMIT — branch per issue, conventional commit referencing #N, push.
  7. HANDBACK — comment summary + commits + test output; swap ds:ready → ds:done.
  8. STOP on that issue. Sleep X min. Repeat from 1.
```

**ONE issue at a time — this is mandatory, not a style preference.** Pick exactly one
`ds:ready` issue per loop iteration, finish it to `ds:done`, then stop. Never hold two.
The reason is **context overload**: an LLM that loads three stories' files at once degrades —
it confuses requirements, edits the wrong file, and produces shallow work. A single story
keeps the working set small enough to reason about precisely. Never skip ahead to a dependent
story either — dependent stories do not carry `ds:ready` until their predecessor is
`chairman:approve`d.

### Pick + claim (exact commands)
```bash
# next ready, unassigned, lowest number
ISSUE=$(gh issue list -R venkatseshadri/antariskh \
  --label ds:ready --state open --json number,assignees \
  -q 'map(select(.assignees|length==0)) | sort_by(.number) | .[0].number')
[ -z "$ISSUE" ] && { echo "nothing ready"; exit 0; }
gh issue edit -R venkatseshadri/antariskh "$ISSUE" --add-assignee @me   # the lock
gh issue view -R venkatseshadri/antariskh "$ISSUE"                      # read the story
```

---

## 2. Read the spec, not just the title

Every issue names its PRD story (e.g. `S0.2`). Open `antariksh/docs/PRD_GOLIVE.md`, find that
story, and treat its **Goal + Acceptance/Test** as the contract. The issue is the summary; the
PRD is the law. If the PRD and a contradicting in-code value disagree, **the resolved value in
PRD §1 wins**; if still ambiguous, comment on the issue asking the Chairman — do not guess.

---

## 3. Code-design rubric (every change must satisfy this)

The goal is **highly scalable, readable, maintainable, well-designed code that any human or
system can understand with little effort.** Before you set `ds:done`, self-check all nine:

| Dimension | What "pass" means |
|---|---|
| **purpose** | The file/function has one clear reason to exist. No dead code added. |
| **test_coverage** | New/changed logic is exercised by a test. Critical paths covered, not just happy path. |
| **simplification** | Minimum code that solves it. No single-use abstractions, no speculative generality. If 200 lines could be 50, write 50. |
| **documentation** | Module + public-function docstrings. Comments only where the *why* isn't obvious. |
| **complexity** | Short functions (<60 LOC), low nesting, low cyclomatic complexity. Readable top-to-bottom. |
| **performance** | No O(n²) on hot paths, no per-tick rescans, no repeated I/O that should be cached. |
| **srp_modularity** | Single responsibility per module/class/function. No god-files (<500 LOC). |
| **naming** | Intention-revealing names for modules/classes/methods/vars. No `tmp`, `data2`, `x1`. |
| **design** | Follows system philosophy: **code enforces risk, LLMs only explain. Fail-closed. Deterministic over LLM for risk/execution.** Never move a risk gate into LLM judgment. |

**Review applies to ALL file types, not just `.py`.** Every file your change touches —
Python, markdown docs, JSON/YAML config, shell scripts, **and cron tables** — must pass the
rubric. For shell/cron specifically: valid shebang, no dead path references (a job pointing at
a script that no longer exists = a stale job — fix or remove it), no references to `.disabled`
units, well-formed cron lines. The audit loop (`ralph/code_audit_loop.py`) now sweeps all of
these and will flag them; don't ship a change that leaves a dead link or a stale job behind.

Non-negotiables from the constitution:
- **Surgical changes.** Touch only what the story needs. Don't reformat or "improve" adjacent code. Every changed line traces to the story.
- **Config changes** (SL/TP/VIX/lot/floor/weights) go through the **24h-cooldown + git-commit** path — never hot-edit live rules.
- **No fabricated data.** Never invent P&L/backtest numbers. Use real captured data or fail loud. (`claude_hallucination_incident_may24`)
- The audit reviewer (`ralph/code_audit_loop.py`) will flag violations of this rubric on its next sweep. Don't ship code that your own review tool would flag.

---

## 4. Test before handback (the gate)

A story is **not** `ds:done` until:
```bash
# 1. the story's own Acceptance/Test conditions pass (write them as real tests)
python3 -m pytest tests/test_<story>.py -q
# 2. the integration suite stays green
python3 tests/test_integration_end_to_end.py          # must be 39/39
# 3. PORCUPINE scenarios stay green (if execution/position paths touched)
python3 -m pytest tests/ -k porcupine -q
```
If anything is red, you are not done. Fix it or, if blocked >1 day, comment the blocker and
leave the issue `ds:ready` (assigned to you) — do not set `ds:done` on red tests.

---

## 5. Commit + push

```bash
git checkout -b ds/issue-<N>-<slug>
# ... implement ...
git add <only the files this story needs>
git commit -m "feat(S0.2): unify free-cash floor to risk_config — closes nothing, refs #<N> [deepseek]"
git push -u origin ds/issue-<N>-<slug>
```
- Conventional Commit subject ≤50 chars. Body explains the *why* if non-obvious.
- Reference `#<N>`. **Do not** write "closes #N" / "fixes #N" — that would auto-close on merge,
  which violates the review gate. Use "refs #N".
- Tag `[deepseek]` to match the repo's authorship convention.

---

## 6. Handback (the only label move you may make)

When tests are green and pushed:
```bash
gh issue comment -R venkatseshadri/antariskh <N> --body "$(cat <<'EOF'
### DeepSeek — implementation complete, awaiting review
- Branch: ds/issue-<N>-<slug>  ·  Commits: <sha1>, <sha2>
- Acceptance/Test: <which conditions, how met>
- Tests: pytest <X passed>; integration 39/39; porcupine green
- Rubric self-check: purpose/test/simplify/docs/complexity/perf/srp/naming/design — all pass
- Notes / risks: <anything Claude should look at>
EOF
)"
gh issue edit -R venkatseshadri/antariskh <N> --remove-label ds:ready --add-label ds:done
git checkout master   # CRITICAL: return to master so the next pickup starts on a clean tree
# leave yourself assigned; STOP. Do not close. Do not add claude:review / chairman:approve.
```
> **Always `git checkout master` after handback.** If you stay on the feature branch, the next
> loop iteration (or any other process) commits to the wrong branch. (Learned from the live
> loop test, 2026-06-13.)

After this you are **done with that issue.** Sleep X minutes, loop again.

---

## 7. What happens next (so you know your boundary)

```
ds:done  ── Claude picks it up ──►  claude:review
                                       │
              review FAILS ────────────┤────────── review PASSES
                    │                                   │
            changes:requested  ──► back to ds:ready    chairman:approve
            (Claude comments what to fix; you redo)         │
                                                       Chairman closes
```

- If you see **`changes:requested`** on an issue assigned to you: read Claude's comment, that
  issue is now effectively `ds:ready` again — fix per the comment, re-run §4, re-handback (§6).
- You **never** apply `claude:review`, `chairman:approve`, or `changes:requested` yourself.
- You **never** close an issue. Even when "done", you stop at `ds:done`.

---

## 8. Scheduling the loop (headless, no interactive approval)

The loop runs **unattended on cron** — no human at a prompt. That means the agent runs in
**headless / print mode** with permissions **pre-granted in a sandbox** (there's nobody to
click "allow"). Two separate runners:

| Loop | Runner | What it may do |
|---|---|---|
| **Build** (this doc) | `deepseek` headless (its `-p`/print mode or API) | implement, test, commit to a **branch**, push, set `ds:done`. **Never** `claude -p` — Board rule: Claude validates only, DeepSeek implements (`feedback_validator_no_fixing`). |
| **Review** | `claude -p` headless | review `ds:done` → set `claude:review` then `chairman:approve` or `changes:requested`. Never closes. |

Reference wrapper `cron/ds_ralph_loop.sh` (create from §1's commands). It picks **exactly one**
issue, runs the agent headless via **`opencode run`**, and captures the reasoning/output to a
per-issue progress file:
```bash
#!/usr/bin/env bash
set -euo pipefail
cd /home/trading_ceo/antariksh
REPO=venkatseshadri/antariskh

# PICK + CLAIM exactly ONE issue (never two — context overload, see §1)
ISSUE=$(gh issue list -R "$REPO" --label ds:ready --state open \
  --json number,assignees -q 'map(select(.assignees|length==0))|sort_by(.number)|.[0].number')
[ -z "$ISSUE" ] && { echo "nothing ready"; exit 0; }
gh issue edit -R "$REPO" "$ISSUE" --add-assignee @me     # the lock

mkdir -p ralph/progress

# --- TOKEN-BURN BRAKE 1: per-day issue cap ---
DAY=$(date +%Y%m%d); CAP=8
DONE_TODAY=$(ls ralph/progress/ 2>/dev/null | grep -c "\.${DAY}\." || true)
[ "${DONE_TODAY:-0}" -ge "$CAP" ] && { echo "daily cap $CAP reached"; exit 0; }

# Build loop runs on DeepSeek (NOT Claude — openclaw/validator rule). --thinking/output → file.
# --- TOKEN-BURN BRAKE 2: per-run step + wall-clock cap (no infinite agent loop) ---
timeout 1800 opencode run "Implement ONLY GitHub issue #$ISSUE. Read its body (self-contained) \
and its docs/stories/ brief. Follow DEEPSEEK_RALPH_LOOP.md §3 rubric (all file types incl \
cron/shell). Branch ds/issue-$ISSUE, make tests green (story + integration 39/39 + PORCUPINE), \
push, then set ds:done and comment the §6 summary. Do NOT close or self-approve." \
  --model deepseek \
  --max-steps 40 \
  > "ralph/progress/${ISSUE}.${DAY}.$(date +%H%M%S).md" 2>&1
```
- **One issue per run.** Do not pass "issue #x and #y" — the cadence handles the next one. Two
  issues in one prompt overloads context (§1).
- **Three token-burn brakes:** (1) `CAP=8` issues/day via the progress-file count; (2)
  `timeout 1800` + `--max-steps 40` bound a single run (tune to your model/issue size); (3)
  `flock -n` singleton = never two runs at once. If an issue can't finish inside the step
  budget, the agent leaves it `ds:ready` (assigned) with a progress file — it does **not**
  thrash; a human/next-tick picks it up.
- **Model = DeepSeek (or MiniMax), never Claude.** Claude is prohibited inside opencode/openclaw
  and is validator-only (`feedback_validator_no_fixing`). The review loop below uses `claude -p`
  **directly**, not through opencode.
- The progress file `ralph/progress/<issue>-<ts>.md` is the verbose thinking/action log (audit
  trail + input for Claude's review); the issue comment is the structured handback (§6).

```cron
# DeepSeek build loop — every 15 min, every day (sim/recorded data, not live ticks → 7 days OK).
# Per-day cap + per-run timeout live inside the wrapper; flock = singleton.
*/15 9-22 * * *  trading_ceo  /usr/bin/flock -n /home/trading_ceo/antariksh/locks/ds_ralph.lock \
    /home/trading_ceo/antariksh/cron/ds_ralph_loop.sh >> logs/ds_ralph.log 2>&1

# Claude review loop — every 20 min, every day. Picks up ds:done, reviews, labels. Never closes.
*/20 9-22 * * *  trading_ceo  /usr/bin/flock -n /home/trading_ceo/antariksh/locks/claude_review.lock \
    /home/trading_ceo/antariksh/cron/claude_review_loop.sh >> logs/claude_review.log 2>&1
```
- **Every day** (not M–F): the loop builds + tests against PORCUPINE sim/recorded data, so it
  doesn't need live market hours. E1/E5 especially are weekend-friendly.
- Hour window `9-22` is just to avoid overnight runaway; widen to `* * * *` if you want 24/7.

**Two kinds of "approval" — only one is removed by headless cron:**
- *Per-action tool prompts* (edit/bash/push) → **removed** by headless + pre-granted sandbox
  permissions. This is the autonomy you want.
- *The workflow close gate* (`chairman:approve` → closed) → **kept, by design.** Cron does the
  labor; the label state machine controls promotion. The loop can build + review fully
  hands-off, but a human still makes the final merge.

**Hard guardrails (because no human is watching a headless run):**
- Pre-authorize permissions **inside a sandbox** — never `--dangerously-skip-permissions` on
  an unconstrained shell.
- **Push to a branch; never auto-merge to master.** Even unattended, the loop cannot deploy.
- `flock -n` = one iteration at a time (`feedback_cron_shell_wrappers`). Paper-only; the
  constitution resource limits still apply.

---

## 9. One-paragraph summary (pin this)

Every X minutes: grab the lowest unassigned `ds:ready` issue, self-assign it, read its PRD
story, implement it surgically to the 9-dimension rubric, prove it with green tests
(story + integration 39/39 + PORCUPINE), commit on a branch referencing `#N` (never "closes"),
comment your summary, and flip `ds:ready`→`ds:done`. Then stop. You do not review. You do not
approve. You do not close. Claude reviews `ds:done`; the Chairman closes. That separation is
the whole point — code enforces, the loop never lets one actor mark its own work complete.
