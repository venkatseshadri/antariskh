"""PORCUPINE path scenarios — DATA, not code.

Each row is a scripted intraday narrative the path-driver replays against the real
position_manager: an entry, a (time, spot) waypoint path, and an `expect` block of
assertions-as-data the orchestrator evaluates over the resulting trace. This is the
seam to MONGOOSE — these are seed rows that will MIGRATE into the MONGOOSE scenario
library; the engine (path_driver + option_pricer + run_path) is what stays here.

Add a narrative = add a dict. No new code.

expect keys (all optional):
  closed                bool  — trade must end closed (vs still ACTIVE)
  closed_at_eod         bool  — closed exactly at the 15:30 EOD square-off
  closed_before_eod     bool  — closed intraday (a protective exit fired first)
  reason_contains       str   — substring of trade_history.close_reason (case-insensitive)
  pnl_sign              "neg"|"pos"
  arc_giveback          bool  — peak MTM in the trace exceeds the final MTM (gave profit back)
"""

# Short straddle at 23000; entry mark ≈118/leg (pricer at 09:20). Wide SLs so a
# normal intraday wobble survives to the EOD square-off.
_STRADDLE_23000 = [
    {"tsym": "SIM_STRD_CE", "type": "CE", "action": "SELL", "strike": 23000,
     "fill_price": 118.0, "quantity": 65, "sl": 200.0, "tp": 40.0},
    {"tsym": "SIM_STRD_PE", "type": "PE", "action": "SELL", "strike": 23000,
     "fill_price": 118.0, "quantity": 65, "sl": 200.0, "tp": 40.0},
]

# Call credit spread (single short CE + OTM long CE hedge). A short straddle's SL
# would close only one side and leave the other short ACTIVE; the single short here
# closes terminally on its SL. The tight cumulative FLOOR (-500) preempts a per-leg
# SL on any *immediate* adverse move, so the SL path is only reachable once the
# position has banked theta — see theta_then_spike.
_CALL_SPREAD = [
    {"tsym": "SIM_CS_CE_SELL", "type": "CE", "action": "SELL", "strike": 23000,
     "fill_price": 118.0, "quantity": 65, "sl": 200.0, "tp": 40.0},
    {"tsym": "SIM_CS_CE_BUY", "type": "CE", "action": "BUY", "strike": 23300,
     "fill_price": 30.0, "quantity": 65, "sl": None, "tp": None},
]

PATH_SCENARIOS = {
    # The user's narrative: flat open → ramp +0.5% by mid-day → fade back below
    # entry into the close. Wide straddle survives the wobble; theta builds a
    # profit, the fade gives some back, then the EOD square-off books it flat.
    "ramp_then_fade": {
        "name": "ramp_then_fade",
        "strategy": "SHORT_STRADDLE",
        "date": "2026-06-05",
        "step_min": 15,
        "legs": _STRADDLE_23000,
        "path": [["09:20", 23000], ["13:00", 23115], ["15:25", 22980], ["15:30", 22980]],
        "expect": {
            "closed": True,
            "closed_at_eod": True,
            "reason_contains": "MARKET",
            "pnl_sign": "pos",
            "arc_giveback": True,
        },
    },

    # Flat morning, THEN a sharp afternoon spike against the short CE. ★ FINDING:
    # the cumulative FLOOR (-500) fires here, NOT the per-leg SL (200). At 65-lot a
    # spike that would breach a 200-point SL is already an ~₹5k mark-to-market loss,
    # so the -500 floor trips many points earlier — the floor PREEMPTS the per-leg
    # SL on any real adverse move. (Per-leg SL is covered by the static `lifecycle`
    # scenario, where mtm stays inside the floor.) This scenario pins that the
    # protective floor squares the position off INTRADAY on a spike.
    "spike_breaches_floor": {
        "name": "spike_breaches_floor",
        "strategy": "CALL_SPREAD",
        "date": "2026-06-05",
        "step_min": 15,
        "legs": _CALL_SPREAD,
        "path": [["09:20", 23000], ["12:30", 23000], ["14:30", 23280]],
        "expect": {
            "closed": True,
            "closed_before_eod": True,
            "reason_contains": "FLOOR",
            "pnl_sign": "neg",
        },
    },
}
