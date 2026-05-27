#!/bin/bash
# Systemd ExecCondition convention: exit 0 = proceed, exit 1+ = skip.
# Exit 0 = market open (start capture).
# Exit 1 = market closed / holiday / weekend (skip capture).

HOLIDAYS_FILE="/root/.picoclaw/workspace/config/market_holidays.json"
TODAY=$(date +%Y-%m-%d)
DOW=$(date +%u)

if [ "$DOW" -ge 6 ]; then
    exit 1
fi

if [ -f "$HOLIDAYS_FILE" ]; then
    python3 -c "
import json, sys
from datetime import datetime
data = json.load(open('$HOLIDAYS_FILE'))
holidays = {h['date'] for h in data.get('holidays', [])}
if datetime.now().strftime('%Y-%m-%d') in holidays:
    sys.exit(1)
else:
    sys.exit(0)
"
    exit $?
fi

exit 0
