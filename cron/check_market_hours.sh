#!/bin/bash
# Time-aware market gate for systemd ExecCondition.
# Exit 0 = within today's trading window for EXCHANGE (start capture).
# Exit 1 = weekend / holiday / outside the time-of-day window (skip).
#
# Why this exists: the day-bounded capture units use RuntimeMaxSec to stop at
# the session close, but a RuntimeMaxSec timeout is classified by systemd as a
# failure, so Restart=on-failure immediately restarts the service into an
# endless bounce loop. Gating the restart on the trading window keeps a service
# down once its session has ended. Date/holiday/weekend logic is delegated to
# check_market_open.sh (kept date-only for its other callers).
#
# Usage: check_market_hours.sh [EXCHANGE]   (EXCHANGE defaults to NSE)

EXCHANGE="${1:-NSE}"
DIR="$(dirname "$0")"

# Weekend / holiday gate first (same calendar all callers rely on).
"$DIR/check_market_open.sh" "$EXCHANGE" || exit 1

NOW=$((10#$(date +%H%M)))
case "$EXCHANGE" in
    MCX)        START=855;  END=2335 ;;
    NSE|BSE|*)  START=900;  END=1531 ;;
esac

if [ "$NOW" -ge "$START" ] && [ "$NOW" -le "$END" ]; then
    exit 0
fi
exit 1
