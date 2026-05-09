# Antariksh — Executive Reporting Framework

**Purpose:** Recurring, structured push of company state from CEO → Chairman via Telegram, with audit trail in files.

**Aligned with:** Constitutional rule "Chairman opts out of operations." Reporting is *information flow upward*, never operational ask-permission gate.

---

## Cadence

| Report | When | Channel | Trigger |
|---|---|---|---|
| **Daily Snapshot** | 6:00 PM IST (post-market) | Telegram + file | cron Mon–Fri |
| **Weekly Deep** | Sunday 8:00 PM IST | Telegram + file | cron Sun |
| **Monthly Board Pack** | 1st of month 9:00 PM IST | Telegram + file | cron 1st |
| **Incident Alert** | Real-time | Telegram only | On 🔴 event |
| **Phase Boundary Report** | On phase transition | Telegram + file | Manual / event |

---

## Status Badges (always lead the message)

- 🟢 **GREEN** — On track, no asks
- 🟡 **YELLOW** — Build-in-progress / minor risk / awaiting decision
- 🔴 **RED** — Blocked / capital at risk / L1 invariant under threat

---

## Daily Snapshot — Format

```
🟢/🟡/🔴 ANTARIKSH DAILY — 2026-05-DD

PHASE: 1 (Dress Rehearsal) | DAY: N of ~14
BUILD: X% complete | BLOCKERS: <count>

TODAY:
✅ <what was built/done>
⏭️ <what's queued for tomorrow>

METRICS:
• Sessions run: N (clean: N, errors: N)
• Telegram delivery: OK/FAIL
• Cron health: OK/FAIL
• OpEx today: ₹X (tokens + infra)
• Capital P&L (mock): ₹X

ASKS: <decisions needed, or "none">

Next: <next action>
```

**Length:** ≤25 lines. Telegram-readable on phone in <10 seconds.

---

## Weekly Deep — Format

```
🟢/🟡/🔴 ANTARIKSH WEEKLY — Week ending 2026-05-DD

PHASE: 1 | WEEK: N of ~2

ACCOMPLISHED THIS WEEK:
- <bullet 1>
- <bullet 2>
- <bullet 3>

NOT DONE (rolled forward):
- <bullet>

METRICS:
• Sessions: N total, win rate W%, avg P&L ₹X
• Cron uptime: X%
• Top OpEx driver: <agent name> @ ₹X
• 10-day burn: ₹X (vs 30%-of-free-cash floor)

RISKS:
🔴 <if any>
🟡 <if any>

NEXT WEEK FOCUS:
- <bullet>
- <bullet>

ASKS:
<decision needed or "none">

Full report: <file path>
```

---

## Monthly Board Pack — Format

Sent as Telegram summary + full file linked.

**Telegram summary (≤30 lines):**
- Phase status + days-to-next-phase
- P&L vs target (₹1K/day initial → ₹2K/day stretch)
- 30-day DD vs ₹30K ceiling
- L1 invariants check (none breached / breaches)
- Roster changes (hired/promoted)
- 3 wins / 3 misses / 3 next

**Full file:** `/home/trading_ceo/antariksh/exec_reports/MONTHLY_YYYY-MM.md`

---

## Incident Alert — Format

Triggered on:
- Cron miss (no session run when scheduled)
- Telegram delivery failure
- Backtest crash / unhandled exception
- L1 projection breach (CFO check fail)
- Capital event (margin call, broker error in Phase 2+)

```
🔴 ANTARIKSH INCIDENT — HH:MM

TYPE: <CRON_MISS | DELIVERY_FAIL | CRASH | L1_BREACH | CAPITAL>
SESSION: <date or N/A>
CAUSE: <one line>
IMPACT: <one line>
ACTION TAKEN: <auto-recovery, halt, etc.>
NEEDS HUMAN: YES/NO
```

---

## Channels & Mechanism

### Primary: Telegram via picoclaw

- **Why:** Existing infra. User reads phone-first.
- **Send model:** picoclaw RPC → Telegram Bot API
- **Format:** Telegram MarkdownV2
- **Bot:** existing Antariksh bot (TBD if separate from Mooshika bot)

### Audit trail: Files

- Path: `/home/trading_ceo/antariksh/exec_reports/`
- Naming:
  - `EXEC_REPORT_YYYY-MM-DD.md` (daily)
  - `WEEKLY_YYYY-WW.md`
  - `MONTHLY_YYYY-MM.md`
  - `INCIDENT_YYYY-MM-DD_HHMM.md`
- All reports immutable once written (append-only audit).

---

## Source-of-Truth Inputs (what the report reader pulls from)

| Input | Source path |
|---|---|
| Build %, TODOs | `/home/trading_ceo/antariksh/phase1_mvs.py` (TODO grep) |
| Phase status | `/home/trading_ceo/.planning/ROADMAP.md` |
| Project decisions | `/home/trading_ceo/.planning/PROJECT.md` |
| Strategy canon | `/home/trading_ceo/python-trader/varaha/STRATEGY_DESIGN_QUESTIONS.md` |
| Session logs | `/home/trading_ceo/antariksh/logs/phase1_YYYYMMDD.log` |
| CFO audit logs | `/home/trading_ceo/antariksh/logs/cfo_audit_YYYYMMDD.json` |
| OpEx counters | (TBD — Phase 2 CFO module) |
| Git activity | `git log` in working dirs |

---

## Implementation

**Generator:** `/home/trading_ceo/antariksh/exec_report.py`

**Cron entries (in SETUP_CRON.md):**
```
0 18 * * 1-5  /usr/bin/python3 /home/trading_ceo/antariksh/exec_report.py daily
0 20 * * 0    /usr/bin/python3 /home/trading_ceo/antariksh/exec_report.py weekly
0 21 1 * *    /usr/bin/python3 /home/trading_ceo/antariksh/exec_report.py monthly
```

**Incident triggers:** invoked from inside `phase1_mvs.py` exception handlers + cron health check.

---

## Governance Rules

1. **Chairman never operates.** Reports inform; they never request execution permission. (Telegram NO replies on *trade* messages remain valid; that's a *trade gate*, not a reporting gate.)
2. **CEO/Director identity in messages.** Every report signed by sender role. Phase 1: "Director (Interim CEO)". Phase 2+: "Vishnu (CEO)".
3. **No surprise.** No status downgrade (🟢 → 🔴) without a prior 🟡 daily snapshot, except for incident alerts.
4. **No PII / sensitive financials in Telegram.** Net worth, account numbers, broker credentials never in messages. Use redactions.
5. **Read-only-on-risk preserved.** Reports describe state; they never ask the LLM to override a risk gate.

---

## Phase 2+ Evolution

- CFO promoted from "audit log" to "monthly OpEx narrative" + per-agent token attribution
- Asset Manager adds capital-structure section (pledged/free cash split, margin headroom)
- Vishnu signs daily reports (Director role retires from CEO duties)
- Multi-instrument expansion: NIFTY + SENSEX + MCX get separate metric blocks
