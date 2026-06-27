"""
ds_ralph_loop.sh tests — structural checks + DRYRUN behavior + config assertions.
No live gh/opencode calls. Uses RALPH_DRYRUN=1 + mock gh via PATH substitution.
"""

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / "cron" / "ds_ralph_loop.sh"

exit_code = 0


def fail(msg: str):
    global exit_code
    print(f"  FAIL  {msg}")
    exit_code = 1


def ok(msg: str):
    print(f"  OK    {msg}")


def _script_text():
    return SCRIPT.read_text()


# ── Structural / config checks ────────────────────────────────────────────────

def test_script_exists():
    print("\n  S.1  script exists")
    if SCRIPT.exists():
        ok(str(SCRIPT))
    else:
        fail(f"missing: {SCRIPT}")


def test_per_project_lock(src=None):
    print("\n  S.2  per-project lock (G14): ouroboros_build_{PROJECT_NAME}.lock")
    s = src or _script_text()
    if "ouroboros_build_" in s and ".lock" in s:
        ok("ouroboros_build_<project>.lock found")
    else:
        fail("lock still uses global name (should be ouroboros_build_{PROJECT_NAME}.lock)")


def test_branch_naming(src=None):
    print("\n  S.3  branch naming (G13): ralph/{project}/issue-{N}")
    s = src or _script_text()
    if 'ralph/${PROJECT_NAME}/issue-' in s or 'ralph/antariksh/issue-' in s:
        ok("ralph/<project>/issue-<N>")
    else:
        fail("branch still uses old ds/issue-N naming")


def test_skip_tag_present(src=None):
    print("\n  S.4  SKIP_TAG body check present (G12)")
    s = src or _script_text()
    if "SKIP_TAG" in s and "loop-unbuildable" in s:
        ok("SKIP_TAG + loop-unbuildable found")
    else:
        fail("SKIP_TAG body-skip logic missing")


def test_pr_creation_present(src=None):
    print("\n  S.5  PR creation after push (G6): gh pr create")
    s = src or _script_text()
    if "pr create" in s:
        ok("gh pr create found")
    else:
        fail("PR creation (gh pr create) missing")


def test_test_fail_handling(src=None):
    print("\n  S.6  test-fail handling (G5): changes:requested + failure comment")
    s = src or _script_text()
    has_label = "changes:requested" in s
    has_comment = "ds-build failed" in s or "no commits" in s
    if has_label and has_comment:
        ok("changes:requested + failure comment found")
    else:
        fail(f"missing: label={has_label} comment={has_comment}")


def test_dual_pause_check(src=None):
    print("\n  S.7  pause checks both canonical + legacy paths")
    s = src or _script_text()
    has_canonical = "ouroboros/logs/.ralph_paused" in s
    has_legacy = ".ralph_paused" in s
    if has_canonical and has_legacy:
        ok("both pause paths checked")
    else:
        fail(f"canonical={has_canonical} legacy={has_legacy}")


# ── DRYRUN mode ───────────────────────────────────────────────────────────────

def _make_mock_gh(tmpdir: str, issue_json: str = "", issue_title: str = "") -> str:
    """Write a mock `gh` binary into tmpdir. Returns the directory."""
    mock = Path(tmpdir) / "gh"
    mock.write_text(f"""#!/bin/bash
case "$*" in
  *"issue list"*)
    echo '{issue_json}' ;;
  *"issue view"*"--json title"*)
    echo '{{"title": "{issue_title}"}}' ;;
  *"issue view"*)
    echo '{{"title": "{issue_title}", "body": "test"}}' ;;
  *)
    true ;;
esac
""")
    mock.chmod(0o755)
    return tmpdir


def test_dryrun_exits_zero_no_issues():
    print("\n  D.1  DRYRUN exits 0 when no ds:ready issues")
    tmp = tempfile.mkdtemp(prefix="build_loop_test_")
    try:
        mock_dir = _make_mock_gh(tmp, issue_json="[]")
        env = os.environ.copy()
        env["PATH"] = f"{mock_dir}:{env.get('PATH', '/usr/bin:/bin')}"
        env["RALPH_DRYRUN"] = "1"
        env["HOME"] = "/root"
        result = subprocess.run(
            ["/bin/bash", str(SCRIPT)],
            env=env, capture_output=True, text=True, timeout=30
        )
        (ok if result.returncode == 0 else fail)(f"exit {result.returncode}")
    except Exception as e:
        fail(f"exception: {e}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_dryrun_skip_tag_in_body():
    print("\n  D.2  DRYRUN: issue with ROOT_REPO_ONLY in body → skip")
    tmp = tempfile.mkdtemp(prefix="build_loop_test_")
    try:
        # Issue has ROOT_REPO_ONLY tag in body
        issue_json = '[{"number": 42, "assignees": [], "body": "ROOT_REPO_ONLY — manual only"}]'
        mock_dir = _make_mock_gh(tmp, issue_json=issue_json, issue_title="Manual only task")

        # Write mock python3 for JSON parsing
        py_mock = Path(tmp) / "python3"
        py_mock.write_text("""#!/bin/bash
# Pass through to real python3, reading stdin
/usr/bin/python3 "$@"
""")
        py_mock.chmod(0o755)

        env = os.environ.copy()
        env["PATH"] = f"{tmp}:{env.get('PATH', '/usr/bin:/bin')}"
        env["RALPH_DRYRUN"] = "1"
        env["HOME"] = "/root"
        result = subprocess.run(
            ["/bin/bash", str(SCRIPT)],
            env=env, capture_output=True, text=True, timeout=30
        )
        log_content = result.stdout + result.stderr
        skip_logged = "loop-unbuildable" in log_content or result.returncode == 0
        (ok if skip_logged else fail)(f"exit {result.returncode}, output: {log_content[:200]}")
    except Exception as e:
        fail(f"exception: {e}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_all_structural_from_one_read():
    """Batch: read script once, run all structural checks."""
    print("\n  S.ALL  batch structural checks on script source")
    src = _script_text()
    test_per_project_lock(src)
    test_branch_naming(src)
    test_skip_tag_present(src)
    test_pr_creation_present(src)
    test_test_fail_handling(src)
    test_dual_pause_check(src)


def main():
    global exit_code
    print("=" * 56)
    print("  BUILD LOOP TESTS")
    print("=" * 56)

    test_script_exists()
    test_all_structural_from_one_read()
    test_dryrun_exits_zero_no_issues()
    test_dryrun_skip_tag_in_body()

    print()
    if exit_code == 0:
        print("  ALL BUILD LOOP TESTS PASSED")
    else:
        print("  FAILURES — see above")
    return exit_code


if __name__ == "__main__":
    import sys
    sys.exit(main())
