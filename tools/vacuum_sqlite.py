#!/usr/bin/env python3
"""VACUUM per-instrument SQLite files to reclaim disk space after deletes.

Cron: 0 2 * * 6  (Saturday 02:00 — outside all market hours)

VACUUM holds an exclusive lock for the duration. On a 4 GB file with SSD
this takes ~30s. Safe because no consumers or enrichers run on Saturday.

Usage:
    python tools/vacuum_sqlite.py
"""

import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.sqlite_schema import get_sqlite_capture_path

INSTRUMENTS = ["NIFTY", "SENSEX", "MCX"]


def vacuum_instrument(instrument: str):
    path = get_sqlite_capture_path(instrument)
    if not path.exists():
        print(f"[{instrument}] {path} not found — skipping")
        return

    size_before = path.stat().st_size
    conn = sqlite3.connect(str(path))
    conn.execute("VACUUM")
    conn.close()
    size_after = path.stat().st_size

    saved_mb = (size_before - size_after) / (1024 * 1024)
    after_mb = size_after / (1024 * 1024)
    print(f"[{instrument}] {after_mb:.1f} MB (reclaimed {saved_mb:.1f} MB)")


def main():
    for inst in INSTRUMENTS:
        try:
            vacuum_instrument(inst)
        except Exception as e:
            print(f"[{inst}] ERROR: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
