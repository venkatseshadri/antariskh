#!/bin/bash
# Check if today is a market holiday or weekend.
# Exit 0 if market closed (service should not start).
# Exit 1 if market open (service should start).

HOLIDAYS_FILE="/root/.picoclaw/workspace/config/market_holidays.json"
TODAY=$(date +%Y-%m-%d)
DOW=$(date +%u)

if [ "$DOW" -ge 6 ]; then
    exit 0
fi

if [ -f "$HOLIDAYS_FILE" ]; then
    python3 -c "
import json, sys
from datetime import datetime
data = json.load(open('$HOLIDAYS_FILE'))
holidays = {h['date'] for h in data.get('holidays', [])}
if datetime.now().strftime('%Y-%m-%d') in holidays:
    sys.exit(0)
else:
    sys.exit(1)
"
    exit $?
fi

exit 1
