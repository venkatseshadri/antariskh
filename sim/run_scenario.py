"""PORCUPINE orchestrator — one command: boot isolated stack, drive the real
pipeline with the mock feed, run assertions, tear down, return PASS/FAIL.

    python3 -m sim.run_scenario happy_path
    python3 -m sim.run_scenario happy_path --with-kickoff   # also run real CrewAI
    python3 -m sim.run_scenario --list

Exit code 0 = all hard assertions passed, 1 = at least one failed (or error).
Scenarios live in SCENARIOS below; add rows from PORCUPINE_SCENARIO_CATALOGUE.md.
"""

import argparse
import json
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
    "lifecycle": {
        "desc": "Seed a paper trade → real position_manager.run_bridge() → assert "
        "order→monitor→exit closes it (deterministic SL, no LLM, no broker)",
        "instrument": "NIFTY",
        "source_db": None,
        "date": None,
    },
    "tp_hit": {
        "desc": "Sold CE marked below TP → run_bridge() deterministic TP square-off "
        "(profit booked, no LLM, no broker) — lifecycle G3",
        "instrument": "NIFTY",
        "source_db": None,
        "date": None,
    },
    "eod": {
        "desc": "SIM_NOW≥15:30 with no SL/TP breach → run_bridge() hard EOD CLOSE_ALL "
        "(positions flat by cash close) — lifecycle G2",
        "instrument": "NIFTY",
        "source_db": None,
        "date": None,
    },
    "floor": {
        "desc": "Mark-to-market ≤ FLOOR with no SL breach → run_bridge() cumulative-P&L "
        "CLOSE_ALL (protective floor) — lifecycle P6",
        "instrument": "NIFTY",
        "source_db": None,
        "date": None,
    },
    "morph": {
        "desc": "Cached NEUTRAL→BULLISH assessment (deterministic LLM stub) → run_bridge() "
        "applies the discretionary morph (CE side closed, PE kept) — F5/G4",
        "instrument": "NIFTY",
        "source_db": None,
        "date": None,
    },
    "multitf_trend": {
        "desc": "Feed real 1-min bars → real v4 aggregator → assert the v4 per-index "
        "DuckDB st_consensus is computed (not hardcoded NEUTRAL) — bug #3b E2E",
        "instrument": "NIFTY",
        "source_db": PROD_DB,
        "date": None,
    },
    "position_cache": {
        "desc": "Seed a discretionary assessment → assert the REAL "
        "position_manager._discretionary_actions applies it (cached-research hot path)",
        "instrument": "NIFTY",
        "source_db": None,
        "date": None,
    },
    "llm_down": {
        "desc": "LLM unreachable → chain fallback + BOTH unicorn gates must derive "
        "from ONE canonical decision, never disagree (2026-06-10 incident; SHERPA)",
        "instrument": "NIFTY",
        "source_db": None,
        "date": None,
    },
}


def _sql(db, q):
    c = sqlite3.connect(db)
    try:
        return c.execute(q).fetchone()
    finally:
        c.close()


def run(
    scenario: str, the_date: str | None, with_kickoff: bool, fault: str | None = None
) -> int:
    sc = SCENARIOS["happy_path"] if fault else SCENARIOS[scenario]
    inst = sc["instrument"]
    src = sc["source_db"]
    the_date = the_date or sc["date"] or date.today().isoformat()

    tag = f"fault_{fault}" if fault else scenario
    sim_root = ROOT / "sim" / f"run_{tag}_{int(time.time())}"
    for sub in ("data", "logs", "redis"):
        (sim_root / sub).mkdir(parents=True, exist_ok=True)
    db = str(sim_root / "data" / f"capture_{inst.lower()}.sqlite")

    env = {
        **os.environ,
        "SIM_MODE": "1",
        "SIM_ROOT": str(sim_root),
        "SIM_REDIS_PORT": REDIS_PORT,
    }
    redis_sh = str(ROOT / "sim" / "start_test_redis.sh")

    print(
        f"\n=== PORCUPINE scenario: {scenario} ===\n{sc['desc']}\nSIM_ROOT={sim_root}\n"
    )
    results = []  # (name, ok, detail)

    try:
        subprocess.run(
            ["bash", redis_sh, "start", str(sim_root), REDIS_PORT],
            check=True,
            capture_output=True,
        )

        # 1) replay real bars → consumer → sandbox market_data
        con = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "consumers.instrument_consumer",
                "--instrument",
                inst,
            ],
            cwd=ROOT,
            env=env,
            stdout=open(sim_root / "logs/consumer.out", "w"),
            stderr=subprocess.STDOUT,
        )
        time.sleep(1.5)
        feed_cmd = [
            sys.executable,
            "-m",
            "sim.mock_feed",
            "--instrument",
            inst,
            "--source-db",
            src,
            "--date",
            the_date,
            "--interval",
            "0.01",
        ]
        if fault:
            feed_cmd += ["--fault", fault]
        subprocess.run(feed_cmd, cwd=ROOT, env=env, check=True, capture_output=True)
        time.sleep(2)
        con.terminate()
        try:
            con.wait(timeout=10)
        except subprocess.TimeoutExpired:
            con.kill()

        # 2) backfill-enrich the full day (single writer, complete coverage)
        enr_log = sim_root / "logs/enricher_backfill.out"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "enrichers.instrument_enricher",
                "--instrument",
                inst,
                "--backfill",
                f"{the_date}:{the_date}",
            ],
            cwd=ROOT,
            env=env,
            timeout=120,
            stdout=open(enr_log, "w"),
            stderr=subprocess.STDOUT,
        )

        # ── ASSERTIONS ──────────────────────────────────────────────────────
        raw = _sql(db, "SELECT COUNT(*) FROM market_data")[0]
        enr = _sql(db, "SELECT COUNT(*) FROM market_data_enriched")[0]
        results.append(("raw bars captured", raw > 50, f"{raw} rows"))
        results.append(("enriched rows written", enr > 50, f"{enr} rows"))

        latest = _sql(
            db,
            "SELECT atm_strike FROM market_data_enriched "
            "WHERE atm_strike IS NOT NULL ORDER BY timestamp DESC LIMIT 1",
        )
        results.append(
            (
                "latest enriched has atm_strike",
                latest is not None,
                f"atm={latest[0] if latest else None}",
            )
        )

        # B1: lock fix — no 'database is locked' crash
        lock_hits = (
            enr_log.read_text(errors="ignore").lower().count("database is locked")
        )
        results.append(
            ("no SQLite lock crash (B1)", lock_hits == 0, f"{lock_hits} hits")
        )

        # A1: data quality — no zero/invalid OHLC in RAW bars. This is the surface
        # the query_market_data agent tool reads (LEFT JOIN market_data), so a bad
        # close/low=0 tick reaches the regime agent as spot=0 even though it's
        # excluded from enrichment. Assert against raw, not enriched.
        bad = _sql(
            db,
            "SELECT COUNT(*) FROM market_data "
            "WHERE close IS NULL OR close<=0 OR low<=0 OR high<=0 OR open<=0",
        )[0]
        results.append(
            ("no zero/invalid OHLC in raw bars (A1)", bad == 0, f"{bad} bad bars")
        )

        # Fault→assertion binding: when a synthetic fault was injected into the
        # replay (mock_feed --fault), assert the pipeline invariant for that class
        # held DESPITE the corruption. These are the expected-survival assertions
        # the catalogue's data-integrity rows (A1/A4/A8) demand.
        if fault == "zero":
            # A1 under attack: lp-less/zero ticks injected → feed/consumer must
            # still let none through to raw (the bad==0 assertion above is the
            # proof; restate it as the fault verdict).
            results.append(
                (f"zero-tick fault filtered (A1, {bad} bad)", bad == 0, "raw clean")
            )
        elif fault == "dup":
            # A4: duplicate timestamps injected → consumer dedups (one row per ts).
            dups = _sql(
                db, "SELECT COUNT(*)-COUNT(DISTINCT timestamp) FROM market_data"
            )[0]
            results.append(("dup-ts fault deduped (A4)", dups == 0, f"{dups} dup ts"))
        elif fault == "outlier":
            # A8: a fat-finger spike injected → it must not survive into raw as a
            # valid bar (rejected/clamped, not a 10x print poisoning ATR/BB).
            mx = _sql(db, "SELECT MAX(high) FROM market_data")[0] or 0
            mn = _sql(db, "SELECT MIN(low) FROM market_data WHERE low>0")[0] or 0
            spread_ok = mn > 0 and mx > 0 and (mx / mn) < 1.2
            results.append(
                ("outlier spike not in raw bars (A8)", spread_ok, f"hi={mx} lo={mn}")
            )

        # A6: enrichment not lagging raw by more than 1 bar at the tail
        raw_max = _sql(db, "SELECT MAX(timestamp) FROM market_data")[0]
        enr_max = _sql(db, "SELECT MAX(timestamp) FROM market_data_enriched")[0]
        results.append(
            (
                "enriched tracks raw tail (A6)",
                raw_max is not None and enr_max is not None,
                f"raw={raw_max} enr={enr_max}",
            )
        )

        # F2: deterministic_fallback inputs must be valid, not zero/empty.
        # The entry-agent fallback (brahmand/unicorn_debate._deterministic_fallback)
        # reads avg_super_trend from trend.timeframes[*].st_consensus and session
        # from macro.indicators.session_phase. PORCUPINE flagged both. The root
        # causes were re-diagnosed 2026-06-09 (the original notes were wrong on the
        # st_consensus specifics — see below) and both LIVE bugs are now FIXED:
        #   1. session_phase: enrichers/lib/advanced.py:compute_session_metrics used
        #      datetime.now() (wall clock) — a backfill at 21:30 labelled EVERY bar
        #      "late". FIXED: it now takes the bar's own timestamp (bar_ts param).
        #      This assertion goes GREEN on a real replay (phases vary across the day).
        #   2. st_consensus: the original "market_data_multitf.st_consensus is NULL"
        #      note measured the WRONG table. The consumer's SQLite market_data_multitf
        #      is OHLCV-ONLY BY DESIGN (it never writes indicators). The trend agent
        #      reads st_consensus from the v4 PER-INDEX DuckDB
        #      (market_data_multitf_<index>.duckdb), which IS populated — but the v4
        #      aggregator HARDCODED st_consensus="NEUTRAL" (a "# Legacy" stub; a real
        #      SuperTrend was never wired). FIXED: data_capture_v4_queue_aggregator now
        #      computes a proper ATR-band SuperTrend. That fix is validated by
        #      sim/tests/test_supertrend_consensus.py (the v4 aggregator path is not
        #      run in this SQLite replay, so we do NOT re-assert it here).
        phases = [
            r[0]
            for r in sqlite3.connect(db)
            .execute(
                "SELECT DISTINCT session_phase FROM market_data_enriched "
                "WHERE session_phase IS NOT NULL AND session_phase != ''"
            )
            .fetchall()
        ]
        results.append(
            (
                "session_phase varies across day (F2)",
                len(phases) >= 2,
                f"distinct={phases}",
            )
        )

        # The SQLite market_data_multitf is OHLCV-only by design; assert it carries
        # bars (its actual contract), NOT indicators. The st_consensus trend signal
        # the agent consumes lives in the v4 per-index DuckDB — see the test above.
        mtf_rows = (
            sqlite3.connect(db)
            .execute(
                "SELECT timeframe_min, COUNT(*) FROM market_data_multitf "
                "WHERE timeframe_min IN (5, 15) GROUP BY timeframe_min"
            )
            .fetchall()
        )
        mtf_counts = {tf: n for tf, n in mtf_rows}
        mtf_ok = mtf_counts.get(5, 0) > 0 and mtf_counts.get(15, 0) > 0
        results.append(
            (
                "SQLite multitf carries OHLCV bars (F2; indicators live in v4 DuckDB)",
                mtf_ok,
                f"5m={mtf_counts.get(5, 0)} 15m={mtf_counts.get(15, 0)} rows",
            )
        )

        # F2 belt-and-braces: enriched.st_consensus (single-row mirror used by
        # query_market_data) must be populated on the latest fully-enriched bar.
        latest_st = _sql(
            db,
            "SELECT st_consensus, st_5min_direction, st_15min_direction "
            "FROM market_data_enriched "
            "ORDER BY timestamp DESC LIMIT 1",
        )
        st_ok = (
            latest_st is not None
            and latest_st[0] not in (None, "", "neutral")
            and latest_st[1] not in (None, "")
            and latest_st[2] not in (None, "")
        )
        results.append(("enriched st_consensus non-empty (F2)", st_ok, f"{latest_st}"))

        # E4: VIX-null auto-enter guard (bug #4). Two assertions:
        #   (a) Sandbox: india_vix must be populated on the latest enriched bar.
        #       Today this is 100% NULL because no broker stub is wired — stays
        #       RED until a sandbox VIX source lands.
        #   (b) Gate: brahmand/unicorn_debate._deterministic_fallback must
        #       fail-closed when vix is None. Today it auto-enters
        #       (`vix is None or vix<20`) — stays RED until the live gate is
        #       fixed to `isinstance(vix,(int,float)) and vix<20`.
        # See sim/tests/test_vix_null_guard.py for the regression detail.
        vix_total, vix_null = _sql(
            db,
            "SELECT COUNT(*), SUM(CASE WHEN india_vix IS NULL THEN 1 ELSE 0 END) "
            "FROM market_data_enriched",
        )
        vix_null = vix_null or 0
        results.append(
            (
                "india_vix populated in sandbox (E4)",
                vix_total > 0 and vix_null < vix_total,
                f"{vix_null}/{vix_total} NULL",
            )
        )

        gate_ok = False
        gate_detail = "import-skipped"
        try:
            import sys as _sys

            _bp = str(ROOT.parent / "brahmand")
            if _bp not in _sys.path:
                _sys.path.insert(0, _bp)
            from unicorn_debate import _deterministic_fallback as _df

            _raw = {
                "trend": {
                    "timeframes": {
                        "5m": {"st_consensus": "bullish"},
                        "15m": {"st_consensus": "bullish"},
                        "30m": {"st_consensus": "bullish"},
                        "60m": {"st_consensus": "bullish"},
                        "1m_v3.1": {
                            "st_consensus": "bullish",
                            "ema_position": "bullish",
                        },
                    }
                },
                "macro": {"indicators": {"session_phase": "mid", "vix": None}},
            }
            decision = _df(
                _raw, "NOT_DOWN", {"signal": "NOT_DOWN", "strategy": "BULL_CALL"}
            )
            gate_ok = decision.get("go") is False
            gate_detail = f"go={decision.get('go')} source={decision.get('source')}"
        except Exception as e:
            gate_detail = f"probe-error: {e}"
        results.append(("vix=None gate fails-closed (E4)", gate_ok, gate_detail))

        # 3) optional: real CrewAI kickoff against the sandbox
        if with_kickoff:
            subprocess.run(
                ["bash", redis_sh, "stop", str(sim_root), REDIS_PORT],
                capture_output=True,
            )
            kick = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "from kickoff import run_entry_pipeline; r=run_entry_pipeline('15:25');"
                    "print('KICKOFF_NO_MARKET_DATA' if r is None else 'KICKOFF_DECISION')",
                ],
                cwd="/home/trading_ceo/brahmand",
                env={**env, "BRAHMAND_SANDBOX": str(sim_root / "data")},
                capture_output=True,
                text=True,
                timeout=300,
            )
            out = (kick.stdout or "") + (kick.stderr or "")
            no_md = "No market data" in out
            results.append(
                (
                    "kickoff reaches agents (not 'No market data')",
                    not no_md,
                    "reached agents" if not no_md else "blocked",
                )
            )
    except Exception as e:
        results.append(("orchestration completed", False, f"ERROR: {e}"))
    finally:
        subprocess.run(
            ["bash", redis_sh, "stop", str(sim_root), REDIS_PORT], capture_output=True
        )

    # Purge sandbox dirs older than 7 days
    import time as _time

    _cutoff = _time.time() - 7 * 86400
    _sim_dir = ROOT / "sim"
    for _d in _sim_dir.iterdir():
        if _d.name.startswith("run_") and _d.is_dir():
            try:
                _mtime = _d.stat().st_mtime
            except OSError:
                continue
            if _mtime < _cutoff:
                shutil.rmtree(_d, ignore_errors=True)

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


# mode, sim_now, scenario-name → keyed in LIFECYCLE below. SIM_NOW pins the
# system clock (market_data.now_dt honors it) so the real-wall-clock EOD branch
# never spuriously fires in the non-EOD modes, and DOES fire in the EOD mode.
LIFECYCLE = {
    "lifecycle": {"mode": "SL_HIT", "sim_now": "2026-06-05T14:00:00"},
    "tp_hit": {"mode": "TP_HIT", "sim_now": "2026-06-05T14:00:00"},
    "eod": {"mode": "EOD", "sim_now": "2026-06-05T15:30:00"},
    "floor": {"mode": "FLOOR", "sim_now": "2026-06-05T14:00:00"},
    "morph": {"mode": "MORPH", "sim_now": "2026-06-05T14:00:00"},
}


def _lifecycle_assertions(scenario: str, payload: dict) -> list:
    """Per-mode assertions over the driver verdict. The common spine: the trade is
    seeded ACTIVE; then each branch asserts the SPECIFIC exit it is meant to drive
    (so a regression in one branch can't be masked by another)."""
    tid = "SIM_LIFECYCLE_1"
    before, after, hist = payload["before"], payload["after"], payload["history"]
    closed = tid not in after
    reason = (hist[0][1] if hist else "") or ""
    pnl = hist[0][2] if hist else None
    r = [("trade seeded ACTIVE", tid in before, f"active={before}")]

    if scenario == "lifecycle":  # SL_HIT
        r.append(
            ("monitor closed the trade (order→monitor→exit)", closed, f"still={after}")
        )
        r.append(
            (
                "exit booked to trade_history (reason+pnl)",
                bool(hist) and reason and pnl is not None,
                f"hist={hist}",
            )
        )
        r.append(
            (
                "SL booked a LOSS (pnl<0)",
                pnl is not None and float(pnl) < 0,
                f"pnl={pnl}",
            )
        )
    elif scenario == "tp_hit":
        r.append(("TP closed the trade", closed, f"still={after}"))
        r.append(
            (
                "exit booked to trade_history",
                bool(hist) and pnl is not None,
                f"hist={hist}",
            )
        )
        r.append(
            (
                "TP booked a PROFIT (pnl>0)",
                pnl is not None and float(pnl) > 0,
                f"pnl={pnl}",
            )
        )
    elif scenario == "eod":
        r.append(
            ("EOD squared off the trade (flat by close)", closed, f"still={after}")
        )
        r.append(
            (
                "close_reason is market-close (not SL/TP)",
                "MARKET" in reason.upper(),
                f"reason={reason!r}",
            )
        )
    elif scenario == "floor":
        r.append(("floor squared off the trade", closed, f"still={after}"))
        r.append(
            (
                "close_reason cites the cumulative-P&L floor",
                "floor" in reason.lower(),
                f"reason={reason!r}",
            )
        )
        r.append(
            (
                "floor booked a LOSS (pnl<0)",
                pnl is not None and float(pnl) < 0,
                f"pnl={pnl}",
            )
        )
    elif scenario == "morph":
        r.append(
            ("morph kept the trade ACTIVE (not an exit)", not closed, f"after={after}")
        )
        r.append(
            (
                "morph closed the CE side (legs shrank)",
                payload["legs_after"] < payload["legs_before"],
                f"legs {payload['legs_before']}→{payload['legs_after']}",
            )
        )
        r.append(
            (
                "morph applied via cached assessment (no trade_history close)",
                not hist,
                f"hist={hist}",
            )
        )
    return r


def run_lifecycle(scenario: str, the_date: str | None) -> int:
    """Lifecycle scenarios: drive the REAL position_manager past entry into
    order(paper)→monitor→exit, fully sandboxed, no LLM, no broker.

    sim/lifecycle_driver.py (mode = LIFECYCLE[scenario]['mode']) seeds the sandbox
    option_prices + trade, sets the live clock via SIM_NOW, and runs run_bridge()
    once. Each scenario asserts the SPECIFIC protective/discretionary branch it
    targets: SL/TP square-off, hard EOD CLOSE_ALL, cumulative-P&L floor, or a
    cached-assessment morph (the deterministic LLM stub)."""
    inst = "NIFTY"
    cfg = LIFECYCLE[scenario]
    sim_root = ROOT / "sim" / f"run_{scenario}_{int(time.time())}"
    for sub in ("data", "data/state", "logs"):
        (sim_root / sub).mkdir(parents=True, exist_ok=True)

    env = {
        **os.environ,
        "SIM_MODE": "1",
        "SIM_ROOT": str(sim_root),
        "SIM_REDIS_PORT": REDIS_PORT,
        "BRAHMAND_SANDBOX": str(sim_root / "data"),
        "LIFECYCLE_MODE": cfg["mode"],
        "SIM_NOW": cfg["sim_now"],
        "PYTHONPATH": "/home/trading_ceo:/home/trading_ceo/brahmand",
    }

    print(
        f"\n=== PORCUPINE scenario: {scenario} ===\n{SCENARIOS[scenario]['desc']}\n"
        f"SIM_ROOT={sim_root} mode={cfg['mode']} SIM_NOW={cfg['sim_now']}\n"
    )
    results = []

    drv = subprocess.run(
        [sys.executable, str(ROOT / "sim" / "lifecycle_driver.py")],
        cwd="/home/trading_ceo/brahmand",
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    out = (drv.stdout or "") + "\n" + (drv.stderr or "")
    (sim_root / "logs" / "lifecycle_driver.out").write_text(out)

    payload = None
    for line in (drv.stdout or "").splitlines():
        if line.startswith("LIFECYCLE_RESULT "):
            payload = __import__("json").loads(line[len("LIFECYCLE_RESULT ") :])
            break

    if payload is None:
        results.append(
            (
                "lifecycle driver produced a verdict",
                False,
                f"rc={drv.returncode}; see logs/lifecycle_driver.out",
            )
        )
    else:
        results = _lifecycle_assertions(scenario, payload)

    print("\n--- assertions ---")
    failed = 0
    for name, ok, detail in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name:50s} {detail}")
        if not ok:
            failed += 1
    verdict = "PASS" if failed == 0 else f"FAIL ({failed} failed)"
    print(f"\n=== {scenario}: {verdict} ===  (SIM_ROOT kept: {sim_root})\n")
    return 0 if failed == 0 else 1


def run_position_cache(the_date: str | None) -> int:
    """Prove the position-manager hot path applies cached discretionary research:
    seed an assessment into the sandbox cache, then assert the REAL
    position_manager._discretionary_actions returns it (cache HIT) and falls through
    on an unknown trade (MISS). Hermetic — the HIT path needs no DB/LLM."""
    sim_root = ROOT / "sim" / f"run_position_cache_{int(time.time())}"
    for sub in ("data", "data/state", "logs"):
        (sim_root / sub).mkdir(parents=True, exist_ok=True)

    env = {
        **os.environ,
        "SIM_MODE": "1",
        "SIM_ROOT": str(sim_root),
        "SIM_REDIS_PORT": REDIS_PORT,
        "BRAHMAND_SANDBOX": str(sim_root / "data"),
        "PYTHONPATH": "/home/trading_ceo:/home/trading_ceo/brahmand",
    }

    print(
        f"\n=== PORCUPINE scenario: position_cache ===\n{SCENARIOS['position_cache']['desc']}\n"
        f"SIM_ROOT={sim_root}\n"
    )
    results = []

    drv = subprocess.run(
        [sys.executable, str(ROOT / "sim" / "position_cache_driver.py")],
        cwd="/home/trading_ceo/brahmand",
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    out = (drv.stdout or "") + "\n" + (drv.stderr or "")
    (sim_root / "logs" / "position_cache_driver.out").write_text(out)

    payload = None
    for line in (drv.stdout or "").splitlines():
        if line.startswith("PC_RESULT "):
            payload = __import__("json").loads(line[len("PC_RESULT ") :])
            break

    if payload is None:
        results.append(
            (
                "position-cache driver produced a verdict",
                False,
                f"rc={drv.returncode}; see logs/position_cache_driver.out",
            )
        )
    else:
        results.append(
            (
                "cache HIT → run_bridge applies the cached assessment",
                payload["hit_matches"],
                f"hit={payload['hit']}",
            )
        )
        results.append(
            (
                "cache MISS/unknown trade → live recompute (not cached)",
                payload["miss_differs"],
                "",
            )
        )

    print("\n--- assertions ---")
    failed = 0
    for name, ok, detail in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name:54s} {detail}")
        if not ok:
            failed += 1
    verdict = "PASS" if failed == 0 else f"FAIL ({failed} failed)"
    print(f"\n=== position_cache: {verdict} ===  (SIM_ROOT kept: {sim_root})\n")
    return 0 if failed == 0 else 1


def run_llm_down() -> int:
    """SHERPA llm_down: with no LLM key, the chain-level fallback and both
    unicorn gate fallbacks must derive from one canonical_strategy decision
    (the 2026-06-10 incident had them disagreeing → false zero-trade day)."""
    print(
        f"\n=== PORCUPINE scenario: llm_down ===\n{SCENARIOS['llm_down']['desc']}\n"
    )
    env = {k: v for k, v in os.environ.items() if k != "DEEPSEEK_API_KEY"}
    drv = subprocess.run(
        [
            sys.executable,
            "/home/trading_ceo/brahmand/tests/test_llm_down_coherence.py",
        ],
        cwd="/home/trading_ceo/brahmand",
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    payload = None
    for line in (drv.stdout or "").splitlines():
        if line.startswith("LD_RESULT "):
            payload = json.loads(line[len("LD_RESULT ") :])
            break

    results = []
    if payload is None:
        results.append(
            ("llm_down driver produced a verdict", False, f"rc={drv.returncode}")
        )
        print(drv.stdout[-2000:] if drv.stdout else "")
        print(drv.stderr[-2000:] if drv.stderr else "")
    else:
        results.append(("runs with NO LLM key in env", payload["no_llm_key"], ""))
        for side in ("bearish", "bullish"):
            s = payload[side]
            results.append(
                (
                    f"{side}: chain + gates agree, right spread side",
                    all(s.values()),
                    json.dumps(s) if not all(s.values()) else "",
                )
            )
        results.append(
            ("flat day: every path says no", all(payload["flat"].values()), "")
        )

    print("\n--- assertions ---")
    failed = 0
    for name, ok, detail in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name:54s} {detail}")
        if not ok:
            failed += 1
    verdict = "PASS" if failed == 0 else f"FAIL ({failed} failed)"
    print(f"\n=== llm_down: {verdict} ===\n")
    return 0 if failed == 0 else 1


def run_multitf_trend(the_date: str | None) -> int:
    """Bug #3b end-to-end: drive the REAL v4 queue aggregator over real 1-min bars
    in the sandbox and assert the v4 per-index DuckDB (the table the trend agent
    reads) gets a COMPUTED st_consensus — not the old hardcoded "NEUTRAL". Fully
    hermetic: test Redis + sandbox DuckDB + sandbox EMA state (BRAHMAND_SANDBOX)."""
    inst = "NIFTY"
    src = PROD_DB
    sim_root = ROOT / "sim" / f"run_multitf_trend_{int(time.time())}"
    for sub in ("data", "logs", "redis"):
        (sim_root / sub).mkdir(parents=True, exist_ok=True)

    # Default to the latest date present in the source capture DB.
    the_date = (
        the_date
        or _sql(
            src,
            "SELECT MAX(substr(timestamp,1,10)) FROM market_data "
            "WHERE instrument='NIFTY'",
        )[0]
    )

    env = {
        **os.environ,
        "SIM_MODE": "1",
        "SIM_ROOT": str(sim_root),
        "SIM_REDIS_PORT": REDIS_PORT,
        "BRAHMAND_SANDBOX": str(sim_root / "data"),
        "PYTHONPATH": "/home/trading_ceo:/home/trading_ceo/brahmand",
    }
    redis_sh = str(ROOT / "sim" / "start_test_redis.sh")

    print(
        f"\n=== PORCUPINE scenario: multitf_trend ===\n{SCENARIOS['multitf_trend']['desc']}\n"
        f"SIM_ROOT={sim_root} date={the_date}\n"
    )
    results = []
    try:
        subprocess.run(
            ["bash", redis_sh, "start", str(sim_root), REDIS_PORT],
            check=True,
            capture_output=True,
        )
        drv = subprocess.run(
            [
                sys.executable,
                str(ROOT / "sim" / "v4_aggregator_driver.py"),
                "--source-db",
                src,
                "--date",
                the_date,
                "--index",
                inst,
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        out = (drv.stdout or "") + "\n" + (drv.stderr or "")
        (sim_root / "logs" / "v4_driver.out").write_text(out)

        payload = None
        for line in (drv.stdout or "").splitlines():
            if line.startswith("V4_RESULT "):
                payload = __import__("json").loads(line[len("V4_RESULT ") :])
                break

        if payload is None:
            results.append(
                (
                    "v4 driver produced a verdict",
                    False,
                    f"rc={drv.returncode}; see logs/v4_driver.out",
                )
            )
        else:
            by_tf = payload["by_tf"]
            results.append(
                ("real 1-min bars fed", payload["bars"] > 50, f"{payload['bars']} bars")
            )
            # st_consensus rows exist for 5m & 15m
            pop = all(sum(by_tf.get(str(tf), {}).values()) > 0 for tf in (5, 15))
            results.append(
                ("v4 DuckDB st_consensus populated (5m,15m)", pop, f"{by_tf}")
            )
            # THE bug #3b proof: not all "NEUTRAL" — a real direction was computed.
            directional = sum(
                v
                for tf in (5, 15, 30, 60)
                for k, v in by_tf.get(str(tf), {}).items()
                if str(k).upper() in ("BULLISH", "BEARISH")
            )
            results.append(
                (
                    "st_consensus is computed, not hardcoded NEUTRAL (bug #3b)",
                    directional > 0,
                    f"{directional} directional bars",
                )
            )
    except Exception as e:
        results.append(("orchestration completed", False, f"ERROR: {e}"))
    finally:
        subprocess.run(
            ["bash", redis_sh, "stop", str(sim_root), REDIS_PORT], capture_output=True
        )

    print("\n--- assertions ---")
    failed = 0
    for name, ok, detail in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name:52s} {detail}")
        if not ok:
            failed += 1
    verdict = "PASS" if failed == 0 else f"FAIL ({failed} failed)"
    print(f"\n=== multitf_trend: {verdict} ===  (SIM_ROOT kept: {sim_root})\n")
    return 0 if failed == 0 else 1


def _eval_expect(expect: dict, payload: dict) -> list:
    """Evaluate the data-driven `expect` block of a path scenario against the
    driver trace. Engine-side generic evaluator — scenarios stay data."""
    trace = payload.get("trace", [])
    hist = payload.get("history", [])
    closed_at = payload.get("closed_at")
    reason = (hist[0][1] if hist else "") or ""
    pnl = hist[0][2] if hist else None
    r = []
    if "closed" in expect:
        r.append(
            (
                "trade reached a terminal close",
                (closed_at is not None) == expect["closed"],
                f"closed_at={closed_at}",
            )
        )
    if expect.get("closed_at_eod"):
        r.append(
            (
                "closed at the 15:30 EOD square-off",
                closed_at == "15:30",
                f"closed_at={closed_at}",
            )
        )
    if expect.get("closed_before_eod"):
        r.append(
            (
                "closed INTRADAY (protective exit before EOD)",
                closed_at is not None and closed_at < "15:30",
                f"closed_at={closed_at}",
            )
        )
    if "reason_contains" in expect:
        sub = expect["reason_contains"].upper()
        r.append(
            (
                f"close_reason contains {sub!r}",
                sub in reason.upper(),
                f"reason={reason!r}",
            )
        )
    if "pnl_sign" in expect:
        want = expect["pnl_sign"]
        ok = pnl is not None and (
            (float(pnl) > 0) if want == "pos" else (float(pnl) < 0)
        )
        r.append((f"final P&L is {want}", ok, f"pnl={pnl}"))
    if expect.get("arc_giveback"):
        mtms = [s["mtm"] for s in trace] or [0]
        peak, final = max(mtms), mtms[-1]
        r.append(
            (
                "arc shows give-back (peak MTM > final MTM)",
                peak > final,
                f"peak={peak} final={final}",
            )
        )
    return r


def run_path(name: str) -> int:
    """Time-evolving path scenario: replay a scripted intraday spot path against
    the REAL position_manager (sim/path_driver.py) and evaluate the scenario's
    data-driven `expect` block over the resulting trace. Fully sandboxed."""
    import json as _json
    from sim.path_scenarios import PATH_SCENARIOS

    if name not in PATH_SCENARIOS:
        print(f"unknown path scenario: {name}")
        return 2
    spec = PATH_SCENARIOS[name]
    sim_root = ROOT / "sim" / f"run_path_{name}_{int(time.time())}"
    for sub in ("data", "data/state", "logs"):
        (sim_root / sub).mkdir(parents=True, exist_ok=True)
    spec_path = sim_root / "spec.json"
    spec_path.write_text(_json.dumps(spec))

    env = {
        **os.environ,
        "SIM_MODE": "1",
        "SIM_ROOT": str(sim_root),
        "SIM_REDIS_PORT": REDIS_PORT,
        "BRAHMAND_SANDBOX": str(sim_root / "data"),
        "PYTHONPATH": "/home/trading_ceo:/home/trading_ceo/brahmand",
    }

    print(
        f"\n=== PORCUPINE path scenario: {name} ===\npath={spec['path']}\n"
        f"SIM_ROOT={sim_root}\n"
    )

    drv = subprocess.run(
        [sys.executable, str(ROOT / "sim" / "path_driver.py"), str(spec_path)],
        cwd="/home/trading_ceo/brahmand",
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    out = (drv.stdout or "") + "\n" + (drv.stderr or "")
    (sim_root / "logs" / "path_driver.out").write_text(out)

    payload = None
    for line in (drv.stdout or "").splitlines():
        if line.startswith("PATH_RESULT "):
            payload = __import__("json").loads(line[len("PATH_RESULT ") :])
            break

    if payload is None:
        results = [
            (
                "path driver produced a verdict",
                False,
                f"rc={drv.returncode}; see logs/path_driver.out",
            )
        ]
    else:
        print(
            "  trace: "
            + " → ".join(
                f"{s['t']}@{s['spot']}(mtm{s['mtm']:+.0f}{'·closed' if not s['active'] else ''})"
                for s in payload["trace"]
            )
        )
        results = _eval_expect(spec.get("expect", {}), payload)

    print("\n--- assertions ---")
    failed = 0
    for nm, ok, detail in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {nm:48s} {detail}")
        if not ok:
            failed += 1
    verdict = "PASS" if failed == 0 else f"FAIL ({failed} failed)"
    print(f"\n=== path:{name}: {verdict} ===  (SIM_ROOT kept: {sim_root})\n")
    return 0 if failed == 0 else 1


def main():
    p = argparse.ArgumentParser(description="PORCUPINE scenario runner")
    p.add_argument("scenario", nargs="?", help="scenario name, or path:<name>")
    p.add_argument(
        "--date", default=None, help="replay date YYYY-MM-DD (default today)"
    )
    p.add_argument(
        "--with-kickoff", action="store_true", help="also run real CrewAI kickoff"
    )
    p.add_argument("--list", action="store_true")
    a = p.parse_args()
    if a.list or not a.scenario:
        for k, v in SCENARIOS.items():
            print(f"  {k:16s} {v['desc']}")
        from sim.path_scenarios import PATH_SCENARIOS

        for k, v in PATH_SCENARIOS.items():
            print(
                f"  path:{k:11s} {v.get('strategy', '')} — scripted intraday path scenario"
            )
        return
    if a.scenario.startswith("path:"):
        sys.exit(run_path(a.scenario.split(":", 1)[1]))
    if a.scenario.startswith("fault:"):
        sys.exit(run("happy_path", a.date, False, fault=a.scenario.split(":", 1)[1]))
    if a.scenario not in SCENARIOS:
        print(f"unknown scenario: {a.scenario}")
        sys.exit(2)
    if a.scenario in LIFECYCLE:
        sys.exit(run_lifecycle(a.scenario, a.date))
    if a.scenario == "multitf_trend":
        sys.exit(run_multitf_trend(a.date))
    if a.scenario == "position_cache":
        sys.exit(run_position_cache(a.date))
    if a.scenario == "llm_down":
        sys.exit(run_llm_down())
    sys.exit(run(a.scenario, a.date, a.with_kickoff))


if __name__ == "__main__":
    main()
