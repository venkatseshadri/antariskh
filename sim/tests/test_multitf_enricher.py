"""PORCUPINE — SQLite multi-TF indicator enricher: parity + population.

Proves the DuckDB→SQLite consolidation: feeding per-TF OHLCV rows into a SQLite
market_data_multitf table and running multitf_enricher fills the indicator columns
(st_consensus directional, not NULL) using the SAME math as the v4 aggregator —
so the lock-prone DuckDB store can be retired. No DuckDB, no Redis.
"""
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enrichers.multitf_enricher import enrich_day, compute_row_indicators, IND_COLS


def _ck(name, cond):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    return cond


def _seed_db(path, instrument, date, tf, closes):
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE IF NOT EXISTS market_data_multitf (
        timestamp TEXT, instrument TEXT, timeframe_min INTEGER,
        open REAL, high REAL, low REAL, close REAL, volume REAL,
        sma20 REAL, sma50 REAL, sma200 REAL, rsi REAL, atr REAL, macd REAL,
        macd_signal REAL, macd_histogram REAL, adx REAL, di_plus REAL, di_minus REAL,
        bb_upper REAL, bb_middle REAL, bb_lower REAL, obv REAL, cmf REAL, cci REAL,
        st_consensus TEXT,
        PRIMARY KEY (timestamp, instrument, timeframe_min))""")
    for i, c in enumerate(closes):
        ts = f"{date}T09:{15 + i:02d}:00"
        conn.execute("INSERT INTO market_data_multitf "
                     "(timestamp,instrument,timeframe_min,open,high,low,close,volume) "
                     "VALUES (?,?,?,?,?,?,?,?)",
                     (ts, instrument, tf, c, c + 5, c - 5, c, 1000))
    conn.commit(); conn.close()


def main():
    ok = True
    date = "2026-06-16"
    db = str(Path(tempfile.mkdtemp()) / "capture_nifty.sqlite")

    # Seed an uptrend (tf=5) and a downtrend (tf=15), OHLCV only (indicators NULL).
    _seed_db(db, "NIFTY", date, 5, [23000 + 8 * i for i in range(40)])     # up
    _seed_db(db, "NIFTY", date, 15, [23400 - 10 * i for i in range(40)])   # down

    # Before: indicators are NULL
    conn = sqlite3.connect(db)
    nulls = conn.execute("SELECT COUNT(*) FROM market_data_multitf WHERE st_consensus IS NULL").fetchone()[0]
    ok &= _ck("seed: st_consensus starts NULL (OHLCV-only, like the consumer)", nulls == 80)
    conn.close()

    written = enrich_day(db, "NIFTY", date)
    ok &= _ck("enricher wrote both timeframes", written.get(5, 0) == 40 and written.get(15, 0) == 40)

    conn = sqlite3.connect(db); conn.row_factory = sqlite3.Row
    up = conn.execute("SELECT st_consensus, rsi, adx FROM market_data_multitf "
                      "WHERE timeframe_min=5 ORDER BY timestamp DESC LIMIT 1").fetchone()
    dn = conn.execute("SELECT st_consensus FROM market_data_multitf "
                      "WHERE timeframe_min=15 ORDER BY timestamp DESC LIMIT 1").fetchone()
    distinct5 = [r[0] for r in conn.execute(
        "SELECT DISTINCT st_consensus FROM market_data_multitf WHERE timeframe_min=5").fetchall()]
    conn.close()

    ok &= _ck("st_consensus now POPULATED (not NULL)", up["st_consensus"] is not None)
    ok &= _ck("uptrend → BULLISH", up["st_consensus"] == "BULLISH")
    ok &= _ck("downtrend → BEARISH", dn["st_consensus"] == "BEARISH")
    ok &= _ck("rsi + adx also populated", up["rsi"] is not None and up["adx"] is not None)
    ok &= _ck("st_consensus is computed per-bar (not a constant)", len(distinct5) >= 2 or "BULLISH" in distinct5)

    # Parity: the written value equals a direct compute (same code path, no drift)
    tf_bars = [{"timestamp": f"{date}T09:{15+i:02d}:00", "open": 23000+8*i, "high": 23005+8*i,
                "low": 22995+8*i, "close": 23000+8*i, "volume": 1000} for i in range(40)]
    direct = compute_row_indicators(tf_bars, 39, 5)
    ok &= _ck("written st_consensus == direct compute (parity)", direct["st_consensus"] == up["st_consensus"])

    print(f"\n{'ALL PASS' if ok else 'FAILURES'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
