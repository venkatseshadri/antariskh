"""
ds_guard.sh tests — all three rules + installation check.
No git operations on the real repo. Each test creates a temp git repo,
stages specific content, and asserts exit code.
"""

import os
import stat
import shutil
import subprocess
import tempfile
from pathlib import Path

GUARD = Path("/home/trading_ceo/ouroboros/ds_guard.sh")
DEV_ANTARIKSH_HOOK = Path("/home/trading_ceo/dev/antariksh/.git/hooks/pre-commit")
DEV_BRAHMAND_HOOK = Path("/home/trading_ceo/dev/brahmand/.git/hooks/pre-commit")


def _git(tmpdir, *args, **kw):
    return subprocess.run(["git", "-C", tmpdir] + list(args),
                          capture_output=True, text=True, **kw)


def _make_repo(content_files: dict[str, str]) -> tempfile.TemporaryDirectory:
    """Create a temp git repo, commit base files, stage changes for content_files."""
    d = tempfile.mkdtemp(prefix="ds_guard_test_")
    _git(d, "init", "-b", "master")
    _git(d, "config", "user.email", "test@test.com")
    _git(d, "config", "user.name", "Test")
    # Install the guard as pre-commit hook
    hook = Path(d) / ".git" / "hooks" / "pre-commit"
    hook.symlink_to(GUARD)
    return d


def _run_guard(tmpdir: str, staged: dict[str, str], base: dict[str, str] | None = None) -> int:
    """
    Commit base files to master, then stage `staged` changes and run guard.
    Returns exit code of guard.
    """
    # Commit base state
    if base:
        for fname, content in base.items():
            p = Path(tmpdir) / fname
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
            _git(tmpdir, "add", fname)
        _git(tmpdir, "commit", "--no-verify", "-m", "base", "--allow-empty")

    # Stage the changes to test
    for fname, content in staged.items():
        p = Path(tmpdir) / fname
        p.parent.mkdir(parents=True, exist_ok=True)
        if content is None:
            p.unlink(missing_ok=True)
            _git(tmpdir, "rm", "--cached", "-f", fname)
        else:
            p.write_text(content)
            _git(tmpdir, "add", fname)

    result = subprocess.run(
        ["/bin/bash", str(GUARD)],
        cwd=tmpdir, capture_output=True, text=True
    )
    return result.returncode


exit_code = 0


def fail(msg: str):
    global exit_code
    print(f"  FAIL  {msg}")
    exit_code = 1


def ok(msg: str):
    print(f"  OK    {msg}")


# ── Installation checks ───────────────────────────────────────────────────────

def test_canonical_exists():
    print("\n  I.1  canonical guard exists at ouroboros/ds_guard.sh")
    if GUARD.exists():
        ok(str(GUARD))
    else:
        fail(f"missing: {GUARD}")


def test_canonical_permissions():
    print("\n  I.2  canonical guard root-owned chmod 755 (exec by all, writable only by root)")
    s = GUARD.stat()
    owner_uid = s.st_uid
    mode = stat.S_IMODE(s.st_mode)
    if owner_uid == 0 and mode == 0o755:
        ok(f"uid={owner_uid} mode={oct(mode)}")
    else:
        fail(f"uid={owner_uid} (want 0), mode={oct(mode)} (want 0o755)")


def test_dev_antariksh_hook_installed():
    print("\n  I.3  dev/antariksh pre-commit symlink → canonical guard")
    if DEV_ANTARIKSH_HOOK.is_symlink() and DEV_ANTARIKSH_HOOK.resolve() == GUARD.resolve():
        ok(str(DEV_ANTARIKSH_HOOK))
    else:
        fail(f"hook missing or wrong target: {DEV_ANTARIKSH_HOOK}")


def test_dev_brahmand_hook_installed():
    print("\n  I.4  dev/brahmand pre-commit symlink → canonical guard")
    if DEV_BRAHMAND_HOOK.is_symlink() and DEV_BRAHMAND_HOOK.resolve() == GUARD.resolve():
        ok(str(DEV_BRAHMAND_HOOK))
    else:
        fail(f"hook missing or wrong target: {DEV_BRAHMAND_HOOK}")


# ── Rule 1: validator line deletion ──────────────────────────────────────────

def test_rule1_blocks_double_tick_deletion():
    print("\n  R1.1  blocks ✅✅ line deletion from .md")
    d = _make_repo({})
    try:
        rc = _run_guard(d,
            staged={"doc.md": "# doc\nsome content\n"},
            base={"doc.md": "# doc\n✅✅ Validator record: all good\nsome content\n"},
        )
        (fail if rc == 0 else ok)(f"exit {rc} (want non-zero)")
    finally:
        shutil.rmtree(d)


def test_rule1_blocks_board_decision_deletion():
    print("\n  R1.2  blocks 'Board decision' line deletion")
    d = _make_repo({})
    try:
        rc = _run_guard(d,
            staged={"doc.md": "# doc\n"},
            base={"doc.md": "# doc\nBoard decision 2026-06-11: approved\n"},
        )
        (fail if rc == 0 else ok)(f"exit {rc}")
    finally:
        shutil.rmtree(d)


def test_rule1_allows_new_validator_line():
    print("\n  R1.3  allows ADDING new ✅✅ line (append-only, not delete)")
    d = _make_repo({})
    try:
        rc = _run_guard(d,
            staged={"doc.md": "# doc\nexisting line\n✅✅ New validator record\n"},
            base={"doc.md": "# doc\nexisting line\n"},
        )
        (ok if rc == 0 else fail)(f"exit {rc} (want 0)")
    finally:
        shutil.rmtree(d)


def test_rule1_allows_normal_code_change():
    print("\n  R1.4  allows normal .py change (no validator lines)")
    d = _make_repo({})
    try:
        rc = _run_guard(d,
            staged={"module.py": "def foo():\n    return 42\n"},
            base={"module.py": "def foo():\n    return 1\n"},
        )
        (ok if rc == 0 else fail)(f"exit {rc} (want 0)")
    finally:
        shutil.rmtree(d)


# ── Rule 2: self-approval flip ───────────────────────────────────────────────

def test_rule2_blocks_negative_to_positive_flip():
    print("\n  R2.1  blocks ❌ removed + ✅ added in same diff")
    d = _make_repo({})
    try:
        rc = _run_guard(d,
            staged={"state.md": "# State\n✅ item is now passing\n"},
            base={"state.md": "# State\n❌ item is failing\n"},
        )
        (fail if rc == 0 else ok)(f"exit {rc} (want non-zero)")
    finally:
        shutil.rmtree(d)


def test_rule2_blocks_warning_to_positive_flip():
    print("\n  R2.2  blocks ⚠️ removed + ✅ added")
    d = _make_repo({})
    try:
        rc = _run_guard(d,
            staged={"state.md": "# State\n✅ resolved\n"},
            base={"state.md": "# State\n⚠️ open issue\n"},
        )
        (fail if rc == 0 else ok)(f"exit {rc} (want non-zero)")
    finally:
        shutil.rmtree(d)


def test_rule2_allows_independent_positive_add():
    print("\n  R2.3  allows ✅ added when no ❌/⚠️ removed")
    d = _make_repo({})
    try:
        rc = _run_guard(d,
            staged={"state.md": "# State\nexisting ok line\n✅ new item passed\n"},
            base={"state.md": "# State\nexisting ok line\n"},
        )
        (ok if rc == 0 else fail)(f"exit {rc} (want 0)")
    finally:
        shutil.rmtree(d)


# ── Rule 3: secret pattern detection ─────────────────────────────────────────

def test_rule3_blocks_api_key_value():
    print("\n  R3.1  blocks API_KEY = 'abc123...' in staged file")
    d = _make_repo({})
    try:
        rc = _run_guard(d,
            staged={"config.py": "API_KEY = 'sk-abc123defghij'\nSOME_VAR = 'ok'\n"},
            base={"config.py": "SOME_VAR = 'ok'\n"},
        )
        (fail if rc == 0 else ok)(f"exit {rc} (want non-zero)")
    finally:
        shutil.rmtree(d)


def test_rule3_blocks_private_key_header():
    print("\n  R3.2  blocks private key header")
    d = _make_repo({})
    try:
        rc = _run_guard(d,
            staged={"key.pem": "-----BEGIN RSA PRIVATE KEY-----\nABCDEF\n-----END RSA PRIVATE KEY-----\n"},
        )
        (fail if rc == 0 else ok)(f"exit {rc} (want non-zero)")
    finally:
        shutil.rmtree(d)


def test_rule3_allows_api_key_variable_name_in_code():
    print("\n  R3.3  allows API_KEY as variable name (no value assignment)")
    d = _make_repo({})
    try:
        # Variable declaration without a value string — should pass
        rc = _run_guard(d,
            staged={"config.py": "API_KEY = os.environ['BROKER_KEY']\n"},
        )
        (ok if rc == 0 else fail)(f"exit {rc} (want 0)")
    finally:
        shutil.rmtree(d)


def test_rule3_skips_test_files():
    print("\n  R3.4  allows secrets in test_ files (fixtures)")
    d = _make_repo({})
    try:
        rc = _run_guard(d,
            staged={"tests/test_auth.py": "API_KEY = 'sk-abc123defghij'  # fixture\n"},
        )
        (ok if rc == 0 else fail)(f"exit {rc} (want 0)")
    finally:
        shutil.rmtree(d)


# ── VALIDATOR_OVERRIDE bypass ─────────────────────────────────────────────────

def test_override_bypasses_all_rules():
    print("\n  OV.1  VALIDATOR_OVERRIDE=1 bypasses all rules")
    d = _make_repo({})
    try:
        env = os.environ.copy()
        env["VALIDATOR_OVERRIDE"] = "1"
        # Stage something that would normally be blocked (Rule 1)
        base_f = Path(d) / "doc.md"
        base_f.write_text("✅✅ Validator record: passes\n")
        _git(d, "add", "doc.md")
        _git(d, "commit", "--no-verify", "-m", "base")
        base_f.write_text("")
        _git(d, "add", "doc.md")
        result = subprocess.run(["/bin/bash", str(GUARD)], cwd=d,
                                capture_output=True, text=True, env=env)
        (ok if result.returncode == 0 else fail)(f"exit {result.returncode} (want 0 with override)")
    finally:
        shutil.rmtree(d)


def main():
    global exit_code
    print("=" * 56)
    print("  DS_GUARD TESTS")
    print("=" * 56)

    test_canonical_exists()
    test_canonical_permissions()
    test_dev_antariksh_hook_installed()
    test_dev_brahmand_hook_installed()

    test_rule1_blocks_double_tick_deletion()
    test_rule1_blocks_board_decision_deletion()
    test_rule1_allows_new_validator_line()
    test_rule1_allows_normal_code_change()

    test_rule2_blocks_negative_to_positive_flip()
    test_rule2_blocks_warning_to_positive_flip()
    test_rule2_allows_independent_positive_add()

    test_rule3_blocks_api_key_value()
    test_rule3_blocks_private_key_header()
    test_rule3_allows_api_key_variable_name_in_code()
    test_rule3_skips_test_files()

    test_override_bypasses_all_rules()

    print()
    if exit_code == 0:
        print("  ALL DS_GUARD TESTS PASSED")
    else:
        print(f"  FAILURES — see above")
    return exit_code


if __name__ == "__main__":
    import sys
    sys.exit(main())
