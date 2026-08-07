#!/bin/bash
# PROTON — LIVE real-money order placement. DRY_RUN by default (proton_live.py
# refuses to place real orders unless PROTON_LIVE_TRADING=YES_REAL_MONEY is set
# below). NOT installed in crontab by this commit — install only after the
# DRY_RUN log has been reviewed and you've deliberately decided to flip the
# env var. flock = at most one run at a time. 1-lot hard cap, no EOD close
# (holds to weekly expiry/PT/SL), Flattrade session (isolated from ATOM).
#
#   0,15,30,45 9-15 * * 1-5 /home/trading_ceo/antariksh/cron/run_proton_live.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON_BIN="/usr/bin/python3"
LOG_FILE="$PROJECT_DIR/logs/proton/proton_live_cron_$(date +%Y%m%d).log"
LOCK_FILE="$PROJECT_DIR/locks/proton_live.lock"

mkdir -p "$(dirname "$LOG_FILE")" "$(dirname "$LOCK_FILE")"

exec {LOCK_FD}>"$LOCK_FILE"
if ! flock -n "$LOCK_FD"; then
    exit 0
fi

cd "$PROJECT_DIR"
echo "----- $(date '+%F %T') -----" >> "$LOG_FILE"
# PROTON_LIVE_TRADING=YES_REAL_MONEY \
"$PYTHON_BIN" proton_live.py >> "$LOG_FILE" 2>&1
