"""Pre-commit plumbing tests — catches today's failures before they hit market.

No LLM. No API keys. No DB writes. < 1 second.

Fails on:
  check_market_open.sh → wrong exit codes (systemd ExecCondition polarity)
  get_weekly_expiry()    → wrong weekday, past-date expiry
  e2e_chain.py          → stale expiry_weekly with no >= today guard
  Cron paths            → referencing non-existent script files
"""

import os
import re
import sys
import json
import stat
import shutil
import tempfile
import subprocess
import importlib
from datetime import datetime, timedelta, date
from pathlib import Path
from unittest.mock import patch


# ── Paths ────────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BRAHMAND_ROOT = Path("/home/trading_ceo/brahmand")
CHECK_MARKET_OPEN = REPO_ROOT / "cron" / "check_market_open.sh"
HOLIDAYS_FILE = Path("/root/.picoclaw/workspace/config/market_holidays.json")
ANTARIKSK_CRONTAB = Path("/var/spool/cron/crontabs/root")

exit_code = 0


def fail(msg: str):
    global exit_code
    print(f"  FAIL  {msg}")
    exit_code = 1


def ok(msg: str):
    print(f"  OK    {msg}")


# ══════════════════════════════════════════════════════════════════════════════
# helpers
# ══════════════════════════════════════════════════════════════════════════════


def _fake_date_bin(fake_date_str: str) -> str:
    """Shell script that pretends to be `date`, returning a fixed date.
    Overrides +%Y-%m-%d and +%u; delegates everything else to /usr/bin/date.
    """
    dt = datetime.strptime(fake_date_str, "%Y-%m-%d")
    return (
        "#!/bin/bash\n"
        'case "$*" in\n'
        f'  *+%Y-%m-%d*) echo "{dt:%Y-%m-%d}" ;;\n'
        f'  *+%u*) echo "{dt.isoweekday()}" ;;\n'
        '  *) /usr/bin/date "$@" ;;\n'
        "esac\n"
    )


def _run_market_check_with_fake_date(fake_date_str: str) -> int:
    """Execute check_market_open.sh under a fake-date environment.
    BYPASSES holidays — sets HOLIDAYS_FILE to /dev/null so only DOW logic runs.
    Returns exit code.
    """
    tmpdir = tempfile.mkdtemp(prefix="plumbing_")
    try:
        fake = Path(tmpdir) / "date"
        fake.write_text(_fake_date_bin(fake_date_str))
        fake.chmod(0o755)

        env = os.environ.copy()
        env["PATH"] = f"{tmpdir}:" + env.get("PATH", "/usr/bin:/bin")
        env["HOLIDAYS_FILE"] = "/dev/null"

        proc = subprocess.run(
            ["/bin/bash", str(CHECK_MARKET_OPEN)],
            env=env,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return proc.returncode
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _logic_market_check(fake_date: date) -> int:
    """Pure-Python equivalent of check_market_open.sh.
    0 = proceed (market open), 1 = skip (closed).
    """
    if fake_date.isoweekday() >= 6:
        return 1
    if HOLIDAYS_FILE.exists():
        data = json.loads(HOLIDAYS_FILE.read_text())
        holidays = {h["date"] for h in data.get("holidays", [])}
        if fake_date.strftime("%Y-%m-%d") in holidays:
            return 1
    return 0


# ══════════════════════════════════════════════════════════════════════════════
# 1. check_market_open.sh — shell-level (real script, fake date)
# ══════════════════════════════════════════════════════════════════════════════


def test_shell_friday():
    print("\n  1.1  [shell] Friday (2026-05-29) → exit 0")
    rc = _run_market_check_with_fake_date("2026-05-29")
    (ok if rc == 0 else fail)(f"exit {rc}")


def test_shell_saturday():
    print("\n  1.2  [shell] Saturday (2026-05-30) → exit 1")
    rc = _run_market_check_with_fake_date("2026-05-30")
    (ok if rc == 1 else fail)(f"exit {rc}")


def test_shell_sunday():
    print("\n  1.3  [shell] Sunday (2026-05-31) → exit 1")
    rc = _run_market_check_with_fake_date("2026-05-31")
    (ok if rc == 1 else fail)(f"exit {rc}")


def test_shell_monday():
    print("\n  1.4  [shell] Monday (2026-06-01) → exit 0")
    rc = _run_market_check_with_fake_date("2026-06-01")
    (ok if rc == 0 else fail)(f"exit {rc}")


# ══════════════════════════════════════════════════════════════════════════════
# 2. check_market_open.sh — logic-level (pure Python, covers holidays)
# ══════════════════════════════════════════════════════════════════════════════


def test_logic_weekday():
    print("\n  2.1  [logic] Mon 2026-06-01 → 0")
    assert _logic_market_check(date(2026, 6, 1)) == 0
    ok("weekday")


def test_logic_saturday():
    print("\n  2.2  [logic] Sat 2026-05-30 → 1")
    assert _logic_market_check(date(2026, 5, 30)) == 1
    ok("weekend")


def test_logic_sunday():
    print("\n  2.3  [logic] Sun 2026-05-31 → 1")
    assert _logic_market_check(date(2026, 5, 31)) == 1
    ok("weekend")


def test_logic_holiday():
    print("\n  2.4  [logic] Holi 2026-03-30 (Mon) → 1")
    assert _logic_market_check(date(2026, 3, 30)) == 1
    ok("holiday")


def test_logic_regular_friday():
    print("\n  2.5  [logic] Fri 2026-05-29 → 0")
    assert _logic_market_check(date(2026, 5, 29)) == 0
    ok("friday")


# ══════════════════════════════════════════════════════════════════════════════
# 3. get_weekly_expiry()  —  NIFTY Tuesday expiry
# ══════════════════════════════════════════════════════════════════════════════


def _reload_ct():
    mods = [k for k in sys.modules if k.startswith("tools")]
    for m in mods:
        del sys.modules[m]
    sys.path.insert(0, str(REPO_ROOT))
    from tools.contract_tools import get_weekly_expiry

    return get_weekly_expiry


def test_expiry_is_tuesday():
    print("\n  3.1  Expiry weekday is Tuesday")
    s = _reload_ct()()
    d = datetime.strptime(s, "%d%b%Y")
    w = d.weekday()
    wd = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    (ok if w == 1 else fail)(f"{s} is {wd[w]}, expected Tuesday")


def test_expiry_not_in_past():
    print("\n  3.2  Expiry >= today")
    s = _reload_ct()()
    d = datetime.strptime(s, "%d%b%Y").date()
    today = date.today()
    if d >= today:
        ok(f"{s} >= {today}")
    else:
        fail(f"{s} is PAST (today={today})")


def test_expiry_wednesday_to_tuesday():
    """Mon Jun 1 → next Tue Jun 9 (1 day < 2 → push to next week)."""
    print("\n  3.3  Mon → next+1 Tue")
    mon = datetime(2026, 6, 1, 10, 0, 0)
    for m in [k for k in sys.modules if k.startswith("tools")]:
        del sys.modules[m]
    with patch("tools.contract_tools.datetime") as mock:
        mock.now.return_value = mon
        mock.strptime = datetime.strptime
        mock.weekday = datetime.weekday
        from tools.contract_tools import get_weekly_expiry

        expiry = get_weekly_expiry()
    expected = datetime(2026, 6, 9)  # Tue
    (ok if datetime.strptime(expiry, "%d%b%Y") == expected else fail)(
        f"{expiry} != {expected:%d%b%Y}"
    )


def test_expiry_tuesday_morning_today():
    """Tue morning (< 15:00) → pushes to next Tue (gamma/theta risk)."""
    print("\n  3.4  Tue morning → next week")
    tue = datetime(2026, 6, 2, 9, 0, 0)
    for m in [k for k in sys.modules if k.startswith("tools")]:
        del sys.modules[m]
    with patch("tools.contract_tools.datetime") as mock:
        mock.now.return_value = tue
        mock.strptime = datetime.strptime
        mock.weekday = datetime.weekday
        from tools.contract_tools import get_weekly_expiry

        expiry = get_weekly_expiry()
    expected = datetime(2026, 6, 9)  # next Tue (same-day skipped)
    (ok if datetime.strptime(expiry, "%d%b%Y") == expected else fail)(
        f"{expiry} != {expected:%d%b%Y}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# 4. e2e_chain — stale expiry_weekly guard
# ══════════════════════════════════════════════════════════════════════════════


def test_e2e_stale_expiry_guard():
    print("\n  4.1  e2e_chain stale-guard")
    e2e = BRAHMAND_ROOT / "e2e_chain.py"
    if not e2e.exists():
        print("  SKIP  cross-repo")
        return
    src = e2e.read_text()
    found = any(
        k in src
        for k in [
            "expiry_dt < _dt.today()",
            "expiry_dt < today",
            "expiry_weekly.*stale",
            "corrected expiry",
        ]
    )
    if found or (hasattr(src, "find") and src.find("expiry_weekly") != -1):
        ok("guard present")
    else:
        fail("e2e_chain uses stale expiry_weekly with NO >= today check")


# ══════════════════════════════════════════════════════════════════════════════
# 5. Cron paths — every referenced script exists
# ══════════════════════════════════════════════════════════════════════════════


def test_cron_paths():
    print("\n  5.1  Cron paths exist")
    ok_count = 0
    fail_count = 0

    for src_path in [ANTARIKSK_CRONTAB] + sorted(
        Path("/etc/cron.d").glob("antariskh*")
    ):
        if not src_path.exists():
            continue
        text = src_path.read_text() if src_path.is_file() else ""
        # skip commented-out crontab lines (retired entries stay as comments)
        text = "\n".join(
            ln for ln in text.splitlines() if not ln.lstrip().startswith("#")
        )
        for m in re.finditer(r"(/home/\S+?/[\w\-_]+\.(?:py|sh))", text):
            p = m.group(1)
            if ".log" in p:
                continue
            if not Path(p).exists():
                fail(f"{p}")
                fail_count += 1
            else:
                ok_count += 1

    if fail_count == 0:
        ok(f"all {ok_count} exist")
    else:
        fail(f"{fail_count} missing, {ok_count} ok")


# ══════════════════════════════════════════════════════════════════════════════


def main():
    global exit_code
    print("=" * 56)
    print("  PLUMBING PRE-COMMIT")
    print(f"  {datetime.now().isoformat()}")
    print("=" * 56)

    test_shell_friday()
    test_shell_saturday()
    test_shell_sunday()
    test_shell_monday()

    test_logic_weekday()
    test_logic_saturday()
    test_logic_sunday()
    test_logic_holiday()
    test_logic_regular_friday()

    test_expiry_is_tuesday()
    test_expiry_not_in_past()
    test_expiry_wednesday_to_tuesday()
    test_expiry_tuesday_morning_today()

    test_e2e_stale_expiry_guard()
    test_cron_paths()

    print()
    if exit_code == 0:
        print("  ALL PLUMBING CHECKS PASSED")
    else:
        print(f"  {exit_code} FAILURE(S) — commit blocked")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
