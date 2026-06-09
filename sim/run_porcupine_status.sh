#!/usr/bin/env bash
# PORCUPINE build-progress nag — deterministic, token-free (no LLM/claude).
# Sends to Telegram only when build status changes. Cron: every 30 min.
set -uo pipefail
cd /home/trading_ceo/antariksh || exit 1
/usr/bin/python3 -m sim.porcupine_status --send >> sim/logs/porcupine_status.log 2>&1
