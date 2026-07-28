#!/bin/bash
# PROTON-ORBITER — ORBITER v3.0 specs on PROTON's weekly cycle. One-shot,
# cron-fired every 15 min during market hours. Paper only. Sibling of
# run_weekly_ic_pilot.sh — separate state/ledger/lock, does not touch the
# validated pilot's files. NOT YET INSTALLED in crontab — propose the line
# below for approval before adding it.
#
#   0,15,30,45 9-15 * * 1-5 /home/trading_ceo/antariksh/cron/run_weekly_ic_pilot_orbiter.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON_BIN="/usr/bin/python3"
LOG_FILE="$PROJECT_DIR/logs/weekly_ic_pilot_orbiter_cron_$(date +%Y%m%d).log"
LOCK_FILE="$PROJECT_DIR/locks/weekly_ic_pilot_orbiter.lock"

mkdir -p "$PROJECT_DIR/logs" "$(dirname "$LOCK_FILE")"

exec {LOCK_FD}>"$LOCK_FILE"
if ! flock -n "$LOCK_FD"; then
    exit 0
fi

cd "$PROJECT_DIR"
echo "----- $(date '+%F %T') -----" >> "$LOG_FILE"
"$PYTHON_BIN" weekly_ic_pilot_orbiter.py >> "$LOG_FILE" 2>&1
