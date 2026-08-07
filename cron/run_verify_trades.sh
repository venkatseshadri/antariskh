#!/bin/bash
# Post-market trade verification — cross-checks every ATOM record against the
# live capture DB's option_prices (Penguin's feed table, NOT ATOM's own path),
# logs results to "ATOM Trade Validation Ledger" Google Sheet for human review.
#
# One row per leg, per position, per day. Runs once after market close, ~15:32.
# Installed in root crontab (same user that owns atom_state.sqlite).

set -e
cd /home/trading_ceo/antariksh
/usr/bin/python3 verify_trades.py && /usr/bin/python3 verify_sheets.py
