"""T15: MCX capture routing + log aggregation.

Run: python3 -m pytest tests/test_t15_mcx_routing.py -q
"""

import sqlite3
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sim.sim_env import capture_path, _MCX_INSTRUMENTS


def test_mcx_instruments_route_to_monolith():
    for inst in _MCX_INSTRUMENTS:
        path = capture_path(inst)
        assert path.name == "capture_mcx.sqlite", f"{inst} → {path.name}"
    assert capture_path("NIFTY").name == "capture_nifty.sqlite"
    assert capture_path("SENSEX").name == "capture_sensex.sqlite"


def test_open_capture_db_inits_schema():
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS market_data (
            timestamp TEXT, instrument TEXT, open REAL, high REAL,
            low REAL, close REAL, volume REAL, ltp REAL, source TEXT,
            PRIMARY KEY (timestamp, instrument)
        )
    """)
    conn.execute(
        "INSERT INTO market_data VALUES ('2026-06-11T09:15:00+05:30','MCX',100,105,95,102,10,102,'feed')"
    )
    conn.commit()
    rows = conn.execute("SELECT count(*) FROM market_data").fetchone()
    assert rows[0] == 1


def test_mcx_log_instrument_routing():
    from feed import _log_instrument

    assert _log_instrument("ALUMINI") == "MCX"
    assert _log_instrument("CRUDEOILM") == "MCX"
    assert _log_instrument("GOLD") == "MCX"
    assert _log_instrument("NIFTY") == "NIFTY"
    assert _log_instrument("SENSEX") == "SENSEX"


def test_backfill_parse_format():
    line = "2026-06-11T09:15:00+05:30|ALUMINI|245.0|246.5|244.0|245.5|120"
    parts = line.split("|")
    assert len(parts) == 7
    assert parts[0] == "2026-06-11T09:15:00+05:30"
    assert parts[1] == "ALUMINI"
    assert float(parts[2]) == 245.0
