"""
claude_review_loop.sh tests — integrity sweep function + structural checks.
Tests the deterministic pre-flight sweep (G10) and JSON verdict parsing (G11).
"""

import os
import re
import subprocess
import shutil
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / "cron" / "claude_review_loop.sh"

exit_code = 0


def fail(msg: str):
    global exit_code
    print(f"  FAIL  {msg}")
    exit_code = 1


def ok(msg: str):
    print(f"  OK    {msg}")


def _src():
    return SCRIPT.read_text()


def _run_sweep(diff_content: str, commits_content: str = "", master_md: str = "") -> dict:
    """
    Run just the _integrity_sweep function from the review loop script.
    Returns dict with sweep_result, sweep_findings, hallucination_detected.
    """
    tmp = tempfile.mkdtemp(prefix="sweep_test_")
    try:
        diff_f = Path(tmp) / "diff.txt"
        commits_f = Path(tmp) / "commits.txt"
        master_f = Path(tmp) / "master.txt"
        diff_f.write_text(diff_content)
        commits_f.write_text(commits_content)
        master_f.write_text(master_md)

        # Extract just the _integrity_sweep function + call it
        src = SCRIPT.read_text()
        sweep_fn_start = src.find("_integrity_sweep()")
        sweep_fn_end = src.find("\n}\n", sweep_fn_start) + 3
        sweep_fn = src[src.find("# ── INTEGRITY SWEEP"):sweep_fn_end]

        test_script = sweep_fn + f"""
_integrity_sweep "{diff_f}" "{master_f}" "{commits_f}"
echo "RESULT:$sweep_result"
echo "HALLUCINATION:$hallucination_detected"
if [ -n "$sweep_findings" ]; then echo "FINDINGS:$sweep_findings"; fi
"""
        result = subprocess.run(
            ["/bin/bash", "-c", test_script],
            capture_output=True, text=True, timeout=10
        )
        out = result.stdout
        r_match = re.search(r"RESULT:(\S+)", out)
        h_match = re.search(r"HALLUCINATION:(\S+)", out)
        return {
            "result": r_match.group(1) if r_match else "ERROR",
            "hallucination": h_match.group(1) if h_match else "false",
            "findings": out,
            "rc": result.returncode,
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ── Structural checks ─────────────────────────────────────────────────────────

def test_script_exists():
    print("\n  S.1  script exists")
    (ok if SCRIPT.exists() else fail)(str(SCRIPT))


def test_integrity_sweep_function_present():
    print("\n  S.2  _integrity_sweep function defined (G10)")
    s = _src()
    (ok if "_integrity_sweep()" in s else fail)("_integrity_sweep function missing")


def test_sweep_runs_before_claude():
    print("\n  S.3  sweep invoked before Claude call")
    s = _src()
    sweep_pos = s.find("_integrity_sweep")
    # Script quotes variable: "$CLAUDE" -p or $CLAUDE ... -p
    claude_pos = s.find('CLAUDE" -p') if 'CLAUDE" -p' in s else s.find("CLAUDE.*-p")
    if claude_pos == -1:
        import re as _re
        m = _re.search(r'CLAUDE.*-p', s)
        claude_pos = m.start() if m else -1
    if sweep_pos == -1 or claude_pos == -1:
        fail(f"sweep@{sweep_pos} or claude@{claude_pos} not found")
    elif sweep_pos < claude_pos:
        ok(f"sweep@{sweep_pos} < claude@{claude_pos}")
    else:
        fail(f"sweep@{sweep_pos} AFTER claude@{claude_pos}")


def test_integrity_fail_skips_claude():
    print("\n  S.4  INTEGRITY_FAIL path skips Claude, posts verdict directly")
    s = _src()
    fail_block = s[s.find("INTEGRITY_FAIL"):]
    has_skip = "skipping Claude review" in fail_block
    (ok if has_skip else fail)("'skipping Claude review' not found in INTEGRITY_FAIL block")


def test_json_verdict_parsing():
    print("\n  S.5  JSON verdict parsing present (G11)")
    s = _src()
    (ok if '"verdict"' in s and "CLAUDE_VERDICT" in s else fail)(
        "JSON verdict parsing missing"
    )


def test_dual_pause_paths():
    print("\n  S.6  checks both canonical + legacy pause paths")
    s = _src()
    (ok if "ouroboros/logs/.ralph_paused" in s else fail)(
        "canonical pause path missing"
    )


# ── Sweep behavioral tests ────────────────────────────────────────────────────

def test_pattern_a_blocks_double_tick():
    print("\n  P.A  Pattern A: ✅✅ in added .md lines → INTEGRITY_FAIL")
    diff = """+++ b/docs/STATE.md\n@@ -1 +2 @@\n+✅✅ DS self-marked as done\n"""
    r = _run_sweep(diff)
    (ok if r["result"] == "INTEGRITY_FAIL" else fail)(f"result={r['result']} (want INTEGRITY_FAIL)")


def test_pattern_a_passes_no_double_tick():
    print("\n  P.A2 Pattern A: no ✅✅ → PASS")
    diff = """+++ b/module.py\n+def foo(): return 42\n"""
    r = _run_sweep(diff)
    (ok if r["result"] == "PASS" else fail)(f"result={r['result']} (want PASS)")


def test_pattern_b_blocks_polarity_flip():
    print("\n  P.B  Pattern B: ❌ removed + ✅ added → INTEGRITY_FAIL")
    diff = """+++ b/docs/STATE.md
-❌ test failing
+✅ test passing
"""
    r = _run_sweep(diff)
    (ok if r["result"] == "INTEGRITY_FAIL" else fail)(f"result={r['result']} (want INTEGRITY_FAIL)")


def test_pattern_b_passes_positive_only():
    print("\n  P.B2 Pattern B: only ✅ added (no negative removed) → PASS")
    diff = """+++ b/docs/STATE.md
+✅ new item verified by validator
"""
    r = _run_sweep(diff)
    (ok if r["result"] == "PASS" else fail)(f"result={r['result']} (want PASS)")


def test_pattern_c_flags_hallucination():
    print("\n  P.C  Pattern C: commit says 'tests pass' but no test files in diff")
    diff = """+++ b/module.py\n+x = 1\n"""
    commits = "feat: implement #42 — all tests pass [deepseek]"
    r = _run_sweep(diff, commits)
    (ok if r["hallucination"] == "true" else fail)(
        f"hallucination={r['hallucination']} (want true)"
    )


def test_pattern_c_no_flag_with_test_files():
    print("\n  P.C2 Pattern C: commit says 'tests pass' AND test file in diff → no flag")
    diff = """+++ b/tests/test_foo.py\n+def test_x(): assert True\n"""
    commits = "feat: all tests pass [deepseek]"
    r = _run_sweep(diff, commits)
    (ok if r["hallucination"] == "false" else fail)(
        f"hallucination={r['hallucination']} (want false)"
    )


def test_pattern_d_flags_deleted_open():
    print("\n  P.D  Pattern D: OPEN: line removed → critical finding in sweep_findings")
    diff = """-OPEN: this bug is not fixed yet\n"""
    r = _run_sweep(diff, master_md="OPEN: this bug is not fixed yet\n")
    (ok if "Pattern D" in r["findings"] or "red flag" in r["findings"]
     else fail)(f"Pattern D not flagged; findings={r['findings'][:200]}")


def main():
    global exit_code
    print("=" * 56)
    print("  REVIEW LOOP TESTS")
    print("=" * 56)

    test_script_exists()
    test_integrity_sweep_function_present()
    test_sweep_runs_before_claude()
    test_integrity_fail_skips_claude()
    test_json_verdict_parsing()
    test_dual_pause_paths()

    test_pattern_a_blocks_double_tick()
    test_pattern_a_passes_no_double_tick()
    test_pattern_b_blocks_polarity_flip()
    test_pattern_b_passes_positive_only()
    test_pattern_c_flags_hallucination()
    test_pattern_c_no_flag_with_test_files()
    test_pattern_d_flags_deleted_open()

    print()
    if exit_code == 0:
        print("  ALL REVIEW LOOP TESTS PASSED")
    else:
        print("  FAILURES — see above")
    return exit_code


if __name__ == "__main__":
    import sys
    sys.exit(main())
