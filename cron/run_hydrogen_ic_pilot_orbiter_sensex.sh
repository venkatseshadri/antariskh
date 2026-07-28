#!/bin/bash
# HYDROGEN-ORBITER — ORBITER v3.0, next-week SENSEX iron condor.
# One-shot, cron-fired every 15 min during market hours. Paper only.
# Separate state/ledger/lock from all other pilots. NOT YET INSTALLED.
#
#   0,15,30,45 9-15 * * 1-5 /home/trading_ceo/antariksh/cron/run_hydrogen_ic_pilot_orbiter_sensex.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON_BIN="/usr/bin/python3"
LOG_FILE="$PROJECT_DIR/logs/hydrogen/hydrogen_ic_pilot_orbiter_sensex_cron_$(date +%Y%m%d).log"
LOCK_FILE="$PROJECT_DIR/locks/hydrogen_ic_pilot_orbiter_sensex.lock"

mkdir -p "$(dirname "$LOG_FILE")" "$(dirname "$LOCK_FILE")"
exec {LOCK_FD}>"$LOCK_FILE"
if ! flock -n "$LOCK_FD"; then exit 0; fi
cd "$PROJECT_DIR"
echo "----- $(date '+%F %T') -----" >> "$LOG_FILE"
"$PYTHON_BIN" hydrogen_ic_pilot_orbiter.py SENSEX >> "$LOG_FILE" 2>&1
