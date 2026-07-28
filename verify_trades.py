"""Deterministic trade validator. No LLM anywhere in this file — every
verdict comes from a direct read of a source-of-truth table/file plus a
plain arithmetic comparison. Never trust a narrated claim ("a trade was
taken at X") — only this sweep's own output is ground truth; anything a
report/conversation says that ISN'T in this sweep's rows is presumptively
false (see memory: claude_hallucination_incident_may24).

ATOM: cross-checked against a genuinely independent second source —
`option_prices` in the live capture SQLite, which ATOM's own code never
writes to (Penguin's feed does). A recorded leg price that has no matching
real tick within tolerance is flagged PRICE_MISMATCH; a leg with no real
tick at all nearby is NO_DATA.

PROTON / PROTON+ / NEUTRON: these price legs via on-demand Flattrade REST
reads that are never persisted anywhere else (see weekly_ic_pilot.py's own
isolation docstring) — there is no independent third-party store to
cross-check the *price* against. What CAN be verified: the ledger row
itself is real (appended directly by the pilot's own code path, not by any
narrative/report layer), and whether the claimed math (credit vs PT/SL
levels) is internally consistent. Verdict LEDGER_ROW_EXISTS reflects that
narrower guarantee — it is not a price cross-check, and this file says so
in the "detail" field of every row so nobody mistakes one for the other.

Known label caveat (see memory: atom_trade_ledger_report): `exit_reason`
can be a relabeled value (e.g. a stale-feed force-flatten reusing "EOD").
This validator does not adjudicate labels — it only confirms recorded
prices against real ticks.
"""

import json
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

ATOM_DIR = Path("/home/trading_ceo/atom")
ANTARIKSH_DIR = Path(__file__).resolve().parent
CAPTURE_DIR = Path("/home/trading_ceo/python-trader/varaha/data")

PRICE_TOLERANCE_PCT = 15.0
TICK_TOLERANCE_MINUTES = 5

_MONTHS = {
    1: "JAN",
    2: "FEB",
    3: "MAR",
    4: "APR",
    5: "MAY",
    6: "JUN",
    7: "JUL",
    8: "AUG",
    9: "SEP",
    10: "OCT",
    11: "NOV",
    12: "DEC",
}
_WEEKLY_MONTH = {10: "O", 11: "N", 12: "D"}


def _expiry_to_tok(expiry: str, index: str) -> str:
    """Mirrors atom/src/atom/penguin.py's _expiry_to_tok exactly — NIFTY and
    SENSEX tsym grammars differ (see that file's own docstring / memory:
    fix_sensex_option_symbols). Getting this wrong means matching the WRONG
    expiry's tick when multiple expiries share a strike+opt_type at the same
    timestamp — a real bug this validator hit and fixed against itself
    (see verify_trades.py history: 29/94 false PRICE_MISMATCH from an
    expiry-blind match before this filter was added)."""
    if index == "SENSEX":
        m = re.match(r"(\d{2})-([A-Z]{3})-(\d{4})", expiry or "")
        if not m:
            return ""
        dd, mon, yyyy = m.groups()
        month_num = {v: k for k, v in _MONTHS.items()}.get(mon)
        if month_num is None:
            return ""
        return f"{yyyy[2:]}{_WEEKLY_MONTH.get(month_num, str(month_num))}{dd}"
    m = re.match(r"(\d{2})-([A-Z]{3})-(\d{4})", expiry or "")
    if not m:
        return ""
    return f"{m.group(1)}{m.group(2)}{m.group(3)[2:]}"


def _open_ro(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _nearest_option_tick(
    capture_db: Path, strike: int, opt_type: str, ts: str, index: str, expiry: str
) -> dict | None:
    if not capture_db.exists():
        return None
    tok = _expiry_to_tok(expiry, index)
    if not tok:
        return None
    target = datetime.fromisoformat(ts)
    lo = (target - timedelta(minutes=TICK_TOLERANCE_MINUTES)).isoformat()
    hi = (target + timedelta(minutes=TICK_TOLERANCE_MINUTES)).isoformat()
    con = _open_ro(capture_db)
    try:
        row = con.execute(
            "SELECT ltp, timestamp FROM option_prices WHERE strike=? AND option_type=? "
            "AND tsym LIKE ? AND timestamp BETWEEN ? AND ? "
            "ORDER BY ABS(julianday(timestamp) - julianday(?)) LIMIT 1",
            (strike, opt_type, f"{index}{tok}%", lo, hi, ts),
        ).fetchone()
    finally:
        con.close()
    return dict(row) if row else None


def verify_atom(index_name: str = "NIFTY", limit: int = 50) -> list[dict]:
    db = (
        ATOM_DIR
        / "data"
        / ("atom_state.sqlite" if index_name == "NIFTY" else "atom_state_sensex.sqlite")
    )
    if not db.exists():
        return []
    capture_db = CAPTURE_DIR / f"capture_{index_name.lower()}.sqlite"
    con = _open_ro(db)
    try:
        rows = con.execute(
            "SELECT ts, structure, net_credit, legs, exit_ts, exit_reason, realized_pnl, expiry "
            "FROM paper_trades ORDER BY ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        con.close()

    now = datetime.now().isoformat(timespec="seconds")
    results = []
    for row in rows:
        legs = json.loads(row["legs"])
        for action, strike, opt_type, recorded_price in legs:
            tick = _nearest_option_tick(
                capture_db, strike, opt_type, row["ts"], index_name, row["expiry"]
            )
            if tick is None:
                verdict = "NO_DATA"
                indep_price = None
                detail = f"no real {opt_type} {strike} tick within {TICK_TOLERANCE_MINUTES}min of {row['ts']}"
            else:
                indep_price = tick["ltp"]
                delta_pct = (
                    abs(recorded_price - indep_price) / indep_price * 100 if indep_price else None
                )
                if delta_pct is not None and delta_pct <= PRICE_TOLERANCE_PCT:
                    verdict = "MATCH"
                    detail = (
                        f"real tick {indep_price} @ {tick['timestamp']} ({delta_pct:.1f}% delta)"
                    )
                else:
                    verdict = "PRICE_MISMATCH"
                    detail = f"recorded {recorded_price} vs real tick {indep_price} @ {tick['timestamp']}"
            results.append(
                {
                    "checked_at": now,
                    "system": "ATOM",
                    "trade_id": row["ts"],
                    "event": f"{action} {row['structure']}"
                    + (f" exit={row['exit_reason']}" if row["exit_ts"] else ""),
                    "strike": strike,
                    "opt_type": opt_type,
                    "recorded_price": recorded_price,
                    "independent_price": indep_price,
                    "verdict": verdict,
                    "detail": detail,
                }
            )
    return results


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def _legs_summary(cycle: dict) -> str:
    if not cycle:
        return ""
    if "sp" in cycle:  # NEUTRON / PROTON (original): flat 4-strike IC
        return f"PE {cycle.get('lp')}/{cycle.get('sp')} CE {cycle.get('sc')}/{cycle.get('lc')}"
    parts = []
    for side_name in ("put", "call"):
        side = cycle.get(side_name)
        if side:
            parts.append(f"{side_name.upper()} {side.get('hedge_k')}/{side.get('short_k')}")
    return " ".join(parts)


def verify_pilot(system_name: str, ledger_path: Path, limit: int = 50) -> list[dict]:
    """PROTON / PROTON+ / NEUTRON — ledger-row-exists check, not a price
    cross-check (see module docstring for why no independent source exists
    for on-demand Flattrade reads)."""
    events = [e for e in _read_jsonl(ledger_path) if e.get("action") in ("ENTER", "EXIT", "MORPH")]
    now = datetime.now().isoformat(timespec="seconds")
    results = []
    for ev in events[-limit:]:
        cycle = ev.get("cycle", {})
        pricing_source = cycle.get("pricing_source")
        if pricing_source is None:
            for side_name in ("put", "call"):
                side = cycle.get(side_name)
                if side and side.get("pricing_source"):
                    pricing_source = side["pricing_source"]
                    break
        results.append(
            {
                "checked_at": now,
                "system": system_name,
                "trade_id": ev.get("ts"),
                "event": f"{ev.get('action')} {cycle.get('structure', '')}".strip(),
                "strike": _legs_summary(cycle),
                "opt_type": "",
                "recorded_price": cycle.get("credit") or cycle.get("net_credit"),
                "independent_price": None,
                "verdict": "LEDGER_ROW_EXISTS",
                "detail": f"pricing_source={pricing_source or 'n/a'} — no independent 3rd-party tick store "
                f"for on-demand Flattrade reads, this confirms the row is real code output, not the price",
            }
        )
    return results


def run_all(limit: int = 50) -> dict[str, list[dict]]:
    return {
        "ATOM": verify_atom("NIFTY", limit) + verify_atom("SENSEX", limit),
        "PROTON": verify_pilot("PROTON", ANTARIKSH_DIR / "logs" / "weekly_ic_pilot.jsonl", limit),
        "PROTON+": verify_pilot(
            "PROTON+", ANTARIKSH_DIR / "logs" / "weekly_ic_pilot_orbiter.jsonl", limit
        ),
        "NEUTRON": verify_pilot(
            "NEUTRON", ANTARIKSH_DIR / "logs" / "monthly_ic_pilot.jsonl", limit
        ),
        "NEUTRON+ NIFTY": verify_pilot(
            "NEUTRON+ NIFTY", ANTARIKSH_DIR / "logs" / "monthly_ic_pilot_orbiter_nifty.jsonl", limit
        ),
        "NEUTRON+ SENSEX": verify_pilot(
            "NEUTRON+ SENSEX",
            ANTARIKSH_DIR / "logs" / "monthly_ic_pilot_orbiter_sensex.jsonl",
            limit,
        ),
        "HYDROGEN+ NIFTY": verify_pilot(
            "HYDROGEN+ NIFTY",
            ANTARIKSH_DIR / "logs" / "hydrogen_ic_pilot_orbiter_nifty.jsonl",
            limit,
        ),
        "HYDROGEN+ SENSEX": verify_pilot(
            "HYDROGEN+ SENSEX",
            ANTARIKSH_DIR / "logs" / "hydrogen_ic_pilot_orbiter_sensex.jsonl",
            limit,
        ),
    }


if __name__ == "__main__":
    for system, rows in run_all().items():
        counts = {}
        for r in rows:
            counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
        print(system, counts or "(no claimed trades in ledger)")
