# Leg Shifter — Code Reference

**File:** `antariksh/trading_desk.py`
**Total:** 1702 lines | **Shifter code:** lines 894–1049 (tools) + 1175–1287 (agent/task) + 1456–1462 (runtime)

---

## Overview

The Leg Shifter is a CrewAI agent that creates a **circular maintenance loop** during live positions. It monitors theta decay, proposes strike shifts, backtests them, and routes approved shifts to the Executioner — all at runtime, without closing the entire position.

```
Shifter → Researcher (backtest) → Risk Agent (direct) → Executioner (close old + open new)
```

---

## Constants & Limits

```python
# trading_desk.py (not explicit constants — inline)
THETA_EXHAUSTED = premium_erosion > 70.0    # line 923
MAX_SHIFT_COUNT = 2                          # line 924
PREMIUM_EROSION = (avg_entry - ltp) / avg_entry * 100  # line 918-920
MOCK_LTP = avg_entry * 0.40                  # line 917 (mock — needs live LTP)
```

---

## Tool 1: `shifter_evaluate()` — Lines 893–964

### Purpose
The Leg Shifter tool. Evaluates premium erosion on active positions. If theta is exhausted (>70% premium decayed), proposes a new optimal strike shift to the Researcher.

### Flow
```python
@tool
def shifter_evaluate() -> str:
    # 1. Guard: no open positions → return NO_POSITIONS
    if not desk.positions_open:
        return {"action": "NO_POSITIONS"}

    # 2. Guard: no handoff data → return error
    if not desk.handoff:
        return {"error": "No handoff data"}

    # 3. Calculate premium erosion
    avg_entry = sum(entry_prices) / len(entry_prices)   # line 916
    current_ltp = avg_entry * 0.40                       # line 917 — MOCK
    premium_erosion = (avg_entry - ltp) / avg_entry * 100

    # 4. Check theta exhaustion
    theta_exhausted = premium_erosion > 70.0             # line 922

    # 5. Propose shift if exhausted and under 2-shift limit
    if theta_exhausted and desk.shift_count < 2:
        desk.shift_count += 1
        shift = ShiftProposal(
            reason="THETA_EXHAUSTED",
            old_leg={"strike": desk.setup.atm_strike, "option_type": "PE"},
            new_strike=desk.setup.atm_strike + 50,
            theta_current=-2.5,
            theta_target=-8.0,
            premium_erosion_pct=round(premium_erosion, 1),
        )
        desk.shift_proposals.append(shift)
        return {"action": "PROPOSE_SHIFT", ...}

    # 6. No shift → HOLD or BLOCKED
    return {
        "premium_erosion_pct": premium_erosion,
        "theta_exhausted": theta_exhausted,
        "action": "HOLD" if not theta_exhausted else "BLOCKED",
    }
```

### Key Data
| Field | Value | Line |
|-------|-------|------|
| Trigger threshold | `premium_erosion > 70%` | 923 |
| Max shifts per trade | 2 | 924 |
| LTP source | `avg_entry * 0.40` (MOCK) | 917 |
| Shift direction | ATM + 50 (always upward) | 933 |
| Target theta | -8.0 | 935 |

---

## Tool 2: `researcher_backtest_shift()` — Lines 966–1022

### Purpose
Researcher validates the Shifter's proposal by running a backtest on the new strike. If P&L-positive, produces a `ValidatedShift` packet for the Risk Agent.

### Flow
```python
@tool
def researcher_backtest_shift() -> str:
    # 1. Guard: no proposals → NO_PROPOSALS
    latest = desk.shift_proposals[-1]   # line 980

    # 2. Build new plan at proposed strike
    new_plan = {
        "spot": spot,
        "atm_strike": latest.new_strike,
        "wing_width": wing,
        "target_profit": 800,
        "max_loss": 3000,
        "lots": 1,
    }

    # 3. Run backtest
    bt = IronFlyBacktester.backtest_iron_fly(new_plan, exit_spot=spot)
    pnl = bt.get("pnl_inr", 0)

    # 4. Decision
    if pnl > 0:
        return {"decision": "APPROVE_SHIFT",
                "close_leg": latest.old_leg,
                "open_leg": {"strike": latest.new_strike, "wing_width": wing}}
    else:
        return {"decision": "REJECT_SHIFT"}
```

---

## Tool 3: `risk_direct_shift(validated_shift: Dict)` — Lines 1025–1052

### Purpose
Risk Agent converts the Researcher's validated shift into Executioner commands: close old leg, open new leg.

### Flow
```python
@tool
def risk_direct_shift(validated_shift: Dict) -> str:
    # 1. Only act on APPROVE_SHIFT
    if validated_shift["decision"] != "APPROVE_SHIFT":
        return {"action": "SHIFT_REJECTED"}

    # 2. Extract close/open legs
    close_leg = validated_shift["close_leg"]
    open_leg = validated_shift["open_leg"]

    # 3. Return Executioner commands
    return {
        "phase": "maintenance",
        "flow": "Risk Agent → Executioner",
        "commands": [
            {"command": "EXIT",    "leg": close_leg, "reason": "SHIFT_CLOSE_OLD"},
            {"command": "EXECUTE", "leg": open_leg,  "reason": "SHIFT_OPEN_NEW"},
        ],
    }
```

---

## Agent Definitions — Lines 1175–1195

```python
shifter_agent = Agent(
    role="Leg Shifter (Theta Optimizer)",
    goal=(
        "Monitor theta decay on live positions. "
        "When premium erodes below threshold, propose optimal strike shift "
        "to the Researcher."
    ),
    backstory=(
        "You are the optimizer — always asking 'is this the best strike right now?' "
        "When theta is exhausted (premium decayed 70%+), you propose a shift. "
        "The Researcher backtests it. If validated, Risk directs Executioner."
    ),
    tools=[shifter_evaluate],
    allow_delegation=False,
    memory=True,
)
```

---

## Task Definition — Lines 1276–1287

```python
shifter_task = Task(
    description=(
        "MAINTENANCE PHASE — Leg Shifter loop.\n\n"
        "1. Call shifter_evaluate to check premium erosion\n"
        "2. If theta exhausted (premium decay > 70%): propose new strike\n"
        "3. Flow ShiftProposal → Researcher for backtest\n"
        "4. If backtest validates → Risk Agent directs Executioner\n"
    ),
    expected_output="Theta condition + shift proposal if warranted",
    agent=shifter_agent,
)
```

---

## Crew Assembly — Line 1315

```python
maintenance_crew = Crew(
    agents=[risk_agent, shifter_agent, ...],
    tasks=[monitor_task, shifter_task],
    process=Process.sequential,
)
```

---

## Runtime Invocation — Lines 1456–1462

```python
# Called during maintenance cycle every 5 min
shifter_result = shifter_evaluate.func()
results = {
    "shifter_eval": json.loads(shifter_result),
    ...
}
```

Also at line 1632–1633 during one-shot maintenance mode.

---

## Full Agent Pipeline (Shifter Context)

```
┌─────────────────────────────────────────────────────────────────┐
│                     MAINTENANCE LOOP (every 5 min)              │
│                                                                 │
│  ┌──────────┐    ┌───────────┐    ┌──────────┐   ┌──────────┐ │
│  │  SHIFTER │───→│ RESEARCHER│───→│   RISK   │──→│EXECUTIONR│ │
│  │ evaluate │    │ backtest  │    │  direct  │   │ EXIT old │ │
│  │  theta   │    │  shift    │    │  shift   │   │ OPEN new │ │
│  │ erosion  │    │           │    │          │   │          │ │
│  └──────────┘    └───────────┘    └──────────┘   └──────────┘ │
│       │               │                │               │       │
│       │  70%+ decay   │   PnL > 0      │   APPROVE     │       │
│       │  → PROPOSE    │   → APPROVE    │   → COMMAND   │       │
│       │               │                │               │       │
│       │  < 70% decay  │   PnL ≤ 0      │   REJECT      │       │
│       │  → HOLD       │   → REJECT     │   → SKIP      │       │
└─────────────────────────────────────────────────────────────────┘
```

---

## Position Manager ROLL (Complementary)

In `brahmand/position_manager.py:408-450`, the ROLL and TIGHTEN actions **physically execute** the leg shift:

| Lines | Action | What it does |
|-------|--------|-------------|
| 411-430 | ROLL | Replace sold leg: book P&L, set new leg with fill_price from action, recalculates SL/TP |
| 411-430 | TIGHTEN | Same as ROLL but triggered by hedge gap condition (P2) |

```python
# position_manager.py:411-430
if action["type"] in (ROLL, TIGHTEN):
    leg = action["leg"]
    # Book P&L on closing leg
    pnl = (leg["fill"] - leg["ltp"]) if leg["action"] == "SELL" else (leg["ltp"] - leg["fill"])
    trade["cumulative_pnl"] += pnl * LOT_SIZE

    # Replace leg with new one
    for i, l in enumerate(trade["legs"]):
        if l["tsym"] == leg["tsym"]:
            trade["legs"][i] = {
                "action": leg["action"],
                "strike": action["new_strike"],
                "type": leg["type"],
                "fill_price": action["new_fill"],
                "tsym": action["new_tsym"],
            }
    # Set new SL/TP for replaced sold leg
    if leg["action"] == "SELL":
        trade["sl"][side_key] = round(new_fill * (1 + SL_PCT), 2)
        trade["tp"][side_key] = round(new_fill * (1 - TP_PCT), 2)
```

### ROLL Detection (P1) — position_manager.py:170-195
```python
# P1: Theta decay ≥ DECAY_PCT on sold leg → ROLL to ATM
decay_pct = (fill_price - ltp) / fill_price * 100  # for SELL leg
if decay_pct >= DECAY_PCT:  # DECAY_PCT = 37.5
    action = {
        "type": ROLL,
        "priority": 1,
        "reason": f"Theta decay {decay_pct:.0f}% on {tsym} → roll to ATM",
        "new_strike": atm_strike,
        ...
    }
```

### TIGHTEN Detection (P2) — position_manager.py:200-218
```python
# P2: Hedge gap ≤ 150pt → tighten wing
hedge_gap = abs(buy_strike - sell_strike)
if hedge_gap <= HEDGE_GAP:  # HEDGE_GAP = 150
    action = {
        "type": TIGHTEN,
        "priority": 2,
        "reason": f"Hedge gap {hedge_gap}pt ≤ {HEDGE_GAP} → tighten",
    }
```

---

## Differences: Shifter vs Morph

| Aspect | Leg Shifter (trading_desk.py) | Position Manager (position_manager.py) |
|--------|------------------------------|----------------------------------------|
| **Owner** | CrewAI agent (LLM-loop) | Deterministic (0 LLM) |
| **Trigger** | Theta > 70% eroded | Theta ≥ 37.5% (P1), Gap ≤ 150pt (P2), Signal change (P3) |
| **Action** | Shift strike ±50, backtest first | Roll to ATM directly |
| **Max shifts** | 2 per trade | 3 morphs + unlimited rolls |
| **LTP source** | Mock (`avg_entry * 0.40`) | DuckDB (real LTPs) |
| **Status** | Part of CrewAI maintenance loop | Standalone checks every 5-min cycle |

---

## Known Issues

| # | Issue | Location | Impact |
|---|-------|----------|--------|
| 1 | **Mock LTP** — `current_ltp = avg_entry * 0.40` | line 917 | Premium erosion always 60% — needs live LTP |
| 2 | **Hardcoded theta** — `theta_current=-2.5`, `theta_target=-8.0` | lines 934-935 | Not based on actual Greeks |
| 3 | **Hardcoded new strike** — always `atm + 50` | line 933 | Doesn't adapt to market conditions |
| 4 | **Hardcoded backtest params** — `target_profit=800`, `max_loss=3000` | lines 991-992 | Not from config |
| 5 | **Return json.dumps** but CrewAI expects string tool output | lines 895-963 | May cause parsing issues |
