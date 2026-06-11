"""PORCUPINE path-driver — the engine mechanism for TIME-EVOLVING scenarios.

Where lifecycle_driver runs ONE monitor cycle against ONE static mark, this drives
the REAL position_manager.run_bridge() across a SCRIPTED intraday spot path: at
each step it re-prices the trade's legs (sim.option_pricer), re-marks the sandbox
option_prices SQLite, advances the clock (SIM_NOW), runs one monitor cycle, and
records a trace row. It STOPS when the trade closes or the path ends at 15:30.

Scenario-agnostic by design (PORCUPINE = engine, MONGOOSE = scenarios): the spec
is DATA (a dict, normally loaded from sim/path_scenarios.py), and this driver only
emits a TRACE — the assertions over that trace live in the scenario layer
(run_scenario.run_path). Runs INSIDE the sandbox (cwd=brahmand, SIM_MODE +
BRAHMAND_SANDBOX); refuses to run otherwise.

Invoked as: python3 -m sim.path_driver <spec.json>   (spec piped via a temp file)
"""
import json
import os
import sqlite3
import sys
from datetime import datetime

if os.environ.get("SIM_MODE") != "1":
    raise SystemExit("REFUSING: SIM_MODE!=1 — path_driver only drives the sandbox.")

sys.path.insert(0, "/home/trading_ceo/antariksh")  # for sim.option_pricer
from sim.option_pricer import option_ltp, time_fraction  # noqa: E402
from antariksh.config.sqlite_schema import get_sqlite_capture_path  # noqa: E402
from trade_execution_db import add_active_trade, get_active_trades, _connect  # noqa: E402
from position_research_cache import save_assessment, compute_position_signature  # noqa: E402
import position_manager  # noqa: E402


def _interp_spot(path: list, hhmm: str) -> float:
    """Linear-interpolate the spot at HH:MM between the path's (time, spot)
    waypoints. Flat-holds before the first / after the last waypoint."""
    mins = lambda s: int(s[:2]) * 60 + int(s[3:5])
    t = mins(hhmm)
    pts = [(mins(ts), float(sp)) for ts, sp in path]
    if t <= pts[0][0]:
        return pts[0][1]
    if t >= pts[-1][0]:
        return pts[-1][1]
    for (t0, s0), (t1, s1) in zip(pts, pts[1:]):
        if t0 <= t <= t1:
            return s0 + (s1 - s0) * (t - t0) / (t1 - t0)
    return pts[-1][1]


def _step_times(start: str, step_min: int, end: str = "15:30") -> list:
    mins = lambda s: int(s[:2]) * 60 + int(s[3:5])
    out, t = [], mins(start)
    while t < mins(end):
        out.append(f"{t // 60:02d}:{t % 60:02d}")
        t += step_min
    out.append(end)  # always land a final step AT the close so EOD can fire
    return out


def _mark(db: str, legs: list, spot: float, t_frac: float) -> dict:
    """Re-price every leg at this spot/time and overwrite option_prices (one row
    per tsym — _check_sl_tp does fetchone). Returns {tsym: ltp}."""
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE IF NOT EXISTS option_prices "
                "(tsym TEXT, strike INTEGER, option_type TEXT, ltp REAL, "
                "oi INTEGER, volume INTEGER, timestamp TEXT)")
    con.execute("DELETE FROM option_prices")
    ltps = {}
    for leg in legs:
        ltp = option_ltp(spot, leg["strike"], leg["type"], t_frac)
        ltps[leg["tsym"]] = ltp
        con.execute("INSERT INTO option_prices (tsym, strike, option_type, ltp) "
                    "VALUES (?,?,?,?)", (leg["tsym"], leg["strike"], leg["type"], ltp))
    con.commit()
    con.close()
    return ltps


def _mtm(legs: list, ltps: dict) -> float:
    m = 0.0
    for leg in legs:
        ltp = ltps.get(leg["tsym"], leg["fill_price"])
        qty = leg.get("quantity", 65)
        if leg["action"] == "SELL":
            m += (leg["fill_price"] - ltp) * qty
        else:
            m += (ltp - leg["fill_price"]) * qty
    return round(m, 2)


def main():
    spec = json.loads(open(sys.argv[1]).read())
    trade_id = spec.get("trade_id", "SIM_PATH_1")
    the_date = spec.get("date", "2026-06-05")
    legs = spec["legs"]
    path = spec["path"]
    step_min = int(spec.get("step_min", 5))
    db = str(get_sqlite_capture_path("NIFTY"))

    # Entry: seed the trade and mark at the first waypoint.
    start = path[0][0]
    _mark(db, legs, _interp_spot(path, start), time_fraction(start))
    add_active_trade(trade_id=trade_id, entry_time=datetime.now().isoformat(),
                     strategy=spec.get("strategy", "SHORT_STRADDLE"),
                     entry_gate_signal=spec.get("signal", "NOT_DOWN"),
                     legs=legs, sl={}, tp={})

    trace = []
    closed_at = None
    for hhmm in _step_times(start, step_min):
        spot = _interp_spot(path, hhmm)
        ltps = _mark(db, legs, spot, time_fraction(hhmm))
        os.environ["SIM_NOW"] = f"{the_date}T{hhmm}:00"

        # On an ACTIVE step (no SL/TP/floor/EOD) run_bridge takes the discretionary
        # path; a cache MISS would fall through to the DuckDB-backed live recompute,
        # which has no market DB in the sandbox. Seed a no-op assessment matching the
        # signature run_bridge will compute (same legs + same mtm bucket) so it's a
        # cache HIT returning [] — the deterministic LLM-stub seam. A MONGOOSE
        # scenario that wants an intraday morph seeds real actions here instead.
        lt = next((t for t in get_active_trades() if t["trade_id"] == trade_id), None)
        if lt is not None:
            sig = compute_position_signature(lt, mtm=_mtm(legs, ltps))
            save_assessment(trade_id, {"actions": [], "recommendation": "HOLD",
                                       "reason": "path no-op"}, signature=sig)

        position_manager.run_bridge()

        actives = get_active_trades()
        active = any(t["trade_id"] == trade_id for t in actives)
        cur = next((t for t in actives if t["trade_id"] == trade_id), None)
        trace.append({
            "t": hhmm, "spot": round(spot, 1), "mtm": _mtm(legs, ltps),
            "active": active, "legs": len(cur.get("legs", [])) if cur else 0,
        })
        if not active:
            closed_at = hhmm
            break

    with _connect() as c:
        hist = c.execute(
            "SELECT trade_id, close_reason, final_pnl FROM trade_history "
            "WHERE trade_id = ?", [trade_id]).fetchall()

    print("PATH_RESULT " + json.dumps({
        "name": spec.get("name", "?"),
        "closed_at": closed_at,
        "steps": len(trace),
        "trace": trace,
        "history": [list(h) for h in hist],
    }, default=str))


if __name__ == "__main__":
    main()
