"""T12: per-strike option premium persistence — append-only time series.

Run: python3 -m pytest tests/test_t12_option_premiums.py -q
"""

import sqlite3
import tempfile
from pathlib import Path

from config.sqlite_schema import init_option_prices_schema


def _make_opt(tsym, strike, otype, ltp, ts):
    return {
        "tsym": tsym,
        "strike": strike,
        "option_type": otype,
        "oi": 100,
        "volume": 10,
        "ltp": ltp,
        "iv": 14.5,
    }


def _persist(conn, option_data, bar_ts):
    for opt in option_data:
        ltp = opt.get("ltp")
        if not ltp or ltp <= 0:
            continue
        try:
            conn.execute(
                """INSERT OR IGNORE INTO option_prices
                   (tsym, strike, option_type, ltp, oi, volume, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    opt["tsym"],
                    opt["strike"],
                    opt["option_type"],
                    ltp,
                    opt.get("oi"),
                    opt.get("volume"),
                    bar_ts,
                ),
            )
        except sqlite3.Error:
            pass


def test_schema_composite_pk_fresh_table():
    conn = sqlite3.connect(":memory:")
    init_option_prices_schema(conn)

    pk = conn.execute("PRAGMA table_info(option_prices)").fetchall()
    pk_names = [r[1] for r in pk if r[5] > 0]
    assert sorted(pk_names) == ["timestamp", "tsym"], (
        f"Expected composite PK, got {pk_names}"
    )


def test_schema_migration_from_old_pk():
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE option_prices (
            tsym TEXT PRIMARY KEY, strike INTEGER, option_type TEXT,
            ltp REAL, oi REAL, volume REAL, timestamp TEXT NOT NULL
        )
    """)
    conn.execute(
        "INSERT INTO option_prices VALUES ('NIFTY16JUN26C23200',23200,'CE',221.5,1000,50,'2026-06-11T09:15:00')"
    )
    conn.commit()

    init_option_prices_schema(conn)

    pk = conn.execute("PRAGMA table_info(option_prices)").fetchall()
    pk_names = [r[1] for r in pk if r[5] > 0]
    assert sorted(pk_names) == ["timestamp", "tsym"], f"Migration failed, PK={pk_names}"

    rows = conn.execute("SELECT * FROM option_prices").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "NIFTY16JUN26C23200"
    conn.close()


def test_append_only_same_tsym_different_bars():
    conn = sqlite3.connect(":memory:")
    init_option_prices_schema(conn)

    opt = _make_opt("NIFTY16JUN26C23200", 23200, "CE", 221.5, "T1")
    _persist(conn, [opt], "2026-06-12T09:15:00+05:30")

    opt["ltp"] = 225.0
    _persist(conn, [opt], "2026-06-12T09:16:00+05:30")

    opt["ltp"] = 219.8
    _persist(conn, [opt], "2026-06-12T09:17:00+05:30")

    rows = conn.execute(
        "SELECT ltp, timestamp FROM option_prices WHERE tsym='NIFTY16JUN26C23200' ORDER BY timestamp"
    ).fetchall()
    assert len(rows) == 3, f"Expected 3 rows for same tsym, got {len(rows)}"
    assert [r[0] for r in rows] == [221.5, 225.0, 219.8]
    assert rows[0][1] < rows[1][1] < rows[2][1], (
        "Timestamps must be monotonically increasing"
    )


def test_ignore_duplicate_tsym_timestamp():
    conn = sqlite3.connect(":memory:")
    init_option_prices_schema(conn)

    opt = _make_opt("NIFTY16JUN26C23200", 23200, "CE", 221.5, "T1")
    _persist(conn, [opt], "2026-06-12T09:15:00+05:30")

    opt["ltp"] = 999.9
    _persist(conn, [opt], "2026-06-12T09:15:00+05:30")

    rows = conn.execute(
        "SELECT ltp FROM option_prices WHERE tsym='NIFTY16JUN26C23200'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == 221.5, (
        f"INSERT OR IGNORE should keep first value, got {rows[0][0]}"
    )


def test_ltp_guard_rejects_zero_and_none():
    conn = sqlite3.connect(":memory:")
    init_option_prices_schema(conn)

    good = _make_opt("NIFTY16JUN26C23200", 23200, "CE", 100.0, "T1")
    zero = _make_opt("NIFTY16JUN26C23000", 23000, "PE", 0.0, "T2")
    none_ltp = _make_opt("NIFTY16JUN26C23400", 23400, "CE", None, "T3")
    neg = _make_opt("NIFTY16JUN26C23600", 23600, "PE", -5.0, "T4")

    _persist(conn, [good, zero, none_ltp, neg], "2026-06-12T09:15:00+05:30")

    rows = conn.execute("SELECT tsym, ltp FROM option_prices ORDER BY tsym").fetchall()
    assert len(rows) == 1, f"Expected 1 row (only good), got {len(rows)}"
    assert rows[0][0] == "NIFTY16JUN26C23200"
    assert rows[0][1] == 100.0


def test_full_bar_22_quotes():
    conn = sqlite3.connect(":memory:")
    init_option_prices_schema(conn)

    chain = []
    atm = 23200
    for i in range(-5, 6):
        strike = atm + i * 50
        for otype, cp in [("CE", "C"), ("PE", "P")]:
            tsym = f"NIFTY16JUN26{cp}{strike:05d}"
            ltp = 100 + abs(i) * 10 + (10 if otype == "CE" else 5)
            chain.append(_make_opt(tsym, strike, otype, ltp, "T1"))

    assert len(chain) == 22

    _persist(conn, chain, "2026-06-12T09:15:00+05:30")
    _persist(conn, chain, "2026-06-12T09:16:00+05:30")
    _persist(conn, chain, "2026-06-12T09:17:00+05:30")

    total = conn.execute("SELECT count(*) FROM option_prices").fetchone()[0]
    per_bar = conn.execute(
        "SELECT count(*) FROM option_prices WHERE timestamp='2026-06-12T09:15:00+05:30'"
    ).fetchone()[0]
    assert total == 66, f"Expected 66 rows (22 × 3 bars), got {total}"
    assert per_bar == 22

    zero_ltp = conn.execute(
        "SELECT count(*) FROM option_prices WHERE ltp <= 0"
    ).fetchone()[0]
    assert zero_ltp == 0
