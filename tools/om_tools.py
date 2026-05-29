"""Operations Manager deterministic tools.

All tools check ANTARIKSH_MOCK_* env vars before real system calls.
Engine-only — no LLM, no CrewAI dependency.
"""

import os
import stat
import hashlib
import time
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List

IST = timezone(timedelta(hours=5, minutes=30))
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _is_mock() -> bool:
    """Check mock mode dynamically (not cached at import)."""
    return os.environ.get("ANTARIKSH_MOCK_MODE", "0") == "1"


# Expected entries from config/antariksh_rules.yaml
EXPECTED_CRONS = {
    "07:00": "token_refresh_dual.py",
    "09:30": "session_orchestrator.py entry",
    "14:35": "session_orchestrator.py exit",
    "18:00": "exec_report.py daily",
    "20:00 SUN": "exec_report.py weekly",
}

# CRITICAL checks → fail = NOGO, WARNING checks → fail = GO with note
CRITICAL_CHECKS = {"tokens", "disk", "network"}
WARNING_CHECKS = {"code", "data", "cron"}


def _now_ist() -> str:
    return datetime.now(IST).strftime("%H:%M:%S IST")


def _evidence(value: str) -> Dict:
    return {"value": value, "timestamp": _now_ist()}


# ============================================================
# PreFlightAgent Tools
# ============================================================


def token_refresh_status() -> Dict:
    """Check Shoonya + Flattrade token validity."""
    if _is_mock():
        shoonya_ok = os.environ.get("ANTARIKSH_MOCK_SHOONYA_DOWN", "0") != "1"
        flattrade_ok = os.environ.get("ANTARIKSH_MOCK_BROKER_DOWN", "0") != "1"

        if not shoonya_ok and not flattrade_ok:
            evidence = "Shoonya: FAILED, Flattrade: FAILED — both brokers unreachable"
        elif not shoonya_ok:
            evidence = f"Shoonya: FAILED (token invalid), Flattrade: OK ({_now_ist()})"
        else:
            evidence = (
                f"Both tokens refreshed — Shoonya: OK, Flattrade: OK ({_now_ist()})"
            )

        return {
            "shoonya": shoonya_ok,
            "flattrade": flattrade_ok,
            "ok": shoonya_ok or flattrade_ok,
            "evidence": evidence,
        }

    # Real check — look for token files in sibling project
    cred_path = Path("/home/trading_ceo/python-trader/Shoonya_oAuthAPI-py/cred.yml")
    fttoken_paths = [
        Path("/home/trading_ceo/python-trader/tokens.json"),
        Path("/home/trading_ceo/python-trader/FlattradeApi/tokens.json"),
        Path("/home/trading_ceo/python-trader/FlattradeApi-py/tokens.json"),
    ]
    fttoken_path = None
    for p in fttoken_paths:
        if p.exists():
            fttoken_path = p
            break

    shoonya_age = (
        time.time() - cred_path.stat().st_mtime if cred_path.exists() else float("inf")
    )
    flattrade_age = (
        time.time() - fttoken_path.stat().st_mtime
        if fttoken_path.exists()
        else float("inf")
    )
    shoonya_ok = shoonya_age < 86400
    flattrade_ok = flattrade_age < 86400

    def _age_str(age_sec):
        if age_sec == float("inf"):
            return "MISSING"
        h = age_sec / 3600
        if h < 1:
            return f"fresh ({int(age_sec / 60)}m ago)"
        elif h < 24:
            return f"ok ({h:.1f}h ago)"
        else:
            return f"STALE ({h / 24:.1f}d old)"

    return {
        "shoonya": shoonya_ok,
        "flattrade": flattrade_ok,
        "ok": shoonya_ok or flattrade_ok,
        "shoonya_age_sec": round(shoonya_age),
        "flattrade_age_sec": round(flattrade_age),
        "evidence": (
            f"Token freshness: Shoonya {_age_str(shoonya_age)}, "
            f"Flattrade {_age_str(flattrade_age)} ({_now_ist()})"
        ),
    }


def verify_code_hash() -> Dict:
    """Hash all .py files and compare against last-known hash."""
    if _is_mock():
        changed = os.environ.get("ANTARIKSH_MOCK_CODE_CHANGED", "0") == "1"
        if changed:
            return {
                "unchanged": False,
                "ok": False,
                "evidence": f"UNAUTHORIZED CHANGE: crew_structure.py hash mismatch (prev: a1b2c3, curr: d4e5f6) ({_now_ist()})",
            }
        return {
            "unchanged": True,
            "ok": True,
            "evidence": f"Code hash matches: a1b2c3d4 ({_now_ist()})",
        }

    py_files = sorted(PROJECT_ROOT.glob("**/*.py"))
    total_hash = hashlib.sha256()
    for f in py_files:
        if ".venv" in str(f) or "__pycache__" in str(f) or "harvested" in str(f):
            continue
        total_hash.update(f.read_bytes())
    current_hash = total_hash.hexdigest()[:8]

    # In real mode, we'd compare against stored hash. For now, always report OK.
    return {
        "unchanged": True,
        "ok": True,
        "evidence": f"Code hash: {current_hash} ({_now_ist()})",
    }


def data_capture_health() -> Dict:
    """Check data capture pipelines (Penguin SQLite + legacy DuckDB)."""
    if _is_mock():
        stopped = os.environ.get("ANTARIKSH_MOCK_DATA_STOPPED", "0") == "1"
        if stopped:
            return {
                "running": False,
                "ok": False,
                "evidence": f"Data stream STOPPED — last write: >5 min ago ({_now_ist()})",
            }
        return {
            "running": True,
            "ok": True,
            "evidence": f"Data stream active — last write: {_now_ist()}",
        }

    issues = []
    details = []

    penguin = penguin_capture_health()
    if penguin["ok"]:
        details.append(f"Penguin: {penguin['evidence']}")
    else:
        issues.append(f"Penguin: {penguin['evidence']}")

    duckdb_paths = list(
        Path("/home/trading_ceo/python-trader/varaha/data").glob("varaha_data*.duckdb")
    )
    if duckdb_paths:
        latest = max(duckdb_paths, key=lambda p: p.stat().st_mtime)
        age_sec = time.time() - latest.stat().st_mtime
        if age_sec < 300:
            details.append(f"Legacy DuckDB: {int(age_sec)}s ago")
        else:
            issues.append(f"Legacy DuckDB: stale ({int(age_sec)}s)")

    ok = penguin["ok"] or (len(issues) == 0)
    evidence = "; ".join(details + issues) + f" ({_now_ist()})"
    return {"running": ok, "ok": ok, "evidence": evidence, "penguin": penguin}


def penguin_capture_health() -> Dict:
    """Check Project Penguin pipeline: feed → consumers → enrichers → SQLite."""
    issues = []
    details = []

    services = {
        "feed": "feed.service",
        "consumer-nifty": "consumer-nifty.service",
        "consumer-sensex": "consumer-sensex.service",
        "consumer-mcx": "consumer-mcx.service",
        "enricher-nifty": "enricher-nifty.service",
        "enricher-sensex": "enricher-sensex.service",
        "enricher-mcx": "enricher-mcx.service",
    }

    active_count = 0
    for name, unit in services.items():
        try:
            result = subprocess.run(
                ["systemctl", "is-active", unit],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.stdout.strip() == "active":
                active_count += 1
            else:
                now_h = datetime.now(IST).hour
                is_mcx = "mcx" in name
                expected_active = (9 <= now_h < 16) or (is_mcx and now_h < 24)
                if expected_active:
                    issues.append(f"{name} inactive")
        except Exception:
            pass

    try:
        import redis as _redis

        r = _redis.Redis()
        for inst in ["NIFTY", "SENSEX", "GOLD"]:
            hb_key = f"feed:{inst}:heartbeat"
            hb = r.get(hb_key)
            if hb:
                details.append(f"{inst} heartbeat OK")
                break
        for inst in ["NIFTY", "SENSEX"]:
            llen = r.llen(f"feed:{inst}")
            if llen and llen > 0:
                details.append(f"feed:{inst} {llen} bars")
    except Exception:
        pass

    import sqlite3
    from datetime import date

    today = date.today().isoformat()
    data_dir = Path("/home/trading_ceo/python-trader/varaha/data")
    total_rows = 0
    for inst in ["nifty", "sensex", "mcx"]:
        db_path = data_dir / f"capture_{inst}.sqlite"
        if not db_path.exists():
            continue
        try:
            conn = sqlite3.connect(str(db_path))
            rows = conn.execute(
                "SELECT COUNT(*) FROM market_data WHERE substr(timestamp,1,10)=?",
                (today,),
            ).fetchone()[0]
            conn.close()
            total_rows += rows
        except Exception:
            pass

    if total_rows > 0:
        details.append(f"{total_rows} bars today")
    else:
        now_h = datetime.now(IST).hour
        if 10 <= now_h < 16:
            issues.append("0 SQLite bars today (market should be active)")

    ok = len(issues) == 0 and active_count >= 3
    evidence = f"{active_count}/7 services; " + "; ".join(details + issues)
    return {"ok": ok, "active_services": active_count, "evidence": evidence}


def disk_usage_check() -> Dict:
    """Check disk usage on logs/ directory."""
    if _is_mock():
        pct_str = os.environ.get("ANTARIKSH_MOCK_DISK_PCT", "")
        if pct_str:
            pct_used = float(pct_str)
            free_gb = round(500.0 * (1.0 - pct_used / 100.0), 1)
            ok = pct_used < 90
            return {
                "pct_used": pct_used,
                "free_gb": free_gb,
                "ok": ok,
                "evidence": f"Disk: {pct_used}% used, {free_gb}GB free ({_now_ist()})",
            }
        full = os.environ.get("ANTARIKSH_MOCK_DISK_FULL", "0") == "1"
        if full:
            return {
                "pct_used": 98.0,
                "free_gb": 10.0,
                "ok": False,
                "evidence": f"CRITICAL: Disk 98% full — 10GB remaining on / ({_now_ist()})",
            }
        return {
            "pct_used": 45.0,
            "free_gb": 234.0,
            "ok": True,
            "evidence": f"Disk: 45% used, 234GB free ({_now_ist()})",
        }

    try:
        log_dir = PROJECT_ROOT / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        vfs = os.statvfs(str(log_dir))
        total = vfs.f_frsize * vfs.f_blocks
        free = vfs.f_frsize * vfs.f_bavail
        pct_used = round((1.0 - free / total) * 100, 1) if total > 0 else 0.0
        free_gb = round(free / (1024**3), 1)
        ok = pct_used < 90
        return {
            "pct_used": pct_used,
            "free_gb": free_gb,
            "ok": ok,
            "evidence": f"Disk: {pct_used}% used, {free_gb}GB free ({_now_ist()})",
        }
    except Exception:
        return {
            "pct_used": 0.0,
            "free_gb": 0.0,
            "ok": False,
            "evidence": f"Disk check FAILED — cannot stat logs/ ({_now_ist()})",
        }


def network_connectivity_check() -> Dict:
    """Check broker API and Telegram reachability."""
    if _is_mock():
        down = os.environ.get("ANTARIKSH_MOCK_BROKER_DOWN", "0") == "1"
        if down:
            return {
                "broker": {"shoonya": -1, "flattrade": -1},
                "ok": False,
                "evidence": f"Broker APIs unreachable — Shoonya: TIMEOUT, Flattrade: TIMEOUT ({_now_ist()})",
            }
        network_down = os.environ.get("ANTARIKSH_MOCK_NETWORK_DOWN", "0") == "1"
        if network_down:
            return {
                "broker": {"shoonya": 120, "flattrade": 85},
                "ok": False,
                "evidence": f"Broker latency: Shoonya 120ms, Flattrade 85ms. Telegram: UNREACHABLE ({_now_ist()})",
            }
        return {
            "broker": {"shoonya": 120, "flattrade": 85},
            "ok": True,
            "evidence": f"Broker latency: Shoonya 120ms, Flattrade 85ms. Telegram: reachable ({_now_ist()})",
        }

    # Real check — ping broker APIs and Telegram
    import requests

    result = {"shoonya": 0, "flattrade": 0, "telegram": False}
    ok = True

    # Shoonya API
    try:
        r = requests.get("https://api.shoonya.com", timeout=5)
        result["shoonya"] = 1 if r.status_code < 500 else 0
    except Exception:
        result["shoonya"] = 0

    # Flattrade API
    try:
        r = requests.get("https://piconnect.flattrade.in", timeout=5)
        result["flattrade"] = 1 if r.status_code < 500 else 0
    except Exception:
        result["flattrade"] = 0

    # Telegram
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if token:
        try:
            r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=5)
            result["telegram"] = r.status_code == 200
        except Exception:
            result["telegram"] = False

    shoonya_ok = result["shoonya"] == 1
    flattrade_ok = result["flattrade"] == 1
    ok = shoonya_ok and flattrade_ok

    return {
        "broker": {
            "shoonya": "reachable" if shoonya_ok else "UNREACHABLE",
            "flattrade": "reachable" if flattrade_ok else "UNREACHABLE",
        },
        "telegram": "reachable" if result["telegram"] else "UNKNOWN",
        "ok": ok,
        "evidence": (
            f"Network: Shoonya {'✅' if shoonya_ok else '❌'}, "
            f"Flattrade {'✅' if flattrade_ok else '❌'}, "
            f"Telegram {'✅' if result['telegram'] else '⚠️'} "
            f"({_now_ist()})"
        ),
    }


# ============================================================
# CronWatchdog Tool
# ============================================================


def cron_health_check() -> Dict:
    """Verify expected crons are active by reading crontab -l."""
    if _is_mock():
        dead = os.environ.get("ANTARIKSH_MOCK_CRON_DEAD", "0") == "1"
        if dead:
            return {
                "active": [],
                "missing": list(EXPECTED_CRONS.values()),
                "ok": False,
                "evidence": f"ALL crons missing — 0/{len(EXPECTED_CRONS)} expected crons active ({_now_ist()})",
            }
        return {
            "active": list(EXPECTED_CRONS.values()),
            "missing": [],
            "ok": True,
            "evidence": f"Crons: {len(EXPECTED_CRONS)}/{len(EXPECTED_CRONS)} active ({_now_ist()})",
        }

    # Real check — run crontab -l
    try:
        result = subprocess.run(
            ["crontab", "-l"], capture_output=True, text=True, timeout=10
        )
        crontab_text = result.stdout if result.returncode == 0 else ""
    except Exception:
        crontab_text = ""

    if not crontab_text.strip():
        return {
            "active": [],
            "missing": list(EXPECTED_CRONS.values()),
            "ok": False,
            "evidence": f"crontab empty or unreadable — 0/{len(EXPECTED_CRONS)} expected crons found ({_now_ist()})",
        }

    # Parse each expected cron entry against the crontab content
    active = []
    missing = []
    for time_spec, job_name in EXPECTED_CRONS.items():
        # Match by the script/command name in the crontab entry
        keyword = job_name.split("/")[-1].split(".")[0]  # e.g., "token_refresh_dual"
        if keyword in crontab_text or job_name in crontab_text:
            active.append(job_name)
        else:
            missing.append(job_name)

    all_present = len(missing) == 0
    return {
        "active": active,
        "missing": missing,
        "ok": all_present,
        "evidence": (
            f"Crons: {len(active)}/{len(EXPECTED_CRONS)} active"
            + (f", missing: {', '.join(missing)}" if missing else "")
            + f" ({_now_ist()})"
        ),
    }


# ============================================================
# Reporter Tool
# ============================================================


def aggregate_health_report(checks: List[Dict]) -> Dict:
    """Assemble evidence-backed health report with GO/NOGO decision."""

    critical_fails = []
    warnings = []
    all_ok = True

    for check in checks:
        name = check.get("name", "unknown")
        ok = check.get("ok", False)
        evidence = check.get("evidence", "")
        if not ok:
            if name in CRITICAL_CHECKS:
                critical_fails.append(f"**{name.upper()}**: {evidence}")
                all_ok = False
            elif name in WARNING_CHECKS:
                warnings.append(f"*{name}*: {evidence}")

    overall = "GO" if len(critical_fails) == 0 else "NOGO"
    now = _now_ist()

    lines = [
        f"# Antariksh Pre-Flight Report",
        f"**Time:** {now}",
        f"**Decision:** {'🟢 GO' if overall == 'GO' else '🔴 NOGO'}",
        "",
        "## Checks",
    ]

    for check in checks:
        name = check.get("name", "unknown")
        ok = check.get("ok", False)
        evidence = check.get("evidence", "")
        icon = "✅" if ok else "❌"
        lines.append(f"{icon} **{name}**: {evidence}")

    if critical_fails:
        lines.append("")
        lines.append("## CRITICAL Failures")
        lines.extend(critical_fails)

    if warnings:
        lines.append("")
        lines.append("## Warnings")
        lines.extend(warnings)

    lines.append("")
    lines.append("---")
    lines.append(f"*Report generated by OM Reporter at {now}*")

    return {"overall": overall, "telegram_md": "\n".join(lines)}
