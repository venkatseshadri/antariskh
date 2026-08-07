#!/bin/bash
# DEPRECATED 2026-07-22 — not installed in any crontab. Folded into
# permission_guard.py's own cron tick instead (refresh_validator_feed()) to
# avoid adding a 6th cron entry for what's mostly one-time-symlink work.
# Kept on disk for reference only; safe to delete manually whenever.
#
# Refreshes /var/log/algo/{atom_plus,proton,neutron,hydrogen,penguin}/ symlinks
# so newly-rotated daily log files (e.g. atom_paper_20260723.log) stay visible
# to algo_validator without manual intervention.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON_BIN="/usr/bin/python3"
LOG_FILE="$PROJECT_DIR/logs/validator_feed_sync_cron_$(date +%Y%m%d).log"
LOCK_FILE="$PROJECT_DIR/locks/validator_feed_sync.lock"

mkdir -p "$PROJECT_DIR/logs" "$(dirname "$LOCK_FILE")"

exec {LOCK_FD}>"$LOCK_FILE"
if ! flock -n "$LOCK_FD"; then
    exit 0
fi

cd "$PROJECT_DIR"
echo "----- $(date '+%F %T') -----" >> "$LOG_FILE"
"$PYTHON_BIN" validator_feed_sync.py >> "$LOG_FILE" 2>&1
