#!/bin/bash
# Antariksh Phase 1 — 9:30 AM Entry Gate Scheduler
# Runs at 9:30 AM IST on weekdays
# Entry decision: PASS/SKIP based on VIX, events, market window

set -e  # Exit on error

PROJECT_ROOT="/home/trading_ceo/antariksh"
LOG_DIR="$PROJECT_ROOT/logs"
SCRIPT="$PROJECT_ROOT/phase1_mvs.py"

# Ensure log directory exists
mkdir -p "$LOG_DIR"

# Run the MVS
python3 "$SCRIPT" >> "$LOG_DIR/scheduler_9am.log" 2>&1

echo "[$(date)] Phase 1 MVS 9 AM run complete" >> "$LOG_DIR/scheduler_9am.log"
