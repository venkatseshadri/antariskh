# Antariksh CrewAI — Scenario Test Plan
**Created:** 2026-05-09
**Purpose:** Comprehensive behavioral validation of the 7-agent CrewAI system against design expectations. Each scenario specifies what each agent should do, what outputs to expect, and pass/fail criteria — so we can verify the multi-agent choreography matches the constitutional intent before live capital.

**Coverage:** 32 scenarios across 8 categories.
**Use:** Run as mock tests over the weekend. Each scenario maps to a CrewAI test in `crew_test.py` (extending the 4 existing tests).

---

## Table of Contents

1. [How to Run Scenarios](#how-to-run-scenarios)
2. [Agent Roster & Expected Behavior](#agent-roster--expected-behavior)
3. [Scenario Categories](#scenario-categories)
4. [Scenarios — Happy Path (HP)](#hp--happy-path)
5. [Scenarios — Risk Management (RM)](#rm--risk-management)
6. [Scenarios — Drawdown / Burn Rate (DD)](#dd--drawdown--burn-rate)
7. [Scenarios — Market Conditions (MC)](#mc--market-conditions)
8. [Scenarios — System Failures (SF)](#sf--system-failures)
9. [Scenarios — Operator / HITL (OP)](#op--operator--hitl)
10. [Scenarios — Lifecycle (LC)](#lc--lifecycle)
11. [Scenarios — Edge Cases (EC)](#ec--edge-cases)
12. [Test Matrix](#test-matrix-summary)
13. [Gaps & Open Questions](#gaps--open-questions)

---

## How to Run Scenarios

### Mock Mode Setup
```bash
export ANTARIKSH_MOCK_MODE=1
export ANTARIKSH_MOCK_DATE="2026-05-12"  # Tuesday
export ANTARIKSH_MOCK_VIX=15.0
export ANTARIKSH_MOCK_NIFTY=24500
export ANTARIKSH_MOCK_PNL=0
export ANTARIKSH_MOCK_MTD=0
```

### Scenario Injector Pattern
Each scenario uses a fixture that pre-seeds:
1. **Historical state** — JSONL audit logs in `logs/` for past sessions
2. **Market state** — environment variables for current VIX, NIFTY, time
3. **Capital state** — `market_state['mtd_pnl']`, `re_entries_used`
4. **External state** — broker API responses (mocked)

### Pass Criteria
Each scenario PASSES if:
- ✅ All listed agents execute in expected order
- ✅ Final `market_state` dict matches expected values
- ✅ Expected JSONL audit entry written
- ✅ Expected Telegram messages dispatched
- ✅ No agent crashes / exceptions raised

### Fail Criteria
Each scenario FAILS if:
- ❌ Agent skips required step
- ❌ Risk Guard fails to halt when it should
- ❌ Re-entry permitted when blocked
- ❌ Audit log incomplete or malformed
- ❌ LLM call made when deterministic rule should fire

---

## Agent Roster & Expected Behavior

| Agent | Role | Critical-Path? | Failure Mode |
|---|---|---|---|
| **Orchestrator** | Hierarchical manager. Delegates tasks. | Yes (manager) | Hangs → no agents fire |
| **Scanner** | VIX, NIFTY spot, event check, gate evaluation | Yes (gate) | Stale data → wrong gate decision |
| **Strategist** | Iron Fly plan generation (strikes, premiums) | Yes (plan) | Bad strikes → unfillable orders |
| **Executor** | Order placement (Flattrade API) — **deterministic** | Yes (orders) | Order fails → no position |
| **Sentinel** | Real-time MTM, SL/target detection | Yes (during session) | Misses SL → ₹3,500+ loss |
| **Risk Guard** | Hard L1 capital enforcement — **deterministic** | Yes (every order) | Allows order past halt → catastrophic |
| **Auditor** | JSONL log write, MTD calc, post-session audit | No (post-hoc) | Silent miss → MTD drifts |

**Key invariants:**
- Risk Guard, Executor, Auditor have **ZERO LLM in critical path** (per design)
- Risk Guard runs BEFORE every Executor call
- Auditor reads existing JSONL → calculates MTD → seeds market_state at session start

---

## Scenario Categories

| Category | Code | Count | Priority |
|---|---|---|---|
| Happy Path | HP | 4 | Validate baseline |
| Risk Management | RM | 6 | 🔴 CRITICAL |
| Drawdown / Burn Rate | DD | 4 | 🔴 CRITICAL |
| Market Conditions | MC | 5 | 🟡 HIGH |
| System Failures | SF | 5 | 🟡 HIGH |
| Operator / HITL | OP | 3 | 🟢 MEDIUM |
| Lifecycle | LC | 3 | 🟢 MEDIUM |
| Edge Cases | EC | 2 | 🟢 MEDIUM |
| **Total** | | **32** | |

---

## HP — Happy Path

### HP-01: Clean Win — Target Hit at 12:30 PM
**What it validates:** Full happy path. Gate → plan → entry → monitor → target → exit → audit.

**Setup:**
- Date: Tue 2026-05-12 (NIFTY weekly expiry)
- VIX: 14.0 (well below 20)
- NIFTY: 24500 (round number, easy ATM)
- MTD P&L: 0 (clean slate)
- Re-entries used: 0
- Free cash: ₹100,000

**Trigger:** 09:30 AM session start → gate check → plan → 10:30 AM entry → 12:30 PM target hit (₹1,000 profit on combined premium).

**Expected agent behavior:**
| Agent | Step | Expected Action |
|---|---|---|
| Orchestrator | T+0s | Initialize session, call AuditorEngine.calculate_mtd_from_logs() → mtd=0 |
| Scanner | T+1s | Fetch VIX=14, NIFTY=24500, no event, within window → gate PASS |
| Strategist | T+3s | ATM=24500, sell 24500CE+24500PE, buy 24800CE+24200PE wings |
| Risk Guard | T+5s | full_check(session_pnl=0, mtd=0) → halt=False, all checks pass |
| Executor | T+6s | Place 4-leg Iron Fly order, returns order_ids |
| Sentinel | T+8s … | Poll MTM every 2s. At 12:30 detects MTM=+₹1000 → triggers exit |
| Executor | T+session+exit | Place exit orders, returns fills |
| Auditor | T+end | Append JSONL: {pnl: 1000, exit_reason: "Target hit", mtd_pnl: 1000} |

**Expected `market_state`:**
```python
{
  'gate_pass': True,
  'trade_plan': {...},
  'positions': [...4 legs...],
  'pnl_realized': 1000,
  'exit_reason': 'Target hit',
  'mtd_pnl': 1000,
  'halt': False,
  're_entries_used': 0
}
```

**Expected Telegram:**
- 09:30: "✅ Gate PASS. Iron Fly @ NIFTY 24500. Plan submitted."
- 12:30: "🎯 TARGET HIT. P&L: +₹1,000. MTD: +₹1,000. WR session: 100%."

**Pass criteria:** All 7 agents fire in order, JSONL written, MTD reflects gain.

**Fail criteria:** Risk Guard fires halt incorrectly, Sentinel misses target, audit omits.

---

### HP-02: Time Exit at 14:30 — No Target Hit
**What it validates:** Hard exit fires correctly when neither target nor SL hit.

**Setup:** Same as HP-01 except market is range-bound. By 14:30, MTM = +₹400 (under target).

**Trigger:** 14:30 hard squareoff time reached; Sentinel calls Executor for time-exit.

**Expected behavior:**
- Sentinel @ 14:30: detects time threshold, sends EXIT signal
- Executor: closes all 4 legs at market
- Auditor: logs `exit_reason: "Time exit (14:30)"`, `pnl: 400`
- Telegram: "⏰ TIME EXIT. P&L: +₹400. MTD: +₹400."

**Pass:** Time exit fires at 14:30 even without SL/target hit. PnL captured correctly.

---

### HP-03: Gate Skip — High VIX
**What it validates:** Layer 1 regime gate correctly skips trading when VIX > 20.

**Setup:**
- Date: Tue 2026-05-12
- VIX: 22.0 (above threshold)
- All other params normal

**Trigger:** Scanner fetches VIX=22 at 09:30.

**Expected behavior:**
- Scanner: returns `gate_pass=False`, `reason="VIX 22.0 > threshold 20.0"`
- Strategist: NOT INVOKED (gate failed)
- Executor: NOT INVOKED
- Sentinel: NOT INVOKED
- Risk Guard: NOT INVOKED
- Auditor: logs `{gate_pass: False, reason: "VIX_HIGH", trade_executed: False, pnl: 0}`
- Telegram: "🚫 GATE SKIP. Reason: VIX 22.0 > 20.0. No trade today."

**Pass:** Only Scanner + Auditor fire. No Strategist, no Executor.
**Fail:** Strategist generates a plan despite gate failure.

---

### HP-04: Gate Skip — Event Day (RBI)
**What it validates:** Event calendar correctly blocks RBI day.

**Setup:**
- Date: 2026-04-08 (assume RBI policy day)
- VIX: 14.0 (would otherwise pass)
- Event calendar: returns `is_event_day=True, name="RBI Policy"`

**Expected behavior:**
- Scanner: gate_pass=False, reason="Event day: RBI Policy"
- Auditor: logs `{gate_pass: False, reason: "EVENT_DAY", event: "RBI Policy"}`
- Telegram: "🚫 GATE SKIP. Reason: Event day — RBI Policy. No trade."

**Pass:** Trading skipped despite favorable VIX.
**Fail:** System trades on RBI day (current bug — `is_event_day()` returns False!).

---

## RM — Risk Management

### RM-01: Session SL Hit (₹3,500) — First Hit, Re-entry Allowed
**What it validates:** Single-position SL with permitted re-entry.

**Setup:**
- Standard happy-path setup
- At 11:45 AM, NIFTY moves sharply (gap from 24500 to 24700)
- MTM at 11:45 = -₹3,500 (SL trigger)
- Re-entries used: 0 (first hit of the day)

**Trigger:** Sentinel detects MTM = -₹3,500.

**Expected behavior:**
| Agent | Action |
|---|---|
| Sentinel | Detect MTM ≤ -3500 → emit STOP_LOSS signal |
| Risk Guard | full_check(session_pnl=-3500, mtd=-3500) → daily SL exact hit. halt=False (only at -4500 portfolio) |
| Executor | Close all 4 legs at market |
| Auditor | Log: `{exit_reason: "Stop loss", pnl: -3500, re_entries_used: 0}` |
| ReEntryTracker | can_re_enter() → True (0 attempts used, no halt) |
| Telegram | "🛑 SL HIT @ -₹3,500. Re-entry option open (1 attempt remaining)." |

**Then post-mortem trigger:**
- Auditor: spawns post-mortem reflection
  - Logs: time of hit, NIFTY move, VIX delta during window, premium decay
  - Required reflection log entry (cooldown.loss_day.require_reflection_log = true)
- Telegram: "📋 Post-mortem queued. Re-entry decision after reflection."

**Pass:**
- ✅ Position closed at -3500 exactly (Sentinel didn't let it slip to -4000)
- ✅ ReEntryTracker shows attempts_remaining=1
- ✅ Halt = False (single-instrument SL, not portfolio)
- ✅ Post-mortem reflection queued
- ✅ JSONL has `re_entries_used: 0` BEFORE re-entry decision

**Fail:** Position drifts to -₹4,000 before exit; halt fires prematurely; re-entry blocked despite attempts available.

---

### RM-02: Re-entry Triggered After RM-01 → Second SL → Hard Halt
**What it validates:** ReEntryTracker enforces 1-attempt limit; second SL → permanent halt for the day.

**Setup:** Continues from RM-01 state. After 30-min cooldown:
- Re-entries used: 0
- Free cash: ₹96,500 (started ₹100k - ₹3,500)
- Time: 12:15 PM (still within window for re-entry)

**Trigger:** Operator approves re-entry via Telegram (HITL gate). Strategist generates new plan. Executor places order.

**At 13:30 PM:** Second adverse move. MTM = -₹3,500 again.

**Expected behavior:**
| Agent | Action |
|---|---|
| ReEntryTracker | mark_re_entry() → attempts_used=1, max=1 |
| Strategist | New Iron Fly plan at refreshed strikes |
| Risk Guard | full_check(session_pnl=-3500, mtd=-7000 cumulative) → not at portfolio yet |
| Executor | Place new 4-leg order |
| Sentinel | Monitor → detect 2nd SL @ 13:30 |
| Risk Guard | full_check(session_pnl=-7000, portfolio_sl=4500) → **PORTFOLIO SL BREACHED**. halt=True |
| Executor | Close all positions, refuse any further orders |
| ReEntryTracker | can_re_enter() → False (attempts_used=1 ≥ max=1, AND halt=True) |
| Auditor | Log: `{exit_reason: "Stop loss", pnl: -3500, halt: True, hard_kill_check: "two_consecutive_session_sl_breaches"}` |
| Telegram | "🚨 SECOND SL HIT. Trading HALTED for today. Hard-kill candidate flagged for chairman review." |

**Pass:**
- ✅ Re-entry permitted exactly once
- ✅ After 2nd SL, halt=True permanently for the day
- ✅ Hard-kill trigger `two_consecutive_session_sl_breaches` flagged in audit
- ✅ Future order attempts (e.g., test injection) are REFUSED by Risk Guard

**Fail:** ReEntryTracker allows 3rd attempt; system continues after 2nd SL; hard-kill flag missed in audit.

---

### RM-03: Portfolio SL Hit Mid-Session (₹4,500)
**What it validates:** Portfolio-wide cumulative SL halts trading even if single-instrument SL not hit.

**Setup:** Multi-instrument session (Phase 3+ but test logic now). Imagine:
- NIFTY position: -₹2,500 unrealized
- SENSEX position: -₹2,000 unrealized
- Cumulative: -₹4,500 → portfolio SL

**Trigger:** Sentinel runs cumulative MTM calc.

**Expected behavior:**
- Risk Guard: `check_portfolio_sl(cumulative=-4500, threshold=-4500)` → BREACH. halt=True
- Executor: Close ALL positions across instruments
- Auditor: Log portfolio breach, flag burn-rate watch
- Telegram: "🛑 PORTFOLIO SL HIT @ -₹4,500. All positions closed."

**Pass:** All positions closed even if individual SLs not hit. Halt prevents new orders.

**Fail:** Only one instrument closed; system attempts new positions.

---

### RM-04: 30-Day Drawdown Breach (₹30,000)
**What it validates:** Long-running DD limit halts the entire week, requires manual restart.

**Setup:**
- Past 28 days of JSONL logs sum to MTD=-₹26,500
- Today (Day 29): Session ends with -₹3,500 SL
- Cumulative MTD: -₹30,000 (exact threshold breach)

**Trigger:** Auditor calculates MTD post-session.

**Expected behavior:**
- Auditor: `check_30day_dd(mtd=-30000, threshold=-30000)` → BREACH
- Risk Guard: halt=True, halt_duration="week"
- AuditorEngine: writes `kill_switch_triggered: "rolling_30d"` to JSONL
- ReEntryTracker: `requires_written_reflection: true` flag set
- Telegram: "🚨 30-DAY DD BREACH (-₹30,000). Weekly halt enforced. Written reflection required before restart."

**Pass:**
- ✅ Tomorrow's session start: AuditorEngine reads JSONL, sees halt flag, BLOCKS gate check
- ✅ Manual override required (chairman acknowledgment)
- ✅ Reflection log file required (e.g., `reflections/2026-05-13.md`)

**Fail:** Next day's session proceeds normally; no halt persisted across sessions.

---

### RM-05: Free Cash Floor Breach (< ₹11,000)
**What it validates:** Capital preservation hard floor; system halts at the floor.

**Setup:**
- Starting free cash: ₹14,000 (already low — past losses)
- Today's session: -₹3,500 SL
- Free cash after: ₹10,500 (below floor)

**Trigger:** Risk Guard `check_free_cash_floor()` post-trade.

**Expected behavior:**
- Risk Guard: `free_cash=10500 < floor=11000` → halt=True
- Auditor: Log `kill_switch: "free_cash_floor_breach"`
- Strategist: Subsequent sessions blocked at gate
- Telegram: "🚨 FREE CASH BELOW FLOOR (₹10,500 < ₹11,000). Trading halted until cash restored."

**Pass:** Halt persists until manual cash injection logged. No bypass possible.

**Fail:** System continues with sub-floor capital; warning issued but trading proceeds.

---

### RM-06: Burn Rate Watch — 30% of Free Cash Lost in 10 Days
**What it validates:** Trend-based protective halt before catastrophic loss.

**Setup:**
- Free cash: ₹10,000 (post-pledge)
- Last 10 sessions JSONL: cumulative -₹3,200 (= 32% of free cash)

**Trigger:** Auditor calculates 10-day rolling sum at session start.

**Expected behavior:**
- AuditorEngine: `calculate_10d_burn(losses=-3200, free_cash=10000)` → 32% > 30% threshold
- Risk Guard: halt=True, reason="burn_rate_exceeded"
- Telegram: "⚠️ BURN RATE TRIGGER. 10-day losses = 32% of free cash. Halt + post-mortem required."
- Auditor: writes burn-rate snapshot to JSONL
- AskUserQuestion (HITL): "Resume trading or pause for review?"

**Pass:** System pauses BEFORE today's session starts. Operator must explicitly resume.

**Fail:** Today's session proceeds; burn rate ignored.

---

## DD — Drawdown / Burn Rate

### DD-01: 5 Consecutive Loss Days
**What it validates:** Pattern detection; cooldown enforcement after consecutive losses.

**Setup:**
- Last 5 sessions JSONL: -3500, -2200, -1800, -3500, -2900 = -₹13,900
- Today is 6th session

**Trigger:** Auditor reads consecutive_losing_days from JSONL.

**Expected behavior:**
- AuditorEngine: detects 5-day streak (≥3 trigger)
- Cooldown: `consecutive_losing_days_2.weekend_pause = true` already triggered after day 2
- Strategist: gate fails on "cooldown_active"
- Telegram: "⏸️ 5 CONSECUTIVE LOSSES. Mandatory cooldown. Reflection log required."

**Pass:** System detects streak from JSONL, blocks today's session.

**Fail:** Cooldown not enforced; continues trading.

---

### DD-02: 10-Day Loss → 30% Free Cash Burn (extends RM-06)
**What it validates:** Auditor's `read_phase1_logs()` correctly aggregates 10-day window.

**Setup:**
- Logs for 10 prior sessions, total -₹3,300 (= 30% of ₹11,000 floor)
- Today: would be 11th session

**Expected behavior:**
- AuditorEngine: `calculate_mtd_from_logs()` plus `calculate_10d_burn()`
- Burn = 30% exact (boundary condition) → triggers halt
- Auditor JSONL: includes `10d_burn_pct: 30.0, threshold_pct: 30.0, breach: true`

**Pass:** Boundary handled correctly (>=, not >).

**Fail:** 30% exact slips through (off-by-one).

---

### DD-03: 30 Sessions Reached — Phase 1 → 2 Advancement Eligibility
**What it validates:** Auditor recognizes phase-advancement criteria from JSONL aggregate.

**Setup:**
- 30 prior sessions in JSONL
- Period-end PnL: +₹6,000 on ₹500,000 capital = +1.2% ✅
- Profit factor: 1.5 ✅
- Max DD in window: -₹12,000 ✅
- Single-day SL breaches: 0 ✅
- Skip rate: 45% (within 30-60% band) ✅
- Sanity check failure rate: 2% ✅

**Trigger:** Auditor's `check_advancement_gate()` runs at session 30.

**Expected behavior:**
- Auditor: writes "ADVANCEMENT_ELIGIBLE" to JSONL
- Telegram: "🎓 PHASE 1 GATE PASS. 30 sessions complete. All metrics green. Awaiting chairman approval to enter Phase 2."
- AskUserQuestion: HITL gate for advancement

**Pass:** Auditor correctly aggregates 6 metrics from JSONL; gate evaluation deterministic.

**Fail:** Misses any of the 6 criteria; advances despite metric breach.

---

### DD-04: Profit Factor Below 1.0 Over 4 Weeks
**What it validates:** Soft-kill trigger detection.

**Setup:**
- 20 sessions in JSONL: 8 wins ₹6,400, 12 losses -₹16,800 → PF = 0.38

**Expected behavior:**
- AuditorEngine: PF=0.38 < 1.0 → soft_kill triggered
- Telegram: "⚠️ SOFT KILL CANDIDATE. Profit factor 0.38 < 1.0 over 4 weeks. Pause + evaluate."
- Risk Guard: halt for review (not hard kill)

**Pass:** Soft kill is distinguished from hard kill (recoverable, not "rebuild from scratch").

**Fail:** Hard kill triggered (overreaction); or soft kill missed.

---

## MC — Market Conditions

### MC-01: Intraday VIX Spike (15 → 22 at 11:00 AM)
**What it validates:** Scanner real-time loop; gate re-evaluation during session.

**Setup:**
- 09:30 VIX: 15 (gate PASS, plan generated)
- 11:00 VIX: 22 (during entry window, before order placed)

**Expected behavior:**
| Agent | Action |
|---|---|
| Scanner | Polls VIX at 11:00, detects 22.0 |
| Risk Guard | re-checks gate, halt=True |
| Strategist | Cancels plan if order not yet placed |
| Executor | If order placed already → squareoff |
| Telegram | "⚠️ INTRADAY VIX SPIKE 15 → 22. Gate revoked. Position closing." |

**Pass:**
- ✅ Scanner detects spike WITHIN session (real-time loop required)
- ✅ Gate re-evaluation triggers halt
- ✅ Position closed if entered; cancelled if not yet

**Fail:** Scanner caches VIX from 09:30 only; misses spike. **(Currently broken — Scanner not in real-time loop.)**

---

### MC-02: Gap-Up Open (>0.5%)
**What it validates:** Gap filter (`gap_pct_max: 0.5`).

**Setup:**
- Yesterday close: NIFTY 24500
- Today open: NIFTY 24650 (+0.61%)

**Expected behavior:**
- Scanner: detects gap=0.61% > 0.5% threshold
- Gate: PASS=False, reason="gap_open_excessive"
- Auditor: logs `{gap_pct: 0.61, gate_pass: false, reason: "gap_open"}`

**Pass:** Gap filter enforced as standalone gate criterion.

---

### MC-03: Late Entry (After 11:30) — Window Closed
**What it validates:** Entry window enforcement — no entries after window closes.

**Setup:**
- 09:30 gate check: VIX=14, but session was paused for sanity check loop
- 11:35 (5 min after window close): system tries to place order

**Expected behavior:**
- Risk Guard or Strategist: `check_entry_window()` → False (current time > 11:30)
- Order BLOCKED
- Telegram: "🚫 ENTRY WINDOW CLOSED. No trade today."
- Auditor: logs `{gate_pass: false, reason: "entry_window_closed"}`

**Pass:** Hard window enforcement; no late entries even if other gates would pass.

---

### MC-04: Wide Bid-Ask Spread (Liquidity Failure)
**What it validates:** Tier 2 liquidity sanity check.

**Setup:**
- ATM CE: bid 100, ask 110 → spread 10% > 5% threshold

**Expected behavior:**
- Strategist: detects spread, triggers Tier 2 sanity fail
- Risk Guard: hard_fail=true → block
- Telegram: "🚫 LIQUIDITY FAIL. ATM CE spread 10% > 5%. No trade."

**Pass:** Tier 2 hard-fail enforced.

**Fail:** Order placed despite wide spread; large slippage.

---

### MC-05: First 15 Minutes / Last 15 Minutes — Skip
**What it validates:** First/last 15-minute skip rule.

**Setup:** Time = 09:35 (within first 15 min of 09:15 open) OR 14:20 (within last 15 min before 14:35 LLM cutoff)

**Expected behavior:**
- Scanner / gate: skip=True, reason="first_minutes_after_open" or "last_minutes_before_close"
- Auditor: logs reason

**Pass:** Window edges respected; no entries during these guard periods.

---

## SF — System Failures

### SF-01: Broker API Down (Shoonya)
**What it validates:** Fallback to Flattrade; if both fail, gate skips.

**Setup:**
- Shoonya: returns 500 error
- Flattrade: returns valid data

**Expected behavior:**
- BrokerManager: fails Shoonya, falls to Flattrade
- Scanner: gets data from Flattrade, gate evaluates normally
- Telegram: "ℹ️ Shoonya API down. Using Flattrade fallback. Trade proceeds."
- Auditor: logs primary broker failure

**Pass:** Resilient failover; no session loss.

---

### SF-02: BOTH Brokers Down — Total Data Failure
**What it validates:** Defensive halt when no data source.

**Setup:**
- Both brokers return None or 5xx

**Expected behavior:**
- Scanner: gate=False, reason="no_market_data"
- Risk Guard: halt=True (cannot verify safety)
- Telegram: "🚨 BOTH BROKERS DOWN. Cannot fetch VIX/NIFTY. Trading halted."
- Auditor: incident_log entry

**Pass:** Safe-by-default — when uncertain, skip.

**Fail:** Trades placed using stale or default data.

---

### SF-03: LLM Provider Failure — Tiered Fallback
**What it validates:** `llm_resilience` config (Claude → Minimax → Haiku for critical).

**Setup:**
- Strategist Agent (tier=critical) calls Claude Sonnet
- Claude returns 429 (rate limit)
- Per config: retry 2× with backoff, then fall through

**Expected behavior:**
- LLMRouter: retries Claude 2× with backoff
- After 3 failures within 60s window → circuit breaker opens
- Falls through to Minimax (tier=critical, second in chain)
- If Minimax succeeds: continue normally
- If Minimax also fails: fall to Claude Haiku
- After cooldown_seconds=300, retry Claude

**Pass:** Strategist completes via Minimax. Auditor logs `llm_fallback: claude_sonnet → minimax`.

**Fail:** First failure → crew halts; no fallback.

---

### SF-04: Cron Miss — Late Trigger (10:15 AM Instead of 09:30)
**What it validates:** System detects late start, decides whether to proceed.

**Setup:**
- Cron failed to fire at 09:30 (server load, container restart)
- Triggered at 10:15 instead

**Expected behavior:**
- Orchestrator: detect current_time > entry_time
- Within entry window (10:30-11:30): proceed normally
- Auditor: logs `{cron_late_trigger: true, delay_min: 45}`
- Telegram: "ℹ️ Late session start (10:15). Within entry window. Proceeding."

**Edge case — triggered at 11:35 (after window):** Skip with reason="window_missed".

**Pass:** System adapts to late triggers; doesn't crash; logs incident.

**Fail:** System crashes on late trigger; OR proceeds outside window.

---

### SF-05: Network Failure Mid-Trade (Sentinel Cannot Poll)
**What it validates:** Defensive squareoff when MTM cannot be determined.

**Setup:**
- Position open at 11:00
- At 12:00: network drops; Sentinel cannot poll for 5 minutes
- Sentinel timeout threshold: 60s (configurable)

**Expected behavior:**
- Sentinel: detects 60s no-poll → emits "MTM_UNKNOWN" status
- Risk Guard: receives unknown status → defensive close (FAIL_SAFE)
- Executor: emergency squareoff at market
- Auditor: logs `{exit_reason: "Sentinel_blackout_60s", emergency_close: true}`
- Telegram: "🚨 SENTINEL BLACKOUT. Emergency close at market."

**Pass:** Position closed when Sentinel can't see; doesn't drift unmonitored.

**Fail:** Position remains open with unknown state; could drift to large loss.

---

## OP — Operator / HITL

### OP-01: Operator Override Attempt — Blocked
**What it validates:** Operator commitment `no_broker_override: true`.

**Setup:**
- Risk Guard halt=True (e.g., DD breach)
- Operator sends Telegram: "Override halt and trade anyway"

**Expected behavior:**
- HITL handler: detects override keyword
- Hard-kill candidate trigger: `operator_override_of_code_halt`
- Telegram: "🚨 OVERRIDE ATTEMPT REJECTED. Hard-kill candidate flagged. Mandatory 24h cooldown + chairman review."
- Auditor: logs override attempt

**Pass:** Override is REFUSED; flag escalates to hard-kill review.

**Fail:** Override accepted; system bypasses halt.

---

### OP-02: Operator Confirmation Timeout
**What it validates:** What happens if user doesn't respond to Telegram HITL prompt.

**Setup:**
- Re-entry decision pending; Telegram asks "Approve re-entry?"
- 30 minutes pass with no response

**Expected behavior:**
- Default: NO action (no re-entry)
- Auditor: logs `{re_entry_decision: "timeout_no_response"}`
- Session ends without re-entry attempt

**Pass:** Safe default = inaction. No silent re-entry.

**Fail:** Auto-approves on timeout.

---

### OP-03: Telegram Unreachable
**What it validates:** System operates without Telegram (logs to file as fallback).

**Setup:**
- TelegramBridge fails to send (network, picoclaw down)

**Expected behavior:**
- TelegramBridge: writes to `/tmp/antariksh_telegram.txt` as fallback
- AuditorEngine: logs `{telegram_send_failed: true}`
- Trading continues (Telegram is observability, not critical-path)

**Pass:** Trading proceeds; messages queued for replay.

**Fail:** System halts because Telegram down (Telegram is informational, not gating).

---

## LC — Lifecycle

### LC-01: Month Rollover — MTD Reset
**What it validates:** AuditorEngine correctly resets MTD on first session of new month.

**Setup:**
- April 2026 logs: cumulative MTD = -₹8,000
- Today: 2026-05-01 (first session of May)

**Expected behavior:**
- AuditorEngine: `calculate_mtd_from_logs()` filters to current month (May 2026)
- Returns mtd=0 (no May entries yet)
- April logs preserved but not summed
- Telegram: "📅 New month. April closed at -₹8,000. MTD reset to ₹0."

**Pass:** MTD correctly scoped to month; no carry-over from April.

**Fail:** April losses bleed into May; MTD starts at -₹8,000.

---

### LC-02: Weekend / Holiday — No Session
**What it validates:** System idle on non-trading days.

**Setup:**
- Today: Saturday 2026-05-09
- Cron fires (cron is weekday-restricted but test edge)

**Expected behavior:**
- Orchestrator: detects weekday=5 (Saturday)
- Cron config: `* * * 1-5` should prevent weekend fires, but if it slips:
- Idempotent skip: log "weekend_skip", do nothing
- No agents invoked, no JSONL entry

**Pass:** Defensive weekend check even if cron config wrong.

**Fail:** Trading attempted on weekend; broker rejection cascades.

---

### LC-03: First Session After 30-Day DD Halt
**What it validates:** Manual restart workflow after persistent halt.

**Setup:**
- Halt active from RM-04 scenario (30-day DD breach)
- Reflection log written by operator: `reflections/2026-05-09.md`
- Operator types `RESUME` keyword in Telegram

**Expected behavior:**
- HITL handler: validates reflection log exists
- AuditorEngine: clears halt flag in next JSONL entry
- Risk Guard: halt=False on next session
- Telegram: "✅ HALT CLEARED. Reflection logged. Resuming with caution flags."
- Caution flags: tighter SL (e.g., -₹2,500 instead of -₹3,500) for first 5 sessions

**Pass:** Restart requires explicit reflection; system adds caution period.

**Fail:** Resume without reflection log; OR resume with full SL immediately.

---

## EC — Edge Cases

### EC-01: VIX Exactly at 20.00 (Boundary)
**What it validates:** Boundary handling — is `<=` or `<` used?

**Setup:**
- Scanner returns VIX = 20.00 exactly
- Threshold = 20.0

**Expected behavior:**
- Per spec `vix_max: 20.0` and Layer 1 says "VIX < 20" → 20.00 should FAIL gate
- Auditor: logs `{vix: 20.00, gate_pass: false, reason: "vix_boundary"}`
- Telegram: "🚫 VIX exactly at threshold. Skip per safety rule."

**Pass:** Boundary closed-side: 20.00 = fail (strict less-than).

**Fail:** 20.00 passes (off-by-one in operator).

---

### EC-02: SL Hit at 14:34:59 (1 Second Before Hard Exit)
**What it validates:** Race condition between Sentinel SL detection and time-based exit.

**Setup:**
- 14:34:59: MTM crosses -₹3,500
- 14:35:00: Hard squareoff time

**Expected behavior:**
- Both Sentinel (SL) and Sentinel (time) emit exit signals
- Audit: should record one exit reason (whichever fired first)
- Convention: SL takes priority over time (more urgent)
- Auditor: logs `exit_reason: "Stop loss"`, NOT "Time exit"

**Pass:** Single exit, single audit entry, deterministic priority.

**Fail:** Double-close orders (both signals fire); ambiguous audit.

---

## Test Matrix Summary

| Scenario ID | Category | Severity | Validates Agent(s) | Existing test? |
|---|---|---|---|---|
| HP-01 | Happy | Med | All 7 | ✅ test_1_mock_dryrun (partial) |
| HP-02 | Happy | Med | Sentinel, Executor, Auditor | ❌ |
| HP-03 | Happy | High | Scanner, Auditor | ✅ test_4_gate_skip_high_vix |
| HP-04 | Happy | 🔴 CRITICAL | Scanner, Auditor | ❌ (event_calendar broken!) |
| RM-01 | Risk | 🔴 CRITICAL | Sentinel, Risk Guard, ReEntryTracker, Auditor | ❌ |
| RM-02 | Risk | 🔴 CRITICAL | ReEntryTracker, Risk Guard | ❌ |
| RM-03 | Risk | 🟡 HIGH | Risk Guard | ❌ |
| RM-04 | Risk | 🔴 CRITICAL | Auditor, Risk Guard | ❌ |
| RM-05 | Risk | 🔴 CRITICAL | Risk Guard | ❌ |
| RM-06 | Risk | 🟡 HIGH | Auditor (burn rate) | ❌ |
| DD-01 | DD | 🟡 HIGH | Auditor | ❌ |
| DD-02 | DD | 🟡 HIGH | Auditor (boundary) | ❌ |
| DD-03 | DD | 🟢 MED | Auditor (advancement) | ❌ |
| DD-04 | DD | 🟢 MED | Auditor (PF calc) | ❌ |
| MC-01 | Market | 🔴 CRITICAL | Scanner (real-time loop) | ❌ |
| MC-02 | Market | 🟡 HIGH | Scanner | ❌ |
| MC-03 | Market | 🟡 HIGH | Risk Guard / Strategist | ❌ |
| MC-04 | Market | 🟡 HIGH | Strategist (sanity) | ❌ |
| MC-05 | Market | 🟢 MED | Scanner | ❌ |
| SF-01 | System | 🟡 HIGH | BrokerManager fallback | ❌ |
| SF-02 | System | 🔴 CRITICAL | Risk Guard | ❌ |
| SF-03 | System | 🟡 HIGH | LLMRouter | ❌ |
| SF-04 | System | 🟡 HIGH | Orchestrator | ❌ |
| SF-05 | System | 🔴 CRITICAL | Sentinel timeout | ❌ |
| OP-01 | Operator | 🔴 CRITICAL | HITL handler | ❌ |
| OP-02 | Operator | 🟡 HIGH | HITL timeout | ❌ |
| OP-03 | Operator | 🟢 MED | TelegramBridge | ❌ |
| LC-01 | Lifecycle | 🟡 HIGH | Auditor (month scope) | ❌ |
| LC-02 | Lifecycle | 🟢 MED | Orchestrator | ❌ |
| LC-03 | Lifecycle | 🟢 MED | HITL + Auditor | ❌ |
| EC-01 | Edge | 🟡 HIGH | Risk Guard (boundary) | ❌ |
| EC-02 | Edge | 🟢 MED | Sentinel (race) | ❌ |

**Existing tests:** 4 (HP-01 partial, HP-03)
**New tests needed:** 30
**Critical gap tests:** 8 (must pass before live)

---

## Gaps & Open Questions

### Gaps in Current System (from these scenarios)

1. **Event calendar broken** — HP-04 will fail. `is_event_day()` always returns False.
2. **No Scanner real-time loop** — MC-01 cannot pass. Scanner is single-fetch only.
3. **Sentinel timeout handling absent** — SF-05 cannot pass. No 60s blackout logic.
4. **Cron not configured** — System won't even start at 09:30. SF-04 partially passes only if invoked manually.
5. **HITL override handler missing** — OP-01 cannot pass. No keyword detection.
6. **No reflection log enforcement** — LC-03, RM-04 cannot fully pass.
7. **No 30-day DD aggregation in Auditor** — RM-04 partially. Need `calculate_30d_dd_from_logs()`.
8. **Burn rate calc untested** — RM-06 and DD-02 need verification.

### Open Questions for Chairman

1. **Re-entry decision: HITL or auto?** — RM-01 / RM-02 ambiguous. Currently spec says `can_re_enter()` returns True if attempts available, but should this also require Telegram approval?

2. **Sentinel poll frequency** — Spec says `monitor_interval_seconds: 2`. Is 2s feasible given LLM latency (Sentinel uses critical-tier LLM)?

3. **Caution period after halt restart** — Should LC-03 enforce tighter SL post-restart? Not explicitly in config.

4. **Multi-instrument portfolio SL** — RM-03 assumes Phase 3+ multi-instrument. For Phase 1 (NIFTY only), is portfolio SL just session SL? Logic should handle gracefully.

5. **MTD reset logic** — LC-01: should April losses count toward 30-day rolling DD into May? (Per RM-04, 30-day window crosses month boundaries — but MTD per "month-to-date" resets.) These are different metrics; need clear naming.

6. **Hard-kill vs soft-kill recovery** — DD-04 soft kill vs hard kill — what's the recovery path for each?

---

## Recommended Test Sequence (Weekend Plan)

### Day 1 (Sat 2026-05-09): CRITICAL scenarios
Run 8 critical scenarios (HP-04, RM-01, RM-02, RM-04, RM-05, MC-01, SF-02, SF-05, OP-01).
Identify which fail due to gaps (most will).

### Day 2 (Sun 2026-05-10): HIGH + extension
Implement minimal mock fixtures for failing tests. Expect 60% pass rate.
Fix critical-path bugs (event calendar, scanner loop, sentinel timeout).

### Day 3 (Mon 2026-05-11): Pre-live check
Run all 32 scenarios. Target: 26/32 passing (80%+).
Reserved 6 = lifecycle/edge that don't block live but should be fixed within Phase 1 soak window.

---

## Implementation Hints

### Adding Scenarios to crew_test.py
Each scenario becomes a test function:
```python
def test_RM_01_session_sl_first_hit():
    # 1. Setup mock JSONL logs
    seed_logs(mtd_pnl=0, sessions=[])
    
    # 2. Set environment for mock market
    os.environ['ANTARIKSH_MOCK_VIX'] = '14'
    os.environ['ANTARIKSH_MOCK_PNL_TRAJECTORY'] = '[-500, -1500, -2500, -3500]'
    
    # 3. Run crew
    crew = build_crew()
    result = crew.kickoff()
    
    # 4. Assertions
    assert market_state['exit_reason'] == 'Stop loss'
    assert market_state['pnl_realized'] == -3500
    assert market_state['re_entries_used'] == 0  # before re-entry decision
    assert ReEntryTracker.can_re_enter() == True
    assert market_state['halt'] == False
    
    # 5. Verify JSONL written
    last_entry = read_last_jsonl()
    assert last_entry['exit_reason'] == 'Stop loss'
    assert 'post_mortem_required' in last_entry
```

### Mock Time Helper
```python
@contextmanager
def mock_time(target: str):
    """Override datetime.now() for the duration of the test."""
    real_dt = datetime.now
    datetime.now = lambda: datetime.fromisoformat(target)
    yield
    datetime.now = real_dt
```

### Mock PnL Trajectory
```python
class MockSentinel:
    def __init__(self, trajectory):
        self.trajectory = trajectory
        self.idx = 0
    
    def get_mtm(self):
        if self.idx >= len(self.trajectory):
            return self.trajectory[-1]
        val = self.trajectory[self.idx]
        self.idx += 1
        return val
```

---

## Sign-Off

**Author:** Claude (interim CEO)
**Status:** DRAFT — for chairman review
**Next step:** Discuss scenarios over weekend; mark which are MUST-PASS before Monday live; implement fixtures and run weekend test cycle.
