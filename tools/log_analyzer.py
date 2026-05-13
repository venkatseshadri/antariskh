#!/usr/bin/env python3
"""
Log Analyzer Daemon — standalone watcher outside CrewAI/Ralph.

Scans all Antariksh + system logs every 30 min, detects issues,
and pushes a clean markdown report to Telegram.

Systemd: deploy/antariskh-log-analyzer.service
Logs:   logs/log_analyzer.log
"""

import os
import re
import sys
import json
import time
import gzip
import logging
import subprocess
import traceback
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import defaultdict

IST = timezone(timedelta(hours=5, minutes=30))
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | LOG-ANALYZER | %(message)s",
    handlers=[
        logging.FileHandler(PROJECT_ROOT / "logs" / "log_analyzer.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("LogAnalyzer")

# ============================================================
# Configuration
# ============================================================

POLL_INTERVAL = 1800  # 30 minutes
LOOKBACK_WINDOW = 100  # lines per log file (per window)
MAX_SCAN_FILES = 8  # max backlog files to scan per pattern
LAST_REPORT_FILE = PROJECT_ROOT / "logs" / "last_report.md"
CURSOR_FILE = PROJECT_ROOT / "logs" / ".log_cursors.json"
MAX_FINDINGS_IN_REPORT = 20  # cap total findings in Telegram to avoid flooding

# Log sources to monitor
LOG_SOURCES = [
    # (pattern, label, severity) — severity determines if flagged in report
    ("logs/*.log", "Antariksh", "medium"),
    ("logs/ralph_scheduler.log", "Ralph Scheduler", "high"),
    ("logs/ralph*.log", "Ralph Loop", "high"),
    # Python-trader logs (sibling project)
    ("/home/trading_ceo/python-trader/*.log", "Python Trader", "medium"),
    ("/home/trading_ceo/python-trader/logs/*.log", "Trader Logs", "low"),
    # Scheduler & cron logs
    ("/home/trading_ceo/python-trader/logs/system/*.log", "System Logs", "medium"),
]

# Cron/syslog scanning (via journal, not glob)
SCAN_SYSLOG_CRON = True
CRON_GREP_PATTERNS = [
    "CRON",
    "varaha",
    "kurma",
    "token_refresh",
    "session_orchestrator",
    "antariskh",
    "picoclaw",
]
SYSLOG_TAIL_LINES = 200

# Regex patterns to detect — (pattern, label, severity)
DETECTORS = [
    # Critical — immediate attention
    (r"ERROR|CRITICAL|FATAL", "ERROR", "critical"),
    (
        r"401\s|403\s|Invalid API|INVALID_IP|api_key.*invalid",
        "API Auth Failure",
        "critical",
    ),
    (r"Token exchange failed|token.*expired|token.*stale", "Token Failure", "critical"),
    (r"Session Expired|Invalid Session", "Session Expired", "critical"),
    (r"INSUFFICIENT.*MARGIN|margin.*exceeded|risk.*breach", "Risk Breach", "critical"),
    (r"RALPH ESCALATION|escalation_needed", "Ralph Escalation", "critical"),
    (
        r"crew_kickoff.*failed|agent_execution_error|agent.*crashed",
        "Crew Failure",
        "critical",
    ),
    (r"GOOGLE_CHROME.*not found|chrome.*launch.*fail", "Chrome Failure", "critical"),
    # Warning — needs attention
    (r"WARNING|WARN ", "Warning", "warning"),
    (r"timeout|timed out|timeout exceeded", "Timeout", "warning"),
    (r"retry|retrying|will retry", "Retry", "warning"),
    (r"No roles due|empty.*result|no data", "Idle/No Data", "low"),
    (r"event pairing mismatch", "Event Order Issue", "warning"),
    # Info — context only
    (r"TOKEN REFRESH.*FAIL|token_refresh.*FAIL", "Token Refresh Failed", "critical"),
    (r"TOKEN REFRESH.*SUCCESS|token.*refreshed", "Token Refreshed", "info"),
    (r"RALPH LOOP CYCLE.*COMPLETE", "Ralph Cycle OK", "info"),
]

# Telegram config
CHAT_ID = "8317944043"


def load_telegram_token():
    """Load Telegram bot token from Picoclaw security file or env var."""
    security_path = "/root/.picoclaw/.security.yml"
    try:
        if os.path.exists(security_path):
            import yaml
            with open(security_path) as f:
                s = yaml.safe_load(f)
            token = (
                s.get("channel_list", {})
                .get("telegram", {})
                .get("settings", {})
                .get("token", "")
            )
            if token:
                return token
    except Exception:
        pass
    return os.environ.get("TELEGRAM_BOT_TOKEN", "") or None


def send_telegram(text: str, save: bool = True):
    """Send markdown message to Telegram. Optionally save to last_report."""
    # Escape underscores in non-code blocks to avoid Markdown parse errors
    escaped = []
    in_code = False
    for line in text.split("\n"):
        if line.startswith("    ") or line.startswith("\t"):
            in_code = True
        elif line.strip() and not line.startswith(" "):
            in_code = False
        if not in_code:
            line = line.replace("_", "\\_")
        escaped.append(line)
    text = "\n".join(escaped)

    if save:
        try:
            with open(LAST_REPORT_FILE, "w") as f:
                f.write(text)
        except Exception:
            pass

    token = load_telegram_token()
    if not token or not CHAT_ID:
        logger.error("Cannot send Telegram: missing token or chat ID")
        return False

    try:
        import requests

        # Truncate to Telegram's 4096 char limit
        if len(text) > 4000:
            text = text[:4000] + "\n...(truncated for Telegram)"
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        if resp.status_code == 200:
            logger.info("Telegram report sent")
            return True
        else:
            logger.error(f"Telegram send failed: {resp.status_code} {resp.text[:100]}")
            return False
    except Exception as e:
        logger.error(f"Telegram send exception: {e}")
        return False


def load_cursors() -> dict:
    """Load saved byte offsets for log files."""
    try:
        if CURSOR_FILE.exists():
            return json.loads(CURSOR_FILE.read_text())
    except Exception:
        pass
    return {}


def save_cursors(cursors: dict):
    """Persist byte offsets so next scan picks up only new lines."""
    try:
        CURSOR_FILE.parent.mkdir(parents=True, exist_ok=True)
        CURSOR_FILE.write_text(json.dumps(cursors, indent=2))
    except Exception as e:
        logger.warning(f"Failed to save cursors: {e}")


def scan_log_file(filepath: Path, cursors: dict) -> list:
    """Scan a log file for issues since the last cursor position.

    Tracks byte offset per file. After reading, updates the cursor
    so the same lines are never reported twice.
    """
    findings = []
    try:
        key = str(filepath.resolve())
        last_offset = cursors.get(key, 0)

        if filepath.suffix == ".gz":
            with gzip.open(filepath, "rt", errors="ignore") as f:
                content = f.read()
        else:
            with open(filepath, "r", errors="ignore") as f:
                content = f.read()

        file_size = len(content)

        # If file was truncated/rotated, reset cursor
        if last_offset > file_size:
            last_offset = 0

        new_content = content[last_offset:]
        if not new_content.strip():
            return findings

        lines = new_content.split("\n")
        base_line = content[:last_offset].count("\n") + 1

        for i, line in enumerate(lines):
            for pattern, label, severity in DETECTORS:
                if re.search(pattern, line, re.IGNORECASE):
                    findings.append(
                        {
                            "file": str(filepath),
                            "line": base_line + i,
                            "label": label,
                            "severity": severity,
                            "text": line.strip()[:200],
                        }
                    )
                    break  # one label per line

        # Update cursor to end of file
        cursors[key] = file_size

    except Exception as e:
        logger.warning(f"Cannot read {filepath}: {e}")

    return findings


def scan_syslog_cron() -> list:
    """Scan /var/log/syslog for cron job entries and scheduler events."""
    findings = []
    try:
        # Build grep for relevant patterns
        grep_re = "|".join(CRON_GREP_PATTERNS)
        result = subprocess.run(
            ["grep", "-iE", grep_re, "/var/log/syslog"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        lines = result.stdout.strip().split("\n") if result.stdout else []
        recent = lines[-SYSLOG_TAIL_LINES:] if len(lines) > SYSLOG_TAIL_LINES else lines

        for line in recent:
            for pattern, label, severity in DETECTORS:
                if re.search(pattern, line, re.IGNORECASE):
                    findings.append(
                        {
                            "file": "syslog",
                            "line": 0,
                            "label": label,
                            "severity": severity,
                            "text": line.strip()[:200],
                        }
                    )
                    break
    except Exception as e:
        logger.warning(f"Syslog scan failed: {e}")
    return findings


def scan_picoclaw_journal() -> list:
    """Scan picoclaw systemd journal for Kubera/Picoclaw events."""
    findings = []
    try:
        result = subprocess.run(
            [
                "journalctl",
                "-u",
                "picoclaw",
                "--no-pager",
                "-q",
                "--since",
                "30 min ago",
                "-n",
                "100",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        lines = [l for l in result.stdout.split("\n") if l.strip()]
        for line in lines:
            for pattern, label, severity in DETECTORS:
                if re.search(pattern, line, re.IGNORECASE):
                    findings.append(
                        {
                            "file": "picoclaw-journal",
                            "line": 0,
                            "label": label,
                            "severity": severity,
                            "text": line.strip()[:200],
                        }
                    )
                    break
    except Exception as e:
        logger.warning(f"Picoclaw journal scan failed: {e}")
    return findings


def scan_scheduler_summary() -> dict:
    """Quick check: are scheduler services alive?"""
    summary = {
        "picoclaw": False,
        "cron_jobs_in_syslog": False,
        "ralph_scheduler": False,
    }
    try:
        # Check if picoclaw service is active
        r = subprocess.run(
            ["systemctl", "is-active", "picoclaw"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        summary["picoclaw"] = r.stdout.strip() == "active"

        # Check ralph-sched service
        r = subprocess.run(
            ["systemctl", "is-active", "ralph-sched"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        summary["ralph_scheduler"] = r.stdout.strip() == "active"

        # Check if recent cron entries exist (last 2 hours)
        r = subprocess.run(
            ["grep", "-c", "CRON", "/var/log/syslog"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        summary["cron_jobs_in_syslog"] = int(r.stdout.strip() or 0) > 0

    except Exception:
        pass
    return summary


def scan_all_sources() -> list:
    """Scan all configured log sources and return findings."""
    all_findings = []
    cursors = load_cursors()

    # 1. File-based log sources
    for pattern, label, severity in LOG_SOURCES:
        if pattern.startswith("/"):
            files = sorted(Path("/").glob(pattern.lstrip("/")))
        else:
            files = sorted(PROJECT_ROOT.glob(pattern))

        cutoff = time.time() - 7200
        recent_files = [f for f in files if f.is_file() and f.stat().st_mtime > cutoff]

        for f in recent_files[-MAX_SCAN_FILES:]:
            findings = scan_log_file(f, cursors)
            for finding in findings:
                finding["source"] = label
            all_findings.extend(findings)

    # Persist updated cursors so scanned lines aren't re-reported
    save_cursors(cursors)

    # 2. Syslog cron entries
    if SCAN_SYSLOG_CRON:
        cron_findings = scan_syslog_cron()
        for f in cron_findings:
            f["source"] = "Cron/Syslog"
        all_findings.extend(cron_findings)

    # 3. Picoclaw journal
    picoclaw_findings = scan_picoclaw_journal()
    for f in picoclaw_findings:
        f["source"] = "Picoclaw"
    all_findings.extend(picoclaw_findings)

    return all_findings


def check_token_freshness() -> dict:
    """Check current token freshness via OM tools (non-mock)."""
    try:
        os.environ["ANTARIKSH_MOCK_MODE"] = "0"
        sys.path.insert(0, str(PROJECT_ROOT))
        from tools.om_tools import token_refresh_status

        result = token_refresh_status()
        return {
            "shoonya_ok": result.get("shoonya", False),
            "flattrade_ok": result.get("flattrade", False),
            "evidence": result.get("evidence", ""),
        }
    except Exception as e:
        logger.warning(f"Token freshness check failed: {e}")
        return {"shoonya_ok": False, "flattrade_ok": False, "evidence": f"Error: {e}"}


def build_report(
    findings: list, token_status: dict, scheduler_status: dict = None
) -> str:
    """Build a clean markdown Telegram report from findings."""
    now = datetime.now(IST).strftime("%H:%M IST")
    lines = [f"📊 *Antariksh Health Report* — {now}", ""]

    # Token status
    shoonya_status = "🟢" if token_status.get("shoonya_ok") else "🔴"
    flattrade_status = "🟢" if token_status.get("flattrade_ok") else "🔴"
    lines.append(f"🔑 Tokens: Shoonya {shoonya_status}  Flattrade {flattrade_status}")
    lines.append(f"_{token_status.get('evidence', '')}_")
    lines.append("")

    # Scheduler health
    if scheduler_status:
        pico = "🟢" if scheduler_status.get("picoclaw") else "🔴"
        cron_ok = "🟢" if scheduler_status.get("cron_jobs_in_syslog") else "🟡"
        ralph_ok = "🟢" if scheduler_status.get("ralph_scheduler") else "🟡"
        lines.append(f"⏱️ Schedulers: Picoclaw {pico}  Cron {cron_ok}  Ralph {ralph_ok}")
        lines.append("")

    # Categorize findings
    criticals = [f for f in findings if f["severity"] == "critical"]
    warnings = [f for f in findings if f["severity"] == "warning"]
    infos = [f for f in findings if f["severity"] == "info"]

    total = len(findings)
    capped = total > MAX_FINDINGS_IN_REPORT

    if capped:
        # Show counts only, no individual lines — backlog mode
        lines.append(f"📦 *Backlog: {total} findings* (first scan after cursor reset)")
        lines.append(f"  🔴 {len(criticals)} critical, 🟡 {len(warnings)} warnings, ℹ️ {len(infos)} info")
        lines.append(f"  _These are pre-existing. Next report will show only NEW issues._")
        lines.append("")
    elif (
        not findings
        and token_status.get("shoonya_ok")
        and token_status.get("flattrade_ok")
    ):
        lines.append("✅ *All systems healthy* — no new issues detected")
    else:
        # Count by label
        label_counts = defaultdict(int)
        for f in criticals + warnings:
            label_counts[f["label"]] += 1

        if criticals:
            lines.append(f"🔴 *{len(criticals)} Critical*")
            for f in criticals[:5]:
                src = f.get("source", "")
                txt = f["text"][:120].replace("*", "\\*")
                lines.append(f"  - [{src}] `{f['label']}`: {txt}")
            if len(criticals) > 5:
                lines.append(f"  • ... and {len(criticals) - 5} more")
            lines.append("")

        if warnings:
            lines.append(f"🟡 *{len(warnings)} Warnings*")
            for f in warnings[:3]:
                src = f.get("source", "")
                txt = f["text"][:100].replace("*", "\\*")
                lines.append(f"  - [{src}] {txt}")
            if len(warnings) > 3:
                lines.append(f"  • ... and {len(warnings) - 3} more")
            lines.append("")

        if infos:
            lines.append(f"ℹ️ *{len(infos)} Info Events*")

    lines.append("")
    lines.append(f"_Next report in 30 min_")
    return "\n".join(lines)


def main():
    logger.info("=" * 60)
    logger.info("LOG ANALYZER DAEMON — STARTING")
    logger.info(f"Poll interval: {POLL_INTERVAL}s ({POLL_INTERVAL // 60} min)")
    logger.info(f"Sources: {len(LOG_SOURCES)}")
    logger.info(f"Detectors: {len(DETECTORS)}")
    logger.info("=" * 60)

    while True:
        try:
            start = time.monotonic()

            logger.info("Scanning logs...")
            findings = scan_all_sources()
            token_status = check_token_freshness()
            scheduler_status = scan_scheduler_summary()

            logger.info(
                f"Found {len(findings)} issues "
                f"(critical={sum(1 for f in findings if f['severity'] == 'critical')}, "
                f"warn={sum(1 for f in findings if f['severity'] == 'warning')})"
            )

            report = build_report(findings, token_status, scheduler_status)
            sent = send_telegram(report)

            if sent:
                logger.info("Report pushed to Telegram")
            else:
                logger.warning("Failed to push report")

            elapsed = time.monotonic() - start
            sleep_for = max(1, POLL_INTERVAL - elapsed)
            logger.info(f"Sleeping {sleep_for:.0f}s until next scan")
            time.sleep(sleep_for)

        except KeyboardInterrupt:
            logger.info("Shutdown requested — exiting")
            break
        except Exception as e:
            logger.error(f"Scan cycle failed: {e}")
            traceback.print_exc()
            time.sleep(120)  # back off on errors


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("--once", "--now"):
        # On-demand: run one cycle and print
        findings = scan_all_sources()
        token_status = check_token_freshness()
        scheduler_status = scan_scheduler_summary()
        report = build_report(findings, token_status, scheduler_status)
        print(report)
        send_telegram(report, save=True)
    elif len(sys.argv) > 1 and sys.argv[1] == "--last":
        # Return last saved report
        if LAST_REPORT_FILE.exists():
            print(LAST_REPORT_FILE.read_text())
        else:
            print("No saved report yet.")
    else:
        # Daemon mode
        main()
