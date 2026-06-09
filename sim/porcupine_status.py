#!/usr/bin/env python3
"""PORCUPINE build-progress reporter — deterministic, token-free (no LLM).

Answers: is the harness development COMPLETE or still IN PROGRESS? Computes
milestones from actual artifacts (files + grep markers) and quick regression
tests, then alerts Telegram ONLY when the status changes (so it can run every
30 min without spamming). Run by cron via run_porcupine_status.sh.

Usage: python3 -m sim.porcupine_status [--send] [--force]
"""
import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "sim" / ".porcupine_status.json"


def _has(path: str, needle: str | None = None) -> bool:
    p = ROOT / path
    if not p.exists():
        return False
    return needle is None or needle in p.read_text(errors="ignore")


def _test_ok(module: str) -> bool:
    try:
        r = subprocess.run([sys.executable, "-m", module], cwd=ROOT,
                           capture_output=True, timeout=90)
        return r.returncode == 0
    except Exception:
        return False


def milestones() -> list[tuple[str, bool]]:
    """BUILDABLE harness milestones — what the autobuilder can actually produce
    (everything under sim/ + tests/). Completion of these = harness DONE.

    Note: bug #3/#4 milestones track the *harness guard* (regression test files),
    NOT the live-code fix. The builder is forbidden from editing live code, so the
    only PORCUPINE deliverable for those bugs is the permanent regression guard.
    The live-code fix is tracked separately in live_fixes() and does NOT gate
    completion (else the builder can never self-terminate — the 2026-06-08 pause)."""
    return [
        ("P0 isolation (sim_env + leak guard)", _has("sim/sim_env.py", "assert_sandboxed")),
        ("P1 mock feed (replay)",               _has("sim/mock_feed.py")),
        ("P2 enricher in sim (lock-fix proven)", _has("sim/run_scenario.py")),
        ("P3 CrewAI kickoff vs sandbox",        _has("docs/PORCUPINE_STATE.md", "CrewAI kickoff")),
        ("P4 orchestrator (run_scenario)",      _has("sim/run_scenario.py", "assertions")),
        ("Synthetic fault driver (--fault)",    _has("sim/mock_feed.py", "--fault")),
        ("Lifecycle in sim (order→monitor→exit)", _has("sim/run_scenario.py", "position_manager")),
        ("Bug #3 harness guard (entry-agent fallback)", _has("sim/tests/test_fallback_inputs.py")),
        ("Bug #4 harness guard (VIX-null)",     _has("sim/tests/test_vix_null_guard.py")),
    ]


def live_fixes() -> list[tuple[str, bool]]:
    """Human-gated LIVE-CODE fixes for the bugs PORCUPINE caught. Informational
    only — surfaced so the bugs aren't forgotten, but NOT part of the builder's
    completion gate (these require editing live enrichment/decision code, which
    the autobuilder is forbidden to touch). Marker files are created by a human
    after the live fix lands."""
    return [
        ("Bug #3 live-fix (session_phase ts + multitf st_consensus)", _has("sim/.bug3_fixed")),
        ("Bug #4 live-fix (VIX-null gate fails-closed)", _has("sim/.bug4_fixed")),
    ]


def report(send: bool, force: bool) -> int:
    ms = milestones()
    done = sum(1 for _, ok in ms if ok)
    total = len(ms)
    iso_ok = _test_ok("sim.tests.test_isolation")
    feed_ok = _test_ok("sim.tests.test_feed_bar_integrity")
    complete = done == total and iso_ok and feed_ok

    pct = round(100 * done / total)
    remaining = [n for n, ok in ms if not ok]
    verdict = "✅ DEVELOPMENT COMPLETE" if complete else f"🚧 IN PROGRESS — {len(remaining)} item(s) left"

    lf = live_fixes()
    lf_pending = [n for n, ok in lf if not ok]

    lines = [
        f"🦔 PORCUPINE build — {datetime.now():%Y-%m-%d %H:%M}",
        f"Milestones: {done}/{total} ({pct}%)   Regression: isolation {'✅' if iso_ok else '❌'} · feed {'✅' if feed_ok else '❌'}",
    ]
    if remaining:
        lines.append("Remaining: " + "; ".join(remaining))
    lines.append(verdict)
    if lf_pending:
        # informational only — does NOT gate completion or the builder
        lines.append("⚠ Live-code fixes still owed (human-gated): " + "; ".join(lf_pending))
    msg = "\n".join(lines)
    print(msg)

    # only notify on change (token-free: direct Telegram bot API, no LLM)
    # live_fixes are included in the signature so a later human fix still notifies,
    # but they are NOT in `complete` — the builder self-terminates on harness done.
    sig = hashlib.sha1(json.dumps([ms, lf, iso_ok, feed_ok]).encode()).hexdigest()[:12]
    prev = ""
    if STATE.exists():
        prev = json.loads(STATE.read_text()).get("sig", "")
    changed = sig != prev
    STATE.write_text(json.dumps({"sig": sig, "at": datetime.now().isoformat(), "verdict": verdict}))

    if send and (changed or force):
        try:
            sys.path.insert(0, str(ROOT))
            from tools.log_analyzer import send_telegram
            send_telegram(msg)
            print("[sent to Telegram — status changed]" if changed else "[sent — forced]")
        except Exception as e:
            print(f"[telegram send failed: {e}]")
    elif send:
        print("[no change — not sending]")
    return 0 if complete else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="push to Telegram on change")
    ap.add_argument("--force", action="store_true", help="send even if unchanged")
    a = ap.parse_args()
    sys.exit(report(a.send, a.force))


if __name__ == "__main__":
    main()
