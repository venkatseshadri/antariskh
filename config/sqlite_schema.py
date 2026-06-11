"""SQLite schema module for per-instrument capture databases.

Mirrors DuckDB schema where applicable. SQLite WAL allows concurrent
reader + writer access — no lock contention across processes.

Usage:
    from config.sqlite_schema import open_capture_db, init_schemas
    conn = open_capture_db("NIFTY")
    init_schemas(conn)
"""

import sqlite3
import sys
from pathlib import Path

# Route capture paths through PORCUPINE's sim_env so SIM_MODE redirects them to
# the sandbox. In production (SIM_MODE unset) this resolves to the same path as
# before. Bootstrap the antariksh root onto sys.path so the import works
# regardless of which entrypoint imported this module.
_ANTARIKSH_ROOT = Path(__file__).resolve().parent.parent
if str(_ANTARIKSH_ROOT) not in sys.path:
    sys.path.insert(0, str(_ANTARIKSH_ROOT))
from sim.sim_env import capture_path as _sim_capture_path, assert_sandboxed


def get_sqlite_capture_path(instrument: str) -> Path:
    return _sim_capture_path(instrument)


def open_capture_db(instrument: str, autocommit: bool = False) -> sqlite3.Connection:
    """Open per-instrument SQLite with WAL, NORMAL sync, busy_timeout.

    autocommit=True sets isolation_level=None so callers can manage explicit
    `BEGIN IMMEDIATE`/`COMMIT` transactions (required for busy_timeout to be
    honored on write-lock acquisition — see PENGUIN_ENRICHER_LOCK_FIX.md). The
    consumer keeps the default implicit-transaction mode.
    """
    path = get_sqlite_capture_path(instrument)
    assert_sandboxed(path)  # PORCUPINE: refuse to open a prod path during a sim run
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    if autocommit:
        conn.isolation_level = None
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.row_factory = sqlite3.Row
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    if mode.lower() != "wal":
        conn.close()
        raise RuntimeError(f"SQLite WAL not enabled — got '{mode}' for {path}")

    init_market_data_schema(conn)
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
    """Per-strike option LTPs — append-only time series with (tsym, timestamp) PK."""
    existing_table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='option_prices'"
    ).fetchone()

    if not existing_table:
        conn.execute("""
            CREATE TABLE option_prices (
                tsym        TEXT NOT NULL,
                strike      INTEGER NOT NULL,
                option_type TEXT NOT NULL CHECK (option_type IN ('CE', 'PE')),
                ltp         REAL,
                oi          REAL,
                volume      REAL,
                timestamp   TEXT NOT NULL,
                PRIMARY KEY (tsym, timestamp)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_option_prices_strike
            ON option_prices(strike, option_type)
        """)
        conn.commit()
        return

    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(option_prices)")}
    for col in ("oi", "volume"):
        if col not in existing_cols:
            conn.execute(f"ALTER TABLE option_prices ADD COLUMN {col} REAL")

    pk_cols = conn.execute("PRAGMA table_info(option_prices)").fetchall()
    pk_names = [row[1] for row in pk_cols if row[5] > 0]
    if "timestamp" not in pk_names:
        conn.execute("BEGIN")
        conn.execute("""
            CREATE TABLE option_prices_new (
                tsym        TEXT NOT NULL,
                strike      INTEGER NOT NULL,
                option_type TEXT NOT NULL CHECK (option_type IN ('CE', 'PE')),
                ltp         REAL,
                oi          REAL,
                volume      REAL,
                timestamp   TEXT NOT NULL,
                PRIMARY KEY (tsym, timestamp)
            )
        """)
        conn.execute("""
            INSERT INTO option_prices_new (tsym, strike, option_type, ltp, oi, volume, timestamp)
            SELECT tsym, strike, option_type, ltp, oi, volume, timestamp FROM option_prices
        """)
        conn.execute("DROP TABLE option_prices")
        conn.execute("ALTER TABLE option_prices_new RENAME TO option_prices")
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_option_prices_strike
            ON option_prices(strike, option_type)
        """)
        conn.commit()
    conn.commit()


def init_schemas(conn: sqlite3.Connection):
    """Create all tables if they don't exist."""
    init_market_data_schema(conn)
    init_multitf_schema(conn)
    init_consumer_state(conn)
    init_option_prices_schema(conn)
    init_enriched_schema(conn)
