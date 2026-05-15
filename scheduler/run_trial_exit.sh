#!/bin/bash
# Antariksh Trial Run v1 — 2:35 PM Exit Session
# Cron: 35 14 * * 1-5
# Monitors P&L, logs audit. No API key needed.

set -e

PROJECT_ROOT="/home/trading_ceo/antariksh"
VENV="$PROJECT_ROOT/.venv/bin/activate"
LOG_DIR="$PROJECT_ROOT/logs"

mkdir -p "$LOG_DIR"

source "$VENV"
python3 "$PROJECT_ROOT/trial_runner.py" --exit >> "$LOG_DIR/trial_exit.log" 2>&1

echo "[$(date)] Trial Exit complete" >> "$LOG_DIR/trial_exit.log"
