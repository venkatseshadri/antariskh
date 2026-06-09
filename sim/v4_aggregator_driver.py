"""PORCUPINE v4-aggregator driver — runs INSIDE the sandbox (SIM_MODE + test
Redis + BRAHMAND_SANDBOX), driving the REAL data_capture_v4_queue_aggregator
end-to-end so the bug #3b SuperTrend fix is validated on the path the trend agent
actually reads (the v4 per-index DuckDB), not just in a unit test.

Flow:
  1. read real 1-min bars from a capture sqlite (read-only),
  2. RPUSH them onto v3_ohlcv_queue_<INDEX> in the TEST Redis (prod key shape),
  3. construct MultiTFAggregatorQueue pointed at a SANDBOX per-index DuckDB and
     run_all_timeframes() — its Redis + log_dir + EMA state all resolve to the
     sandbox (SIM_MODE / BRAHMAND_SANDBOX), so nothing live is touched,
  4. print a JSON verdict: distinct st_consensus values per timeframe.

Refuses to run outside SIM_MODE.
"""
import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

if os.environ.get("SIM_MODE") != "1":
    raise SystemExit("REFUSING: SIM_MODE!=1 — v4_aggregator_driver only drives the sandbox.")

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), "/home/trading_ceo/brahmand"):
    if p not in sys.path:
        sys.path.insert(0, p)

import redis  # noqa: E402
from sim.sim_env import redis_kwargs, sim_root  # noqa: E402
from data_capture_v4_queue_aggregator import MultiTFAggregatorQueue  # noqa: E402


def _load_1min(src_db: str, instrument: str, date: str) -> list:
    con = sqlite3.connect(f"file:{src_db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT timestamp, open, high, low, close, volume FROM market_data "
        "WHERE instrument = ? AND substr(timestamp,1,10) = ? ORDER BY timestamp",
        (instrument, date),
    ).fetchall()
    con.close()
    return [
        {"index": instrument, "timestamp": r["timestamp"], "open": r["open"],
         "high": r["high"], "low": r["low"], "close": r["close"],
         "volume": r["volume"] or 0}
        for r in rows
    ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-db", required=True)
    ap.add_argument("--date", required=True)
    ap.add_argument("--index", default="NIFTY")
    a = ap.parse_args()

    bars = _load_1min(a.source_db, a.index, a.date)

    r = redis.Redis(**redis_kwargs())
    qkey = f"v3_ohlcv_queue_{a.index}"
    r.delete(qkey)
    if bars:
        r.rpush(qkey, *[json.dumps(b) for b in bars])

    db_path = str(sim_root() / "data" / f"market_data_multitf_{a.index.lower()}.duckdb")
    agg = MultiTFAggregatorQueue(duckdb_path=db_path, verbose=False)
    agg.run_all_timeframes(index_name=a.index)

    import duckdb
    con = duckdb.connect(db_path, read_only=True)
    out = {}
    for tf in (5, 15, 30, 60):
        rows = con.execute(
            "SELECT st_consensus, COUNT(*) FROM market_data_multitf "
            "WHERE timeframe_min = ? GROUP BY st_consensus", [tf]
        ).fetchall()
        out[tf] = {k: v for k, v in rows}
    con.close()

    print("V4_RESULT " + json.dumps({"bars": len(bars), "by_tf": out}))


if __name__ == "__main__":
    main()
