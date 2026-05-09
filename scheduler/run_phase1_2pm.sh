#!/bin/bash
# Antariksh Phase 1 — 2:35 PM Exit Report Scheduler
# Runs at 2:35 PM IST on weekdays
# Exit report: P&L, MTD stats, system status

set -e  # Exit on error

PROJECT_ROOT="/home/trading_ceo/antariksh"
LOG_DIR="$PROJECT_ROOT/logs"
SCRIPT="$PROJECT_ROOT/phase1_mvs.py"

# Ensure log directory exists
mkdir -p "$LOG_DIR"

# Run the MVS
python3 "$SCRIPT" >> "$LOG_DIR/scheduler_2pm.log" 2>&1

echo "[$(date)] Phase 1 MVS 2 PM run complete" >> "$LOG_DIR/scheduler_2pm.log"
