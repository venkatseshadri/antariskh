# OUROBOROUS — Autonomous Loop-Based Development & Fixing

> The serpent eating its tail. An endless **build → review → deploy → build** cycle that
> develops *and* fixes the trading system on its own. DeepSeek builds in isolation, Claude
> reviews, a gate ships to prod, the loop comes back around.
>
> (Spelling "OUROBOROUS" is intentional, kept like the `antariskh` repo name. Canonical: *Ouroboros*.)

**Status:** 2026-06-14 — infra live, first real builds running. PRD epic = **E6**.
Umbrella over the two ralph loops + dev/prod isolation + deploy gate.

---

## 1. The loop (one picture)

```
            ┌─────────────────────── ds:ready (GitHub issue) ───────────────────────┐
            │                                                                        │
            ▼                                                                        │
   ┌──────────────────┐      ds:done      ┌──────────────────┐   chairman:approve   │
   │  BUILD LOOP       │ ───────────────► │  REVIEW LOOP      │ ──────────────►  Chairman
   │  (DeepSeek/dsdev) │   branch pushed  │  (Claude, R/O)    │   comment+verdict    │
   └──────────────────┘                  └──────────────────┘                       │
            │ builds in isolated clone                                              │
            │ (sandbox, no prod access)                                             │
            ▼                                                                        │
   ┌──────────────────┐  approved branch  ┌──────────────────┐                      │
   │  DEPLOY GATE      │ ◄──────────────── │  (human runs)    │                      │
   │  prod ← branch    │  markets-closed   └──────────────────┘                      │
   │  smoke + rollback │                                                             │
   └──────────────────┘ ──────────────── new code in prod ────────────────────────►┘
```

The **only** path from dev to production is the deploy gate. Everything else is isolated.

---

## 2. Components

| Part | File | Role |
|---|---|---|
| Build loop | `cron/ds_ralph_loop.sh` | Pull lowest `ds:ready`, opencode/DeepSeek implements it in the dev clone, run tests, push branch, set `ds:done`. Runs as **dsdev**. |
| Review loop | `cron/claude_review_loop.sh` | Validate `ds:done` + `[deepseek]` commits read-only; comment verdict on the issue + Telegram; integrity sweep for self-marked ✅✅. **Never** flips labels/pushes (Option A+). |
| Deploy gate | `cron/deploy_gate.sh` | The only dev→prod bridge: markets-closed + no-open-position + merge approved branch + PORCUPINE smoke + rollback on fail + service restart. Run by a **trusted operator**, not dsdev. |
| Schedule | `/etc/cron.d/antariksh` ← `cron/antariksh-ralph.cron` | Build + review cadence. |
| Harness | `sim/run_scenario.py` (PORCUPINE) | The validation harness — mock-websocket E2E, no live broker/data. No new harness needed. |
| Guard | `deploy/hooks/ds_guard.sh` | Pre-commit: validator/Board lines in docs are append-only. |

PRD stories: **E6** (`docs/stories/S6.*.md`, GH #21–24). Backlog + label machine:
`docs/PRD_GOLIVE.md`. Build/review runbooks: `docs/DEEPSEEK_RALPH_LOOP.md`, `docs/CODE_AUDIT_LOOP.md`.

---

## 3. Isolation model (why it can run 24/7)

`dsdev` (uid 1003) is an unprivileged user. The agent it runs **cannot touch production**:

| Vector | Containment |
|---|---|
| Code | Builds in a **clone** `/home/trading_ceo/dev/{antariksh,brahmand}`, never the live tree. |
| Data (write) | Prod data dir is `755` → dsdev (other) **cannot write** → prod-coupled writes fail-closed. Verified. |
| Data (read) | `BRAHMAND_SANDBOX=/home/trading_ceo/dev/sandbox` redirects data paths to the sandbox. Residual: ~15 absolute-path files still read prod (low harm; **S6.2 / #22** closes them). |
| Services | dsdev has **no sudo** → cannot restart feed/enricher/order services. |
| Broker | No broker creds in dsdev's env → broker calls fail-closed. |
| GitHub | **Fine-grained PAT scoped to 2 repos** (Contents+Issues+PR R/W, **no admin/delete**) in `/home/dsdev/.ralph_env` (chmod 600). Worst case = a reversible branch push; cannot delete repos or admin the org. The root god-token (`delete_repo`,`admin:org`) is **never** given to the agent. |

Because the agent physically cannot reach prod, *when* it runs stops mattering → **no market-hours
guard on the loops**. Only the **deploy gate** keeps the markets-closed guard (it's the sole prod-toucher).

**Root-repo stories** (e.g. #1 ABOUTME, repo = `/home/trading_ceo`) are **not loop-buildable** —
the root repo is not cloned (its history holds credentials). Those are done manually and kept off
`ds:ready`.

---

## 4. Operating procedures

- **Pause everything (no sudo):** `touch /home/trading_ceo/antariksh/logs/.ralph_paused`
  (both loops early-exit). Remove the file to resume.
- **Deploy an approved branch:** `cron/deploy_gate.sh <branch> [service ...]` as the operator,
  markets closed. Refuses during a session / open position; rolls back on smoke failure.
- **Label state machine:** `ds:ready → ds:done → claude:review → chairman:approve`
  (+ `changes:requested` bounce). DS pulls only `ds:ready`; Claude reviews `ds:done`; only the
  Chairman approves & closes. (PRD §5.)
- **Secrets:** `/home/dsdev/.ralph_env` (600, dsdev-owned) — `GH_TOKEN`, `DEEPSEEK` (opencode auth),
  `ANTHROPIC_API_KEY` (review loop, optional), `TELEGRAM_*`. Never committed.

## 5. Security notes

- The scoped PAT is the only credential the agent holds; rotate it on exposure (regenerate →
  update `.ralph_env`). It cannot perform destructive GitHub ops.
- Untrusted LLM-generated code runs **only** as dsdev in the clone. Trusted prod mutation
  (deploy gate) is operator-run, deterministic, market-gated, reversible.
- The review loop's integrity sweep catches DS self-marking validator `✅✅` (recurring pattern).

## 6. Open items (2026-06-14)

- **#22 / S6.2** (`ds:ready`): sandbox-aware paths — closes the residual prod read-leak + makes the
  PORCUPINE lifecycle sims green (currently prod-coupled). The validation-quality unblocker.
- dsdev `ANTHROPIC_API_KEY` for the review loop (runs as root for now).
- Cron flip to 24/7 once the first real build proves green E2E.
- Optional: move clone to `/home/dsdev/`; rotate the exposed PAT.
