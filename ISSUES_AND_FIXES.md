# Trading System Issues & Fixes Required

**Date:** May 20, 2026  
**Last Updated:** May 20, 2026 (late session fixes applied)

---

## Summary

The trading system has several integration gaps that prevented it from running correctly on May 20:

1. **Entry Check not running** (no cron job) → ✅ Fixed: Added cron
2. **7th traffic light (GAP) always unknown** → ✅ Fixed: Added Redis prev_close writer
3. **EMA files not updating** → ✅ Fixed: v4 aggregator properly integrated, fallback added
4. **Redis queue not consumed** → ✅ Fixed: Safe cleanup after processing
5. **V4 aggregator crashed** → ✅ Fixed: Pre-flight checks, better restart logging

---

## Issue 1: Entry Check Missing from Cron

**Status:** ✅ FIXED

### Root Cause
- entry_check.py was not scheduled in crontab
- Cron was installed at 20:53 (after market close) on May 20
- No entry signals generated all day → No trades executed

### Solution Applied
```bash
# Added to /var/spool/cron/crontabs/root:
*/5 9-15 * * 1-5 cd /home/trading_ceo/antariksh && /usr/bin/python3 -m agents.entry.entry_check >> logs/entry_check_cron.log 2>&1
```

### Permanent Fix Status
- ✅ Cron entry added
- ⬜ Log rotation for entry_check_cron.log

---

## Issue 2: 7th Traffic Light (GAP) Always Unknown

**Status:** ✅ FIXED

### Solution Applied
- `data_capture_v3.1_duckdb.py` writes `prev_close_{INDEX}` to Redis on each capture
- `entry_tools.py` gap dict included in combine_entry_scores output
- Gap boost/penalty applied to traffic light confidence

---

## Issue 3: Redis Queue Not Being Consumed (Memory Leak)

**Status:** ✅ FIXED

### Solution Applied
- Queue deleted only after successful DuckDB write + EMA update (not before)
- Safe to re-process: DuckDB uses `ON CONFLICT DO UPDATE` (idempotent)
- If processing crashes, queue retains data for retry

---

## Issue 4: EMA State Files Not Updating in Real-Time

**Status:** ✅ FIXED

### Root Cause
- v4 aggregator crashed on May 19, never recovered

### Solution Applied
1. **`run_data_capture_with_v4.sh`**: Pre-flight import check, startup PID verification, restart failure detection
2. **`data_capture_v4_queue_aggregator.py`**: Per-TF EMA update logging
3. **`entry_tools.py`**: Fallback from 60-min to 1-min EMA when stale (>30 min), `ema_source` field logged

### Expected Behavior Tomorrow
- v4 starts at 09:14, updates EMA files every 60 seconds
- Entry check uses 60-min EMA if fresh, falls back to 1-min otherwise
- Trend confidence improves as data accumulates

---

## Issue 5: V4 Aggregator Startup Failures

**Status:** ✅ FIXED

### Solution Applied
- Pre-flight import test in `run_data_capture_with_v4.sh`
- PID verification with `sleep 2 && kill -0` after startup
- Restart loop logs success/failure

---

## Issue 6: Missing Data in V4 Database

**Status:** ✅ FIXED (one-time backfill applied May 20)

---

## Issue 7: Entry Check Trend Confidence Low (40%)

**Status:** ✅ MITIGATED

- Added 60-min → 1-min EMA fallback when stale
- Expected to resolve once v4 starts tomorrow and EMA files are fresh

---

## Summary of Fixes (May 20 Session)

### Priority 1 — ✅ ALL FIXED

| # | Issue | File(s) | Fix |
|---|-------|---------|-----|
| 1 | V4 startup reliability | `run_data_capture_with_v4.sh` | Pre-flight check, PID verify, restart logging |
| 2 | EMA update logging | `data_capture_v4_queue_aggregator.py` | Per-TF bar counts, summary after each cycle |
| 3 | Entry check stale EMA | `entry_tools.py` | 60-min → 1-min fallback, ema_source field |

### Priority 2 — ✅ FIXED

| # | Issue | File(s) | Fix |
|---|-------|---------|-----|
| 4 | Queue cleanup unsafe | `data_capture_v4_queue_aggregator.py` | Delete-after-process, idempotent via UPSERT |

### Additional Fixes Applied

| # | Issue | File(s) | Fix |
|---|-------|---------|-----|
| 5 | /tmp state files | `kickoff.py`, `data_health.py`, `order_agent.py`, `risk_monitor.py` | Moved to `brahmand/data/` |
| 6 | /tmp config files | `broker_limits.py`, `morning_startup.py`, `risk_config.py`, `trading_desk.py` | Moved to `antariksh/data/` |
| 7 | Stale date in kickoff state | `kickoff.py` | Date-reset guard in `load_state()` |

### Priority 3 — ⬜ NOT YET DONE

- Log rotation
- Health check monitoring (queue size, EMA age, v3.1→v4 lag)
- Documentation / runbooks

---

## Files Modified

- `/home/trading_ceo/python-trader/varaha/run_data_capture_with_v4.sh` — Pre-flight check, PID verify, restart logging
- `/home/trading_ceo/python-trader/varaha/data_capture_v3.1_duckdb.py` — Redis prev_close writer
- `/home/trading_ceo/antariksh/tools/entry_tools.py` — Gap output, EMA staleness fallback, ema_source
- `/home/trading_ceo/antariksh/data_capture_v4_queue_aggregator.py` — Queue delete-after-process, EMA logging
- `/home/trading_ceo/brahmand/kickoff.py` — State from /tmp → data/, date-reset
- `/home/trading_ceo/brahmand/data_health.py` — State from /tmp → data/
- `/home/trading_ceo/brahmand/order_agent.py` — Ledger from /tmp → data/
- `/home/trading_ceo/brahmand/risk_monitor.py` — Lock/ledger from /tmp → data/
- `/home/trading_ceo/antariksh/broker_limits.py` — Limits from /tmp → data/
- `/home/trading_ceo/antariksh/morning_startup.py` — Limits cache from /tmp → data/
- `/home/trading_ceo/antariksh/risk_config.py` — Order ledger path from /tmp → data/
- `/home/trading_ceo/antariksh/trading_desk.py` — Docstring /tmp refs → data/
- `/home/trading_ceo/antariksh/tests/scenario_runner.py` — Test log prefix from /tmp → data/

---

## Test Plan for Tomorrow

1. **09:14 AM** — Data capture starts
   - [ ] v3.1 NIFTY captures bars
   - [ ] v3.1 SENSEX captures bars
   - [ ] v4 aggregator starts (check `v4_aggregator.log` for pre-flight result)
   - [ ] v4 PID verified after startup

2. **09:15–09:30 AM** — First entry checks
   - [ ] entry_check runs every 5 minutes
   - [ ] Check `ema_source` field: should show "1min (fallback)" initially, switch to "60min" once fresh
   - [ ] Gap is populated (not "unknown")
   - [ ] v4 EMA update counts logged

3. **09:30–10:00 AM** — EMA freshness
   - [ ] EMA file timestamps updating every 60s
   - [ ] Trend confidence increasing
   - [ ] Kickoff reads `entry_check_latest.json`
   - [ ] Kickoff state resets to `trades_today: 0` (date changed from May 20)

4. **3:30–4:00 PM** — EOD shutdown
   - [ ] All processes exit gracefully
   - [ ] Queue empty (cleared after last cycle)
