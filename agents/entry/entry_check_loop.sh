#!/bin/bash
# Entry Check Continuous Loop
# Generates fresh entry signals every 5 minutes during market hours
# Runs 09:15-15:30 IST weekdays

cd /home/trading_ceo/antariksh
LOG=/tmp/entry_check_loop.log

exec >> "$LOG" 2>&1

is_market_open() {
    local dow=$(date +%u)
    local now=$(date +%H%M)
    [ "$dow" -le 5 ] && [ "$now" -ge "0915" ] && [ "$now" -le "1530" ]
}

echo "[$(date)] Entry check loop started"

while is_market_open; do
    python3 agents/entry/entry_check.py > /dev/null 2>&1
    sleep 300  # Run every 5 minutes
done

echo "[$(date)] Market closed, exiting"
