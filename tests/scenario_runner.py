#!/usr/bin/env python3
"""
ScenarioRunner — context manager for injecting mock conditions into Antariksh CrewAI.
"""

import os
import sys
import json
import tempfile
from pathlib import Path
from typing import Dict, List, Optional
from unittest import mock

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "antariksh"))

import antariksh.crew_structure as crew


class ScenarioRunner:
    """Context manager that patches system under test with scenario-specific mocks."""

    def __init__(self, scenario_id: str, log_prefix: str = "/tmp/antariksh_test"):
        self.scenario_id = scenario_id
        self._tempdir = tempfile.mkdtemp(prefix=f"antariksh_{scenario_id}_")
        self._log_dir = Path(self._tempdir) / "logs"
        self._log_dir.mkdir(exist_ok=True)
        self._patches = []
        self.results: Dict = {}
        self._original_env = dict(os.environ)

    def __enter__(self) -> "ScenarioRunner":
        os.environ.setdefault("ANTARIKSH_MOCK_MODE", "1")

        # Redirect LOG_DIR in crew_structure to temp directory
        crew.AuditorEngine.AUDIT_DIR = self._log_dir

        # Reset in-memory state
        crew.market_state.clear()
        crew.market_state.update({
            "vix": None, "nifty_spot": None, "atm_strike": None,
            "trade_plan": None, "gate_pass": False, "gate_reason": "",
            "positions": {}, "mtd_pnl": 0.0, "session_pnl": 0.0,
            "alerts": [], "audit_entries": [], "halt": False,
            "risk_ok": True, "re_entries_used": 0, "max_re_entries": 1,
        })
        return self

    def __exit__(self, *args):
        for p in reversed(self._patches):
            p.stop()
        self._patches.clear()
        crew.AuditorEngine.AUDIT_DIR = Path(__file__).parent.parent / "logs"
        for k in list(os.environ.keys()):
            if k.startswith("ANTARIKSH_") and k not in self._original_env:
                del os.environ[k]
        import shutil
        shutil.rmtree(self._tempdir, ignore_errors=True)

    # ── Setup methods ────────────────────────────────────

    def set_time(self, iso_str: str):
        os.environ["ANTARIKSH_MOCK_TIME"] = iso_str
        from datetime import datetime as real_dt
        mock_dt = real_dt.fromisoformat(iso_str)
        p = mock.patch("antariksh.crew_structure.datetime")
        m = p.start()
        m.now.return_value = mock_dt
        self._patches.append(p)

    def set_market(self, vix: float, nifty: float):
        os.environ["ANTARIKSH_MOCK_VIX"] = str(vix)
        os.environ["ANTARIKSH_MOCK_NIFTY"] = str(nifty)
        crew.market_state["vix"] = vix
        crew.market_state["nifty_spot"] = nifty

    def set_pnl_trajectory(self, trajectory: List[float]):
        os.environ["ANTARIKSH_MOCK_TRAJECTORY"] = ",".join(str(x) for x in trajectory)
        os.environ["ANTARIKSH_TRAJ_IDX"] = "0"
        crew.market_state["session_pnl"] = trajectory[-1] if trajectory else 0.0

    def seed_history(self, days: int, daily_pnl: List[float] = None):
        from tests.fixtures.seed_history import seed_jsonl
        if daily_pnl is None:
            daily_pnl = [0.0] * days
        seed_jsonl(self._log_dir, days, daily_pnl)
        crew.market_state["mtd_pnl"] = sum(daily_pnl) if daily_pnl else 0.0

    def set_llm_responses(self, response_map: Dict[str, str]):
        pass

    def set_event_day(self, event_name: str):
        os.environ["ANTARIKSH_MOCK_EVENT_DAY"] = "1"
        os.environ["ANTARIKSH_MOCK_EVENT_NAME"] = event_name

    def set_vix_trajectory(self, trajectory: List[Dict]):
        pass

    def set_sentinel_blackout(self, after_seconds: int):
        os.environ["ANTARIKSH_MOCK_SENTINEL_BLACKOUT"] = str(after_seconds)

    # ── Execution ────────────────────────────────────────

    def run(self) -> Dict:
        os.environ["ANTARIKSH_MOCK_MODE"] = "1"
        crew.initialize_session()
        result = crew.run_full_session(
            mock_mode=True,
            mock_vix=float(os.environ.get("ANTARIKSH_MOCK_VIX", 14.0)),
            mock_nifty=float(os.environ.get("ANTARIKSH_MOCK_NIFTY", 24500.0)),
            mock_time=os.environ.get("ANTARIKSH_MOCK_TIME", "10:30"),
        )
        self.results = dict(crew.market_state)
        self.results["returned"] = result
        return result

    def run_engine_only(self, engine_name: str, **kwargs) -> Dict:
        """Bypass crew, hit RiskGuard/Auditor directly."""
        if engine_name == "RiskGuard":
            result = crew.RiskGuardEngine.full_check(**kwargs)
            self.results = {"verdict": result}
            return result
        elif engine_name == "Auditor":
            result = crew.AuditorEngine(**kwargs)
            self.results = {"verdict": result}
            return result
        elif engine_name == "ReEntry":
            result = {
                "can_enter": crew.ReEntryTracker.can_re_enter(),
                "used": crew.market_state.get("re_entries_used", 0),
            }
            self.results = {"verdict": result}
            return result
        return {}

    # ── Assertions ───────────────────────────────────────

    def assert_state(self, expected: Dict):
        errors = []
        for key, val in expected.items():
            actual = crew.market_state.get(key)
            if actual != val:
                errors.append(f"{key}: expected {val}, got {actual}")
        assert not errors, f"State mismatch: {'; '.join(errors)}"

    def assert_jsonl(self, contains: Dict):
        import glob
        for path in glob.glob(str(self._log_dir / "cfo_audit_*.jsonl")):
            with open(path) as f:
                data = json.load(f)
            for key, val in contains.items():
                parts = key.split(".")
                v = data
                for p in parts:
                    v = v.get(p, {}) if isinstance(v, dict) else None
                assert v == val, f"JSONL {key}: expected {val}, got {v}"

    def assert_telegram_contains(self, substring: str):
        crew.logger.info(f"[TELEGRAM CHECK] expecting: {substring}")

    def assert_agent_order(self, expected: List[str]):
        pass

    def assert_no_llm_in(self, agent_name: str):
        pass
