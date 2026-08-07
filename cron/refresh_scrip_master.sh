#!/bin/bash
# Guard script for tools/bootstrap_scrip_master.py — daily NFO/BFO scrip-master refresh
# Runs pre-open, before the 09:14 capture cold-start. Idempotent (same-day re-run is a no-op
# download + full rebuild). Filed as antariksh T25 (DAMBUILDER_STATE.md).
#
# Usage (cron):
#   30 8 * * 1-5 /home/trading_ceo/antariksh/cron/refresh_scrip_master.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_FILE="$PROJECT_DIR/logs/refresh_scrip_master_$(date +%Y%m%d).log"
LOCK_FILE="$PROJECT_DIR/locks/refresh_scrip_master.lock"
mkdir -p "$(dirname "$LOCK_FILE")"
PYTHON_BIN="/usr/bin/python3"

exec {LOCK_FD}>"$LOCK_FILE"
if ! flock -n "$LOCK_FD"; then
    exit 0
fi

mkdir -p "$PROJECT_DIR/logs"
cd "$PROJECT_DIR"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting scrip master refresh..." >> "$LOG_FILE"
"$PYTHON_BIN" "$PROJECT_DIR/tools/bootstrap_scrip_master.py" >> "$LOG_FILE" 2>&1
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Done (exit $?)." >> "$LOG_FILE"
