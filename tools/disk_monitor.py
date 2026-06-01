#!/usr/bin/env python3
"""Disk usage monitor — early warning for Year-2 warehouse offload (OQ#4).

Runs every 30 min via cron. Alerts Chairman when `/` partition crosses
80% / 90% / 95% thresholds. De-dups: only re-alerts when crossing a NEW
threshold or when usage drops below current alert level.

Action guide (escalation tree for Chairman when alerts fire):
  80%  — Plan: pick one of (a) compress oldest warehouse months with tar.zst
         (~3x ratio), (b) offload research/ to S3/R2/external, (c) upgrade
         VPS plan, (d) drop research months older than 12mo. 6-8 mo runway.
  90%  — Act: ship one of the above. ~2-3 mo runway.
  95%  — Emergency: stop new writes by suspending consumer-*.service and
         eod_etl cron until offload completes. Data risk imminent.
"""

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.notifications import push_info  # noqa: E402

STATE_FILE = Path("/home/trading_ceo/antariksh/data/disk_monitor_state.json")
THRESHOLDS = [95, 90, 80]  # check high → low; alert at highest crossed


def current_pct(path: str = "/") -> int:
    used = shutil.disk_usage(path)
    return round(used.used / used.total * 100)


def load_last_alert() -> int:
    if not STATE_FILE.exists():
        return 0
    try:
        return int(json.loads(STATE_FILE.read_text()).get("last_alert_pct", 0))
    except Exception:
        return 0


def save_last_alert(pct: int) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps({"last_alert_pct": pct}))


def main() -> int:
    pct = current_pct()
    last = load_last_alert()

    crossed = next((t for t in THRESHOLDS if pct >= t), 0)

    if crossed > last:
        used = shutil.disk_usage("/")
        free_gb = used.free / 1024**3
        msg = (
            f"💾 **Disk alert — {pct}% used** (threshold {crossed}%)\n"
            f"Free: {free_gb:.1f} GB on `/`.\n\n"
            f"Action guide (see disk_monitor.py docstring):\n"
            f"  80% → plan offload (compress / S3 / VPS upgrade)\n"
            f"  90% → ship offload now\n"
            f"  95% → emergency: stop consumer-*.service + EOD ETL"
        )
        push_info(msg)
        save_last_alert(crossed)
        print(f"ALERT {pct}% (crossed {crossed}, prev {last})")
    elif crossed < last:
        save_last_alert(crossed)
        print(f"recovered: {pct}% (was alerting {last})")
    else:
        print(f"ok: {pct}% (alert at {last})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
