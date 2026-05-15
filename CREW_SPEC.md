# Antariksh Phase 2 — CrewAI Agent Role Specs & Task Flow — SUPERSEDED

> **Status:** ARCHIVED — superseded by 10-crew system  
> **Date:** 2026-05-08 (original) / 2026-05-15 (archived)  
> **Reason:** This 7-agent spec (Orchestrator, Scanner, Strategist, Executor, Sentinel, Risk Guard, Auditor) was the Phase 2 design. The project has since evolved into 10 specialized crews (OM, TA, PM, PA, AM, CEO, CTO, Dev, QA, TelegramReporter) with Chairman orchestrator dispatch, Ralph Loop PRD verification, and self-improvement mandate. See `ARCHITECTURE.md` for current state.

---

## Agent Roster

| # | Agent | Role | LLM Required | Autonomy |
|---|---|---|---|---|
| 1 | **Orchestrator** | Master coordinator — manages entry/exit windows, delegates tasks, pauses on Risk Guard alerts | DeepSeek | Can delegate, CANNOT override Risk Guard HALT |
| 2 | **Scanner** | Market data ingestion — VIX, NIFTY spot, option chain, event calendar. Updates shared `market_state` | DeepSeek | Read-only — feeds data upstream |
| 3 | **Strategist** | Trade plan generation — ATM strike, wing width, lot size, Iron Fly 4-leg basket. Layer 2/3 signals | DeepSeek | Recommends plans — Executor executes |
| 4 | **Executor** | Order placement — Flattrade primary, Shoonya fallback. Hedge-first order sequencing | DeepSeek (stubbed) | Follows Strategist plans only |
| 5 | **Sentinel** | Real-time P&L tracking — MTM, SL proximity alerts, target/EOD notifications | DeepSeek | Alerts only — never closes positions |
| 6 | **Risk Guard** | L1 capital preservation — hard limits: daily SL ₹3,500, portfolio ₹4,500, 30-day DD ₹30,000 | DeepSeek (recs only) | **CAN AUTONOMOUSLY HALT** — no override |
| 7 | **Auditor** | Governance logging — immutable JSONL audit trail, L1 invariant validation, Phase 1 log integration | DeepSeek | Append-only — never modifies logs |

---

## Task Flow (Daily Session)

```
┌─────────────────────────────────────────────────────────────┐
│                    9:30 AM — ENTRY SESSION                    │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  [1] Scanner: Fetch VIX, NIFTY spot, check window            │
│       │                                                      │
│       ▼                                                      │
│  [2] Gate Check (code-level): VIX < 20? Window valid?        │
│       │                                                      │
│       ├── NO  ──▶ Gate SKIP → [6] Auditor logs → EXIT        │
│       │                                                      │
│       ▼ YES                                                  │
│  [3] Strategist: Generate Iron Fly trade plan                 │
│       │                                                      │
│       ▼                                                      │
│  [4] Risk Guard: Validate L1 capital rules                    │
│       │                                                      │
│       ├── HALT ──▶ Trading paused → [6] Auditor logs → EXIT  │
│       │                                                      │
│       ▼ APPROVED                                             │
│  [5] Executor: Place 4-leg basket (stubbed in Phase 2)       │
│       │                                                      │
│       └──▶ [6] Auditor: Append session to JSONL audit trail   │
│                                                              │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                 10:30 AM–2:30 PM — MONITORING                 │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  [Sentinel] Continuous loop (every 2s):                      │
│     ├─ MTM P&L from Black-Scholes                            │
│     ├─ SL proximity: within ₹500 → escalate to Risk Guard    │
│     ├─ Target hit → notify Executor to close                 │
│     └─ EOD approaching (14:25) → notify Executor              │
│                                                              │
│  [Risk Guard] Hard limit watchdog (parallel):                │
│     ├─ P&L ≤ -₹3,500 → HALT                                  │
│     ├─ Portfolio ≤ -₹4,500 → HALT                            │
│     └─ 10-day burn > 30% free cash → HALT                    │
│                                                              │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                    2:35 PM — EXIT SESSION                     │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  [1] Executor: Close all positions (hard square-off)         │
│       │                                                      │
│       ▼                                                      │
│  [2] Sentinel: Calculate final session P&L                   │
│       │                                                      │
│       ▼                                                      │
│  [3] Auditor: Final JSONL entry + MTD summary                │
│       │                                                      │
│       ▼                                                      │
│  [4] Telegram: Send exit report (two-message protocol)       │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## L1 Capital Preservation Rules (Risk Guard — HARD, DETERMINISTIC)

| Rule | Threshold | Action |
|---|---|---|
| Daily SL | P&L ≤ -₹3,500 | HALT trading for session |
| Portfolio cumulative SL | Cumulative loss > ₹4,500 | HALT trading until Chairman approval |
| 30-day drawdown | DD > ₹30,000 | HALT, full review required |
| Free cash floor | Net cash < ₹11,000 | HALT, cannot place orders |
| Burn rate (10-day) | Loss > 30% of free cash | HALT, lot size reduction mandatory |

**Risk Guard's HALT is absolute.** No agent can override. Not the Strategist. Not the Orchestrator. Only Chairman (human) can resume via Telegram.

---

## Shared State (`market_state` dict)

All agents read/write through a shared context dictionary:

```python
market_state = {
    "vix": float | None,
    "nifty_spot": float | None,
    "atm_strike": float | None,
    "trade_plan": dict | None,
    "gate_pass": bool,
    "gate_reason": str,
    "positions": dict,
    "session_pnl": float,
    "mtd_pnl": float,
    "halt": bool,
    "risk_ok": bool,
    "alerts": list[str],
    "audit_entries": list[dict],
}
```

---

## Integration Points

### Scanner ↔ BrokerManager
- `broker_manager.get_broker_manager().get_vix()` → `market_state['vix']`
- `broker_manager.get_broker_manager().get_nifty_spot()` → `market_state['nifty_spot']`
- Mock mode: `ANTARIKSH_MOCK_MODE=1` bypasses live broker

### Executor ↔ BrokerManager
- `broker_manager.place_order()` → stubbed in Phase 2 (Claude will wire Flattrade API)
- Order sequence: buy OTM wings first (hedge), 1.5s delay, sell ATM straddle

### Auditor ↔ Phase 1 CFO Logs
- Reads: `logs/cfo_audit_YYYY-MM-DD.jsonl` at crew startup → calculates MTD P&L
- Writes: Same JSONL schema, appending each session

### Telegram Bridge
- `telegram_bridge.TelegramBridge.send_entry_gate()` → 9:30 AM message
- `telegram_bridge.TelegramBridge.send_exit_report()` → 2:35 PM message
- `telegram_bridge.TelegramBridge.send_alert()` → Risk Guard alerts

---

## LLM Assignment (Cost Optimization)

| Agent | Current | Recommended for Production |
|---|---|---|
| Orchestrator | DeepSeek | Claude Sonnet (critical decisions) |
| Scanner | DeepSeek | DeepSeek (pattern matching, cost-efficient) |
| Strategist | DeepSeek | Claude Sonnet (options reasoning) |
| Executor | Deterministic (stubbed) | NO LLM — pure Python |
| Sentinel | DeepSeek | Claude Sonnet (real-time logic) |
| Risk Guard | Hard rules only | LLM for recommendations only |
| Auditor | DeepSeek | DeepSeek (bulk data, cost-efficient) |

---

## File Structure

```
antariksh/
├── crew_structure.py          # 7 agents + 6 tasks + crew definition (MAIN)
├── crew_test.py               # 4 mock tests (dry-run, trace, halt, high-VIX)
├── CREW_SPEC.md               # This file — role specs + flow diagram
├── phase1_mvs.py              # Phase 1 standalone (locked, DO NOT MODIFY)
├── broker_manager.py          # Dual-broker interface (Shoonya + Flattrade)
├── backtester.py              # Black-Scholes P&L calculator
├── cfo_auditor.py             # Phase 1 CFO audit (read-only for Phase 2)
├── telegram_bridge.py         # Telegram messaging via picoclaw
└── logs/
    └── cfo_audit_YYYY-MM-DD.jsonl  # Immutable audit trail
```

---

## Testing Commands

```bash
# Test 1: Mock dry-run (VIX gate pass)
python3 crew_test.py --mock-mode --vix 18.5 --nifty 24500 --time 10:30

# Test 2: Task dependency trace
python3 crew_test.py --trace

# Test 3: Risk Guard halt on capital breach
python3 crew_test.py --capital-floor-breach

# Test 4: Gate skip on high VIX
python3 crew_test.py --high-vix

# All tests
python3 crew_test.py --all
```
