"""T21: Frozen-yesterday fixture — proves score_trend/families fail-closed.

No LLM. No API keys. No DB. Mocks entry_tools.query_* to simulate
stale (yesterday-only) market_data_multitf responses.
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, date

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

STALE_RESPONSE = json.dumps(
    {
        "family": "Trend",
        "index": "NIFTY",
        "timestamp": datetime.now().isoformat(),
        "insufficient_history": True,
        "timeframes": {},
    }
)


def test_score_trend_fails_closed_on_stale():
    with (
        patch("tools.entry_tools.query_trend", return_value=STALE_RESPONSE),
        patch("tools.entry_tools.MULTITF_SOURCE", "duckdb"),
    ):
        from tools.entry_tools import score_trend

        result = score_trend("NIFTY")
        assert result["signal"] == "insufficient_history", (
            f"Expected insufficient_history, got {result['signal']}"
        )
        assert result["score"] == 0.0
        assert result["confidence"] == 0.0


def test_score_trend_passes_on_fresh():
    """Live-like response without insufficient_history should NOT return insufficient_history."""
    fresh_response = json.dumps(
        {
            "family": "Trend",
            "index": "NIFTY",
            "timestamp": datetime.now().isoformat(),
            "timeframes": {
                "5m": {"ema_position": "bullish", "st_consensus": "BULLISH", "adx": 30},
                "15m": {"ema_position": "bullish", "st_consensus": "BULLISH", "adx": 28},
                "30m": {"ema_position": "bullish", "st_consensus": "BULLISH", "adx": 26},
                "60m": {"ema_position": "bullish", "st_consensus": "BULLISH", "adx": 25},
                "240m": {"ema_position": "bullish", "st_consensus": "BULLISH", "adx": 24},
                "1440m": {"ema_position": "bullish", "st_consensus": "BULLISH", "adx": 22},
            },
        }
    )
    with (
        patch("tools.entry_tools.query_trend", return_value=fresh_response),
        patch("tools.entry_tools.MULTITF_SOURCE", "duckdb"),
    ):
        from tools.entry_tools import score_trend

        result = score_trend("NIFTY")
        assert result["signal"] != "insufficient_history", (
            f"Fresh data should NOT return insufficient_history, got {result['signal']}"
        )


def test_families_report_insufficient_history():
    """All public query functions should return insufficient_history when stale."""
    from tools.entry_tools import (
        query_trend,
        query_momentum,
        query_volatility,
        query_volume,
    )

    with (
        patch("tools.entry_tools._multitf_is_stale", return_value=True),
        patch("tools.entry_tools.MULTITF_SOURCE", "duckdb"),
    ):
        for name, fn in [
            ("trend", query_trend),
            ("momentum", query_momentum),
            ("volatility", query_volatility),
            ("volume", query_volume),
        ]:
            result = json.loads(fn("NIFTY"))
            assert result.get("insufficient_history"), (
                f"{name}: expected insufficient_history=True, got {result}"
            )


def test_staleness_guard_present():
    """Guard function must exist and be importable."""
    from tools.entry_tools import _multitf_is_stale

    assert callable(_multitf_is_stale)


if __name__ == "__main__":
    for name in sorted(globals()):
        if name.startswith("test_"):
            fn = globals()[name]
            fn()
            print(f"  PASS  {name}")
    print("  T21: ALL TESTS PASSED")
