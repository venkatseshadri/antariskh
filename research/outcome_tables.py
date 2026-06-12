"""outcome_tables.py — DDL + helpers for decision_trace and trade_outcomes tables.

These live in the capture SQLite alongside the indicator data so research
can join outcomes to the indicator snapshot at decision time.

Used by:
  - brahmand e2e_chain.py: write decision_trace per gate per cycle
  - brahmand position_manager.py: write trade_outcomes on close
"""

import sqlite3
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30))

_DDL_DECISION_TRACE = """
CREATE TABLE IF NOT EXISTS decision_trace (
    timestamp       TEXT NOT NULL,
    index_name      TEXT NOT NULL,
    decision_id     TEXT NOT NULL,
    gate_type       TEXT NOT NULL,       -- NOT_UP | NOT_DOWN
    decision_source TEXT,                -- canonical | unicorn_cache | llm_debate
    signal          TEXT,                -- NOT_UP | NOT_DOWN | NONE
    go              INTEGER DEFAULT 0,   -- 0/1
    confidence      REAL,
    regime          TEXT,
    regime_recommendation TEXT,
    vix             REAL,
    spot            REAL,
    PRIMARY KEY (decision_id, gate_type)
)
"""

_DDL_TRADE_OUTCOMES = """
CREATE TABLE IF NOT EXISTS trade_outcomes (
    trade_id        TEXT PRIMARY KEY,
    entry_time      TEXT,
    exit_time       TEXT,
    strategy        TEXT,
    wing_width      INTEGER,
    entry_pnl       REAL,
    final_pnl       REAL,
    duration_mins   INTEGER,
    close_reason    TEXT,                -- SL_HIT | TP_HIT | EOD | FLOOR | MANUAL
    legs_json       TEXT,                -- JSON blob of leg details
    created_at      TEXT
)
"""


def init_outcome_tables(db_path: str):
    """Idempotent init — safe to call every kickoff."""
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(_DDL_DECISION_TRACE)
        conn.execute(_DDL_TRADE_OUTCOMES)
        conn.commit()
    except sqlite3.OperationalError:
        conn.rollback()
    finally:
        conn.close()


def write_decision_trace(db_path: str, row: dict):
    """INSERT OR IGNORE a decision_trace row."""
    import logging

    _log = logging.getLogger("outcome_tables")
    conn = sqlite3.connect(db_path, timeout=10)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT OR IGNORE INTO decision_trace "
            "(timestamp, index_name, decision_id, gate_type, decision_source, "
            "signal, go, confidence, regime, regime_recommendation, vix, spot) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row.get("timestamp"),
                row.get("index_name", "NIFTY"),
                row.get("decision_id"),
                row.get("gate_type"),
                row.get("decision_source"),
                row.get("signal"),
                int(row.get("go", False)),
                row.get("confidence"),
                row.get("regime"),
                row.get("regime_recommendation"),
                row.get("vix"),
                row.get("spot"),
            ),
        )
        conn.commit()
    except sqlite3.OperationalError as e:
        _log.warning(
            "decision_trace write failed: %s gate=%s id=%s db=%s",
            e,
            row.get("gate_type"),
            row.get("decision_id"),
            db_path,
        )
        try:
            conn.rollback()
        except Exception:
            pass
    except Exception as e:
        _log.warning("decision_trace write FAILED: %s row=%s", e, str(row)[:200])
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


def write_trade_outcome(db_path: str, trade: dict):
    """INSERT OR REPLACE a trade_outcomes row."""
    conn = sqlite3.connect(db_path, timeout=10)
    try:
        conn.execute("BEGIN IMMEDIATE")
        legs_json = json.dumps(trade.get("legs", []))
        conn.execute(
            "INSERT OR REPLACE INTO trade_outcomes "
            "(trade_id, entry_time, exit_time, strategy, wing_width, "
            "entry_pnl, final_pnl, duration_mins, close_reason, legs_json, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                trade.get("trade_id"),
                trade.get("entry_time"),
                trade.get("exit_time"),
                trade.get("strategy"),
                trade.get("wing_width"),
                trade.get("entry_pnl"),
                trade.get("final_pnl"),
                trade.get("duration_mins"),
                trade.get("close_reason"),
                legs_json,
                datetime.now(IST).isoformat(),
            ),
        )
        conn.commit()
    except sqlite3.OperationalError:
        conn.rollback()
    finally:
        conn.close()
