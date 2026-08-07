"""Permission drift monitor — deterministic, no LLM.

Re-checks the exact permission/ownership invariants this session established
today (2026-07-21) after two live incidents:
  1. Cron `.sh` wrappers lost their execute bit (chmod 640 applied too broadly
     during the algo_validator source-isolation setup) — every trading cron
     failed until fixed.
  2. Penguin's enricher heartbeat files got root-owned, crash-looping the
     trading_ceo-run enricher-nifty/sensex services on PermissionError.

Checks only — a mechanical comparison against a known-good baseline. No
judgment calls, so no LLM involved (this is exactly what a deterministic
checker should do; see CANONICAL_STRATEGY_PLAN's "deterministic logic IS the
system" principle applied to ops tooling too).

Run: python3 permission_guard.py
"""

import grp
import json
import os
import pwd
import stat
import sys
from datetime import datetime
from pathlib import Path

REPOS = [Path("/home/trading_ceo/atom"), Path("/home/trading_ceo/antariksh")]
HEARTBEAT_DIR = Path("/home/trading_ceo/antariksh/data/live")
LOG_PATH = Path("/home/trading_ceo/antariksh/logs/permission_guard.jsonl")

TRADING_CEO_GID = grp.getgrnam("trading_ceo").gr_gid
TRADING_CEO_UID = pwd.getpwnam("trading_ceo").pw_uid

EXCLUDE_DIRS = {"logs", "data", ".git", "__pycache__", "graphify-out", ".venv"}


def _iter_source_files(repo: Path):
    for p in repo.rglob("*"):
        if p.suffix not in (".py", ".sh"):
            continue
        if any(part in EXCLUDE_DIRS for part in p.relative_to(repo).parts[:-1]):
            continue
        if p.is_file():
            yield p


def check_source_perms() -> list[dict]:
    """Source files: group must be trading_ceo, must NOT be world-readable,
    and .sh files must keep owner+group execute (cron/systemd exec them
    directly — losing the x bit is exactly what broke every cron today)."""
    fixes = []
    for repo in REPOS:
        if not repo.exists():
            continue
        for f in _iter_source_files(repo):
            st = f.stat()
            mode = stat.S_IMODE(st.st_mode)
            world_readable = bool(mode & 0o004)
            wrong_group = st.st_gid != TRADING_CEO_GID
            missing_exec = f.suffix == ".sh" and not (mode & 0o110)

            if not (world_readable or wrong_group or missing_exec):
                continue

            before = oct(mode)
            if wrong_group:
                os.chown(f, -1, TRADING_CEO_GID)
            target_mode = 0o750 if f.suffix == ".sh" else 0o640
            os.chmod(f, target_mode)
            fixes.append(
                {
                    "file": str(f),
                    "issue": [
                        k
                        for k, v in {
                            "world_readable": world_readable,
                            "wrong_group": wrong_group,
                            "missing_exec": missing_exec,
                        }.items()
                        if v
                    ],
                    "mode_before": before,
                    "mode_after": oct(target_mode),
                }
            )
    return fixes


def check_heartbeat_ownership() -> list[dict]:
    """Penguin heartbeat files must be owned by trading_ceo (the systemd
    User= for feed/enricher/consumer services) — root ownership crash-loops
    the enricher services on PermissionError, as happened today."""
    fixes = []
    if not HEARTBEAT_DIR.exists():
        return fixes
    for f in HEARTBEAT_DIR.glob("*.heartbeat"):
        st = f.stat()
        if st.st_uid != TRADING_CEO_UID or st.st_gid != TRADING_CEO_GID:
            before = f"{st.st_uid}:{st.st_gid}"
            os.chown(f, TRADING_CEO_UID, TRADING_CEO_GID)
            fixes.append({"file": str(f), "owner_before": before, "owner_after": "trading_ceo:trading_ceo"})
    return fixes


def refresh_validator_feed() -> int:
    """Piggybacks on this cron tick to keep /var/log/algo/*/ current — no
    separate cron for this (2026-07-22: too many crons already). Only the
    daily-rotating cron-stdout logs actually need re-linking each run; the
    trade-evidence files (jsonl ledgers, state json/sqlite, capture DBs) are
    non-dated and get symlinked once, permanently, by the same call."""
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from validator_feed_sync import sync

        return sum(sync().values())
    except Exception as e:
        print(f"[permission_guard] validator feed sync failed (non-fatal): {e}", file=sys.stderr)
        return 0


def main() -> int:
    fixes = check_source_perms() + check_heartbeat_ownership()
    linked = refresh_validator_feed()
    event = {"ts": datetime.now().isoformat(), "fixes": fixes, "count": len(fixes), "feed_files_linked": linked}

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a") as fh:
        fh.write(json.dumps(event, default=str) + "\n")

    if fixes:
        try:
            sys.path.insert(0, str(Path(__file__).parent))
            from telegram_bridge import send_alert

            body = "\n".join(f"- {fx['file']}" for fx in fixes[:10])
            if len(fixes) > 10:
                body += f"\n...and {len(fixes) - 10} more"
            send_alert(
                "warning",
                f"Permission drift auto-corrected ({len(fixes)} file(s))",
                body,
            )
        except Exception as e:
            print(f"[permission_guard] alert failed (non-fatal): {e}", file=sys.stderr)

    print(f"[permission_guard] {len(fixes)} correction(s) applied" if fixes else "[permission_guard] OK, no drift")
    return 0


if __name__ == "__main__":
    sys.exit(main())
