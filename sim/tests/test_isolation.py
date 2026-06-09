"""PORCUPINE Phase-0 gate: prove SIM_MODE isolation + the sandbox-leak guard.

Run: python3 -m sim.tests.test_isolation   (from the antariksh root)
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim import sim_env

PROD_CAPTURE = "/home/trading_ceo/python-trader/varaha/data/capture_nifty.sqlite"


def _clear():
    for k in ("SIM_MODE", "SIM_ROOT", "SIM_REDIS_PORT"):
        os.environ.pop(k, None)


def test_production_defaults_unchanged():
    _clear()
    assert sim_env.sim_active() is False
    assert str(sim_env.capture_path("NIFTY")) == PROD_CAPTURE
    assert sim_env.redis_kwargs()["port"] == 6379
    # guard is a no-op in production — even a prod path must not raise
    sim_env.assert_sandboxed(PROD_CAPTURE)
    assert sim_env.log_dir() is None


def test_sim_mode_redirects(tmp_root):
    _clear()
    os.environ["SIM_MODE"] = "1"
    os.environ["SIM_ROOT"] = tmp_root
    os.environ["SIM_REDIS_PORT"] = "6380"
    assert sim_env.sim_active() is True
    cap = sim_env.capture_path("NIFTY")
    assert str(cap).startswith(tmp_root) and cap.name == "capture_nifty.sqlite"
    assert sim_env.redis_kwargs()["port"] == 6380
    assert str(sim_env.log_dir()).startswith(tmp_root)
    # a path inside the sandbox passes
    sim_env.assert_sandboxed(cap)


def test_leak_guard_raises_on_prod_path(tmp_root):
    _clear()
    os.environ["SIM_MODE"] = "1"
    os.environ["SIM_ROOT"] = tmp_root
    raised = False
    try:
        sim_env.assert_sandboxed(PROD_CAPTURE)  # prod path during sim → must raise
    except RuntimeError as e:
        raised = "SANDBOX LEAK" in str(e)
    assert raised, "assert_sandboxed must raise on a path outside SIM_ROOT"


def test_sim_mode_without_root_raises():
    _clear()
    os.environ["SIM_MODE"] = "1"
    try:
        sim_env.sim_root()
    except RuntimeError:
        pass
    else:
        raise AssertionError("SIM_MODE=1 without SIM_ROOT must raise")


if __name__ == "__main__":
    import tempfile

    tmp = tempfile.mkdtemp(prefix="porcupine_test_")
    passed = 0
    test_production_defaults_unchanged(); passed += 1; print("✅ production defaults unchanged")
    test_sim_mode_redirects(tmp); passed += 1; print("✅ SIM_MODE redirects paths + redis")
    test_leak_guard_raises_on_prod_path(tmp); passed += 1; print("✅ leak guard raises on prod path")
    test_sim_mode_without_root_raises(); passed += 1; print("✅ SIM_MODE without SIM_ROOT raises")
    _clear()
    print(f"\nPhase-0 isolation gate: {passed}/4 passed")
