#!/usr/bin/env bash
# PORCUPINE — boot/stop an isolated test redis-server for sim runs.
#   start_test_redis.sh start <SIM_ROOT> [port]
#   start_test_redis.sh stop  <SIM_ROOT> [port]
# The test instance is fully separate from production redis (6379): own port,
# own dir, no persistence. FLUSHALL-safe — it holds only sim data.
set -euo pipefail

ACTION="${1:?usage: start|stop <SIM_ROOT> [port]}"
SIM_ROOT="${2:?SIM_ROOT required}"
PORT="${3:-6380}"
REDIS_DIR="$SIM_ROOT/redis"
PIDFILE="$REDIS_DIR/redis.pid"

mkdir -p "$REDIS_DIR"

case "$ACTION" in
  start)
    redis-server \
      --port "$PORT" \
      --dir "$REDIS_DIR" \
      --save "" \
      --appendonly no \
      --pidfile "$PIDFILE" \
      --daemonize yes \
      --bind 127.0.0.1
    sleep 0.3
    redis-cli -p "$PORT" ping
    echo "test redis up on port $PORT (dir=$REDIS_DIR)"
    ;;
  stop)
    if [ -f "$PIDFILE" ]; then
      redis-cli -p "$PORT" shutdown nosave 2>/dev/null || kill "$(cat "$PIDFILE")" 2>/dev/null || true
      echo "test redis on $PORT stopped"
    else
      echo "no pidfile at $PIDFILE — nothing to stop"
    fi
    ;;
  *) echo "unknown action: $ACTION"; exit 1 ;;
esac
