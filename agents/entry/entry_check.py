#!/usr/bin/env python3
"""
Entry Check — Redis-only deterministic scoring.
0 DuckDB calls, 0 LLM calls. Reads live data from Redis v3_ohlcv_queue.

Usage:
    python -m agents.entry.entry_check
"""

import os, sys, json, logging
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT.parent / "python-trader"))

from tools.entry_tools import (
    score_trend_redis,
    score_traffic_light_redis,
    combine_entry_scores,
)

logger = logging.getLogger("EntryCheck")


def check_entry(index: str = "NIFTY") -> dict:
    logger.info(f"Entry gate for {index} (Redis-only, 0 DuckDB, 0 LLM)")

    trend = score_trend_redis(index)
    tl = score_traffic_light_redis(index)
    decision = combine_entry_scores(trend, tl)

    decision["timestamp"] = datetime.now().isoformat()
    decision["index"] = index

    icon = "🟢 GO" if decision["go"] else "🔴 NO-GO"
    logger.info(
        f"{icon} | {decision['signal']} {decision['confidence']}% "
        f"| T:{decision['trend_signal']}({decision['trend_confidence']}%) "
        f"TL:{decision['traffic_light_signal']}({decision['traffic_light_confidence']}%)"
    )
    logger.info(
        f"  Trend: {trend.get('score', 0):.1f} ({trend['_method']}) | TL: {tl.get('score', 0)} ({tl['_method']})"
    )

    # Write to persistent location only
    persistent_path = Path("/home/trading_ceo/antariksh/logs/entry_check_latest.json")
    persistent_path.parent.mkdir(parents=True, exist_ok=True)
    persistent_path.write_text(json.dumps(decision, indent=2))

    # Append to daily history log (one line per run — easy to grep)
    history_path = Path(
        f"/home/trading_ceo/antariksh/logs/entry_check_{datetime.now().strftime('%Y%m%d')}.log"
    )
    history_line = (
        f"{decision['timestamp']} | "
        f"{'GO' if decision['go'] else 'NO-GO'} | "
        f"{decision['signal']} {decision['confidence']}% | "
        f"T:{decision['trend_signal']}({decision['trend_confidence']}%) "
        f"TL:{decision['traffic_light_signal']}({decision['traffic_light_confidence']}%) | "
        f"ema_src={decision.get('ema_source', '?')} | "
        f"tl_pattern={decision.get('traffic_light_pattern', '?')} | "
        f"trade={decision.get('suggested_trade', '?')} | "
        f"reason={decision.get('reasoning', '?')}\n"
    )
    with open(history_path, "a") as f:
        f.write(history_line)

    return decision


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s"
    )
    print(json.dumps(check_entry("NIFTY"), indent=2))
