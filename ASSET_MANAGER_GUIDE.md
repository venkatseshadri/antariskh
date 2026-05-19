# Antariksh Trading Desk — Asset Manager Quick Reference

This guide explains how to manage the trading system as an asset manager.

## Daily Startup (09:15 Market Open)

### Step 1: Fetch Live Limits from Broker

```python
# Script: run at 09:15 (market open) with credentials
from varaha_auth import Varaha  # Uses cred.yml for Shoonya OAuth
from broker_limits import fetch_live_limits_from_broker, sync_with_config

# Login to Shoonya via Varaha
print("Connecting to Shoonya...")
varaha = Varaha()
if not varaha.login():
    print("ERROR: Shoonya login failed")
    exit(1)

# Fetch LIVE margin from broker
print("Fetching live limits from broker...")
limits = fetch_live_limits_from_broker(varaha.api)

if limits:
    # Sync with system config (no agent sees hardcoded values)
    sync_with_config()
    print("✓ System updated with live broker limits")
else:
    print("ERROR: Could not fetch limits from broker")
```

**Credentials**: Uses `cred.yml` (OAuth token, UID, Account_ID from Shoonya)

### Step 2: Verify Configuration

```bash
# Check what the system sees
python3 -c "from risk_config import get_config_summary; print(get_config_summary())"
```

Output:
```
╔════════════════════════════════════════════════════════════════╗
║           RISK MANAGEMENT CONFIGURATION SUMMARY               ║
╠════════════════════════════════════════════════════════════════╣
║ CAPITAL:
║   Total Capital:                ₹<LIVE FROM BROKER>
║   Free Cash Floor:              ₹50,000
║   Max Margin Utilization:       85%
│ ...
```

---

## Updating Risk Policies (Anytime)

### Update Capital Limits

```python
from risk_config import update_capital_limits

# Increase total capital
update_capital_limits(
    total_capital=750_000,       # Up to ₹750k (from ₹611k)
    free_cash_floor=75_000,      # Increase floor to ₹75k
    max_margin_utilization_pct=0.80  # Reduce to 80%
)

# Agents now see new limits automatically
```

### Update Risk Limits

```python
from risk_config import update_risk_limits

# Tighten risk after bad week
update_risk_limits(
    max_loss_per_trade=20_000,   # Reduce trade loss to ₹20k
    max_loss_per_day=50_000,     # Reduce daily loss to ₹50k
    max_concurrent_trades=2      # Reduce concurrent from 4 to 2
)

# All agents respect new limits on next cycle
```

### Update Position Parameters

```python
from risk_config import POSITION

# Adjust TSL activation
POSITION.tsl_activation_threshold_pct = 0.30  # Activate at 30% (was 25%)
POSITION.tsl_default_lock_ratio = 0.60       # Lock 60% of moves (was 50%)

# Adjust SL/TP levels
POSITION.sl_placement_pct = 0.12              # SL at 12% above (was 10%)
POSITION.tp_placement_pct = 0.60              # TP at 60% below (was 50%)
```

---

## Monitoring During Market Hours

### View Current Status

```bash
# Show broker limits (live or cached)
python3 -c "from broker_limits import print_limits_summary; print_limits_summary()"
```

### Check Order Ledger

```bash
# View all orders placed today
import json
ledger = json.load(open("/tmp/order_ledger.json"))

# Summary by status
filled = len([o for o in ledger["orders"].values() if o["status"] == "FILLED"])
pending = len([o for o in ledger["orders"].values() if o["status"] == "PENDING"])
cancelled = len([o for o in ledger["orders"].values() if o["status"] == "CANCELLED"])

print(f"Orders: {filled} filled, {pending} pending, {cancelled} cancelled")

# View specific trade's orders
trade_id = "trade_001"
trade_orders = [o for o in ledger["orders"].values() if o.get("trade_id") == trade_id]
for order in trade_orders:
    print(f"{order['order_id']}: {order['action_type']} {order['symbol']} @ {order['price']}")
```

### Check Agent Status

```python
from agent_registry import list_agents, get_agent

# List active agents
for agent_name in list_agents():
    agent = get_agent(agent_name)
    print(f"Agent: {agent_name} | Role: {agent.role}")
```

---

## Emergency Actions

### Halt All Trades

```python
from risk_config import update_risk_limits

# Immediately stop new trades
update_risk_limits(
    max_concurrent_trades=0,  # No new trades
    max_loss_per_day=0        # Emergency stop
)

# Current open positions continue (with SL/TP)
# No new positions will be taken
```

### Reduce Risk Immediately

```python
from risk_config import POSITION

# Tighten all MORPH thresholds (harder to detect regime changes)
POSITION.morph_bullish_threshold = 5.0   # Was 3.0 (now needs stronger signal)
POSITION.morph_bearish_threshold = -5.0  # Was -3.0

# Reduce shift frequency
from risk_config import RISK
RISK.theta_exhaustion_threshold_pct = 0.80  # Shift only at 80% decay (was 70%)
```

### Close All Positions

```bash
# Manual exit (if system fails)
# Risk Agent will execute via Order Agent
# Orders logged to /tmp/order_ledger.json
```

---

## Configuration File Location

### Primary Configuration
- **File**: `/home/trading_ceo/antariksh/risk_config.py`
- **Usage**: All agents query this for limits
- **Update**: Use `update_capital_limits()` and `update_risk_limits()` functions
- **No Restart Needed**: Changes take effect immediately

### Live Broker Limits
- **File**: `/tmp/broker_limits.json`
- **Updated**: Daily at market open via `fetch_live_limits_from_broker()`
- **Cached**: Updated automatically, agents use live data
- **Format**: JSON with total_margin_available, free_margin, cash_available, margin_multiplier

### Order Ledger
- **File**: `/tmp/order_ledger.json`
- **Updated**: Every order placement, modification, cancellation
- **Audit Trail**: Complete history of all trades
- **Format**: order_id → order details (symbol, price, status, timestamp, etc.)

---

## Glossary

**Total Capital**: Sum of all cash + margin available from broker

**Free Cash Floor**: Minimum free cash that must always remain (safety buffer)

**Margin Utilization %**: (Used Margin / Total Margin) × 100

**Max Loss per Trade**: Single position loss limit (e.g., ₹30k)

**Max Loss per Day**: Cumulative daily loss limit (e.g., ₹100k)

**Max Concurrent Trades**: How many positions can be open simultaneously

**PAPER Mode**: Orders filled immediately in ledger (no broker calls)

**LIVE Mode**: Orders forwarded to broker API (requires connectivity)

**Margin Multiplier**: Broker's dynamic adjustment (VIX effect)
- 1.0x = Normal volatility
- 1.25x = Moderate volatility (requires 25% more margin)
- 1.5x+ = High volatility (requires 50%+ more margin)

**TSL**: Trailing Stop Loss (ratchets down as position profits)

**Theta Decay**: Rate of option premium erosion (daily degradation)

**Wing Width**: Distance between SELL and BUY strikes in spread

**Regime**: Market condition (BULLISH, BEARISH, SIDEWAYS)

---

## Troubleshooting

### "No limits available" Error

**Problem**: System says no broker limits cached

**Solution**:
```python
from broker_limits import fetch_live_limits_from_broker, get_api, get_account_id
api = get_api()
fetch_live_limits_from_broker(api, get_account_id())
```

### Orders Not Executing

**Problem**: Orders placed but not showing in ledger

**Check**:
```bash
# Verify order ledger exists
ls -la /tmp/order_ledger.json

# Check Order Agent PAPER mode
python3 -c "from order_agent import LIVE_MODE; print(f'LIVE_MODE: {LIVE_MODE}')"
```

### Agent Not Responding

**Problem**: Agent missing from registry

**Check**:
```python
from agent_registry import list_agents
print(list_agents())  # Should show all 7 agents
```

---

## Key Safeguards

✅ **No Hardcoded Values**: All limits in `risk_config.py`  
✅ **Live Broker Data**: Fetched daily, synced automatically  
✅ **Complete Audit Trail**: Every order in `/tmp/order_ledger.json`  
✅ **Discoverable Agents**: Can query any agent for status  
✅ **Emergency Stop**: Set `max_concurrent_trades=0` to halt  
✅ **Paper Trading First**: Test thoroughly before LIVE mode  
✅ **Configuration Hot-Reload**: Changes take effect immediately  

---

## Before Going LIVE

Checklist before switching to live broker trading:

- [ ] All agents tested and verified
- [ ] Order Agent integration tested with paper trades
- [ ] Broker API credentials validated
- [ ] Order ledger audited for 1 week
- [ ] Risk limits reviewed by compliance
- [ ] Margin calculations verified against broker
- [ ] SL/TP logic tested with real data
- [ ] Shift execution tested end-to-end
- [ ] Rollback plan documented
- [ ] 24/7 monitoring set up

Once approved:

```python
# In risk_config.py
EXECUTION.live_mode_enabled = True  # Single flag to go live
```

---

## Support

For questions or issues:
- Check `/home/trading_ceo/antariksh/AGENTS_SPECIFICATION.md` for agent details
- Check `/home/trading_ceo/antariksh/SYSTEM_INTEGRATION_GUIDE.md` for architecture
- Check `/home/trading_ceo/antariksh/ORDER_AGENT_INTEGRATION.md` for order routing

**No code changes needed** to update limits — all configuration changes are in `risk_config.py`.

