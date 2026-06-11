#!/bin/bash
# EOD multi-TF backfill + parquet export (DAMBUILDER T10).
# Cron-safe wrapper: cd + env + pgrep guard + per-day log.
# Schedule: 16:00 IST Mon-Fri (after close). Safe to re-run (idempotent).

set -u

REPO=/home/trading_ceo/antariksh
LOG_DIR="$REPO/logs"
DATE="${1:-$(TZ=Asia/Kolkata date +%F)}"
LOG="$LOG_DIR/eod_backfill_$(TZ=Asia/Kolkata date +%Y%m%d).log"

mkdir -p "$LOG_DIR"

# Weekend guard (holidays: script no-ops cleanly when day has no 1-min bars)
dow=$(TZ=Asia/Kolkata date +%u)
if [ "$dow" -gt 5 ]; then
    echo "[$(date -Is)] weekend — skip" >> "$LOG"
    exit 0
fi

# Single-instance guard
if pgrep -f "enrichers/eod_backfill.py" > /dev/null; then
    echo "[$(date -Is)] already running — skip" >> "$LOG"
    exit 0
fi

cd "$REPO" || exit 1

for INST in NIFTY SENSEX; do
    echo "[$(date -Is)] eod_backfill $INST $DATE" >> "$LOG"
    /usr/bin/python3 enrichers/eod_backfill.py --instrument "$INST" --date "$DATE" >> "$LOG" 2>&1
    rc=$?
    echo "[$(date -Is)] $INST exit=$rc" >> "$LOG"
done
