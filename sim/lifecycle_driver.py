"""PORCUPINE lifecycle driver — runs INSIDE the sandbox (cwd=brahmand, with
SIM_MODE/SIM_ROOT + BRAHMAND_SANDBOX env set by run_scenario.run_lifecycle).

Drives the REAL order→monitor→exit path with no LLM and no broker. The exit
branch exercised is selected by the LIFECYCLE_MODE env var — every protective /
discretionary branch of position_manager.run_bridge gets a fail-then-pass
regression (PORCUPINE rule: every path that can fire in live needs one):

  SL_HIT  sold CE marked above its SL          → deterministic SL square-off
  TP_HIT  sold CE marked below its TP          → deterministic TP square-off
  EOD     SIM_NOW≥15:30, no SL/TP breach        → hard EOD CLOSE_ALL
  FLOOR   mark-to-market ≤ FLOOR, no SL breach  → cumulative-P&L CLOSE_ALL
  MORPH   cached NEUTRAL→BULLISH assessment     → discretionary morph (LLM stub)

For every mode the driver seeds the sandbox option_prices (the same SQLite the
real _check_sl_tp reads, via get_sqlite_capture_path), seeds the trade via the
real trade_execution_db, runs the REAL position_manager.run_bridge() once, then
prints a JSON verdict the orchestrator asserts on.

Hermetic: every DB (trade ledger duckdb, order_ledger.json, option-price sqlite,
research cache) redirects to the sandbox via env. Refuses to run outside SIM_MODE.
"""
import json
import os
import sqlite3
import sys
from datetime import datetime

if os.environ.get("SIM_MODE") != "1":
    raise SystemExit("REFUSING: SIM_MODE!=1 — lifecycle_driver only drives the sandbox.")

from antariksh.config.sqlite_schema import get_sqlite_capture_path  # noqa: E402
from trade_execution_db import add_active_trade, get_active_trades, _connect  # noqa: E402
import position_manager  # noqa: E402

TRADE_ID = "SIM_LIFECYCLE_1"
MODE = os.environ.get("LIFECYCLE_MODE", "SL_HIT").upper()

# Each spec: legs (with sl/tp), and the live option ltp keyed by tsym. fill=100
# on the sold CE; the hedge BUY CE is protection. SL_PCT/TP_PCT defaults make
# sl=150/tp=50 the natural credit-spread guards.
CE_SELL, CE_BUY = "SIM_NIFTY_CE_SELL", "SIM_NIFTY_CE_BUY"
PE_SELL, PE_BUY = "SIM_NIFTY_PE_SELL", "SIM_NIFTY_PE_BUY"

_BULL_CALL_LEGS = [
    {"tsym": CE_SELL, "type": "CE", "action": "SELL", "strike": 23000,
     "fill_price": 100.0, "quantity": 65, "sl": 150.0, "tp": 50.0},
    {"tsym": CE_BUY, "type": "CE", "action": "BUY", "strike": 23150,
     "fill_price": 40.0, "quantity": 65, "sl": None, "tp": None},
]

# Iron-fly for the MORPH case: NEUTRAL→BULLISH closes the CE side, keeps the PE.
_IRON_FLY_LEGS = [
    {"tsym": CE_SELL, "type": "CE", "action": "SELL", "strike": 23000,
     "fill_price": 100.0, "quantity": 65, "sl": 150.0, "tp": 50.0},
    {"tsym": CE_BUY, "type": "CE", "action": "BUY", "strike": 23200,
     "fill_price": 40.0, "quantity": 65, "sl": None, "tp": None},
    {"tsym": PE_SELL, "type": "PE", "action": "SELL", "strike": 23000,
     "fill_price": 90.0, "quantity": 65, "sl": 135.0, "tp": 45.0},
    {"tsym": PE_BUY, "type": "PE", "action": "BUY", "strike": 22800,
     "fill_price": 30.0, "quantity": 65, "sl": None, "tp": None},
]


def _spec(mode):
    """(strategy, legs, option_prices{tsym:ltp}, cached_actions or None)."""
    if mode == "SL_HIT":
        # sold CE marked 160 ≥ sl 150 → SL_HIT (loss).
        return "BULL_CALL", _BULL_CALL_LEGS, {CE_SELL: 160.0, CE_BUY: 55.0}, None
    if mode == "TP_HIT":
        # sold CE marked 45 ≤ tp 50 → TP_HIT (profit).
        return "BULL_CALL", _BULL_CALL_LEGS, {CE_SELL: 45.0, CE_BUY: 25.0}, None
    if mode == "EOD":
        # No SL/TP breach (marked at fill); SIM_NOW≥15:30 forces EOD CLOSE_ALL.
        return "BULL_CALL", _BULL_CALL_LEGS, {CE_SELL: 100.0, CE_BUY: 40.0}, None
    if mode == "FLOOR":
        # sold CE marked 160 but sl raised to 300 → NO SL_HIT; mtm
        # (100-160)*65 + (55-40)*65 = -2925 ≤ FLOOR(-500) → cumulative CLOSE_ALL.
        legs = [dict(l) for l in _BULL_CALL_LEGS]
        legs[0]["sl"], legs[0]["tp"] = 300.0, 10.0
        return "BULL_CALL", legs, {CE_SELL: 160.0, CE_BUY: 55.0}, None
    if mode == "MORPH":
        # All legs marked at fill → mtm≈0, no SL/TP/floor. A cached NEUTRAL→BULLISH
        # assessment (the deterministic LLM stub) drives the discretionary morph:
        # run_bridge closes the CE side and keeps the PE → legs 4→2, still ACTIVE.
        prices = {CE_SELL: 100.0, CE_BUY: 40.0, PE_SELL: 90.0, PE_BUY: 30.0}
        actions = [{"type": "MORPH", "from_type": "NEUTRAL", "to_type": "BULLISH",
                    "priority": 1, "reason": "sim cached morph NEUTRAL→BULLISH"}]
        return "IRON_FLY", _IRON_FLY_LEGS, prices, actions
    raise SystemExit(f"unknown LIFECYCLE_MODE={mode}")


def _seed_option_prices(prices):
    db = str(get_sqlite_capture_path("NIFTY"))
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE IF NOT EXISTS option_prices "
                "(tsym TEXT, strike INTEGER, option_type TEXT, ltp REAL, "
                "oi INTEGER, volume INTEGER, timestamp TEXT)")
    con.executemany(
        "INSERT INTO option_prices (tsym, ltp, timestamp) VALUES (?,?,?)",
        [(tsym, ltp, "2026-06-05T14:00:00") for tsym, ltp in prices.items()],
    )
    con.commit()
    con.close()


def main():
    strategy, legs, prices, cached = _spec(MODE)
    _seed_option_prices(prices)

    add_active_trade(
        trade_id=TRADE_ID,
        entry_time=datetime.now().isoformat(),
        strategy=strategy,
        entry_gate_signal="NOT_DOWN",
        legs=legs,
        sl={},
        tp={},
    )

    before = get_active_trades()
    legs_before = next((len(t.get("legs", [])) for t in before
                        if t["trade_id"] == TRADE_ID), 0)

    # MORPH: seed the discretionary cache with a signature matching exactly what
    # run_bridge will compute (ledger trade dict, mtm=0) so it's a cache HIT.
    if cached is not None:
        from position_research_cache import save_assessment, compute_position_signature
        ledger_trade = next(t for t in before if t["trade_id"] == TRADE_ID)
        sig = compute_position_signature(ledger_trade, mtm=0.0)
        save_assessment(TRADE_ID,
                        {"actions": cached, "recommendation": "MORPH",
                         "reason": "sim cached morph"},
                        signature=sig)

    # The single monitor cycle: deterministic protective check → square-off/morph.
    position_manager.run_bridge()

    after_trades = get_active_trades()
    after = [t["trade_id"] for t in after_trades]
    legs_after = next((len(t.get("legs", [])) for t in after_trades
                       if t["trade_id"] == TRADE_ID), 0)
    with _connect() as c:
        hist = c.execute(
            "SELECT trade_id, close_reason, final_pnl FROM trade_history "
            "WHERE trade_id = ?", [TRADE_ID]
        ).fetchall()

    print("LIFECYCLE_RESULT " + json.dumps({
        "mode": MODE,
        "before": [t["trade_id"] for t in before],
        "after": after,
        "legs_before": legs_before,
        "legs_after": legs_after,
        "history": [list(h) for h in hist],
    }, default=str))


if __name__ == "__main__":
    main()
