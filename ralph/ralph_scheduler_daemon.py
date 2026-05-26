#!/usr/bin/env python3
"""
Ralph Loop Scheduler Daemon — runs continuously, polls run_ralph_cycle() every 60s.
This is what makes Antariksh autonomous — no external cron needed.

Systemd service: deploy/antariskh-ralph-scheduler.service
"""

import os
import sys
import time
import logging
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml
from ralph.ralph_loop import run_ralph_cycle
from tools.notifications import push_ralph_escalation
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | RALPH-SCHEDULER | %(message)s",
    handlers=[
        logging.FileHandler(
            Path(__file__).parent.parent / "logs" / "ralph_scheduler.log"
        ),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("RalphSchedulerDaemon")

# Environment — load API key for DeepSeek
if not os.environ.get("DEEPSEEK_API_KEY"):
    try:
        with open("/root/.picoclaw/.security.yml") as f:
            s = yaml.safe_load(f)
        keys = s.get("model_list", {}).get("deepseek:0", {}).get("api_keys", [])
        if keys:
            os.environ["DEEPSEEK_API_KEY"] = keys[0]
            os.environ["OPENAI_API_KEY"] = keys[0]
            os.environ["OPENAI_BASE_URL"] = "https://api.deepseek.com/v1"
            os.environ["OPENAI_MODEL_NAME"] = "deepseek-chat"
        else:
            logger.warning("No API keys found in security.yml")
    except PermissionError:
        # Running as non-root — try /home/trading_ceo/antariksh/.env
        try:
            with open("/home/trading_ceo/antariksh/.env") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("DEEPSEEK_API_KEY="):
                        key = line.split("=", 1)[1].strip().strip('"').strip("'")
                        os.environ["DEEPSEEK_API_KEY"] = key
                        os.environ["OPENAI_API_KEY"] = key
                        os.environ["OPENAI_BASE_URL"] = "https://api.deepseek.com/v1"
                        os.environ["OPENAI_MODEL_NAME"] = "deepseek-chat"
                        break
        except FileNotFoundError:
            pass
    except Exception as e:
        logger.warning(f"Could not load API key: {e}")

POLL_INTERVAL = 30  # seconds — fast enough to hit ±2 min windows reliably


def main():
    logger.info("=" * 60)
    logger.info("RALPH SCHEDULER DAEMON — STARTING")
    logger.info(f"Poll interval: {POLL_INTERVAL}s")
    logger.info("=" * 60)

    # Sync to wall clock — wait until next even poll boundary
    now = time.time()
    offset = now % POLL_INTERVAL
    if offset > 1:
        sleep_ms = POLL_INTERVAL - offset
        logger.info(f"Syncing to wall clock — sleeping {sleep_ms:.0f}s")
        time.sleep(sleep_ms)

    consecutive_empty = 0  # track idle cycles (no roles due)

    while True:
        try:
            start = time.monotonic()
            result = run_ralph_cycle()

            roles_loaded = result.get("roles_loaded", 0)
            roles_run = result.get("roles_run", 0)
            summary = result.get("summary", "")

            if roles_run > 0:
                logger.info(f"Cycle: {roles_run}/{roles_loaded} roles run — {summary}")
                consecutive_empty = 0

                # Check for escalations in results
                for r in result.get("results", []):
                    if r.get("escalation_needed"):
                        role = r.get("role", "unknown")
                        count = r.get("escalation_consecutive", 0)
                        logger.warning(
                            f"ESCALATION: {role} has {count} consecutive PRD failures"
                        )
                        try:
                            push_ralph_escalation(role, count, r.get("metrics", []))
                        except Exception as e:
                            logger.error(f"Failed to push escalation: {e}")
            else:
                consecutive_empty += 1
                if consecutive_empty % 60 == 0:  # log every ~1 hour idle
                    logger.info(f"No roles due — idle for {consecutive_empty} cycles")

            # Sleep until next poll, accounting for execution time
            elapsed = time.monotonic() - start
            sleep_for = max(1, POLL_INTERVAL - elapsed)
            time.sleep(sleep_for)

        except KeyboardInterrupt:
            logger.info("Shutdown requested — exiting")
            break
        except Exception as e:
            logger.error(f"Cycle failed: {e}", exc_info=True)
            time.sleep(60)  # back off on errors


if __name__ == "__main__":
    main()
