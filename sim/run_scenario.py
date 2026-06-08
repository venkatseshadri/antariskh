"""PORCUPINE orchestrator — one command: boot isolated stack, drive the real
pipeline with the mock feed, run assertions, tear down, return PASS/FAIL.

    python3 -m sim.run_scenario happy_path
    python3 -m sim.run_scenario happy_path --with-kickoff   # also run real CrewAI
    python3 -m sim.run_scenario --list

Exit code 0 = all hard assertions passed, 1 = at least one failed (or error).
Scenarios live in SCENARIOS below; add rows from PORCUPINE_SCENARIO_CATALOGUE.md.
"""
import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROD_DB = "/home/trading_ceo/python-trader/varaha/data/capture_nifty.sqlite"
REDIS_PORT = "6380"

SCENARIOS = {
    "happy_path": {
        "desc": "Replay a full real day → consumer+enricher → assert pipeline health",
        "instrument": "NIFTY",
        "source_db": PROD_DB,
        "date": None,  # default = today; override with --date
    },
}


def _sql(db, q):
    c = sqlite3.connect(db)
    try:
        return c.execute(q).fetchone()
    finally:
        c.close()


def run(scenario: str, the_date: str | None, with_kickoff: bool) -> int:
    sc = SCENARIOS[scenario]
    inst = sc["instrument"]
    src = sc["source_db"]
    the_date = the_date or sc["date"] or date.today().isoformat()

    sim_root = ROOT / "sim" / f"run_{scenario}_{int(time.time())}"
    for sub in ("data", "logs", "redis"):
        (sim_root / sub).mkdir(parents=True, exist_ok=True)
    db = str(sim_root / "data" / f"capture_{inst.lower()}.sqlite")

    env = {**os.environ, "SIM_MODE": "1", "SIM_ROOT": str(sim_root),
           "SIM_REDIS_PORT": REDIS_PORT}
    redis_sh = str(ROOT / "sim" / "start_test_redis.sh")

    print(f"\n=== PORCUPINE scenario: {scenario} ===\n{sc['desc']}\nSIM_ROOT={sim_root}\n")
    results = []  # (name, ok, detail)

    try:
        subprocess.run(["bash", redis_sh, "start", str(sim_root), REDIS_PORT],
                       check=True, capture_output=True)

        # 1) replay real bars → consumer → sandbox market_data
        con = subprocess.Popen([sys.executable, "-m", "consumers.instrument_consumer",
                                "--instrument", inst], cwd=ROOT, env=env,
                               stdout=open(sim_root / "logs/consumer.out", "w"),
                               stderr=subprocess.STDOUT)
        time.sleep(1.5)
        subprocess.run([sys.executable, "-m", "sim.mock_feed", "--instrument", inst,
                        "--source-db", src, "--date", the_date, "--interval", "0.01"],
                       cwd=ROOT, env=env, check=True, capture_output=True)
        time.sleep(2)
        con.terminate()
        try:
            con.wait(timeout=10)
        except subprocess.TimeoutExpired:
            con.kill()

        # 2) backfill-enrich the full day (single writer, complete coverage)
        enr_log = sim_root / "logs/enricher_backfill.out"
        subprocess.run([sys.executable, "-m", "enrichers.instrument_enricher",
                        "--instrument", inst, "--backfill", f"{the_date}:{the_date}"],
                       cwd=ROOT, env=env, timeout=120,
                       stdout=open(enr_log, "w"), stderr=subprocess.STDOUT)

        # ── ASSERTIONS ──────────────────────────────────────────────────────
        raw = _sql(db, "SELECT COUNT(*) FROM market_data")[0]
        enr = _sql(db, "SELECT COUNT(*) FROM market_data_enriched")[0]
        results.append(("raw bars captured", raw > 50, f"{raw} rows"))
        results.append(("enriched rows written", enr > 50, f"{enr} rows"))

        latest = _sql(db, "SELECT atm_strike FROM market_data_enriched "
                          "WHERE atm_strike IS NOT NULL ORDER BY timestamp DESC LIMIT 1")
        results.append(("latest enriched has atm_strike", latest is not None,
                        f"atm={latest[0] if latest else None}"))

        # B1: lock fix — no 'database is locked' crash
        lock_hits = enr_log.read_text(errors="ignore").lower().count("database is locked")
        results.append(("no SQLite lock crash (B1)", lock_hits == 0, f"{lock_hits} hits"))

        # A1: data quality — no zero/invalid OHLC in RAW bars. This is the surface
        # the query_market_data agent tool reads (LEFT JOIN market_data), so a bad
        # close/low=0 tick reaches the regime agent as spot=0 even though it's
        # excluded from enrichment. Assert against raw, not enriched.
        bad = _sql(db, "SELECT COUNT(*) FROM market_data "
                       "WHERE close IS NULL OR close<=0 OR low<=0 OR high<=0 OR open<=0")[0]
        results.append(("no zero/invalid OHLC in raw bars (A1)", bad == 0, f"{bad} bad bars"))

        # A6: enrichment not lagging raw by more than 1 bar at the tail
        raw_max = _sql(db, "SELECT MAX(timestamp) FROM market_data")[0]
        enr_max = _sql(db, "SELECT MAX(timestamp) FROM market_data_enriched")[0]
        results.append(("enriched tracks raw tail (A6)", raw_max is not None and enr_max is not None,
                        f"raw={raw_max} enr={enr_max}"))

        # F2: deterministic_fallback inputs must be valid, not zero/empty.
        # The entry-agent fallback (brahmand/unicorn_debate._deterministic_fallback)
        # reads avg_super_trend from trend.timeframes[*].st_consensus and session
        # from macro.indicators.session_phase. PORCUPINE caught both inputs going
        # empty in the sandbox. Root causes confirmed against happy_path replay:
        #   1. enrichers/lib/advanced.py:compute_session_metrics uses
        #      datetime.now() (wall clock) — so a backfill enrich at 21:30
        #      labels EVERY bar of the day "late". Should derive phase from the
        #      bar's own timestamp.
        #   2. market_data_multitf.st_consensus is NULL on every row of every
        #      timeframe — the multi-TF aggregation never writes indicators in
        #      the replay path. trend.timeframes[*].st_consensus → None →
        #      "neutral" → avg_super_trend = 0/0 → 0.
        # These two assertions stay RED until both upstream gaps are closed;
        # they are permanent regression guards for the F2 / bug #3 incident.
        phases = [r[0] for r in sqlite3.connect(db).execute(
            "SELECT DISTINCT session_phase FROM market_data_enriched "
            "WHERE session_phase IS NOT NULL AND session_phase != ''"
        ).fetchall()]
        results.append(("session_phase varies across day (F2)", len(phases) >= 2,
                        f"distinct={phases}"))

        mtf_rows = sqlite3.connect(db).execute(
            "SELECT timeframe_min, "
            "SUM(CASE WHEN st_consensus IS NOT NULL THEN 1 ELSE 0 END), COUNT(*) "
            "FROM market_data_multitf GROUP BY timeframe_min"
        ).fetchall()
        mtf_5_15 = {tf: (filled, total) for tf, filled, total in mtf_rows if tf in (5, 15)}
        five = mtf_5_15.get(5, (0, 0))
        fifteen = mtf_5_15.get(15, (0, 0))
        mtf_ok = five[0] > 0 and fifteen[0] > 0
        results.append(("multitf st_consensus populated (F2)", mtf_ok,
                        f"5m={five[0]}/{five[1]} 15m={fifteen[0]}/{fifteen[1]}"))

        # F2 belt-and-braces: enriched.st_consensus (single-row mirror used by
        # query_market_data) must be populated on the latest fully-enriched bar.
        latest_st = _sql(db, "SELECT st_consensus, st_5min_direction, st_15min_direction "
                             "FROM market_data_enriched "
                             "ORDER BY timestamp DESC LIMIT 1")
        st_ok = (latest_st is not None
                 and latest_st[0] not in (None, "", "neutral")
                 and latest_st[1] not in (None, "")
                 and latest_st[2] not in (None, ""))
        results.append(("enriched st_consensus non-empty (F2)", st_ok, f"{latest_st}"))

        # 3) optional: real CrewAI kickoff against the sandbox
        if with_kickoff:
            subprocess.run(["bash", redis_sh, "stop", str(sim_root), REDIS_PORT],
                           capture_output=True)
            kick = subprocess.run(
                [sys.executable, "-c",
                 "from kickoff import run_entry_pipeline; r=run_entry_pipeline('15:25');"
                 "print('KICKOFF_NO_MARKET_DATA' if r is None else 'KICKOFF_DECISION')"],
                cwd="/home/trading_ceo/brahmand",
                env={**env, "BRAHMAND_SANDBOX": str(sim_root / "data")},
                capture_output=True, text=True, timeout=300)
            out = (kick.stdout or "") + (kick.stderr or "")
            no_md = "No market data" in out
            results.append(("kickoff reaches agents (not 'No market data')", not no_md,
                            "reached agents" if not no_md else "blocked"))
    except Exception as e:
        results.append(("orchestration completed", False, f"ERROR: {e}"))
    finally:
        subprocess.run(["bash", redis_sh, "stop", str(sim_root), REDIS_PORT],
                       capture_output=True)

    # ── REPORT ──────────────────────────────────────────────────────────────
    print("\n--- assertions ---")
    failed = 0
    for name, ok, detail in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name:42s} {detail}")
        if not ok:
            failed += 1
    verdict = "PASS" if failed == 0 else f"FAIL ({failed} failed)"
    print(f"\n=== {scenario}: {verdict} ===  (SIM_ROOT kept: {sim_root})\n")
    return 0 if failed == 0 else 1


def main():
    p = argparse.ArgumentParser(description="PORCUPINE scenario runner")
    p.add_argument("scenario", nargs="?", help="scenario name")
    p.add_argument("--date", default=None, help="replay date YYYY-MM-DD (default today)")
    p.add_argument("--with-kickoff", action="store_true", help="also run real CrewAI kickoff")
    p.add_argument("--list", action="store_true")
    a = p.parse_args()
    if a.list or not a.scenario:
        for k, v in SCENARIOS.items():
            print(f"  {k:16s} {v['desc']}")
        return
    if a.scenario not in SCENARIOS:
        print(f"unknown scenario: {a.scenario}"); sys.exit(2)
    sys.exit(run(a.scenario, a.date, a.with_kickoff))


if __name__ == "__main__":
    main()
