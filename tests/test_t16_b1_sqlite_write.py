"""T16-B1: _write_1min_sqlite integration — bar dict writes to DB, contract column populated.

Run: python3 -m pytest tests/test_t16_b1_sqlite_write.py -q
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from feed import _write_1min_sqlite, _INSTRUMENT_CONTRACT


def test_write_1min_sqlite_bar_lands(tmp_path):
    # Hijack _get_capture_db + _INSTRUMENT_CONTRACT
    db_path = tmp_path / "test_capture.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE market_data (
            timestamp TEXT, instrument TEXT, open REAL, high REAL,
            low REAL, close REAL, volume REAL, ltp REAL, source TEXT,
            contract TEXT, PRIMARY KEY (timestamp, instrument))
    """)
    conn.commit()
    conn.close()

    import feed

    orig = feed._get_capture_db
    feed._get_capture_db = lambda inst: sqlite3.connect(str(db_path))
    _INSTRUMENT_CONTRACT["GOLD"] = "GOLDPETAL30JUN26"

    try:
        bar = {
            "timestamp": "2026-06-12T09:15:00+05:30",
            "instrument": "GOLD",
            "open": 7500.0,
            "high": 7520.0,
            "low": 7490.0,
            "close": 7515.0,
            "volume": 100,
            "ltp": 7515.0,
        }
        _write_1min_sqlite(bar)
    finally:
        feed._get_capture_db = orig

    c = sqlite3.connect(str(db_path))
    c.row_factory = sqlite3.Row
    row = c.execute("SELECT * FROM market_data").fetchone()
    assert row is not None, "No row written"
    assert row["instrument"] == "GOLD"
    assert row["contract"] == "GOLDPETAL30JUN26", (
        f"Expected GOLDPETAL30JUN26 in contract, got {row['contract']}"
    )
    assert row["close"] == 7515.0
    c.close()
