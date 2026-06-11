#!/bin/bash
# DAMBUILDER Phase A step 1-2: install the multi-TF enricher shadow units.
# RUN AFTER MARKET CLOSE ONLY (per the cutover doc: no capture changes mid-session).
# Shadow-only: writes indicator columns nobody reads yet; v4 aggregator untouched.
set -euo pipefail

HH=$(TZ=Asia/Kolkata date +%H%M)
DOW=$(TZ=Asia/Kolkata date +%u)
if [ "$DOW" -le 5 ] && [ "$HH" -ge 0900 ] && [ "$HH" -le 1535 ]; then
    echo "REFUSING: market session window (IST $HH). Install after 15:35."
    exit 1
fi

cd "$(dirname "$0")"
for f in multitf-enricher-nifty multitf-enricher-sensex; do
    sudo cp "$f.service" "$f.timer" /etc/systemd/system/
done
sudo systemctl daemon-reload
sudo systemctl enable multitf-enricher-nifty.timer multitf-enricher-sensex.timer
echo "Installed + enabled. First start: next trading day 09:15 IST."
echo "Watch: tail -f ~/antariksh/logs/multitf_enricher_nifty.log"
echo "Parity check after the session:"
echo "  python3 ~/antariksh/enrichers/multitf_parity_check.py --date \$(date +%F)"
