"""
Ouroboros config system tests (G1).
Verifies: conf files exist, required vars present, scripts source them.
"""

import subprocess
from pathlib import Path

OUROBOROS_DIR = Path("/home/trading_ceo/ouroboros")
PROJECTS_DIR = OUROBOROS_DIR / "projects"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

exit_code = 0


def fail(msg: str):
    global exit_code
    print(f"  FAIL  {msg}")
    exit_code = 1


def ok(msg: str):
    print(f"  OK    {msg}")


REQUIRED_CONF_VARS = [
    "PROJECT_NAME", "DEV_DIR", "REPO", "SKIP_TAG", "LOG_DIR"
]


def test_ouroboros_dir_exists():
    print("\n  C.1  /home/trading_ceo/ouroboros/ exists")
    (ok if OUROBOROS_DIR.is_dir() else fail)(str(OUROBOROS_DIR))


def test_projects_dir_exists():
    print("\n  C.2  ouroboros/projects/ exists")
    (ok if PROJECTS_DIR.is_dir() else fail)(str(PROJECTS_DIR))


def test_antariksh_conf_exists():
    print("\n  C.3  antariksh.conf exists")
    conf = PROJECTS_DIR / "antariksh.conf"
    (ok if conf.exists() else fail)(str(conf))


def test_antariksh_conf_required_vars():
    print("\n  C.4  antariksh.conf has all required vars")
    conf = PROJECTS_DIR / "antariksh.conf"
    if not conf.exists():
        fail("conf missing — skip"); return
    text = conf.read_text()
    missing = [v for v in REQUIRED_CONF_VARS if v + "=" not in text]
    (ok if not missing else fail)(
        f"missing vars: {missing}" if missing else "all present"
    )


def test_build_loop_sources_config():
    print("\n  C.5  ds_ralph_loop.sh sources ouroboros project config when OUROBOROS_PROJECT set")
    s = (REPO_ROOT / "cron" / "ds_ralph_loop.sh").read_text()
    (ok if "ouroboros/projects" in s and "OUROBOROS_PROJECT" in s else fail)(
        "config sourcing missing from build loop"
    )


def test_config_sourced_on_valid_project():
    print("\n  C.6  conf source exports PROJECT_NAME correctly")
    conf = PROJECTS_DIR / "antariksh.conf"
    if not conf.exists():
        fail("conf missing — skip"); return
    result = subprocess.run(
        ["/bin/bash", "-c", f". {conf} && echo $PROJECT_NAME"],
        capture_output=True, text=True, timeout=5
    )
    name = result.stdout.strip()
    (ok if name == "antariksh" else fail)(f"PROJECT_NAME='{name}' (want 'antariksh')")


def test_logs_dir_from_conf():
    print("\n  C.7  LOG_DIR in conf points to existing dir (or creatable)")
    conf = PROJECTS_DIR / "antariksh.conf"
    if not conf.exists():
        fail("conf missing — skip"); return
    result = subprocess.run(
        ["/bin/bash", "-c", f". {conf} && echo $LOG_DIR"],
        capture_output=True, text=True, timeout=5
    )
    log_dir = result.stdout.strip()
    log_path = Path(log_dir)
    (ok if log_path.exists() or log_path.parent.exists() else fail)(
        f"LOG_DIR={log_dir} — parent dir doesn't exist"
    )


def main():
    global exit_code
    print("=" * 56)
    print("  OUROBOROS CONFIG SYSTEM TESTS")
    print("=" * 56)

    test_ouroboros_dir_exists()
    test_projects_dir_exists()
    test_antariksh_conf_exists()
    test_antariksh_conf_required_vars()
    test_build_loop_sources_config()
    test_config_sourced_on_valid_project()
    test_logs_dir_from_conf()

    print()
    if exit_code == 0:
        print("  ALL CONFIG TESTS PASSED")
    else:
        print("  FAILURES — see above")
    return exit_code


if __name__ == "__main__":
    import sys
    sys.exit(main())
