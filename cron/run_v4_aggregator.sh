#!/bin/bash
# Wrapper for v4 Multi-TF Aggregator (run from cron every 5 min).
#
# Idempotent failsafe: the aggregator is a long-running daemon, not a batch
# job. It has no internal singleton guard, so a bare 5-min cron stacked one
# fresh daemon per tick (7+ duplicates draining the same redis queue,
# 2026-05-26 leak). v4 now runs ONE process per index, each writing its own
# per-index DuckDB. Gate on a PER-INDEX command-pattern liveness check — same
# approach as run_data_capture_with_v4.sh's v4_alive() — and start only the
# index(es) not currently alive. Backgrounded so this wrapper returns promptly.

cd /home/trading_ceo/antariksh

LOG_DIR=/home/trading_ceo/antariksh/logs
mkdir -p "$LOG_DIR"

for index in NIFTY SENSEX; do
    if pgrep -f "data_capture_v4_queue_aggregator.py --index $index" >/dev/null 2>&1; then
        echo "[$(date)] v4 $index already running, skipping"
        continue
    fi
    echo "[$(date)] No v4 $index alive, starting one"
    nohup python3 data_capture_v4_queue_aggregator.py --index "$index" \
        >> "$LOG_DIR/v4_${index,,}.log" 2>&1 &
done
