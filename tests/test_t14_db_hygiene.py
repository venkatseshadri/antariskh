"""T14: DB-hygiene — staleness guard + SENSEX weekly filter.

Run: python3 -m pytest tests/test_t14_db_hygiene.py -q
"""

import re
import sqlite3
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))


def test_staleness_guard_rejects_old_data():
    def read_option_prices_from_db(conn, bar_ts):
        rows = conn.execute(
            "SELECT tsym, strike, option_type, ltp, oi, timestamp "
            "FROM option_prices ORDER BY timestamp DESC LIMIT 300"
        ).fetchall()
        if not rows:
            return []
        latest_ts_str = rows[0]["timestamp"]
        bar_dt = datetime.fromisoformat(bar_ts)
        latest_dt = datetime.fromisoformat(latest_ts_str)
        if (bar_dt - latest_dt) > timedelta(minutes=3):
            return []
        result = []
        for r in rows:
            if r["timestamp"] != latest_ts_str:
                continue
            result.append(dict(r))
        return result

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE option_prices (tsym TEXT, strike INTEGER, option_type TEXT,
            ltp REAL, oi REAL, timestamp TEXT, PRIMARY KEY (tsym, timestamp))
    """)
    conn.execute(
        "INSERT INTO option_prices VALUES ('NIFTY16JUN26C23200',23200,'CE',221.5,1000,'2026-06-12T09:15:00+05:30')"
    )
    conn.execute(
        "INSERT INTO option_prices VALUES ('NIFTY16JUN26P23200',23200,'PE',180.0,1200,'2026-06-12T09:15:00+05:30')"
    )
    conn.commit()

    # Fresh bar (1 min after option data) — stale but within 3 min
    fresh_ts = "2026-06-12T09:16:00+05:30"
    result = read_option_prices_from_db(conn, fresh_ts)
    assert len(result) == 2, f"Fresh data should return 2 rows, got {len(result)}"

    # Stale bar (10 min after option data)
    stale_ts = "2026-06-12T09:26:00+05:30"
    result = read_option_prices_from_db(conn, stale_ts)
    assert len(result) == 0, "Stale guard should return empty"

    # Within 3 min window
    edge_ts = "2026-06-12T09:18:00+05:30"
    result = read_option_prices_from_db(conn, edge_ts)
    assert len(result) == 2, "Edge within 3 min should return data"


def test_sensex_weekly_filter_excludes_monthly():
    _monthly_rx = re.compile(r"^SENSEX\d{2}[A-Z]{3}\d+[CP][PE]$")

    # Weekly: SENSEX{YY}{M}{DD}{strike}{CE/PE}
    weekly = "SENSEX2660975500PE"
    assert not _monthly_rx.match(weekly)

    weekly2 = "SENSEX2660975000CE"
    assert not _monthly_rx.match(weekly2)

    # Monthly: SENSEX{YY}{Mmm}{strike}{CE/PE}
    monthly = "SENSEX26JUN75800PE"
    assert _monthly_rx.match(monthly)

    monthly2 = "SENSEX26JUN76000CE"
    assert _monthly_rx.match(monthly2)

    # NIFTY — never matches monthly pattern
    nifty = "NIFTY16JUN26C23200"
    assert not _monthly_rx.match(nifty)


def test_sensex_filter_in_full_flow():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE option_prices (tsym TEXT, strike INTEGER, option_type TEXT,
            ltp REAL, oi REAL, timestamp TEXT, PRIMARY KEY (tsym, timestamp))
    """)
    bar_ts = "2026-06-12T09:15:00+05:30"
    # Weekly SENSEX
    conn.execute(
        "INSERT INTO option_prices VALUES ('SENSEX2660975500PE',75500,'PE',180.0,1000,?)",
        (bar_ts,),
    )
    conn.execute(
        "INSERT INTO option_prices VALUES ('SENSEX2660975000CE',75000,'CE',200.0,800,?)",
        (bar_ts,),
    )
    # Monthly SENSEX — should be filtered out
    conn.execute(
        "INSERT INTO option_prices VALUES ('SENSEX26JUN75800PE',75800,'PE',250.0,500,?)",
        (bar_ts,),
    )
    conn.execute(
        "INSERT INTO option_prices VALUES ('SENSEX26JUN76000CE',76000,'CE',150.0,600,?)",
        (bar_ts,),
    )
    conn.commit()

    _monthly_rx = re.compile(r"^SENSEX\d{2}[A-Z]{3}\d+[CP][PE]$")

    rows = conn.execute(
        "SELECT tsym, strike, option_type, ltp, oi, timestamp "
        "FROM option_prices ORDER BY timestamp DESC LIMIT 300"
    ).fetchall()

    result = []
    latest_ts = rows[0]["timestamp"]
    for r in rows:
        if r["timestamp"] != latest_ts:
            continue
        if _monthly_rx.match(r["tsym"]):
            continue
        result.append(dict(r))

    assert len(result) == 2, f"Expected 2 weekly rows, got {len(result)}"
    tsyms = {r["tsym"] for r in result}
    assert "SENSEX2660975500PE" in tsyms
    assert "SENSEX2660975000CE" in tsyms
    assert "SENSEX26JUN75800PE" not in tsyms
