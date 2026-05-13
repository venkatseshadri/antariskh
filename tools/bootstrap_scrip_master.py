"""Scrip Master bootstrap — Creates static_metadata.db with scrip_master table.

Run once per day (or after Shoonya master download) to populate the table.
Used by the Contract Specialist (Librarian) for symbol → token → lot_size lookups.

Usage:
    python3 tools/bootstrap_scrip_master.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import duckdb

DB_PATH = Path("/home/trading_ceo/antariksh/data/static_metadata.db")


def init_schema():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH))
    con.execute("""
        CREATE TABLE IF NOT EXISTS scrip_master (
            tsym        VARCHAR PRIMARY KEY,
            token       VARCHAR NOT NULL,
            exchange    VARCHAR NOT NULL,
            symbol      VARCHAR NOT NULL,
            expiry      DATE    NOT NULL,
            strike      DOUBLE  NOT NULL,
            option_type VARCHAR NOT NULL,
            lot_size    INTEGER NOT NULL,
            instrument  VARCHAR NOT NULL,
            imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_scrip_tsym ON scrip_master(tsym)")
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_scrip_lookup "
        "ON scrip_master(symbol, expiry, strike, option_type)"
    )
    con.close()
    print(f"Schema initialized at {DB_PATH}")


def upsert_from_dataframe(df):
    """Upsert records from a pandas DataFrame into scrip_master."""
    con = duckdb.connect(str(DB_PATH))
    con.execute("DELETE FROM scrip_master")

    # Register DataFrame as a virtual table and insert
    con.register("_incoming", df)
    con.execute("""
        INSERT INTO scrip_master (token, tsym, exchange, symbol, expiry, strike, option_type, lot_size, instrument)
        SELECT token::VARCHAR, tsym::VARCHAR, exchange::VARCHAR, symbol::VARCHAR,
               expiry::DATE, strike::DOUBLE, option_type::VARCHAR,
               lot_size::INTEGER, instrument::VARCHAR
        FROM _incoming
    """)
    count = con.execute("SELECT COUNT(*) FROM scrip_master").fetchone()[0]
    con.close()
    print(f"Upserted {count} rows into scrip_master")


def seed_sample():
    """Seed with today's NIFTY weekly contracts (demo — replace with Shoonya master download)."""
    from datetime import datetime, timedelta

    init_schema()

    today = datetime.now()
    days_until_thu = (3 - today.weekday()) % 7
    if days_until_thu == 0 and today.hour >= 15:
        days_until_thu = 7
    expiry_current = today + timedelta(days=days_until_thu)
    expiry_next = expiry_current + timedelta(days=7)

    records = []
    atm = round(23810 / 50) * 50  # Approximate — live would use actual spot

    for expiry in (expiry_current, expiry_next):
        expiry_str = expiry.strftime("%d%b%Y").upper()
        expiry_iso = expiry.strftime("%Y-%m-%d")
        for offset in range(-600, 650, 50):
            for opt in ("CE", "PE"):
                strike = atm + offset
                tsym = f"NIFTY{expiry_str}{strike}{opt}"
                token = str(35000 + abs(offset) // 50 + (0 if opt == "CE" else 200))
                if expiry == expiry_next:
                    token = str(int(token) + 1000)  # Unique tokens for next expiry
                records.append(
                    {
                        "token": token,
                        "tsym": tsym,
                        "exchange": "NFO",
                        "symbol": "NIFTY",
                        "expiry": expiry_iso,
                        "strike": float(strike),
                        "option_type": opt,
                        "lot_size": 65,
                        "instrument": "OPTIDX",
                    }
                )

    import pandas as pd

    df = pd.DataFrame(records)
    upsert_from_dataframe(df)


if __name__ == "__main__":
    seed_sample()
