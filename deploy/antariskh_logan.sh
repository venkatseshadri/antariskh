#!/bin/bash
# Kubera /logan skill — on-demand log analysis or return last saved report.
# Usage: /logan         → runs fresh analysis cycle + sends to Telegram
#        /logan last    → returns the last saved report without re-scanning

QUERY="${1:-now}"
REPORT_FILE="/home/trading_ceo/antariksh/logs/last_report.md"

if [ "$QUERY" == "last" ]; then
    if [ -f "$REPORT_FILE" ]; then
        echo "--- Last saved Antariksh Health Report ---"
        echo
        cat "$REPORT_FILE"
    else
        echo "No saved report yet. Try '/logan' to generate one."
    fi
else
    echo "Scanning logs (may take a few seconds)..."
    cd /home/trading_ceo/antariksh && /usr/bin/python3 tools/log_analyzer.py --now 2>&1
fi