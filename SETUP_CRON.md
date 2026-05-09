# Setting Up Antariksh Phase 1 Cron Jobs

## Quick Setup

```bash
# Edit your crontab
crontab -e

# Add these lines:

# Token refresh (both brokers) — 7 AM daily
0 7 * * * /usr/bin/python3 /home/trading_ceo/antariksh/token_refresh_dual.py

# Phase 1 entry gate (9:30 AM) — weekdays only
30 09 * * 1-5 /home/trading_ceo/antariksh/scheduler/run_phase1_9am.sh

# Phase 1 exit & report (2:35 PM) — weekdays only
35 14 * * 1-5 /home/trading_ceo/antariksh/scheduler/run_phase1_2pm.sh

# Exec reporting — daily 6 PM, weekly Sun 8 PM, monthly 1st 9 PM
0 18 * * 1-5 /usr/bin/python3 /home/trading_ceo/antariksh/exec_report.py daily
0 20 * * 0 /usr/bin/python3 /home/trading_ceo/antariksh/exec_report.py weekly
0 21 1 * * /usr/bin/python3 /home/trading_ceo/antariksh/exec_report.py monthly
```

## Cron Format

```
Minute Hour Day Month DayOfWeek Command

30     09   *   *     1-5         run_phase1_9am.sh
       |    |   |     |
       |    |   |     └─ Monday(1) through Friday(5)
       |    |   └─────── Every day of month
       |    └─────────── Every month
       └────────────────  09:30 AM IST

35     14   *   *     1-5         run_phase1_2pm.sh
       └────────────────  02:35 PM IST
```

## Verify Installation

```bash
# Check crontab is set
crontab -l

# Monitor cron logs (on Linux)
tail -f /var/log/syslog | grep CRON

# Check execution logs
tail -f /home/trading_ceo/antariksh/logs/scheduler_9am.log
tail -f /home/trading_ceo/antariksh/logs/scheduler_2pm.log
```

## Manual Testing

```bash
# Test 9 AM run
/home/trading_ceo/antariksh/scheduler/run_phase1_9am.sh

# Test 2 PM run
/home/trading_ceo/antariksh/scheduler/run_phase1_2pm.sh

# Check logs
tail -50 /home/trading_ceo/antariksh/logs/phase1_20260508.log
cat /home/trading_ceo/antariksh/logs/cfo_audit_20260508.jsonl | jq .
```

## Troubleshooting

### Cron Not Executing

1. **Check if cron daemon is running:**
   ```bash
   systemctl status cron
   # or
   ps aux | grep cron
   ```

2. **Verify script permissions:**
   ```bash
   ls -la /home/trading_ceo/antariksh/scheduler/
   # Should show: -rwxr-xr-x
   ```

3. **Check Python path in script:**
   ```bash
   which python3
   # If output differs from /usr/bin/python3, update the shebang in run_phase1_9am.sh
   ```

### No Logs Generated

1. **Check if script runs manually:**
   ```bash
   bash /home/trading_ceo/antariksh/scheduler/run_phase1_9am.sh
   ```

2. **Check if log directory is writable:**
   ```bash
   ls -ld /home/trading_ceo/antariksh/logs/
   touch /home/trading_ceo/antariksh/logs/test.txt
   ```

### Timestamps Wrong

- Cron uses system timezone. Verify IST (UTC+5:30):
  ```bash
  date
  timedatectl status
  ```

## Next Steps (Phase 1 Iteration)

1. Verify cron jobs run correctly for 2–3 days
2. Check logs daily for errors or unexpected behavior
3. Monitor Telegram messages (9:30 AM + 2:35 PM arrivals)
4. Once stable: integrate real market data (VIX, NIFTY spot, events)
5. Run soak-test for 10–15 sessions (≈2 weeks)
