# Antariksh Trading Desk — Complete System Integration Guide

## Overview

The Antariksh trading desk is a **7-agent hierarchical system** with **3 registries** and **centralized configuration**. All agents, tools, and policies are discoverable, configurable, and extensible.

```
Configuration (risk_config.py)
  ↓
Agent Registry (agent_registry.py)
  ↓
Tools Registry (tools_registry.py)
  ↓
Trading Desk Crew (build_trading_desk_crew)
  ↓
Order Agent (order_agent.py) ← Central Hub
```

---

## System Architecture

### Component Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│                   ANTARIKSH TRADING DESK SYSTEM                  │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  CONFIGURATION LAYER:                                            │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ risk_config.py                                             │ │
│  │  • CapitalConfig (total_capital, free_cash_floor, ...)    │ │
│  │  • RiskLimitsConfig (max_loss_per_trade, per_day, ...)    │ │
│  │  • ExecutionConfig (lot_size, wing_widths, ...)           │ │
│  │  • PositionManagementConfig (TSL, SL/TP, thresholds, ...) │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  REGISTRY LAYER:                                                 │
│  ┌─────────────────────┐  ┌─────────────────────┐              │
│  │ agent_registry.py   │  │ tools_registry.py   │              │
│  │                     │  │                     │              │
│  │ 7 agents:           │  │ 10 tools:           │              │
│  │ • scout             │  │ • scout_*           │              │
│  │ • researcher        │  │ • research_*        │              │
│  │ • pm                │  │ • pm_*              │              │
│  │ • executioner       │  │ • execute_*         │              │
│  │ • risk              │  │ • shifter_*         │              │
│  │ • shifter           │  │ • risk_*            │              │
│  │ • order_agent       │  │ • order_agent_*     │              │
│  └─────────────────────┘  └─────────────────────┘              │
│                                                                  │
│  CREW LAYER:                                                     │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ trading_desk.py                                            │ │
│  │  • 7 agents (with tools)                                   │ │
│  │  • 7 tasks (sequenced)                                     │ │
│  │  • Hierarchical crew (manager_llm coordinates)             │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  ORDER AGENT (Central Hub):                                      │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ order_agent.py                                             │ │
│  │  • place_order() → /tmp/order_ledger.json (PAPER)         │ │
│  │  • modify_order() → ledger or Shoonya API (LIVE)          │ │
│  │  • cancel_order() → ledger or Shoonya API (LIVE)          │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

---

## Configuration System (risk_config.py)

### How to Update Values

Asset manager updates configuration values here (NOT in agent code):

```python
from risk_config import CAPITAL, RISK, EXECUTION, POSITION
from risk_config import update_capital_limits, update_risk_limits

# Update total capital
update_capital_limits(
    total_capital=750_000,      # Increase to ₹750k
    free_cash_floor=75_000,     # Increase floor to ₹75k
    max_margin_utilization_pct=0.80  # Reduce to 80%
)

# Update risk limits
update_risk_limits(
    max_loss_per_trade=50_000,   # Increase trade loss limit
    max_loss_per_day=150_000,    # Increase daily loss limit
    max_concurrent_trades=6      # Allow more concurrent trades
)

# Query current values
print(f"Available margin: ₹{CAPITAL.get_available_margin(margin_locked=100000)}")
print(f"Max loss per trade: ₹{RISK.max_loss_per_trade}")
print(f"Max loss per day: ₹{RISK.max_loss_per_day}")
```

### Configuration Hierarchy

```
CAPITAL
  ├── total_capital (default: ₹611,000)
  ├── free_cash_floor (default: ₹50,000)
  ├── max_margin_utilization_pct (default: 0.85)
  └── vix_spike_margin_multiplier (default: 1.25)

RISK
  ├── max_loss_per_trade (default: ₹30,000)
  ├── max_loss_per_day (default: ₹100,000)
  ├── max_concurrent_trades (default: 4)
  ├── max_shifts_per_trade (default: 2)
  ├── theta_exhaustion_threshold_pct (default: 0.70)
  ├── hedge_decay_threshold_pct (default: 0.50)
  ├── sell_decay_threshold_pct (default: 0.60)
  └── max_position_age_minutes (default: 45)

EXECUTION
  ├── nifty_lot_size (default: 65)
  ├── wing_widths (default: [50, 100, 150, 200, 250])
  ├── default_wing_width (default: 100)
  ├── margin_matrix_path (default: /home/trading_ceo/brahmand/data/margin_matrix.json)
  ├── order_ledger_path (default: /tmp/order_ledger.json)
  └── live_mode_enabled (default: False)

POSITION
  ├── tsl_activation_threshold_pct (default: 0.25)
  ├── tsl_default_lock_ratio (default: 0.50)
  ├── sl_placement_pct (default: 0.10)
  ├── tp_placement_pct (default: 0.50)
  ├── morph_bullish_threshold (default: 3.0)
  ├── morph_bearish_threshold (default: -3.0)
  ├── wing_butterfly (default: 200)
  └── wing_spread (default: 200)
```

---

## Agent Registry (agent_registry.py)

### How to Discover Agents

```python
from agent_registry import list_agents, get_agent, get_registry

# List all agents
for agent_name in list_agents():
    print(f"Agent: {agent_name}")

# Get specific agent
order_agent = get_agent("order_agent")
print(f"Role: {order_agent.role}")
print(f"Goal: {order_agent.goal}")
print(f"Tools: {[str(t) for t in order_agent.tools]}")

# Get metadata
registry = get_registry()
metadata = registry.get_metadata("order_agent")
print(f"Metadata: {metadata}")
```

### Registered Agents

| Name | Role | Phase | Tools |
|------|------|-------|-------|
| scout | Technical Scout | Preparation | scout_market_regime |
| researcher | Quantitative Analyst | Preparation + Maintenance | research_setup, researcher_backtest_shift |
| pm | Portfolio Manager | Validation | pm_approve |
| executioner | Execution Specialist | Action | execute_orders, order_agent_* (3 tools) |
| risk | Risk Sentry | Maintenance | shifter_evaluate, risk_direct_shift, order_agent_* (3 tools) |
| shifter | Leg Shifter | Maintenance | shifter_evaluate |
| order_agent | Order Router | All phases | order_agent_place_order, order_agent_modify_order, order_agent_cancel_order |

---

## Tools Registry (tools_registry.py)

### How to Discover Tools

```python
from tools_registry import list_tools, get_tool, get_registry

# List all tools
for tool_name in list_tools():
    print(f"Tool: {tool_name}")

# Get specific tool
place_order_tool = get_tool("order_agent_place_order")
print(f"Tool: {place_order_tool.name}")

# Get tools by phase
registry = get_registry()
all_tools = registry.get_all()
print(f"Total tools: {len(all_tools)}")

# Tools by agent
order_tools = [t for t in all_tools.keys() if "order_agent" in t]
print(f"Order Agent tools: {order_tools}")
```

### Registered Tools

| Name | Agent | Phase | Purpose |
|------|-------|-------|---------|
| scout_market_regime | scout | preparation | Detect market regime |
| research_setup | researcher | preparation | Design Iron Butterfly |
| researcher_backtest_shift | researcher | maintenance | Validate leg shifts |
| pm_approve | pm | validation | Authorize capital |
| execute_orders | executioner | action | Place 4-leg basket |
| shifter_evaluate | risk/shifter | maintenance | Monitor theta decay |
| risk_direct_shift | risk | maintenance | Command shifts |
| order_agent_place_order | order_agent | all | Place order |
| order_agent_modify_order | order_agent | all | Modify order |
| order_agent_cancel_order | order_agent | all | Cancel order |

---

## Data Flows

### Entry Flow (PREPARATION → VALIDATION → ACTION)

```
SCOUT detects regime
  ↓
RESEARCHER designs setup
  ↓
PM authorizes lots
  ↓
EXECUTIONER places 4-leg basket
  ↓
RISK monitors live positions
```

### Maintenance Flow (MAINTENANCE PHASE)

```
SHIFTER detects theta decay
  ↓
RESEARCHER backtests shift
  ↓
RISK directs shift via ORDER_AGENT
  ↓
EXECUTIONER executes via ORDER_AGENT
  ↓
RISK monitors new position
```

### Order Routing (All Phases)

```
Component (Executioner/Shifter/Risk)
  ↓
ORDER_AGENT
  ├─ PAPER mode: Update /tmp/order_ledger.json
  └─ LIVE mode: Forward to Shoonya API
  ↓
Confirmation (order_id, status, execution_time)
  ↓
Component stores order_id in trade structure
```

---

## Testing & Verification

### 1. Test Configuration

```bash
python3 -c "from risk_config import get_config_summary; print(get_config_summary())"
```

Output:
```
╔════════════════════════════════════════════════════════════════╗
║           RISK MANAGEMENT CONFIGURATION SUMMARY               ║
╠════════════════════════════════════════════════════════════════╣
║ CAPITAL:
║   Total Capital:                ₹611,000
║   Free Cash Floor:              ₹50,000
║   Max Margin Utilization:       85%
│ ...
```

### 2. Test Agent Registry

```bash
python3 /home/trading_ceo/antariksh/registry_demo.py
```

Output:
```
1. List all registered agents:
   • scout                : Technical Scout (Market Eyes)
   • researcher           : Strategy Researcher
   • pm                   : Portfolio Manager
   • executioner          : Execution Specialist
   • risk                 : Risk & Compliance Sentry
   • shifter              : Leg Shifter (Theta Optimizer)
   • order_agent          : Order Agent (Order Router)
```

### 3. Test Order Agent

```bash
python3 /home/trading_ceo/brahmand/order_agent.py
```

Output:
```
Order 1: {"order_id": "ORD-20260519-0001", "status": "FILLED", ...}
Order 2: {"order_id": "ORD-20260519-0002", "status": "FILLED", ...}
```

### 4. Test Full Desk (Preparation Phase)

```bash
python3 /home/trading_ceo/antariksh/trading_desk.py --preparation-only
```

### 5. Test Full Session (All Phases)

```bash
python3 /home/trading_ceo/antariksh/trading_desk.py --full-session
```

---

## Transition to LIVE Mode

### When Ready to Trade Live

1. **Update risk_config.py**:
   ```python
   EXECUTION.live_mode_enabled = True
   ```

2. **Implement Shoonya API integration** in order_agent.py:
   ```python
   if LIVE_MODE:
       # Call api.place_order(symbol, action_type, quantity, price)
       # Store broker_order_id in ledger
       # Setup webhook for order status updates
   ```

3. **Test with paper trading** first:
   ```python
   EXECUTION.live_mode_enabled = False  # Keep paper mode on
   ```

4. **Gradually increase capital**:
   ```python
   update_capital_limits(total_capital=100_000)  # Start with ₹100k
   ```

---

## Key Design Principles

1. **No Hardcoded Values**: All limits in `risk_config.py`
2. **Discoverable Agents**: Agent registry enables dynamic lookup
3. **Discoverable Tools**: Tools registry enables dynamic discovery
4. **Centralized Order Hub**: Order Agent is single source of truth
5. **PAPER → LIVE Transition**: Transparent via `LIVE_MODE` flag
6. **Audit Trail**: All orders logged in `/tmp/order_ledger.json`
7. **Configurable Thresholds**: All thresholds in risk_config.py

---

## File Organization

```
/home/trading_ceo/antariksh/
├── risk_config.py              # Configuration (update here!)
├── agent_registry.py           # Agent discovery
├── tools_registry.py           # Tools discovery
├── trading_desk.py             # Crew + agent definitions
├── registry_demo.py            # Demo / test registries
├── AGENTS_SPECIFICATION.md     # Agent knowledge docs
├── ORDER_AGENT_INTEGRATION.md  # Order Agent docs
└── SYSTEM_INTEGRATION_GUIDE.md # This file

/home/trading_ceo/brahmand/
├── order_agent.py              # Order routing + ledger
├── leg_shifter.py              # Theta monitoring + shifts
├── position_manager.py         # MORPH detection
├── kickoff.py                  # Scheduler
└── data/
    └── order_ledger.json       # Order history (symlink: /tmp/order_ledger.json)
```

---

## Summary

The Antariksh trading desk is now:

✅ **Fully documented** — All agents have complete knowledge, backstory, tools  
✅ **Configurable** — All values in `risk_config.py` (no hardcoding)  
✅ **Discoverable** — Agent and tools registries for dynamic lookup  
✅ **Audit-ready** — Order ledger tracks all operations  
✅ **PAPER→LIVE ready** — Transparent transition via `LIVE_MODE` flag  
✅ **Team-friendly** — Clear agent roles and responsibilities  

**Next steps:**
1. Test with `python3 registry_demo.py`
2. Verify configuration: `python3 -c "from risk_config import get_config_summary; print(get_config_summary())"`
3. Run end-to-end: `python3 trading_desk.py --full-session`
4. Update CONTEXT.md with current state

