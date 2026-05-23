#!/usr/bin/env python3
"""
Daily log cleanup — keep last 7 days, truncate ralph_scheduler (append-only spam).
Called by cron: @daily python3 /home/trading_ceo/antariksh/tools/log_cleanup.py
"""

import os
from pathlib import Path
from datetime import datetime, timedelta

LOG_DIRS = [
    Path("/home/trading_ceo/antariksh/logs"),
    Path("/home/trading_ceo/brahmand/logs"),
]

# Files that tend to balloon — truncate to last 10,000 lines instead of deleting
TRUNCATE_PATTERNS = ["ralph_scheduler", "dispatch_", "log_analyzer"]

THRESHOLD_MB = 50
MAX_LINES = 10_000
KEEP_DAYS = 7
cutoff = datetime.now() - timedelta(days=KEEP_DAYS)


def cleanup_dir(log_dir: Path):
    if not log_dir.exists():
        return

    for f in sorted(log_dir.glob("*.log")):
        try:
            size_mb = f.stat().st_size / (1024 * 1024)
            should_truncate = any(p in f.name for p in TRUNCATE_PATTERNS)

            if should_truncate and size_mb > THRESHOLD_MB:
                # Truncate large append-only logs
                lines = f.read_text(errors="ignore").splitlines()
                if len(lines) > MAX_LINES:
                    f.write_text("\n".join(lines[-MAX_LINES:]) + "\n")
                    print(f"  Truncated {f.name}: {len(lines)} → {MAX_LINES} lines")
            else:
                # Delete old files beyond KEEP_DAYS
                mtime = datetime.fromtimestamp(f.stat().st_mtime)
                if mtime < cutoff:
                    f.unlink()
                    print(f"  Deleted old: {f.name} ({mtime.strftime('%Y-%m-%d')})")
        except Exception as e:
            print(f"  Skip {f.name}: {e}")


if __name__ == "__main__":
    print(f"Log cleanup — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    for d in LOG_DIRS:
        print(f"  {d}")
        cleanup_dir(d)
    print("Done")
