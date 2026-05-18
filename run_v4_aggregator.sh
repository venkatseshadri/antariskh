#!/bin/bash
# Wrapper for v4 Multi-TF Aggregator (run from cron every 5 min)

cd /home/trading_ceo/antariksh
python3 data_capture_v4_queue_aggregator.py >> logs/v4_aggregator.log 2>&1
