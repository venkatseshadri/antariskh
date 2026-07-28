#!/usr/bin/env python3
"""
Redis Queue Tap — snapshot, replay, step-through for debug/testing kickoff.

  Snapshot live queue into a replay queue + disk backup.
  Step-through mode: push one bar at a time, inspect, wait for Enter.
  Play mode: push N bars automatically.
  KICKOFF READS FROM THE REPLAY QUEUE when REPLAY=True env var is set.

Usage:
  python3 tools/redis_tap.py snapshot --index NIFTY    # copy live → replay
  python3 tools/redis_tap.py step --index NIFTY          # step-through
  python3 tools/redis_tap.py play 20 --index NIFTY       # push next 20 bars
  python3 tools/redis_tap.py status --index NIFTY        # show queue state
  python3 tools/redis_tap.py clear --index NIFTY         # clear replay queue

How kickoff reads from replay:
  export REPLAY=true
  python3 kickoff.py --once
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent
SNAPSHOT_DIR = PROJECT_ROOT / "data" / "replay_snapshots"

try:
    import redis
except ImportError:
    print("pip install redis", file=sys.stderr)
    sys.exit(1)

KEY_TPL = "v3_ohlcv_queue_{index}"
REPLAY_KEY_TPL = "v3_ohlcv_queue_{index}_replay"
SNAPSHOT_FILE_TPL = "snapshot_{index}_{date}.json"


def _r():
    return redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)


def cmd_snapshot(index: str):
    r = _r()
    key = KEY_TPL.format(index=index)
    replay_key = REPLAY_KEY_TPL.format(index=index)

    bars = r.lrange(key, 0, -1) or []
    if not bars:
        print(f"[snapshot] {key} is empty — nothing to snapshot")
        return

    # Wipe previous replay queue
    r.delete(replay_key)

    # Push to replay queue (newest first — LPUSH each bar)
    for bar in reversed(bars):
        r.lpush(replay_key, bar)

    # Save to disk
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    snap_file = SNAPSHOT_DIR / SNAPSHOT_FILE_TPL.format(
        index=index, date=datetime.now().strftime("%Y%m%d_%H%M%S")
    )
    snap_file.write_text("\n".join(bars))

    print(f"[snapshot] {len(bars)} bars copied: {key} → {replay_key}")
    print(f"[snapshot] Disk backup: {snap_file}")


def cmd_step(index: str):
    """Interactive step-through: show next bar, push to replay, wait."""
    r = _r()
    snap_files = sorted(SNAPSHOT_DIR.glob(f"snapshot_{index}_*.json"), reverse=True)
    if not snap_files:
        print("[step] No snapshot found — run 'snapshot' first")
        return

    snap_file = snap_files[0]
    bars = [line for line in snap_file.read_text().splitlines() if line.strip()]
    replay_key = REPLAY_KEY_TPL.format(index=index)
    live_key = KEY_TPL.format(index=index)
    pushed = r.llen(replay_key)

    print(f"[step] Snapshot: {snap_file.name} ({len(bars)} bars)")
    print(f"[step] Replay queue: {pushed} bars pushed so far")
    print(f"[step] Live queue: {r.llen(live_key)} bars")
    print(
        f"[step] Press ENTER to push next bar | 'q' to quit | 's N' to skip N | 'live' to switch to live\n"
    )

    while pushed < len(bars):
        bar = json.loads(bars[-1 - pushed])  # reversed: oldest first
        ts = bar.get("timestamp", "")[:19]
        o = bar.get("open", "")
        c = bar.get("close", "")
        print(
            f"[{pushed + 1}/{len(bars)}] {ts} | O:{o} C:{c} → push? ",
            end="",
            flush=True,
        )

        choice = input().strip().lower()
        if choice == "q":
            print(
                f"[step] Quit. {pushed}/{len(bars)} bars pushed. Replay key: {replay_key}"
            )
            return
        if choice.startswith("s"):
            try:
                n = int(choice.split()[1])
                for _ in range(n):
                    if pushed >= len(bars):
                        break
                    bar = json.loads(bars[-1 - pushed])
                    r.lpush(replay_key, json.dumps(bar))
                    pushed += 1
                print(f"[step] Skipped {n} bars → {pushed}/{len(bars)}")
                continue
            except (IndexError, ValueError):
                pass
        if choice == "live":
            print("[step] Switching to live mode — clearing replay queue")
            r.delete(replay_key)
            return

        # Push one bar
        r.lpush(replay_key, json.dumps(bar))
        pushed += 1

    print(f"[step] All {len(bars)} bars replayed to {replay_key}")


def cmd_play(index: str, n: int):
    """Push next N bars from snapshot to replay queue."""
    r = _r()
    snap_files = sorted(SNAPSHOT_DIR.glob(f"snapshot_{index}_*.json"), reverse=True)
    if not snap_files:
        print("[play] No snapshot found — run 'snapshot' first")
        return

    bars = [line for line in snap_files[0].read_text().splitlines() if line.strip()]
    replay_key = REPLAY_KEY_TPL.format(index=index)
    pushed = r.llen(replay_key)

    actual = min(n, len(bars) - pushed)
    for i in range(actual):
        bar = json.loads(bars[-1 - (pushed + i)])
        r.lpush(replay_key, json.dumps(bar))

    print(
        f"[play] Pushed {actual} bars → {pushed + actual}/{len(bars)} in {replay_key}"
    )


def cmd_status(index: str):
    r = _r()
    live_key = KEY_TPL.format(index=index)
    replay_key = REPLAY_KEY_TPL.format(index=index)

    print(f"[status] Live queue ({live_key}): {r.llen(live_key)} bars")
    print(f"[status] Replay queue ({replay_key}): {r.llen(replay_key)} bars")
    latest = r.lindex(replay_key, 0)
    if latest:
        bar = json.loads(latest)
        print(
            f"[status] Latest replay bar: {bar.get('timestamp', '')[:19]} | O:{bar.get('open')} C:{bar.get('close')}"
        )


def cmd_clear(index: str):
    r = _r()
    replay_key = REPLAY_KEY_TPL.format(index=index)
    r.delete(replay_key)
    print(f"[clear] Replay queue cleared: {replay_key}")


def main():
    parser = argparse.ArgumentParser(
        description="Redis Queue Tap — step-through replay for kickoff debug"
    )
    parser.add_argument(
        "command", choices=["snapshot", "step", "play", "status", "clear"]
    )
    parser.add_argument("arg", nargs="?", type=str, default="")
    parser.add_argument("--index", default="NIFTY", choices=["NIFTY", "SENSEX"])
    args = parser.parse_args()

    cmds = {
        "snapshot": cmd_snapshot,
        "step": cmd_step,
        "status": cmd_status,
        "clear": cmd_clear,
    }

    if args.command == "play":
        n = int(args.arg) if args.arg.isdigit() else 5
        cmd_play(args.index, n)
    elif args.command in cmds:
        cmds[args.command](args.index)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
