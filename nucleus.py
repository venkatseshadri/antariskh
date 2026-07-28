"""NUCLEUS — capital-orchestration layer for the 4-tier portfolio.

Binds the 4 already-built, already-backtested tiers together with one dynamic
capital picture. Does NOT touch any tier's entry/TSL/TP/legging logic — those
stay exactly as built:
  - Tier 1 (Gamma Scalper, intraday)  = ATOM        (real orders, own Shoonya session)
  - Tier 2 (Theta Engine)             = PROTON paper (weekly_ic_pilot.py, paper only)
  - Tier 3 (Vega Balancer)            = HYDROGEN    (proton_live.py, real orders, DRY_RUN today)
  - Tier 4 (Macro Anchor, monthly)    = NEUTRON     (monthly_ic_pilot.py, paper only)

Only T1/T3 place real broker orders today, so only they get a real capital
ceiling; T2/T4 get a simulated/notional ceiling (logged for visibility, not
gating anything) until they graduate to live order placement — matching the
same paper->live pattern already used for PROTON->HYDROGEN.

Capital source: a live, stateless Shoonya `get_limits()` call reusing the SAME
proven pattern as proton_live.py's `_shoonya_session()`/`check_account_margin()`
(no new persistent broker login — Board decision 2026-07-05, see
atom/src/atom/connectivity.py). Falls back to the daily-cached
antariksh/data/broker_limits.json (margin_calculator.py, refreshed 08:30) if
the live call fails — never blocks on a broker hiccup.

Tier ceiling % are a first-cut heuristic taken directly from the ORBITER doc's
floor/ceiling matrix (Project Square), applied independently per tier (not
summed to 100% — v1 doesn't track cross-tier reservations, matching the
existing convention where ATOM's and HYDROGEN's ceilings are already
independent of each other). Retune TIER_CEILING_PCT after a few live sessions.

Run once per cycle via `run_once()`. Scheduled every 15 min, 9:15-15:30 IST
weekdays, via cron/run_nucleus.sh (own flock, own log — mirrors
run_monthly_ic_pilot.sh).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, "/home/trading_ceo/atom/src")
from atom.broker_session import load_live_api

BUFFER_PCT = 0.15  # withheld from every sweep, absorbs cross-tier MTM/gamma spikes

# Independent ceiling % of (pool - buffer) per tier. Not summed to 100% (v1 —
# see module docstring). Source: ORBITER doc's floor/ceiling matrix.
TIER_CEILING_PCT = {
    "T1_ATOM": 0.60,
    "T2_PROTON": 0.40,
    "T3_HYDROGEN": 0.40,
    "T4_NEUTRON": 0.40,
}
REAL_TIERS = {"T1_ATOM", "T3_HYDROGEN"}  # place real orders today; rest are paper/simulated

CACHED_LIMITS_FILE = Path(__file__).resolve().parent / "data" / "broker_limits.json"
ALLOCATION_PATH = Path(__file__).resolve().parent / "data" / "nucleus_allocation.json"
LEDGER_PATH = Path(__file__).resolve().parent / "logs" / "nucleus.jsonl"

# Same daily-fetch cadence as broker_limits.json's own consumers (connectivity.py) —
# a cached read this old is treated as unusable, not "0 used, all clear."
MAX_CACHED_AGE_DAYS = 4


def _log_ledger(event: dict):
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    event = {"ts": datetime.now().isoformat(), **event}
    with open(LEDGER_PATH, "a") as f:
        f.write(json.dumps(event, default=str) + "\n")


def _live_free_margin() -> float | None:
    """Stateless REST get_limits() against the shared Shoonya session — same
    proven session pattern as proton_live.py's check_account_margin(). None on
    any failure, never a guess.

    Field names verified against the REAL response (2026-07-15), not assumed:
    there's no "marginavailable"/"collat"/"col" key on this broker — the real
    keys are "cash" and "grcoll" (gross collateral, haircut-adjusted — "usable
    for margin" per broker_limits.py's own BrokerLimits.gross_collateral
    docstring). proton_live.py's check_account_margin() checks for "collat"/
    "col" instead, which don't exist in the real response either — it silently
    falls back to cash-only there too. Flagged separately; not fixed here
    (that function is HYDROGEN's existing entry gate, out of this change's
    scope — still fails safe in the conservative direction: cash-only
    undercounts margin, so it blocks trades rather than over-permitting them)."""
    try:
        api = load_live_api()
        limits = api.get_limits()
        if not isinstance(limits, dict):
            return None
        cash = float(limits.get("cash", 0) or 0)
        gross_collateral = float(limits.get("grcoll", 0) or 0)
        return cash + gross_collateral
    except Exception:
        return None


def _cached_free_margin() -> tuple[float | None, str | None]:
    """Fallback: antariksh/data/broker_limits.json (margin_calculator.py, 08:30
    daily). Returns (free_margin, reason) — reason is None on success."""
    try:
        raw = json.loads(CACHED_LIMITS_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None, "NO_FILE"
    try:
        ts = datetime.fromisoformat(raw["timestamp"])
    except (KeyError, TypeError, ValueError):
        return None, "MALFORMED"
    age_days = (datetime.now() - ts).total_seconds() / 86400
    if age_days < 0:
        return None, "FUTURE_TIMESTAMP"
    if age_days > MAX_CACHED_AGE_DAYS:
        return None, "STALE"
    fm = raw.get("free_margin")
    if fm is None:
        return None, "MALFORMED"
    return float(fm), None


def compute_allocation(pool_total: float, source: str) -> dict:
    buffer_reserved = pool_total * BUFFER_PCT
    sweepable = max(pool_total - buffer_reserved, 0.0)
    tiers = {
        tier: {
            "ceiling_inr": round(sweepable * pct, 2),
            "real": tier in REAL_TIERS,
        }
        for tier, pct in TIER_CEILING_PCT.items()
    }
    return {
        "pool_total": pool_total,
        "buffer_reserved_inr": round(buffer_reserved, 2),
        "source": source,
        "updated_at": datetime.now().isoformat(),
        "tiers": tiers,
    }


def run_once() -> dict | None:
    pool_total = _live_free_margin()
    source = "live"
    if pool_total is None:
        pool_total, reason = _cached_free_margin()
        source = "cached"
        if pool_total is None:
            _log_ledger({"action": "SKIP", "reason": f"no_margin_source:{reason}"})
            return None

    allocation = compute_allocation(pool_total, source)
    ALLOCATION_PATH.parent.mkdir(parents=True, exist_ok=True)
    ALLOCATION_PATH.write_text(json.dumps(allocation, indent=2, default=str))
    _log_ledger({"action": "ALLOCATE", **allocation})
    return allocation


if __name__ == "__main__":
    result = run_once()
    if result:
        print(json.dumps(result, indent=2))
    else:
        print("NUCLEUS: no margin source available this cycle (see ledger)")
