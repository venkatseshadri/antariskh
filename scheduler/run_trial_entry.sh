#!/bin/bash
# Antariksh Trial Run v1 — 10:30 AM Entry Session
# Cron: 30 10 * * 1-5
# Reads DuckDB market data, paper trades, no API key needed

set -e

PROJECT_ROOT="/home/trading_ceo/antariksh"
VENV="$PROJECT_ROOT/.venv/bin/activate"
LOG_DIR="$PROJECT_ROOT/logs"

mkdir -p "$LOG_DIR"

source "$VENV"
python3 "$PROJECT_ROOT/trial_runner.py" --entry >> "$LOG_DIR/trial_entry.log" 2>&1

echo "[$(date)] Trial Entry complete" >> "$LOG_DIR/trial_entry.log"
