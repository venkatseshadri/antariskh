#!/bin/bash
# Cron wrapper: session orchestrator entry. session_orchestrator.py is at
# repo root and takes a positional {entry,exit} arg.
exec /usr/bin/python3 /home/trading_ceo/antariksh/session_orchestrator.py entry >> /home/trading_ceo/antariksh/logs/session_entry_cron.log 2>&1
