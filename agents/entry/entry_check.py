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

# Ensure project paths are available (add BEFORE any imports)
PROJECT_ROOT = Path(__file__).parent.parent.parent
TOOLS_PATH = PROJECT_ROOT / "tools"
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(TOOLS_PATH))

# Now import after paths are set
from entry_tools import (
    score_trend_redis,
    score_traffic_light_redis,
    combine_entry_scores,
)

# Import research agent broker for market context + pattern matching
try:
    from entry_signal_broker import EntrySignalBroker
    _broker = EntrySignalBroker()
except Exception as e:
    logger_temp = logging.getLogger("EntryCheck")
    logger_temp.warning(f"Could not load EntrySignalBroker: {e} — continuing without research patterns")
    _broker = None

logger = logging.getLogger("EntryCheck")


def check_entry(index: str = "NIFTY") -> dict:
    logger.info(f"Entry gate for {index} (Redis + research patterns)")

    trend = score_trend_redis(index)
    tl = score_traffic_light_redis(index)

    # Get market context (VIX, PCR, patterns) from research broker if available
    market_ctx = None
    if _broker:
        try:
            market_ctx = _broker.get_full_context(index)
            if market_ctx.get("matching_patterns"):
                logger.info(f"  Research patterns matched: {market_ctx['matching_patterns']}")
        except Exception as e:
            logger.warning(f"Market context lookup failed: {e}")

    decision = combine_entry_scores(trend, tl, market_ctx)

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
    if market_ctx:
        logger.info(
            f"  Market Context: VIX={market_ctx.get('vix', '?')}, "
            f"PCR={market_ctx.get('pcr_total', '?')}, "
            f"ADX={market_ctx.get('adx', '?')}"
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
