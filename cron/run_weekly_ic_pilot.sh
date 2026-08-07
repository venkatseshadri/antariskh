#!/bin/bash
# PROTON — weekly NIFTY iron-condor paper pilot. One-shot, cron-fired every
# 15 min during market hours. Paper only. Own Flattrade session (separate from
# ATOM's Shoonya feed), own state/ledger files. Reads market_data READ-ONLY.
# No writes to any file/table ATOM touches. flock = at most one run at a time.
#
#   0,15,30,45 9-15 * * 1-5 /home/trading_ceo/antariksh/cron/run_weekly_ic_pilot.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON_BIN="/usr/bin/python3"
LOG_FILE="$PROJECT_DIR/logs/weekly_ic_pilot_cron_$(date +%Y%m%d).log"
LOCK_FILE="$PROJECT_DIR/locks/weekly_ic_pilot.lock"

mkdir -p "$PROJECT_DIR/logs" "$(dirname "$LOCK_FILE")"

exec {LOCK_FD}>"$LOCK_FILE"
if ! flock -n "$LOCK_FD"; then
    exit 0
fi

cd "$PROJECT_DIR"
echo "----- $(date '+%F %T') -----" >> "$LOG_FILE"
"$PYTHON_BIN" weekly_ic_pilot.py >> "$LOG_FILE" 2>&1
