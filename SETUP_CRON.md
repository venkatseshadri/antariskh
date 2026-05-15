# Setting Up Antariksh Cron Jobs

## Trial Run v1 (Active) — Live DuckDB + Paper Trading

No API key needed. Reads real market data, paper trades only.

```bash
# Edit your crontab
crontab -e

# Add these lines:

# Trial v1 entry session — 10:30 AM IST weekdays (scan → plan → risk → execute)
30 10 * * 1-5 /home/trading_ceo/antariksh/scheduler/run_trial_entry.sh

# Trial v1 exit session — 2:35 PM IST weekdays (monitor P&L → audit log)
35 14 * * 1-5 /home/trading_ceo/antariksh/scheduler/run_trial_exit.sh
```

### Manual testing

```bash
python3 /home/trading_ceo/antariksh/trial_runner.py --entry   # Entry session only
python3 /home/trading_ceo/antariksh/trial_runner.py --exit    # Exit session only
python3 /home/trading_ceo/antariksh/trial_runner.py --full    # Entry + exit
```

### Log monitoring

```bash
tail -f /home/trading_ceo/antariksh/logs/trial_runner.log
tail -f /home/trading_ceo/antariksh/logs/trial_entry.log
tail -f /home/trading_ceo/antariksh/logs/trial_exit.log
```

---

## Phase 1 Cron (Legacy — disabled, re-enable if needed)

Phase 1 used `phase1_mvs.py` via `run_phase1_9am.sh` and `run_phase1_2pm.sh`.
Trial Run v1 replaces these with `crew_structure.py` deterministic tools + DuckDB data.

To re-enable Phase 1 cron:

```bash
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
