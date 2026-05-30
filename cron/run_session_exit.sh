#!/bin/bash
# Cron wrapper: session orchestrator exit. session_orchestrator.py is at
# repo root and takes a positional {entry,exit} arg.
exec /usr/bin/python3 /home/trading_ceo/antariksh/session_orchestrator.py exit >> /home/trading_ceo/antariksh/logs/session_exit_cron.log 2>&1
