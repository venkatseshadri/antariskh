"""Scrip Master bootstrap — Creates static_metadata.db with scrip_master table.

Run once per day (pre-open, before feed cold-start) to rebuild the table from the
real Shoonya NFO/BFO master dump. Used by the Contract Specialist (Librarian) and
by ATOM Module 12 for symbol -> token -> lot_size lookups.

Usage:
    python3 tools/bootstrap_scrip_master.py
"""

import csv
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import duckdb

from config.token_resolver import MASTER_DIR, _download_master

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


def _rows_from_master(exchange: str, symbol_name: str, keep) -> list:
    """Parse one broker master file, keep only OPTIDX rows `keep(row)` accepts."""
    path = MASTER_DIR / f"{exchange}_symbols.txt"
    if not path.exists():
        _download_master(exchange)
    records = []
    with open(path) as f:
        for row in csv.DictReader(f):
            if row.get("Instrument") != "OPTIDX" or not keep(row):
                continue
            try:
                expiry = datetime.strptime(row["Expiry"], "%d-%b-%Y").date().isoformat()
            except (ValueError, KeyError):
                continue
            records.append(
                {
                    "token": row.get("Token", ""),
                    "tsym": row.get("TradingSymbol", ""),
                    "exchange": exchange,
                    "symbol": symbol_name,
                    "expiry": expiry,
                    "strike": float(row.get("StrikePrice", 0) or 0),
                    "option_type": row.get("OptionType", ""),
                    "lot_size": int(row.get("LotSize", 0) or 0),
                    "instrument": "OPTIDX",
                }
            )
    return records


def build_from_broker_master():
    """Real NIFTY + SENSEX index-option contracts from the Shoonya NFO/BFO master
    dump (master-as-truth) — token/expiry/strike/lot_size all come from the broker
    file itself, never hardcoded. Same filter rules as
    config/token_resolver.py:_broker_weekly_expiries (NIFTY excludes NIFTYNXT;
    SENSEX = BFO Symbol=='BSXOPT', not the SENSEX50 stock-option series)."""
    import pandas as pd

    nifty = _rows_from_master(
        "NFO",
        "NIFTY",
        lambda r: r.get("TradingSymbol", "").upper().startswith("NIFTY")
        and not r.get("TradingSymbol", "").upper().startswith("NIFTYNXT"),
    )
    sensex = _rows_from_master("BFO", "SENSEX", lambda r: r.get("Symbol") == "BSXOPT")
    return pd.DataFrame(nifty + sensex)


def refresh():
    """Daily pre-open entrypoint: re-download today's master (if not already fresh),
    rebuild scrip_master from it. Fails loudly on an empty result rather than
    silently leaving stale/no data."""
    _download_master("NFO")
    _download_master("BFO")
    init_schema()
    df = build_from_broker_master()
    if df.empty:
        raise SystemExit("scrip_master build produced 0 rows — check master files/filters")
    upsert_from_dataframe(df)


if __name__ == "__main__":
    refresh()
