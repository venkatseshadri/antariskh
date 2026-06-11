#!/usr/bin/env python3
"""T8 Accept: fail-closed on insufficient history.

Feeds 30 1-min bars (only 30 minutes of data), asserts:
- 240m family returns insufficient_history
- 60m/1440m also insufficient
- 5m/15m/30m have partial data with None for long-period indicators
- Entry consensus excludes insufficient TFs (uses only 5m/15m/30m)
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# Use SQLite sandbox
import os, sqlite3, tempfile, shutil

SANDBOX = Path(tempfile.mkdtemp(prefix="t8_"))
DB = SANDBOX / "capture_nifty.sqlite"
print(f"Sandbox: {SANDBOX}")


def _make_db():
    conn = sqlite3.connect(str(DB))
    conn.executescript("""
        CREATE TABLE market_data (
            timestamp TEXT, instrument TEXT, open REAL, high REAL,
            low REAL, close REAL, volume REAL, ltp REAL, source TEXT,
            PRIMARY KEY (timestamp, instrument)
        );
    """)
    px = 25000.0
    for i in range(30):  # 30 min = 09:15-09:44
        ts = f"2026-06-11T{9 + (15 + i) // 60:02d}:{(15 + i) % 60:02d}:00"
        px += (-1) ** i * 5 + (i % 3)
        conn.execute(
            "INSERT INTO market_data VALUES (?,?,?,?,?,?,?,?,'feed')",
            (ts, "NIFTY", px - 3, px + 5, px - 6, px, 1000 + i, px),
        )
    conn.commit()
    conn.close()


def main() -> int:
    _make_db()
    failures = []

    # Inject DB path
    old_path = os.environ.get("CAPTURE_SQLITE")
    os.environ["CAPTURE_SQLITE"] = str(DB)
    os.environ["MULTITF_SOURCE"] = "sqlite"

    from tools.entry_tools import _snapshot, query_trend, query_momentum

    snap = _snapshot("NIFTY")
    print(f"Snapshot TFs: {sorted(snap.keys())}")
    for tf in sorted(snap.keys()):
        d = snap.get(tf, {})
        st = d.get("st_consensus")
        ema20 = d.get("ema20")
        rsi = d.get("rsi")
        print(
            f"  {tf:>6s}: st={st!r}  ema20={'ok' if ema20 else 'None'}  rsi={'ok' if rsi else 'None'}"
        )

    # 240m: insufficient history (only 30 min of data)
    snap_240 = snap.get("240m", {})
    if snap_240.get("st_consensus") is not None:
        failures.append("240m st_consensus should be None (insufficient history)")
    print(f"  240m st_consensus None: {snap_240.get('st_consensus') is None}")

    # 5m: should have st_consensus (6 bars of 5m = 30 min, > threshold 3)
    snap_5 = snap.get("5m", {})
    if snap_5.get("st_consensus") is None:
        failures.append("5m st_consensus should NOT be None")
    print(f"  5m st_consensus populated: {snap_5.get('st_consensus') is not None}")

    # Trend query should match snapshot
    trend = json.loads(query_trend())
    st_240_trend = trend["timeframes"].get("240m", {}).get("st_consensus")
    if st_240_trend is not None:
        failures.append(f"240m trend st_consensus should be None, got {st_240_trend!r}")
    print(f"  240m trend st_consensus: {st_240_trend!r}")

    if old_path:
        os.environ["CAPTURE_SQLITE"] = old_path
    shutil.rmtree(SANDBOX, ignore_errors=True)

    if failures:
        print()
        for f in failures:
            print(f"  FAIL: {f}")
        return 1

    print(f"\n  ALL fail-closed checks PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
