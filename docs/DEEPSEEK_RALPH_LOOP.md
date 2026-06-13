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

**One issue at a time.** Never hold two. Never skip ahead to a dependent story — dependent
stories do not carry `ds:ready` until their predecessor is `chairman:approve`d.

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
# leave yourself assigned; STOP. Do not close. Do not add claude:review / chairman:approve.
```

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

## 8. Scheduling the loop

A reference loop wrapper lives at `cron/ds_ralph_loop.sh` (create it from §1's commands). Run
it via cron with a singleton guard so two loops never run at once:

```cron
# DeepSeek build loop — every 15 min, work hours, Mon–Fri. Singleton via flock.
*/15 9-22 * * 1-5  trading_ceo  /usr/bin/flock -n /home/trading_ceo/antariksh/locks/ds_ralph.lock \
    /home/trading_ceo/antariksh/cron/ds_ralph_loop.sh >> logs/ds_ralph.log 2>&1
```
- `flock -n` ensures one iteration at a time (`feedback_cron_shell_wrappers`).
- Off-hours/weekends optional — strategy/cleanup stories (E1/E5) can run any time; session
  stories (E2/E3) are best validated against fresh market data on weekdays.

---

## 9. One-paragraph summary (pin this)

Every X minutes: grab the lowest unassigned `ds:ready` issue, self-assign it, read its PRD
story, implement it surgically to the 9-dimension rubric, prove it with green tests
(story + integration 39/39 + PORCUPINE), commit on a branch referencing `#N` (never "closes"),
comment your summary, and flip `ds:ready`→`ds:done`. Then stop. You do not review. You do not
approve. You do not close. Claude reviews `ds:done`; the Chairman closes. That separation is
the whole point — code enforces, the loop never lets one actor mark its own work complete.
