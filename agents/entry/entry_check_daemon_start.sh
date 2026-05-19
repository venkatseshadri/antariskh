#!/bin/bash
# Entry Check Daemon Startup Script
# Launched by cron at 09:15 to generate fresh entry signals every 5 min

LOGDIR="/home/trading_ceo/antariksh/logs"
DAEMON_SCRIPT="/home/trading_ceo/antariksh/entry_check_daemon.py"

# Create logs dir if needed
mkdir -p "$LOGDIR"

# Start the daemon if not already running
if ! pgrep -f "entry_check_daemon.py" > /dev/null; then
    nohup python3 "$DAEMON_SCRIPT" >> "$LOGDIR/entry_check_daemon_$(date +%Y%m%d).log" 2>&1 &
    echo "[$(date '+%H:%M:%S')] Entry Check Daemon started (PID: $!)" >> "$LOGDIR/entry_check_daemon_$(date +%Y%m%d).log"
else
    echo "[$(date '+%H:%M:%S')] Entry Check Daemon already running" >> "$LOGDIR/entry_check_daemon_$(date +%Y%m%d).log"
fi
