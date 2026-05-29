#!/bin/bash
# Systemd ExecCondition convention: exit 0 = proceed, exit 1+ = skip.
# Exit 0 = market open (start capture).
# Exit 1 = market closed / holiday / weekend (skip capture).
#
# Usage: check_market_open.sh [EXCHANGE]
#   EXCHANGE defaults to NSE. Pass MCX (or BSE) to use that exchange's
#   holiday calendar. Holidays in market_holidays.json carry a 'market'
#   field (e.g., "NSE/BSE/MCX" or "NSE/BSE"); we skip the day only if
#   the named EXCHANGE appears in that field.

EXCHANGE="${1:-NSE}"
HOLIDAYS_FILE="/root/.picoclaw/workspace/config/market_holidays.json"
DOW=$(date +%u)

if [ "$DOW" -ge 6 ]; then
    exit 1
fi

if [ -f "$HOLIDAYS_FILE" ]; then
    python3 -c "
import json, sys
from datetime import datetime
data = json.load(open('$HOLIDAYS_FILE'))
today = datetime.now().strftime('%Y-%m-%d')
for h in data.get('holidays', []):
    if h['date'] == today and '$EXCHANGE' in h.get('market', ''):
        sys.exit(1)
sys.exit(0)
"
    exit $?
fi

exit 0
