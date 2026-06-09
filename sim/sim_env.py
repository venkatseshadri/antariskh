"""Project PORCUPINE — single source of truth for test-stack isolation.

When SIM_MODE=1, every stateful path and the Redis connection resolve to an
isolated sandbox under SIM_ROOT (+ SIM_REDIS_PORT). When SIM_MODE is unset,
every helper returns the exact production default, so importing this from
production code is a no-op. See docs/E2E_SIM_HARNESS_BUILD_SPEC.md.

Contract:
    SIM_MODE=1
    SIM_ROOT=/home/trading_ceo/antariksh/sim/run_<scenario>_<ts>/
    SIM_REDIS_PORT=6380
"""

import os
from pathlib import Path

# Production defaults — must match the values previously hardcoded in
# config/sqlite_schema.py, feed.py, and the consumers/enrichers.
_PROD_CAPTURE_DIR = Path("/home/trading_ceo/python-trader/varaha/data")
_PROD_REDIS_PORT = 6379


def sim_active() -> bool:
    return os.environ.get("SIM_MODE") == "1"


def sim_root() -> Path | None:
    """Resolved SIM_ROOT, or None in production. Raises if SIM_MODE=1 without SIM_ROOT."""
    root = os.environ.get("SIM_ROOT")
    if sim_active() and not root:
        raise RuntimeError("SIM_MODE=1 but SIM_ROOT is unset")
    return Path(root).resolve() if root else None


def redis_kwargs() -> dict:
    """kwargs for redis.Redis(...). Points at the test instance under SIM_MODE."""
    port = int(os.environ.get("SIM_REDIS_PORT", _PROD_REDIS_PORT))
    return {"host": "localhost", "port": port, "db": 0, "decode_responses": True}


def capture_dir() -> Path:
    return (sim_root() / "data") if sim_active() else _PROD_CAPTURE_DIR


def capture_path(instrument: str) -> Path:
    return capture_dir() / f"capture_{instrument.lower()}.sqlite"


def log_dir() -> Path | None:
    """Sandbox log dir under SIM_MODE, else None (callers keep prod logging)."""
    return (sim_root() / "logs") if sim_active() else None


def assert_sandboxed(path) -> None:
    """HARD GUARD against sandbox leaks.

    Under SIM_MODE, every write path MUST live inside SIM_ROOT. If a resolved
    path escapes it (a missed/hardcoded production path), raise immediately
    rather than silently corrupt production data. No-op in production.
    """
    if not sim_active():
        return
    root = sim_root()
    p = Path(path).resolve()
    if p != root and root not in p.parents:
        raise RuntimeError(
            f"PORCUPINE SANDBOX LEAK: {p} is outside SIM_ROOT {root}"
        )
