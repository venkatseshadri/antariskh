"""PORCUPINE lifecycle driver — runs INSIDE the sandbox (cwd=brahmand, with
SIM_MODE/SIM_ROOT + BRAHMAND_SANDBOX env set by run_scenario.run_lifecycle).

Drives the REAL order→monitor→exit path with no LLM and no broker:
  1. seed a paper CE credit spread (sold leg already breached SL) into the
     sandbox trade_execution.duckdb via the real trade_execution_db,
  2. run the REAL position_manager.run_bridge() once — its DETERMINISTIC SL/TP
     check fires (skips the LLM), squares off the side (paper fill, no broker),
     and closes the trade in both sandbox stores,
  3. print a JSON verdict the orchestrator asserts on.

Hermetic: every DB (trade ledger duckdb, order_ledger.json, option-price sqlite)
redirects to the sandbox via env. Refuses to run outside SIM_MODE.
"""
import json
import os
import sys
from datetime import datetime

if os.environ.get("SIM_MODE") != "1":
    raise SystemExit("REFUSING: SIM_MODE!=1 — lifecycle_driver only drives the sandbox.")

from trade_execution_db import add_active_trade, get_active_trades, _connect  # noqa: E402
import position_manager  # noqa: E402

TRADE_ID = "SIM_LIFECYCLE_1"

# Sold CE @100 with SL=150; hedge BUY CE @40. The sandbox option_prices (seeded
# by the orchestrator) marks the sold CE to 160 → current_ltp >= sl → SL_HIT.
LEGS = [
    {"tsym": "SIM_NIFTY_CE_SELL", "type": "CE", "action": "SELL",
     "fill_price": 100.0, "quantity": 65, "sl": 150.0, "tp": 50.0},
    {"tsym": "SIM_NIFTY_CE_BUY", "type": "CE", "action": "BUY",
     "fill_price": 40.0, "quantity": 65, "sl": None, "tp": None},
]


def main():
    add_active_trade(
        trade_id=TRADE_ID,
        entry_time=datetime.now().isoformat(),
        strategy="BULL_CALL",
        entry_gate_signal="NOT_DOWN",
        legs=LEGS,
        sl={},
        tp={},
    )
    before = [t["trade_id"] for t in get_active_trades()]

    # The single monitor cycle: deterministic SL/TP → square-off → close.
    position_manager.run_bridge()

    after = [t["trade_id"] for t in get_active_trades()]
    with _connect() as c:
        hist = c.execute(
            "SELECT trade_id, close_reason, final_pnl FROM trade_history "
            "WHERE trade_id = ?", [TRADE_ID]
        ).fetchall()

    print("LIFECYCLE_RESULT " + json.dumps({
        "before": before,
        "after": after,
        "history": [list(h) for h in hist],
    }, default=str))


if __name__ == "__main__":
    main()
