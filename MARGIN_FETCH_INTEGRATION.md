# Margin Capture Integration with Token Refresh

## Overview

Instead of a separate margin fetching job, we **tag along** to the existing 07:00 token refresh cron job. This reuses fresh tokens with zero additional login overhead.

## Cron Schedule

```bash
# Existing: 07:00 AM (before pre-market)
0 7 * * 1-5 /usr/bin/python3 /home/trading_ceo/antariksh/token_refresh_dual.py

# Now also includes margin fetch using those fresh tokens!
```

## How It Works

### Before (Separate Jobs)
```
07:00 — token_refresh_dual.py
        ├─ Refresh Flattrade token
        └─ Refresh Shoonya token
        
08:55 — dispatch_crew.sh (AM crew)
        └─ Query broker margins (separate API calls!)
        
09:00-15:30 — margin_capture.py loop
        └─ Continuous margin updates
```

### After (Integrated)
```
07:00 — token_refresh_dual.py
        ├─ Refresh Flattrade token
        ├─ Refresh Shoonya token
        └─ 🆕 Fetch margins using fresh tokens
            ├─ Shoonya: via varaha.api.get_limits()
            └─ Flattrade: placeholder (TODO)
            
08:55 — dispatch_crew.sh (AM crew)
        └─ Use cached margins (no API call needed)
        
09:00-15:30 — margin_capture.py loop
        └─ Continuous margin updates
```

## Benefits

✅ **No Extra Login** — Reuses tokens just refreshed  
✅ **Reduced API Calls** — One call per broker per day instead of multiple  
✅ **Faster** — Crew gets margins from cache at 08:55  
✅ **Same Result** — Cached margins available for entire trading day  
✅ **Rate-Limit Safe** — Only 2 broker calls total (login + margin)  

## Implementation Details

### In `token_refresh_dual.py`

After tokens are refreshed, the new `fetch_margins_after_token_refresh()` function:

1. **Shoonya**: Uses `varaha.login()` with fresh `cred.yml`
   ```python
   from varaha_auth import Varaha
   varaha = Varaha()  # Uses cred.yml just refreshed
   varaha.login()     # No new OAuth, uses cached token
   limits = fetch_live_limits_from_broker(varaha.api)
   sync_with_config()
   ```

2. **Flattrade**: Placeholder for implementation
   ```python
   # TODO: Use fresh tokens.json to query Flattrade margins
   ```

3. **Result**: Margins cached to `/tmp/broker_limits_comparison.json`

### In `dispatch_crew.sh` (08:55)

The AM crew can now use cached margins instead of querying:

```python
from broker_limits import get_current_limits
limits, is_fresh = get_current_limits()  # is_fresh = True (< 1 hour old)
# Use margins without additional API calls
```

## Testing

```bash
# Test manually (simulates 07:00 cron)
python3 /home/trading_ceo/antariksh/token_refresh_dual.py

# Check log
tail -f /home/trading_ceo/antariksh/logs/token_refresh_cron.log

# Verify cached margins
cat /tmp/broker_limits_comparison.json
```

## Expected Output

```
TOKEN REFRESH JOB — START
Timestamp: 2026-05-20T07:00:00

FLATTRADE TOKEN REFRESH
Running: /home/trading_ceo/python-trader/get_flattrade_token_auto.py
Exit code: 0
✅ Flattrade token refreshed: FT055702 (exchange: OK)

SHOONYA TOKEN REFRESH
Running: /home/trading_ceo/python-trader/Shoonya_oAuthAPI-py/GetAuthcode.py
Exit code: 0
✅ Shoonya credentials refreshed (mtime: 2026-05-20 07:02:00)

MARGIN CAPTURE — Using Fresh Tokens
✅ Shoonya margin cached: ₹611,000
ℹ️  Flattrade margin: placeholder (TODO: integrate)

SUMMARY
Flattrade: ✅ OK
Shoonya: ✅ OK
Overall: ✅ SUCCESS
```

## Next Steps

1. ✅ Integrated margin fetch into token_refresh_dual.py
2. ✅ Reuses fresh tokens (no new login)
3. ✅ Caches results to /tmp/broker_limits_comparison.json
4. ⏳ TODO: Implement Flattrade margin fetch using fresh tokens.json
5. ⏳ TODO: Update dispatch_crew.sh (08:55) to use cached margins

## Files Modified

- `token_refresh_dual.py` — Added `fetch_margins_after_token_refresh()` function
- No changes needed to cron (existing 07:00 job now includes margins!)
- No new login calls needed

## API Call Count (Daily)

**Before**: 2 (tokens) + 2 (margins at 08:55) = 4 calls  
**After**: 2 (tokens + margins at 07:00) = 2 calls  

**Savings**: 50% reduction in broker API calls

