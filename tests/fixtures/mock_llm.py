#!/usr/bin/env python3
"""
Mock LLM responses for CrewAI agents.
"""

from typing import Dict, List


class MockLLM:
    """Returns canned responses based on agent role detection."""

    def __init__(self, response_map: Dict[str, str]):
        self.response_map = response_map
        self.calls: List[Dict] = []

    def call(self, messages, **kwargs):
        for msg in reversed(messages):
            content = str(msg.get("content", "")).lower()
            if "scanner" in content or "market scanner" in content:
                role = "scanner"
            elif "strategist" in content or "trade strategist" in content:
                role = "strategist"
            elif "orchestrator" in content:
                role = "orchestrator"
            elif "executor" in content:
                role = "executor"
            elif "sentinel" in content:
                role = "sentinel"
            elif "risk guard" in content:
                role = "risk_guard"
            elif "auditor" in content:
                role = "auditor"
            else:
                role = "default"
            break
        else:
            role = "default"

        response = self.response_map.get(role, self.response_map.get("default", "OK"))
        self.calls.append({"role": role, "response": response[:200], "canned": True})
        return type("LLMResponse", (), {
            "choices": [type("Choice", (), {
                "message": type("Message", (), {"content": response, "role": "assistant"})()
            })()],
            "usage": type("Usage", (), {"total_tokens": 100, "prompt_tokens": 70, "completion_tokens": 30})(),
        })()

    @classmethod
    def call_direct(cls, response_map: Dict[str, str]):
        """Return a function suitable for mock.patch side_effect."""
        mocker = cls(response_map)
        return mocker.call


def make_mock_responses(default_response: str = "OK") -> Dict[str, str]:
    """Generate standard canned responses for all 7 agents."""
    return {
        "scanner": '{"vix": 14, "nifty_spot": 24500, "gate_pass": true, "gate_reason": "VIX OK, within window"}',
        "strategist": '{"trade_plan": {"instrument": "NIFTY", "atm_strike": 24500, "expiry": "13-MAY-2026", "lots": 1, "wing_width": 300, "target_profit": 1000, "max_loss": 3500}}',
        "risk_guard": '{"passed": true, "violations": [], "halt": false, "recommendations": []}',
        "executor": '{"success": true, "fills": [{"leg": "put_buy", "order_id": "MOCK-1"}, {"leg": "put_sell", "order_id": "MOCK-2"}]}',
        "sentinel": '{"pnl": 1000, "mtm": 1000, "target_hit": true, "sl_breach": false}',
        "auditor": '{"appended": true, "mtd_pnl": 1000, "session_count": 1}',
        "orchestrator": '{"crew_status": "COMPLETE"}',
        "default": "OK",
    }
