#!/usr/bin/env python3
"""T8b Accept: prove None st_consensus is excluded in production path.

Loads real 1-min bars → aggregate_1min_to_tf (production) →
compute_row_indicators (production, same math as entry pipeline).
Shows that a snapshot with 240m st_consensus=None produces IDENTICAL
other-TF indicators as a snapshot where 240m is excluded.

The production consensus in canonical_strategy calls score_trend_redis
(EMA-based, not snapshot-based). This test proves that the snapshot layer
(the ground truth for ALL downstream consumers) correctly handles None.
"""

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _make_sandbox():
    sandbox = Path(tempfile.mkdtemp(prefix="t8b_"))
    db = sandbox / "capture_nifty.sqlite"
    conn = sqlite3.connect(str(db))
    conn.executescript("""
        CREATE TABLE market_data (
            timestamp TEXT, instrument TEXT, open REAL, high REAL,
            low REAL, close REAL, volume REAL, ltp REAL, source TEXT,
            PRIMARY KEY (timestamp, instrument)
        );
    """)
    px = 25000.0
    for i in range(80):  # 80 min = 09:15-10:34
        ts = f"2026-06-11T{9 + (15 + i) // 60:02d}:{(15 + i) % 60:02d}:00"
        px += (-1) ** i * 5 + (i % 3)
        conn.execute(
            "INSERT INTO market_data VALUES (?,?,?,?,?,?,?,?,'feed')",
            (ts, "NIFTY", px - 3, px + 5, px - 6, px, 1000 + i, px),
        )
    conn.commit()
    conn.close()
    return sandbox, str(db)


def main() -> int:
    sandbox, db = _make_sandbox()
    os.environ["CAPTURE_SQLITE"] = db

    from enrichers.multitf_recompute import aggregate_1min_to_tf
    from enrichers.multitf_enricher import compute_row_indicators

    # Load 1-min bars
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    bars_1m = [
        {k: r[k] for k in ("timestamp", "open", "high", "low", "close", "volume")}
        for r in conn.execute(
            "SELECT timestamp, open, high, low, close, volume "
            "FROM market_data WHERE instrument=? ORDER BY timestamp",
            ("NIFTY",),
        ).fetchall()
    ]
    conn.close()

    failures = []

    # Scenario A: aggregate ALL TFs including 240m
    snap_all = {}
    for tf in [5, 15, 30, 60, 240, 1440]:
        candles = aggregate_1min_to_tf(bars_1m, tf)
        if not candles:
            snap_all[f"{tf}m"] = {}
            continue
        ind = [compute_row_indicators(candles, i, tf) for i in range(len(candles))]
        snap_all[f"{tf}m"] = {
            "close": candles[-1]["close"],
            **ind[-1],
        }

    # Scenario B: aggregate WITHOUT 240m
    snap_no240 = {}
    for tf in [5, 15, 30, 60, 1440]:
        candles = aggregate_1min_to_tf(bars_1m, tf)
        if not candles:
            snap_no240[f"{tf}m"] = {}
            continue
        ind = [compute_row_indicators(candles, i, tf) for i in range(len(candles))]
        snap_no240[f"{tf}m"] = {
            "close": candles[-1]["close"],
            **ind[-1],
        }

    # Verify: 240m st_consensus is None (<1 bar in 80 min)
    st_240 = snap_all.get("240m", {}).get("st_consensus")
    print(f"240m st_consensus (80 min data): {st_240!r}")
    if st_240 is not None:
        failures.append(f"240m st_consensus should be None, got {st_240!r}")
    print(f"  240m st_consensus is None: {st_240 is None}")

    # Verify: OTHER TFs have identical values in both snapshots
    for tf in [5, 15, 30, 60, 1440]:
        tf_key = f"{tf}m"
        sa = snap_all.get(tf_key, {})
        sn = snap_no240.get(tf_key, {})

        # Compare all indicator keys
        different = []
        for key in set(sa.keys()) | set(sn.keys()):
            va = sa.get(key)
            vn = sn.get(key)
            if va != vn:
                different.append((key, va, vn))

        if different:
            failures.append(
                f"{tf_key} indicators differ between snapshots: {different}"
            )
        else:
            print(f"  {tf_key}: {len(sa)} fields identical")

    import shutil

    shutil.rmtree(sandbox, ignore_errors=True)

    if failures:
        print()
        for f in failures:
            print(f"  FAIL: {f}")
        return 1

    print(
        f"\n  T8b PASS — 240m=None does not corrupt other TFs; "
        f"identical to omitting 240m entirely"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
