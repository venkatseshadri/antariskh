#!/bin/bash
# Guard script for token_refresh_dual.py — daily broker auth refresh
# Runs at 07:00 before session start. Idempotent.
#
# Usage (cron):
#   0 7 * * 1-5 /home/trading_ceo/antariksh/cron/run_token_refresh.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_FILE="$PROJECT_DIR/logs/token_refresh_$(date +%Y%m%d).log"
LOCK_FILE="/tmp/token_refresh.lock"
PYTHON_BIN="/usr/bin/python3"

exec {LOCK_FD}>"$LOCK_FILE"
if ! flock -n "$LOCK_FD"; then
    exit 0
fi

mkdir -p "$PROJECT_DIR/logs"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting token refresh..." >> "$LOG_FILE"
"$PYTHON_BIN" "$PROJECT_DIR/token_refresh_dual.py" >> "$LOG_FILE" 2>&1
