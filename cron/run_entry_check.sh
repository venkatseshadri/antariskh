#!/bin/bash
cd /home/trading_ceo/antariksh
/usr/bin/python3 -m agents.entry.entry_check >> logs/entry_check_$(date +%Y%m%d).log 2>&1
