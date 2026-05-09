#!/usr/bin/env python3
"""
Mock broker manager — returns env-var values, captures orders for assertion.
"""

import os
import json
from typing import Dict, List, Optional


class MockBrokerManager:
    """Reads from env vars; captures orders for assertions."""

    captured_orders: List[Dict] = []

    def get_vix(self) -> float:
        return float(os.environ.get("ANTARIKSH_MOCK_VIX", "14.0"))

    def get_nifty_spot(self) -> float:
        return float(os.environ.get("ANTARIKSH_MOCK_NIFTY", "24500.0"))

    def get_position_mtm(self, position_id: str) -> float:
        trajectory = os.environ.get("ANTARIKSH_MOCK_TRAJECTORY", "0")
        vals = [float(x) for x in trajectory.split(",") if x.strip()]
        idx = int(os.environ.get("ANTARIKSH_TRAJ_IDX", "0"))
        if idx < len(vals):
            return vals[idx]
        return vals[-1] if vals else 0.0

    def place_order(self, leg: Dict) -> Dict:
        order_id = f"MOCK-ORDER-{len(MockBrokerManager.captured_orders):05d}"
        entry = {"order_id": order_id, "leg": leg, "status": "COMPLETE"}
        MockBrokerManager.captured_orders.append(entry)
        return entry

    def get_position(self, instrument: str) -> Optional[Dict]:
        return {"instrument": instrument, "qty": 1, "avg_price": 24500.0}

    @classmethod
    def reset(cls):
        cls.captured_orders.clear()


def get_broker_manager() -> MockBrokerManager:
    return MockBrokerManager()
