"""PORCUPINE position-cache driver — runs INSIDE the sandbox (cwd=brahmand,
SIM_MODE + BRAHMAND_SANDBOX), proving the REAL position_manager hot path reads the
cache that position_research writes.

Seeds a per-trade discretionary assessment into the sandbox cache (with the exact
signature run_bridge computes), then calls the REAL
position_manager._discretionary_actions and asserts it returns the cached actions.
The cache-HIT path takes no DB/LLM, so this is fully hermetic.
"""
import json
import os
import sys
from pathlib import Path

if os.environ.get("SIM_MODE") != "1":
    raise SystemExit("REFUSING: SIM_MODE!=1 — position_cache_driver only drives the sandbox.")

for p in ("/home/trading_ceo/brahmand", "/home/trading_ceo"):
    if p not in sys.path:
        sys.path.insert(0, p)

from position_research_cache import save_assessment, compute_position_signature  # noqa: E402
import position_manager as pm  # noqa: E402

TRADE = {
    "trade_id": "SIM_PC_1", "strategy": "IRON_FLY", "entry_gate_signal": "NOT_DOWN",
    "legs": [
        {"type": "CE", "action": "SELL", "strike": 23000, "fill_price": 100.0, "quantity": 65},
        {"type": "CE", "action": "BUY", "strike": 23150, "fill_price": 40.0, "quantity": 65},
    ],
}
MTM = -150.0
CACHED = [{"type": "ROLL", "priority": 1, "reason": "sim cached roll"}]


def main():
    sig = compute_position_signature(TRADE, mtm=MTM)
    save_assessment("SIM_PC_1",
                    {"actions": CACHED, "recommendation": "ROLL", "reason": "sim"},
                    signature=sig)

    # HIT: same trade+mtm → matching signature → cached actions returned (no run()).
    hit = pm._discretionary_actions(TRADE, "SIM_PC_1", MTM)

    # MISS: unknown trade_id → no cache file → falls through to a LIVE recompute
    # (run(), which reads DBs). The point is only that it does NOT return the cached
    # actions; whether the sandbox run() yields [] or errors, both mean "recompute".
    try:
        miss = pm._discretionary_actions(TRADE, "SIM_PC_UNKNOWN", MTM)
        miss_differs = miss != CACHED
    except Exception:
        miss_differs = True

    print("PC_RESULT " + json.dumps({
        "hit_matches": hit == CACHED,
        "miss_differs": miss_differs,
        "hit": hit,
    }, default=str))


if __name__ == "__main__":
    main()
