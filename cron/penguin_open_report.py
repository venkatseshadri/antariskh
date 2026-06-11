#!/usr/bin/env python3
"""Penguin open health report → Telegram.

Read-only. Checks the live capture+paper-entry chain and sends a GO/NOGO so the
operator (at work) sees status without troubleshooting. Safe to run anytime.
Scheduled via cron; also runnable by hand: python3 cron/penguin_open_report.py
"""
import os
import sqlite3
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30))
TODAY = datetime.now(IST).strftime("%Y-%m-%d")
HHMM = datetime.now(IST).strftime("%H:%M")
DATA = Path("/home/trading_ceo/python-trader/varaha/data")
KICK_LOG = Path(
    f"/home/trading_ceo/brahmand/logs/kickoff_{datetime.now(IST).strftime('%Y%m%d')}.log"
)


def _svc(name: str) -> bool:
    try:
        return subprocess.run(
            ["systemctl", "is-active", "--quiet", f"{name}.service"]
        ).returncode == 0
    except Exception:
        return False


def _qlen(key: str) -> int:
    try:
        import redis
        return redis.Redis(decode_responses=True).llen(key)
    except Exception:
        return -1


def _sqlite_today(db: str, table: str) -> tuple:
    """(row_count_today, max_timestamp) — (-1, None) on error."""
    try:
        c = sqlite3.connect(f"file:{DATA/db}?mode=ro", uri=True, timeout=3)
        r = c.execute(
            f"SELECT COUNT(*), MAX(timestamp) FROM {table} WHERE timestamp LIKE ?",
            (f"{TODAY}%",),
        ).fetchone()
        c.close()
        return (r[0] or 0, r[1])
    except Exception:
        return (-1, None)


def _enriched_quality() -> str:
    """Confirm tonight's enricher fixes landed: pivots + expiry non-NULL today."""
    try:
        c = sqlite3.connect(
            f"file:{DATA/'capture_nifty.sqlite'}?mode=ro", uri=True, timeout=3
        )
        r = c.execute(
            "SELECT COUNT(*), COUNT(pivot_pp), COUNT(expiry_weekly) "
            "FROM market_data_enriched WHERE timestamp LIKE ?",
            (f"{TODAY}%",),
        ).fetchone()
        c.close()
        tot, piv, exp = r
        if not tot:
            return "enriched: none yet"
        return f"enriched(N): {tot} rows, pivots {piv}/{tot}, expiry {exp}/{tot}"
    except Exception:
        return "enriched: check failed"


def _last_kickoff() -> str:
    try:
        lines = [l for l in KICK_LOG.read_text().splitlines() if TODAY in l]
        return lines[-1][-90:] if lines else "no entry-runs today yet"
    except Exception:
        return "kickoff log unreadable"


def _send(message: str) -> bool:
    try:
        import yaml, requests
        sec = yaml.safe_load(open("/root/.picoclaw/.security.yml"))
        token = (
            sec.get("channel_list", {}).get("telegram", {})
            .get("settings", {}).get("token", "")
        ) or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if not token:
            return False
        return requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": "8317944043", "text": message},
            timeout=10,
        ).ok
    except Exception:
        return False


def main():
    svcs = {n: _svc(n) for n in (
        "feed", "consumer-nifty", "consumer-sensex",
        "enricher-nifty", "enricher-sensex",
    )}
    qn, qs = _qlen("v3_ohlcv_queue_NIFTY"), _qlen("v3_ohlcv_queue_SENSEX")
    cn, cn_ts = _sqlite_today("capture_nifty.sqlite", "market_data")
    cs, cs_ts = _sqlite_today("capture_sensex.sqlite", "market_data")
    en, _ = _sqlite_today("capture_nifty.sqlite", "market_data_enriched")

    now = datetime.now(IST)
    pre_open = now.hour < 9 or (now.hour == 9 and now.minute < 16)
    all_up = all(svcs.values())
    flowing = qn > 0 and cn > 0

    if pre_open:
        verdict = "⏳ PRE-OPEN"
    elif all_up and flowing:
        verdict = "✅ GO — capture flowing"
    elif all_up and not flowing:
        verdict = "🟡 WARMING UP / NO DATA"
    else:
        verdict = "🔴 NOGO — service(s) down"

    svc_line = " ".join(
        f"{n.replace('consumer-','con-').replace('enricher-','enr-')}"
        f"{'✅' if up else '❌'}" for n, up in svcs.items()
    )
    msg = (
        f"🐧 PENGUIN {verdict} — {HHMM} IST\n"
        f"Services: {svc_line}\n"
        f"Queue: NIFTY={qn} SENSEX={qs}\n"
        f"Capture today: N {cn} bars (last {cn_ts or '-'}) | S {cs} (last {cs_ts or '-'})\n"
        f"{_enriched_quality()}\n"
        f"Paper-entry: {_last_kickoff()}"
    )
    print(msg)
    _send(msg)


if __name__ == "__main__":
    main()
