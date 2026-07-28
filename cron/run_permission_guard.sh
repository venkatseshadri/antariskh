#!/bin/bash
# Permission drift guard — every 5 min, market hours. Deterministic checker,
# no LLM: re-applies the source-file group/mode and heartbeat-ownership
# baseline established 2026-07-21 after two live incidents (cron .sh exec-bit
# stripped, Penguin heartbeat root-owned). Silent when clean; logs + Telegram
# alert when it has to correct something.
#
#   */5 9-15 * * 1-5 /home/trading_ceo/cron_notify_wrapper.sh run_permission_guard.sh /home/trading_ceo/antariksh/cron/run_permission_guard.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON_BIN="/usr/bin/python3"
LOG_FILE="$PROJECT_DIR/logs/permission_guard_cron_$(date +%Y%m%d).log"
LOCK_FILE="$PROJECT_DIR/locks/permission_guard.lock"

mkdir -p "$PROJECT_DIR/logs" "$(dirname "$LOCK_FILE")"

exec {LOCK_FD}>"$LOCK_FILE"
if ! flock -n "$LOCK_FD"; then
    exit 0
fi

cd "$PROJECT_DIR"
echo "----- $(date '+%F %T') -----" >> "$LOG_FILE"
"$PYTHON_BIN" permission_guard.py >> "$LOG_FILE" 2>&1
