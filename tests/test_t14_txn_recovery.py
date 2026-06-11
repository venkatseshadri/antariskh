"""T14 validator regression: a failed bar+options txn must not poison the cached conn.

Exercises the REAL feed._persist_bar_and_options (not a reimplementation):
1. happy path writes a bar
2. a commit-time failure triggers rollback (validator hotfix) so the
   NEXT bar on the same cached connection still succeeds — without the
   rollback the conn stays in_transaction and every later bar fails with
   "cannot start a transaction within a transaction".

Run: PYTHONPATH=. python3 -m pytest tests/test_t14_txn_recovery.py -q
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import feed
from config.sqlite_schema import init_market_data_schema, init_option_prices_schema


def _bar(ts):
    return {
        "timestamp": ts,
        "instrument": "NIFTY",
        "open": 23500.0,
        "high": 23510.0,
        "low": 23495.0,
        "close": 23505.0,
        "volume": 100,
    }


class _FailingCommitConn:
    """Delegates to a real conn; commit() raises once."""

    def __init__(self, conn):
        self._conn = conn
        self.fail_next_commit = True

    def execute(self, *a, **kw):
        return self._conn.execute(*a, **kw)

    def commit(self):
        if self.fail_next_commit:
            self.fail_next_commit = False
            raise sqlite3.OperationalError("disk I/O error (injected)")
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()


def test_failed_txn_does_not_poison_cached_conn(tmp_path):
    real = sqlite3.connect(str(tmp_path / "t14.sqlite"))
    real.isolation_level = None
    real.row_factory = sqlite3.Row
    init_market_data_schema(real)
    init_option_prices_schema(real)

    wrapper = _FailingCommitConn(real)
    feed._capture_dbs["NIFTY"] = wrapper
    try:
        # bar 1: commit raises → handler must rollback the open BEGIN IMMEDIATE
        feed._persist_bar_and_options(_bar("2026-06-12T09:15:00"))
        assert not real.in_transaction, "rollback missing — write lock still held"

        # bar 2: same cached conn must work again
        feed._persist_bar_and_options(_bar("2026-06-12T09:16:00"))
        rows = real.execute("SELECT timestamp FROM market_data").fetchall()
        assert [r["timestamp"] for r in rows] == ["2026-06-12T09:16:00"]
    finally:
        feed._capture_dbs.pop("NIFTY", None)
        real.close()
