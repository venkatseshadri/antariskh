#!/bin/bash
# NUCLEUS — capital-orchestration layer across the 4-tier system. One-shot,
# cron-fired every 15 min during market hours. Reads live Shoonya margin
# (stateless REST, same pattern as proton_live.py), falls back to the cached
# daily broker_limits.json on failure. Writes data/nucleus_allocation.json.
# flock = at most one run at a time.
#
#   0,15,30,45 9-15 * * 1-5 /home/trading_ceo/antariksh/cron/run_nucleus.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON_BIN="/usr/bin/python3"
LOG_FILE="$PROJECT_DIR/logs/nucleus_cron_$(date +%Y%m%d).log"
LOCK_FILE="$PROJECT_DIR/locks/nucleus.lock"

mkdir -p "$PROJECT_DIR/logs" "$(dirname "$LOCK_FILE")"

exec {LOCK_FD}>"$LOCK_FILE"
if ! flock -n "$LOCK_FD"; then
    exit 0
fi

cd "$PROJECT_DIR"
echo "----- $(date '+%F %T') -----" >> "$LOG_FILE"
"$PYTHON_BIN" nucleus.py >> "$LOG_FILE" 2>&1
