"""SQLite schema module for per-instrument capture databases.

Mirrors DuckDB schema where applicable. SQLite WAL allows concurrent
reader + writer access — no lock contention across processes.

Usage:
    from config.sqlite_schema import open_capture_db, init_schemas
    conn = open_capture_db("NIFTY")
    init_schemas(conn)
"""

import sqlite3
from pathlib import Path

_DATA_DIR = Path("/home/trading_ceo/python-trader/varaha/data")


def get_sqlite_capture_path(instrument: str) -> Path:
    return _DATA_DIR / f"capture_{instrument.lower()}.sqlite"


def open_capture_db(instrument: str) -> sqlite3.Connection:
    """Open per-instrument SQLite with WAL, NORMAL sync, busy_timeout."""
    path = get_sqlite_capture_path(instrument)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.row_factory = sqlite3.Row
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    if mode.lower() != "wal":
        conn.close()
        raise RuntimeError(f"SQLite WAL not enabled — got '{mode}' for {path}")
    return conn


def init_market_data_schema(conn: sqlite3.Connection):
    """Raw OHLCV bar table — one row per instrument per minute."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS market_data (
            timestamp   TEXT NOT NULL,
            instrument  TEXT NOT NULL,
            open        REAL,
            high        REAL,
            low         REAL,
            close       REAL,
            volume      REAL,
            ltp         REAL,
            source      TEXT DEFAULT 'feed',
            PRIMARY KEY (timestamp, instrument)
        )
    """)
    conn.commit()


def init_multitf_schema(conn: sqlite3.Connection):
    """Multi-TF aggregated indicator table — mirrors market_data_multitf schema."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS market_data_multitf (
            timestamp       TEXT NOT NULL,
            instrument      TEXT NOT NULL,
            timeframe_min   INTEGER NOT NULL,

            open            REAL,
            high            REAL,
            low             REAL,
            close           REAL,
            volume          REAL,

            sma20           REAL,
            sma50           REAL,
            sma200          REAL,
            rsi             REAL,
            atr             REAL,
            macd            REAL,
            macd_signal     REAL,
            macd_histogram  REAL,

            adx             REAL,
            di_plus         REAL,
            di_minus        REAL,
            bb_upper        REAL,
            bb_middle       REAL,
            bb_lower        REAL,
            obv             REAL,
            cmf             REAL,
            cci             REAL,

            st_consensus    TEXT,

            PRIMARY KEY (timestamp, instrument, timeframe_min)
        )
    """)
    conn.commit()


def init_consumer_state(conn: sqlite3.Connection):
    """Tracks consumer checkpoint — last processed timestamp per instrument."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS consumer_state (
            key    TEXT PRIMARY KEY,
            value  TEXT
        )
    """)
    conn.commit()


def init_enriched_schema(conn: sqlite3.Connection):
    """Full enriched data table — mirrors legacy DuckDB 104-column market_data schema.
    Filled by the enricher process (Phase 1.4).
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS market_data_enriched (
            timestamp                      TEXT NOT NULL,
            instrument                     TEXT NOT NULL,

            spot                           REAL,
            futures                        REAL,
            open_price                     REAL,
            prev_close                     REAL,
            atm_strike                     INTEGER,
            expiry_weekly                  TEXT,
            days_to_weekly                 INTEGER,
            expiry_next_weekly             TEXT,
            days_to_next_weekly            INTEGER,
            expiry_monthly                 TEXT,
            days_to_monthly                INTEGER,

            ema_5                          REAL,
            ema_20                         REAL,
            ema_50                         REAL,
            supertrend_value               REAL,
            supertrend_direction           TEXT,
            adx                            REAL,
            atr                            REAL,
            rsi                            REAL,
            india_vix                      REAL,
            vwap                           REAL,
            bb_pct_b                       REAL,
            bb_width                       REAL,
            ema20_slope                    REAL,
            gap_pct                        REAL,
            prev_day_high                  REAL,
            prev_day_low                   REAL,
            prev_day_range                 REAL,
            intraday_high                  REAL,
            intraday_low                   REAL,

            pivot_pp                       REAL,
            pivot_r1                       REAL,
            pivot_r2                       REAL,
            pivot_r3                       REAL,
            pivot_s1                       REAL,
            pivot_s2                       REAL,
            pivot_s3                       REAL,

            fib_0                          REAL,
            fib_236                        REAL,
            fib_382                        REAL,
            fib_50                         REAL,
            fib_618                        REAL,
            fib_786                        REAL,
            fib_100                        REAL,

            open_range_high                REAL,
            open_range_low                 REAL,

            iv_current                     REAL,
            iv_52w_high                    REAL,
            iv_52w_low                     REAL,
            iv_rank                        REAL,
            iv_regime                      TEXT,
            iv_short                       REAL,
            iv_long                        REAL,
            iv_slope                       REAL,
            hv_20                          REAL,
            hv_60                          REAL,

            agg_delta                      REAL,
            agg_gamma                      REAL,
            agg_vega                       REAL,
            agg_theta                      REAL,
            wings_delta                    REAL,
            body_delta                     REAL,

            pcr_total                      REAL,
            pcr_atm                        REAL,
            sentiment                      TEXT,
            max_pain_strike                INTEGER,
            call_oi_concentration          REAL,
            put_oi_concentration           REAL,
            oi_skew                        REAL,

            ob_zone_high                   REAL,
            ob_zone_low                    REAL,
            ob_strength                    INTEGER,
            fvg_high                       REAL,
            fvg_low                        REAL,
            fvg_mitigated                  INTEGER,
            swing_high                     REAL,
            swing_low                      REAL,
            liquidity_swept                INTEGER,
            structure_type                 TEXT,
            structure_confirmed            INTEGER,
            next_target                    REAL,
            smc_strength                   REAL,

            cluster_support                REAL,
            cluster_resistance             REAL,
            distance_to_support            REAL,
            distance_to_resistance         REAL,

            st_5min_value                  REAL,
            st_5min_direction              TEXT,
            st_15min_value                 REAL,
            st_15min_direction             TEXT,
            st_consensus                   TEXT,

            session_phase                  TEXT,
            open_to_current_pct            REAL,
            distance_to_pivot_pct          REAL,
            distance_to_r1_pct             REAL,
            distance_to_s1_pct             REAL,

            data_source                    TEXT DEFAULT 'penguin',
            buffer_bars                    INTEGER,

            PRIMARY KEY (timestamp, instrument)
        )
    """)
    conn.commit()


def init_option_prices_schema(conn: sqlite3.Connection):
    """Per-strike option LTPs from WebSocket feed — used by position_manager SL/TP checks."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS option_prices (
            tsym        TEXT PRIMARY KEY,
            strike      INTEGER NOT NULL,
            option_type TEXT NOT NULL CHECK (option_type IN ('CE', 'PE')),
            ltp         REAL,
            oi          REAL,
            volume      REAL,
            timestamp   TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_option_prices_strike
        ON option_prices(strike, option_type)
    """)
    # Additive migration for pre-existing DBs (oi/volume added 2026-06-03).
    existing = {row[1] for row in conn.execute("PRAGMA table_info(option_prices)")}
    for col in ("oi", "volume"):
        if col not in existing:
            conn.execute(f"ALTER TABLE option_prices ADD COLUMN {col} REAL")
    conn.commit()


def init_schemas(conn: sqlite3.Connection):
    """Create all tables if they don't exist."""
    init_market_data_schema(conn)
    init_multitf_schema(conn)
    init_consumer_state(conn)
    init_option_prices_schema(conn)
    init_enriched_schema(conn)
