# Broker API Safety Guidelines

## CRITICAL: Fetch Limits ONCE Per Day Only

**Problem**: Broker API has rate limits. Multiple calls = lockout risk.

**Solution**: Fetch ONCE at market open, cache for entire day.

## Daily Workflow (STRICT)

### 09:15 Market Open — SINGLE Broker Call

```python
# ONE TIME ONLY at market open (asset manager's job)
from varaha_auth import Varaha
from broker_limits import fetch_live_limits_from_broker, sync_with_config

varaha = Varaha()
varaha.login()
fetch_live_limits_from_broker(varaha.api)  # ← SINGLE API CALL
sync_with_config()

# NOW: All agents use CACHED limits for the entire day
```

### 09:30-15:30 Trading Hours — NO Broker Calls

All agents query **cached** limits only:

```python
# Scout uses config (no broker call)
from risk_config import CAPITAL, RISK, POSITION

# PM uses config (no broker call)
if free_margin < CAPITAL.free_cash_floor:
    reject_trade()

# Risk Agent uses config (no broker call)
if daily_loss >= RISK.max_loss_per_day:
    exit_positions()

# Order Agent uses config (no broker call)
# Shifter uses config (no broker call)
# Researcher uses config (no broker call)
# Executioner uses config (no broker call)
```

### 15:30 Market Close — Review Cached Data

```python
# Optional: Verify what broker data we used today
from broker_limits import get_current_limits
limits, is_fresh = get_current_limits()
print(f"Limits are from: {limits.timestamp}")
print(f"Fresh? {is_fresh}")  # Should be False after 1 hour
```

## Architecture: No Runtime Broker Calls

```
STARTUP (09:15)
  ↓
varaha.login()        [1 broker call for OAuth]
fetch_live_limits()   [1 broker call for margin] ← THE ONLY API CALL
sync_with_config()    [local operation, no broker]
  ↓
TRADING (09:30-15:30)
  ↓
All agents query risk_config.py (CACHED, no broker calls)
All orders via Order Agent (local ledger, no broker in PAPER mode)
  ↓
CLOSE (15:30)
  ↓
Review order_ledger.json (local file, no broker)
```

## What Agents Access (No Broker Calls)

| Agent | Data Source | Broker Call? |
|-------|-------------|--------------|
| Scout | risk_config.py | NO |
| Researcher | risk_config.py | NO |
| PM | risk_config.py | NO |
| Executioner | Order Agent | NO (PAPER mode) |
| Risk | risk_config.py | NO |
| Shifter | risk_config.py | NO |
| Order Agent | /tmp/order_ledger.json | NO (PAPER mode) |

## When Going LIVE

Only change needed for LIVE mode broker integration:

```python
# In order_agent.py, place_order() function
if LIVE_MODE:
    # Forward to broker (ONE call per order)
    # NOT multiple status checks or modifications
    # Broker calls webhook for updates
    broker_order_id = api.place_order(...)
```

**Still ONE limit fetch per day** — we don't refetch margins unless market is closed and reopened.

## Fallback: Stale Cache Handling

If limits are > 24 hours old:

```python
from broker_limits import get_current_limits

limits, is_fresh = get_current_limits()
if not is_fresh:
    # Limits are stale (> 1 hour old from fetch time)
    # PM Agent should:
    # 1. Log warning: "Using stale margin data"
    # 2. Apply safety discount (use 80% of cached margin, not 100%)
    # 3. Reject trades if conservative estimate insufficient
    available_margin = limits.get_net_available_margin() * 0.80  # 20% buffer
```

## Testing: Verify No Extra Broker Calls

```python
# After a trading day, audit the logs:
# Should see:
# - varaha.login() — 1 OAuth call
# - fetch_live_limits() — 1 margin call
# - NO other broker API calls

# Total: 2 broker calls (or just 1 if already authenticated)

# If you see MORE, something is wrong!
# Check:
# 1. Is any agent calling broker directly? (BAD)
# 2. Is any agent refetching limits? (BAD)
# 3. Are we retrying on failure? (OK if <5 retries in error case)
```

## Summary

✅ **Fetch ONCE**: Market open, single call  
✅ **Cache ALL DAY**: `/tmp/broker_limits.json`  
✅ **Zero Runtime Calls**: All agents use cached config  
✅ **LIVE Mode Safe**: One call per order execution  
✅ **No Rate Limiting**: Single daily fetch, no retries  

**Status: BROKER API SAFE, NO LOCKOUT RISK**

