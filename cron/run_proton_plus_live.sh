#!/bin/bash
# PROTON+ — ORBITER v3.0 Tier 2, ORBITER-gated NIFTY/SENSEX iron condor.
# Retrofit (2026-07-17): adds `use_orbiter=True` to proton_live.py,
# following the same boolean-flag retrofit pattern as ATOM+ (run_live_once.py).
# Flipped to PAPER 2026-07-20 (Board call: more research trades > real capital
# risk while the shared account sits margin-constrained). PROTON_LIVE_TRADING
# is intentionally NOT set here anymore — was YES_REAL_MONEY 2026-07-17 to
# 2026-07-20, never placed a real order in that window (always blocked by
# GATE1/margin). PROTON_INSTANCE_SUFFIX keeps its paper state/ledger separate
# from base PROTON's own dry-run files (same script, same schedule, would
# otherwise race on one file). Nearest-expiry index entry rule (replaces
# Friday-only NIFTY).
#
#   0,15,30,45 9-15 * * 1-5 /home/trading_ceo/antariksh/cron/run_proton_plus_live.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON_BIN="/usr/bin/python3"
LOG_FILE="$PROJECT_DIR/logs/proton/proton_plus_live_cron_$(date +%Y%m%d).log"
LOCK_FILE="$PROJECT_DIR/locks/proton_plus_live.lock"

mkdir -p "$(dirname "$LOG_FILE")" "$(dirname "$LOCK_FILE")"

exec {LOCK_FD}>"$LOCK_FILE"
if ! flock -n "$LOCK_FD"; then
    exit 0
fi

cd "$PROJECT_DIR"
echo "----- $(date '+%F %T') -----" >> "$LOG_FILE"
PROTON_INSTANCE_SUFFIX=_plus \
"$PYTHON_BIN" proton_live.py >> "$LOG_FILE" 2>&1
