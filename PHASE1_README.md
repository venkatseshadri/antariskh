# Antariksh Phase 1 MVS — Minimum Viable System

**Status:** Phase 1 scaffolding complete. Ready for data integration and iteration.

**Timeline:** 1–2 weeks of operational soak-test (dry-run, no real money).

## What Is Phase 1 MVS?

A **minimal, working autonomous trading system** that implements the Varaha strategy on NIFTY weekly options (Iron Butterfly, 1 lot, ₹3,500 SL, VIX<20 gate).

**Key constraint:** Real market data, dry-run execution (no broker orders). Validates operational structure without risking capital.

### Two-Message Protocol

1. **9:30 AM Entry Gate Message**
   - Gate decision: PASS or SKIP
   - If PASS: instrument, spot, ATM strike, contract details, SL/TP targets
   - User can override with ❌ reaction (system learns from feedback)

2. **2:35 PM Exit Report Message**
   - Backtest result (mock P&L if traded)
   - MTD stats (profit factor, win rate, max DD)
   - System status (✅ operational, resource usage)

## Architecture

```
phase1_mvs.py                Main orchestrator (entry point)
├── MarketDataBridge         Pull real VIX, NIFTY spot, events
├── GateChecker             3-layer gate (Regime → Signal → Confirmation)
├── TradeDecisionEngine     Iron Butterfly trade plan
├── Backtester              Dry-run P&L simulation
├── TelegramBridge          Two-Message Protocol
├── CFOAuditor              Resource + capital tracking
└── Phase1Orchestrator      Coordinator
```

### Governance Layers

| Layer | Status | Notes |
|---|---|---|
| **L1 — Purpose/Invariants** | ✅ Implemented | Capital preservation, ₹1,000/day target, kill-switch rules |
| **L2 — Mechanisms** | ✅ Implemented | Gate exists, SL exists, cooldowns, skip conditions |
| **L3 — Parameter Values** | ✅ Config-locked | `config/antariksh_rules.yaml`: ₹3,500 SL, VIX<20, etc. |

### CFO Auditing (Active from Day 1)

Each session logged to `logs/cfo_audit_YYYYMMDD.jsonl`:

```json
{
  "timestamp": "2026-05-08T18:18:59",
  "gate_pass": false,
  "trade_executed": false,
  "backtest_pnl": 0,
  "resources_used": {
    "llm_tokens_approx": 500,
    "session_duration_seconds": 300
  },
  "capital_impact": {
    "gross_pnl": 0,
    "net_pnl": 0,
    "free_cash_after": 11000
  }
}
```

CFO duties:
- Track token spend per agent (Opus vs DeepSeek vs Haiku)
- Monitor session duration and compute efficiency
- Validate each trade decision against L1 burn-rate rule (10-day rolling loss < 30% free cash)
- Flag capital preservation violations before they become real losses

## Current Status — Completed in Phase 1 Scaffold

✅ **Orchestrator** — `Phase1Orchestrator.run()` ties all pieces together
✅ **Gate logic** — Layer 1 (VIX, event day, entry window) implemented; Layers 2–3 scaffolded
✅ **Trade plan generation** — ATM strike calc, Iron Butterfly legs, SL/TP targets
✅ **Two-Message Protocol** — 9:30 AM entry + 2:35 PM exit message formats
✅ **CFO auditing** — JSON session logs with resource and capital tracking
✅ **Backtester** — Dry-run mock P&L (will become realistic in next iteration)
✅ **Logging** — File + console, timestamped, categorized by agent

## TODO — Priority Order for Phase 1 Iteration

### Week 1: Real Data Integration

**1. Market Data Bridge** (CRITICAL)
- [ ] `MarketDataBridge.get_current_vix()` — broker API call or NSE MSER scraper
- [ ] `MarketDataBridge.get_nifty_spot()` — live price from broker
- [ ] `MarketDataBridge.is_event_day()` — load `config/event_calendar.json`
- [ ] Verify data updates at 9:30 AM IST (cron + systemd timer)

**2. Telegram Integration**
- [ ] Hook `TelegramBridge.send_message()` to write to `/tmp/antariksh_telegram.txt`
- [ ] picoclaw watches and relays to user's Telegram
- [ ] Test: run phase1_mvs.py manually, confirm Telegram message arrives

**3. Scheduler (Cron)**
- [ ] Create `scheduler/run_phase1_9am.sh` — invoke phase1_mvs.py at 9:30 AM IST
- [ ] Create `scheduler/run_phase1_2pm.sh` — invoke phase1_mvs.py at 2:35 PM IST
- [ ] Test on mock time (override time for testing)

### Week 2: Realism + Soak-Test

**4. Backtester Realism**
- [ ] Integrate varaha_master.py for real contract lookups
- [ ] Estimate entry premium from real option prices
- [ ] Simulate intraday P&L based on volatility + theta decay
- [ ] Log trade-level details for post-session review

**5. Gate Layer 2–3 Implementation** (Data-driven)
- [ ] Layer 2: Calculate supertrend_1min from real 1-min bars (stored by Orbiter?)
- [ ] Layer 3: Implement 2-of-3 confirmation (EMA alignment, SMC BoS, ADX>20)
- [ ] Log signal state for post-mortem if gate skips

**6. Soak-Test**
- [ ] Run on paper for 10–15 sessions (≈2 weeks)
- [ ] Operational correctness checklist:
  - [ ] Crons fire on time (no missed sessions)
  - [ ] Telegram messages arrive at 9:30 AM + 2:35 PM
  - [ ] Gate decisions are reasonable (not skipping every session, not always trading)
  - [ ] Audit logs are complete and parseable
  - [ ] No crashes, no unhandled exceptions
- [ ] If soak-test passes: Phase 2 decision (activate CFO + Asset Manager, prep for real money)

## How to Run Phase 1 MVS

### Manual (Test)
```bash
cd /home/trading_ceo/antariksh
python3 phase1_mvs.py
```

Expected output (if outside entry window):
```
Gate check result: gate_pass=False, reason='Outside entry window 10:30:00-11:30:00'
```

### Scheduled (Production)
```bash
# Install cron job (to be done in Week 1)
# Runs at 9:30 AM and 2:35 PM IST on weekdays
crontab -e
# Add:
# 30 09 * * 1-5 /home/trading_ceo/antariksh/scheduler/run_phase1_9am.sh
# 35 14 * * 1-5 /home/trading_ceo/antariksh/scheduler/run_phase1_2pm.sh
```

### Logs
```bash
# Session log (today)
tail -f /home/trading_ceo/antariksh/logs/phase1_20260508.log

# CFO audit (all sessions)
cat /home/trading_ceo/antariksh/logs/cfo_audit_20260508.jsonl | jq .

# Telegram messages (written by bridge)
tail -f /tmp/antariksh_telegram.txt
```

## Phase 1 Success Criteria

From STRATEGY_DESIGN_QUESTIONS.md §Q12 + CHARTER.md:

✅ **Operational correctness, NOT strategy correctness.** P&L is secondary.

- [ ] 10–15 consecutive trading days without crashes
- [ ] 100% cron execution (no missed sessions)
- [ ] 100% Telegram message delivery (9:30 AM + 2:35 PM)
- [ ] Gate decisions are reasonable (skip rate 30–60%, not 0 or 100%)
- [ ] Audit logs are parseable and complete
- [ ] CFO log shows token usage declining (via caching) or at least stable
- [ ] Capital preservation rule enforced (kill-switch never triggers in Phase 1, but logic tested)

**If Phase 1 passes:** Promote to Phase 2 (activate CFO, Asset Manager, prep for real money with ₹5L capital).

## Design Philosophy — Three Layers + CEO/CFO

(From memory: `antariksh_project.md`)

**L1 (Immutable):** Don't burn capital. Rate-based burn watch (10-day rolling loss < 30% free cash). Mission: ≥1%/month profitability.

**L2 (Constitutional):** Mechanisms exist: daily SL, 30-day DD cap, skip conditions, single-strategy-first, cooldowns.

**L3 (Operational):** Parameter values (₹3,500 SL, VIX<20, ±300 wings, ₹1,000 target). CFO screens all L3 proposals against L1 first.

**CEO (Vishnu, to be built):** Owns Phase 1 MVP build + operations. Claude is interim CEO during Phase 1; steps aside when Vishnu is stable.

**CFO:** Governance (forward-projection) + resource efficiency (tokens = cash). Not just trade risk; also OpEx management.

## Next Session — What to Focus On

1. **Data bridge** — get real VIX + NIFTY spot flowing into phase1_mvs.py
2. **Telegram hook** — confirm messages are relayed to your phone
3. **Scheduler** — set up cron to run at 9:30 AM + 2:35 PM
4. **Manual test** — run one full cycle during market hours to confirm end-to-end flow
5. **Iteration cycle** — gather feedback, enhance backtester, implement Layer 2–3 signals

## File Structure

```
antariksh/
├── phase1_mvs.py                  Main orchestrator
├── config/
│   └── antariksh_rules.yaml       L3 parameter config (immutable in Phase 1)
├── logs/
│   ├── phase1_YYYYMMDD.log       Session logs (INFO + DEBUG)
│   └── cfo_audit_YYYYMMDD.jsonl   CFO audit trail
├── scheduler/
│   ├── run_phase1_9am.sh          Cron wrapper (9:30 AM)
│   └── run_phase1_2pm.sh          Cron wrapper (2:35 PM)
├── docs/
│   ├── Varaha_Sovereign_Constitution.md  
│   └── Project_Varaha_CrewAI_Design.md
├── agents/                         (to be populated: Orchestrator, Scanner, etc.)
├── crews/                          (to be populated: daily crew, weekly analyzer)
├── tools/                          (to be populated: thin broker API wrappers)
├── hitl/                           (to be populated: Telegram HITL interface)
├── harvested/                      (to be populated: read-only copies of Varaha infra)
└── autonomy/                       (Phase 2+: trust engine, change governor)
```

## Key Design Decisions (Phase 1 Ratified)

1. **Real data, no simulation.** Even in dry-run, use live VIX, spot, events.
2. **No broker execution, dry-run P&L.** Validate logic without risking capital.
3. **Two-Message Protocol.** One entry, one exit. No intraday streaming (prevents "session brain" override urge).
4. **Async gate, learn from feedback.** Auto-execute on L1 checks; user overrides with NO reaction; system learns.
5. **CFO from day 1.** Monitor resources (tokens, time) and capital (P&L, preservation) even in Phase 1.
6. **Iteration-first.** Don't pre-optimize. Scaffold for easy addition of pieces. Launch, gather feedback, improve.

## Questions / Next Steps

1. **Broker API credentials:** How should we store/access them? (picoclaw secrets vault?)
2. **Event calendar:** Where is `config/event_calendar.json`? Does it exist, or do we build it?
3. **Telegram relay:** Should phase1_mvs.py write to `/tmp/antariksh_telegram.txt`, or call picoclaw directly?
4. **Market data sources:** Use Shoonya API (existing), NSE MSER (public), or yfinance?
5. **Backtest accuracy:** Should we simulate MTM updates at 1-min intervals, or daily snapshot?

---

**Phase 1 MVS Ready to Iterate.** Scaffolding is solid. Data integration and Telegram hook are next priorities.
