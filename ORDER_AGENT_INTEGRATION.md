# Order Agent — Centralized Order Routing System

## Overview

The **Order Agent** is a centralized order routing system that handles all order management for the Antariksh trading desk. It provides:

1. **Single source of truth** for all orders and fills
2. **Seamless transition** from PAPER trading to LIVE broker integration
3. **Audit trail** of all order operations
4. **Dynamic registry** for agent and tool discovery

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    ORDER AGENT (Central Router)                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Tools:                                                          │
│   • order_agent_place_order()    → place order via ledger/API  │
│   • order_agent_modify_order()   → update SL/TP triggers       │
│   • order_agent_cancel_order()   → cancel existing order        │
│                                                                  │
│  Ledger: /tmp/order_ledger.json                                │
│   {                                                             │
│     "orders": {                                                 │
│       "ORD-20260519-0001": {                                    │
│         "symbol": "NIFTY23750PE",                               │
│         "action_type": "SELL",                                  │
│         "quantity": 65,                                         │
│         "price": 150.0,                                         │
│         "status": "FILLED",                                     │
│         "order_type": "ENTRY",                                  │
│         "component": "executioner",                             │
│         "trade_id": "trade_001",                                │
│         "timestamp": "2026-05-19T10:30:00",                     │
│         "execution_time": "2026-05-19T10:30:00"                │
│       }                                                         │
│     }                                                           │
│   }                                                             │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
            ▲       ▲         ▲          ▲
            │       │         │          │
      ┌─────┘       │         │          └──────┐
      │         ┌───┘         └────┐            │
      │         │                  │            │
  executioner  risk_agent    leg_shifter   position_manager
  (ENTRY)      (SL/TP mods,  (shift CLOSE/ (MORPH CLOSE/
               CANCEL/EXIT)   OPEN)         OPEN)
```

## Order Routing

### Order Flow

1. **Component requests order** → calls `order_agent_place_order()`
2. **Order Agent routes**:
   - **PAPER mode**: Updates `/tmp/order_ledger.json`, returns immediate confirmation
   - **LIVE mode**: Forwards to Shoonya API, tracks broker order_id
3. **Component receives** order_id, status, execution_time
4. **Order tracked** in ledger for audit and settlement

### Order Types

| Type | Component | Action | Example |
|------|-----------|--------|---------|
| ENTRY | executioner | BUY/SELL initial legs | Iron Butterfly legs |
| SHIFT_OPEN | leg_shifter | BUY/SELL new shifted leg | New SELL at 24600 PE |
| SHIFT_CLOSE | leg_shifter | Close old shifted leg | Close 24500 PE SELL |
| MODIFY_SL | risk_agent | Update SL trigger | SL 160 → SL 155 |
| MODIFY_TP | risk_agent | Update TP trigger | TP 100 → TP 95 |
| EXIT | risk_agent | Close all positions | SL hit or manual |

## Component Integration

### 1. Leg Shifter Integration

**File**: `/home/trading_ceo/brahmand/leg_shifter.py`

```python
# HEDGE_SHIFT: Buy new hedge, then close old hedge
open_order = place_order(
    symbol=new_hedge_tsym,
    action_type="BUY",
    quantity=65,
    price=new_hedge_ltp,
    order_type="SHIFT_OPEN",
    component="leg_shifter",
    trade_id=trade.get("trade_id"),
    reason="HEDGE_SHIFT: 24000→24050"
)

close_order = place_order(
    symbol=old_hedge_tsym,
    action_type="SELL",
    quantity=65,
    price=old_hedge_ltp,
    order_type="SHIFT_CLOSE",
    component="leg_shifter",
    trade_id=trade.get("trade_id"),
    reason="HEDGE_SHIFT_CLOSE: 24000"
)
```

### 2. Position Manager Integration (via kickoff.py)

**File**: `/home/trading_ceo/brahmand/kickoff.py`

When MORPH is executed, orders are placed via Order Agent:

```python
# MORPH execution triggers order placement
execute_action(action, trade)  # Updates trade structure
# Each new leg entry will call order_agent via position_manager
```

### 3. Risk Agent Integration

**File**: `/home/trading_ceo/antariksh/trading_desk.py`

```python
# Modify SL/TP
modify_result = order_agent_modify_order(
    order_id=sl_order_id,
    new_trigger=new_sl_price,
    reason="TSL update"
)

# Cancel orders
cancel_result = order_agent_cancel_order(
    order_id=tp_order_id,
    reason="TP_HIT - liquidating"
)
```

## Registry System

### Agent Registry

**File**: `/home/trading_ceo/antariksh/agent_registry.py`

```python
from agent_registry import list_agents, get_agent

# List all agents
for agent_name in list_agents():
    agent = get_agent(agent_name)
    print(f"{agent_name}: {agent.role}")

# Output:
# scout: Technical Scout (Market Eyes)
# researcher: Strategy Researcher
# pm: Portfolio Manager
# executioner: Execution Specialist
# risk: Risk & Compliance Sentry
# shifter: Leg Shifter (Theta Optimizer)
# order_agent: Order Agent (Order Router)
```

### Tools Registry

**File**: `/home/trading_ceo/antariksh/tools_registry.py`

```python
from tools_registry import list_tools, get_tool

# List all Order Agent tools
for tool_name in list_tools():
    if "order_agent" in tool_name:
        tool = get_tool(tool_name)
        print(f"{tool_name}: Place/Modify/Cancel orders")

# Output:
# order_agent_place_order: Place order (PAPER ledger or LIVE broker)
# order_agent_modify_order: Modify existing order (SL/TP update)
# order_agent_cancel_order: Cancel existing order
```

## Ledger Schema

```json
{
  "orders": {
    "ORD-20260519-0001": {
      "order_id": "ORD-20260519-0001",
      "component": "leg_shifter",
      "symbol": "NIFTY23750PE",
      "action_type": "SELL",
      "quantity": 65,
      "price": 150.0,
      "order_type": "SHIFT_OPEN",
      "trade_id": "trade_001",
      "reason": "HEDGE_SHIFT: 24000→24050",
      "timestamp": "2026-05-19T10:30:00",
      "status": "FILLED",
      "mode": "PAPER",
      "execution_time": "2026-05-19T10:30:00",
      "execution_price": 150.0
    }
  },
  "order_counter": 1
}
```

## PAPER vs LIVE Mode

### PAPER Mode (Current)

- No broker API calls
- Orders immediately FILLED
- Ledger updated synchronously
- Perfect for backtesting and dry-runs

### LIVE Mode (Future)

```python
# Set in order_agent.py
LIVE_MODE = True

# Then:
# 1. place_order() forwards to Shoonya API
# 2. Order status starts as PENDING
# 3. Webhook/callback updates status to FILLED when broker confirms
# 4. Broker order_id tracked in ledger
```

## Testing

### Run Registry Demo

```bash
cd /home/trading_ceo/antariksh
python3 registry_demo.py
```

This shows:
- All 7 agents registered
- All 10 tools registered (3 from Order Agent)
- Tool → Agent mapping
- Tool → Phase mapping

### Test Order Agent Directly

```bash
python3 /home/trading_ceo/brahmand/order_agent.py
```

This will:
1. Create test orders
2. Modify an order
3. Cancel an order
4. Retrieve orders by trade_id
5. Show ledger contents

## Future Enhancements

1. **Broker Integration**: Set `LIVE_MODE = True` and implement Shoonya API calls
2. **Order Tracking**: Add webhook handlers for broker order status updates
3. **Settlement**: Track which orders have been settled
4. **Audit Reports**: Generate daily/weekly audit trails
5. **Position Reconciliation**: Compare ledger vs broker positions
6. **Order Cancellation Workflows**: Handle partial fills, rejections

## Key Design Decisions

1. **Centralized Routing**: All orders flow through Order Agent
   - Single source of truth
   - Easy to audit
   - Easy to extend to LIVE

2. **Ledger-Based**: Paper trading uses in-memory ledger
   - Fast operations
   - No database dependency
   - Can be saved/loaded as JSON

3. **Component Abstraction**: Components don't know if PAPER or LIVE
   - place_order() returns same interface
   - LIVE mode is transparent switch

4. **Order Tracking**: order_id links orders to components and trades
   - Can trace any order back to source
   - Can group orders by trade
   - Can calculate fills by component

## Integration Checklist

- [x] Order Agent created (order_agent.py)
- [x] Order Agent tools added to trading_desk.py
- [x] Order Agent registered in CrewAI agent registry
- [x] Leg shifter integrated with order_agent
- [x] Agent registry system created
- [x] Tools registry system created
- [x] Registry demo implemented
- [ ] Position manager MORPH execution integration
- [ ] Risk Agent SL/TP modification integration
- [ ] End-to-end test with live shifter execution
- [ ] Transition to LIVE mode when broker API ready
