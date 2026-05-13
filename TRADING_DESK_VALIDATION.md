# Antariksh Trading Desk — Cross-Session Validation Document

**Date:** 2026-05-12
**File:** `trading_desk.py` (`/home/trading_ceo/antariksh/trading_desk.py`)

---

## 1. ARCHITECTURE OVERVIEW

### Full Desk Hierarchy (State Machine)

```
 PREPARATION → VALIDATION → ACTION → MAINTENANCE → CLOSED
     │              │           │           │
   Scout         PM (capital  Executioner   Risk Agent
     │            check, lot  (places       (listens to
     ▼            auth)        orders)      WS + commands)
  Researcher
```

### 6 Agents

| # | Agent | Role | Tools | Delegation |
|---|-------|------|-------|------------|
| 1 | **Technical Scout** | Market regime detection (VIX, ADX, SuperTrend) | `scout_market_regime` | No |
| 2 | **Quantitative Researcher** | Strategy design + backtest + shift validation | `research_setup`, `researcher_backtest_shift` | No |
| 3 | **Portfolio Manager** | Capital check, lot authorization | `pm_approve` | No |
| 4 | **Execution Specialist** | Order placement (wings-first) | `execute_orders` | No |
| 5 | **Risk & Compliance Sentry** | Live monitoring, TSL, command issuance | `shifter_evaluate`, `risk_direct_shift` | No |
| 6 | **Leg Shifter** | Theta optimization, circular feedback | `shifter_evaluate` | No |

**Manager LLM:** DeepSeek (in hierarchical mode via LLM, but all risk decisions are DETERMINISTIC tools — no LLM in capital/risk path).

---

## 2. INFORMATION FLOWS (CONVEYOR BELT)

### Flow 2.1: Scout → Researcher (`MarketRegime`)
**File:** `trading_desk.py:155-174`
```python
@dataclass
class MarketRegime:
    regime: str        # TRENDING_BULL | TRENDING_BEAR | SIDEWAYS
    vix: float
    nifty_spot: float
    adx: float
    supertrend: str    # UP | DOWN | NEUTRAL
    gap_pct: float
    event_day: bool
    timestamp: str
```
**Tool:** `scout_market_regime()` — line 99

### Flow 2.2: Researcher → PM (`ProposedSetup`)
**File:** `trading_desk.py:178-198`
```python
@dataclass
class ProposedSetup:
    strategy_type: str     # IRON_BUTTERFLY | CREDIT_SPREAD
    instrument: str        # NIFTY | SENSEX
    spot: float
    atm_strike: int
    wing_width: int        # 300 normal, 350 high VIX
    lots: int
    exp_profit: float      # Expected P&L ₹
    max_loss: float        # Max loss estimate ₹
    req_margin: float      # Required margin ₹
    legs: List[Dict]       # 4-leg basket [{action, strike, option_type, role}]
    sl_level: float
    tp_level: float
    gamma_risk: str        # LOW | MED | HIGH
    vega_risk: str         # LOW | MED | HIGH
    timestamp: str
```
**Tool:** `research_setup()` — line 136

### Flow 2.3: PM → Executioner (`AuthorizedOrder`)
**File:** `trading_desk.py:202-215`
```python
@dataclass
class AuthorizedOrder:
    status: str            # AUTHORIZED | REJECTED
    symbol: str            # NIFTY | SENSEX
    strategy: str
    authorized_lots: int   # PM-approved lot count (1 or 2)
    max_margin: float      # Max allowed margin ₹
    spec: Dict             # Full strategy spec dict
    sl_level: float
    tp_level: float
    tsl_config: Dict       # {tsl_activation_pct, tsl_lock_ratio}
    timestamp: str
```
**Tool:** `pm_approve()` — line 175

### Flow 2.4: Executioner → Risk Agent (`HandoffReport`)
**File:** `trading_desk.py:219-229`
```python
@dataclass
class HandoffReport:
    symbol: str
    order_ids: Dict[str, str]        # {leg_name: norenordno}
    fills: List[Dict]                # [{leg, tsym, status, order_id, fill_price}]
    entry_prices: Dict[str, float]   # {tsym: avg_entry}
    tsyms: Dict[str, str]            # {leg_name: trading_symbol}
    total_legs: int
    wings_count: int                 # BUY hedges (2 for Iron Fly)
    center_count: int                # SELL straddle (2 for Iron Fly)
    timestamp: str
```
**Tool:** `execute_orders()` — line 214

### Flow 2.5: Leg Shifter → Researcher (`ShiftProposal`)
**File:** `trading_desk.py:232-240`
```python
@dataclass
class ShiftProposal:
    reason: str                # THETA_EXHAUSTED | GAMMA_SQUEEZE
    old_leg: Dict
    new_strike: int
    theta_current: float
    theta_target: float
    premium_erosion_pct: float  # Must exceed 70% to trigger
    timestamp: str
```

---

## 3. LISTEN TRIGGERS (EVENT-DRIVEN)

All triggers live in `ListenTriggers` class — `trading_desk.py:472-688`

### 3.1 `event_handler_order_update` (Risk Agent)
**Method:** `ListenTriggers.on_order_update()` — line 518

| Trigger | Condition | Action | Command Issued |
|---------|-----------|--------|----------------|
| TP ORDER fills | `status == "COMPLETE" and order_type == "TP"` | Cancel ALL SL orders | `CANCEL_ALL_SL` |
| SL ORDER fills | `status == "COMPLETE" and order_type == "SL"` | Cancel ALL TP orders | `CANCEL_ALL_TP` |
| Other order completion | `status == "COMPLETE"` but not TP/SL | Log only | `IGNORE` |

**Side effects:**
- Sets `desk.positions_open = False` on TP/SL fill
- Clears `active_sl_orders` or `active_tp_orders`
- Returns CANCEL command dict with cancelled order IDs

### 3.2 `event_handler_feed_update` (Risk Agent)
**Method:** `ListenTriggers.on_feed_update()` — line 570

| Trigger | Condition | Action | Command Issued |
|---------|-----------|--------|----------------|
| Hard SL breach | `ltp >= avg_entry * (1 + sl_buffer_pct/100)` | EXIT all positions | `EXIT_POSITION` |
| TSL breach | `tsl_active and ltp > tsl_level` | MODIFY SL order | `MODIFY` with new trigger |
| No breach | Neither condition met | Continue monitoring | `HOLD` |
| No positions | `positions_open == False` | Ignore tick | `IGNORE` |

**Tracks:** `highest_favorable` (lowest LTP seen — tracks favorable moves for short positions)

### 3.3 Executioner's Listen (Risk Agent Commands)
**Method:** `ListenTriggers.on_risk_command()` — line 625

| Command | API Call | Response |
|---------|----------|----------|
| `MODIFY` | `api.modify_order(order_id, newtrigger_price)` | `MODIFY_CONFIRMED` |
| `CANCEL` | `api.cancel_order(orderno)` | `CANCEL_CONFIRMED` |
| `EXIT` | Close all positions | `EXIT_CONFIRMED`, phase→CLOSED |

---

## 4. LEG SHIFTER LOOP (CIRCULAR FEEDBACK)

**File:** `trading_desk.py:690-795`

### The Loop:
```
Shifter ──feed_update──▶  evaluate theta exhaustion
   │                           │
   │                    premium_erosion > 70% ?
   │                           │ YES
   │                           ▼
   │                    Propose ShiftProposal
   │                           │
   │                           ▼
   │                    Researcher ──backtest──▶  Validate
   │                                                  │
   │                                           backtest_pnl > 0 ?
   │                                                  │ YES
   │                                                  ▼
   │                    Risk Agent ──COMMAND──▶  Executioner
   │                       EXIT old leg, EXECUTE new leg
   │                                                  │
   └────────────────── Executioner ──CONFIRM──▶ (loop closed)
```

### Tools involved:
1. `shifter_evaluate()` — line 693 — Checks premium erosion %, produces `ShiftProposal`
2. `researcher_backtest_shift()` — line 740 — Backtests proposed new strike via `IronFlyBacktester`
3. `risk_direct_shift()` — line 773 — Issues EXIT + EXECUTE commands to Executioner

### Theta Exhaustion Logic:
```python
premium_erosion = ((avg_entry - current_ltp) / avg_entry) * 100
theta_exhausted = premium_erosion > 70.0
```
- Max 2 shifts per session (`desk.shift_count < 2`)
- Backtest must show positive P&L to proceed
- If rejected, ShiftProposal is discarded

---

## 5. SHARED DESK STATE

**Class:** `DeskState` — `trading_desk.py:247-278`
**Singleton:** `desk` — line 280

### Key state fields:
| Field | Type | Purpose |
|-------|------|---------|
| `phase` | `DeskPhase` enum | Current state machine phase |
| `halt` | `bool` | Trading halted (capital breach) |
| `regime` | `MarketRegime` | Latest market regime packet |
| `setup` | `ProposedSetup` | Latest strategy proposal |
| `order` | `AuthorizedOrder` | Latest PM authorization |
| `handoff` | `HandoffReport` | Latest execution handoff |
| `positions_open` | `bool` | Whether positions are live |
| `session_pnl` | `float` | Current session P&L |
| `active_sl_orders` | `Dict[str,str]` | Open SL orders {leg_name: order_id} |
| `active_tp_orders` | `Dict[str,str]` | Open TP orders {leg_name: order_id} |
| `highest_favorable` | `float` | Best price seen (for TSL tracking) |
| `tsl_active` | `bool` | Whether TSL is currently enabled |
| `tsl_level` | `float` | Current TSL trigger price |
| `shift_proposals` | `List[ShiftProposal]` | All shift proposals this session |
| `shift_count` | `int` | Number of shifts executed |

Thread-safe via `threading.Lock` on all mutations.

---

## 6. VERIFICATION COMMANDS

All commands run from `/home/trading_ceo/antariksh/`.

### 6.1 Show Data Flows Architecture
```bash
cd /home/trading_ceo/antariksh
python3 trading_desk.py --show-flows
```
**Expected:** ASCII art diagram of all flows, triggers, and loops.

### 6.2 Test All Listen Triggers
```bash
cd /home/trading_ceo/antariksh
python3 trading_desk.py --test-triggers
```
**Expected output — 4 test results:**
```json
{
  "tp_complete_trigger": {
    "event": "order_update",
    "trigger": "TP_COMPLETE",
    "action": "CANCEL_ALL_SL",
    "cancelled_orders": ["ORD-SL-001"],
    "command": "CANCEL"
  },
  "tsl_breach_trigger": {
    "event": "feed_update",
    "action": "IGNORE",
    "reason": "no_positions"
  },
  "executioner_respond": {
    "flow": "Executioner → Risk Agent",
    "action": "MODIFY_CONFIRMED",
    "order_id": "ORD-SL-001",
    "new_trigger": 95.0,
    "status": "PENDING",
    "api_call": "api.modify_order(order_id=ORD-SL-001, newtrigger_price=95.0)"
  },
  "shifter_eval": {
    "phase": "maintenance",
    "loop": "shifter",
    "premium_erosion_pct": 60.0,
    "theta_exhausted": false,
    "action": "HOLD"
  }
}
```

**Verification checklist:**
- [ ] TP_COMPLETE trigger fires: `action=CANCEL_ALL_SL`, cancelled `ORD-SL-001`
- [ ] TSL trigger ignores correctly (positions already closed by TP trigger)
- [ ] Executioner responds to MODIFY with proper `api.modify_order` call
- [ ] Shifter shows 60% erosion (below 70% threshold) → `action=HOLD`

### 6.3 Test Maintenance Cycle
```bash
cd /home/trading_ceo/antariksh
python3 trading_desk.py --mock --maintenance-cycle
```
**Expected output:**
```json
{
  "phase": "maintenance",
  "feed_trigger": {
    "event": "feed_update",
    "action": "HOLD",
    "ltp": 60.0
  },
  "order_trigger": {
    "event": "order_update",
    "trigger": "TP_COMPLETE",
    "action": "CANCEL_ALL_SL",
    "cancelled_orders": ["ORD-SL-001"],
    "command": "CANCEL"
  },
  "shifter_eval": {
    "phase": "maintenance",
    "loop": "shifter",
    "action": "NO_POSITIONS"
  }
}
```

**Verification checklist:**
- [ ] Feed update processes LTP 60.0 (below SL 110.0) → `HOLD`
- [ ] Order update detects TP_COMPLETE → CANCEL_ALL_SL
- [ ] Shifter detects positions closed → `NO_POSITIONS`
- [ ] Phase transitions: preparation → maintenance
- [ ] Log shows MOCK state initialized

### 6.4 Syntax and Import Check
```bash
cd /home/trading_ceo/antariksh
python3 -c "
import ast
ast.parse(open('trading_desk.py').read())
print('SYNTAX OK')
"
```
```bash
cd /home/trading_ceo/antariksh
python3 -c "
import sys, os
os.environ['ANTARIKSH_MOCK_MODE'] = '1'
from trading_desk import (
    DeskState, DeskPhase,
    MarketRegime, ProposedSetup, AuthorizedOrder,
    HandoffReport, ShiftProposal,
    ListenTriggers,
    desk,
    scout_market_regime, research_setup,
    pm_approve, execute_orders,
    shifter_evaluate, researcher_backtest_shift,
    risk_direct_shift,
)
print('ALL IMPORTS OK')
print(f'Desk phase: {desk.phase.value}')
"
```

### 6.5 Full Session (requires DEEPSEEK_API_KEY)
```bash
export DEEPSEEK_API_KEY="your-key"
cd /home/trading_ceo/antariksh
python3 trading_desk.py --mock --full-session --vix 18.5 --nifty 24500
```

### 6.6 Preparation Phase Only
```bash
cd /home/trading_ceo/antariksh
python3 trading_desk.py --mock --preparation-only --vix 18.5 --nifty 24500
```

---

## 7. DATA FLOW SUMMARY TABLE

| From | To | Packet Type | Trigger | Data Content |
|------|----|------------|---------|-------------|
| Scout | Researcher | `MarketRegime` | `scout_market_regime()` completes | VIX, ADX, SuperTrend, regime type |
| Researcher | PM | `ProposedSetup` | `research_setup()` completes | Strikes, wings, lots, exp P&L, legs |
| PM | Executioner | `AuthorizedOrder` | `pm_approve()` completes | Lots authorized, margin cap, full spec |
| Executioner | Risk Agent | `HandoffReport` | `execute_orders()` completes | Order IDs, fill prices, tsyms |
| Broker WS | Risk Agent | LTP ticks + Order status | WebSocket callback | Live price + order state changes |
| Risk Agent | Executioner | Modify/Cancel/Exit command | SL/TSL breach OR TP fill | `trade_command` JSON |
| Shifter | Researcher | `ShiftProposal` | Theta > 70% eroded | New strike, premium erosion % |
| Researcher | Risk Agent | `ValidatedShift` | Backtest confirms | Close leg + Open leg instructions |
| Risk Agent | Executioner | Shift commands | Validation passes | EXIT old + EXECUTE new |

---

## 8. KEY DESIGN DECISIONS

1. **All risk decisions are DETERMINISTIC** — no LLM in the Risk Agent's decision path. The `ListenTriggers` class uses pure Python comparison logic.
2. **Wings-first sequencing** — Executioner places BUY (hedge) legs before SELL (straddle) to unlock margin.
3. **Risk Agent commands, never touches API** — The Risk Agent issues structured commands via `ListenTriggers.on_risk_command()`. The Executioner translates those into `api.modify_order()` / `api.cancel_order()` / close calls.
4. **Lazy LLM initialization** — `_get_llm()` avoids import-time crashes when `DEEPSEEK_API_KEY` is not set. Deterministic tests work without an API key.
5. **Thread-safe DeskState** — All mutations go through `self._lock` to support production WebSocket callback threading.
6. **Maximum 2 shifts per session** — Prevents infinite theta-chasing loops.
7. **Backtest-gated shifts** — No shift executes unless the Researcher's backtest confirms positive P&L.
8. **Simulation mode by default** — All broker API calls return mock data unless credentials are configured.

---

## 9. FILE REFERENCE

| Component | File | Lines |
|-----------|------|-------|
| Data packet definitions | `trading_desk.py` | 130-240 |
| DeskState singleton | `trading_desk.py` | 247-280 |
| Deterministic tools (6) | `trading_desk.py` | 96-319 |
| ListenTriggers class | `trading_desk.py` | 472-688 |
| Leg Shifter tools | `trading_desk.py` | 690-795 |
| Agent definitions (6) | `trading_desk.py` | 798-950 |
| Task definitions (6) | `trading_desk.py` | 953-1040 |
| Crew builder | `trading_desk.py` | 1045-1070 |
| CLI entry point | `trading_desk.py` | 1490-1580 |
| Backtester (reused) | `backtester.py` | 1-161 |
| Broker API (reused) | `broker_manager.py` | 1-317 |
| Existing TA crew (reused config) | `crews/ta_crew.py` | 1-424 |
| Existing PM crew (reused config) | `crews/pm_crew.py` | 1-167 |
| Agent config (reused) | `config/agents.json` | 1-110 |

---

## 10. QUICK START FOR ANOTHER SESSION

```bash
# 1. Verify syntax
cd /home/trading_ceo/antariksh
python3 -c "import ast; ast.parse(open('trading_desk.py').read()); print('OK')"

# 2. Show the architecture
python3 trading_desk.py --show-flows

# 3. Test all event triggers (no API key needed)
python3 trading_desk.py --test-triggers

# 4. Run a mock maintenance cycle
python3 trading_desk.py --mock --maintenance-cycle

# 5. If API key available, run full session
export DEEPSEEK_API_KEY="sk-..."
python3 trading_desk.py --mock --full-session --vix 18.5 --nifty 24500
```
