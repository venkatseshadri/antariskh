#!/bin/bash
# Guard script for multitf_recompute.py --live (intraday market_data_multitf refresh)
# Dual guard: pgrep liveness check + flock atomic lock. Cron-safe — no duplicates.
# The --live process self-exits after 15:35, so cron re-launches it each session.
#
# Usage (cron):
#   */5 9-15 * * 1-5 /home/trading_ceo/antariksh/cron/run_multitf_live.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_FILE="$PROJECT_DIR/logs/multitf_live.log"
LOCK_FILE="$PROJECT_DIR/locks/multitf_live.lock"
mkdir -p "$(dirname "$LOCK_FILE")" "$PROJECT_DIR/logs"
PYTHON_BIN="/usr/bin/python3"

# Primary guard: reliable liveness check (backgrounded daemon releases inherited
# flock FDs, so pgrep is authoritative).
if pgrep -f "multitf_recompute.py --live" > /dev/null; then
    exit 0
fi

# Secondary guard: close the race between two near-simultaneous cron ticks.
exec {LOCK_FD}>"$LOCK_FILE"
if ! flock -n "$LOCK_FD"; then
    exit 0
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting multitf live enricher..." >> "$LOG_FILE"
cd "$PROJECT_DIR"
nohup "$PYTHON_BIN" "$PROJECT_DIR/enrichers/multitf_recompute.py" --live --both >> "$LOG_FILE" 2>&1 &
