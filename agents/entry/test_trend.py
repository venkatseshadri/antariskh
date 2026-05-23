"""

import json
import os
import sys
import tempfile
from pathlib import Path
        import duckdb
    from tools.entry_tools import query_trend
    from tools.entry_tools import query_trend
    from agents.entry.trend_agent import run_trend_analysis
from dotenv import load_dotenv

Test Trend Agent — standalone and mock.

Coverage:
  1. Tool test: query_trend_tool returns valid JSON with expected keys (no DuckDB needed)
  2. Agent integration: run_trend_analysis (requires DEEPSEEK_API_KEY, skipped if absent)
"""


PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT.parent))  # python-trader root


def _setup_env():
    """Load .env for DEEPSEEK_API_KEY if available."""
    env_file = Path(__file__).parent.parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().split("\n"):
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def test_trend_tool_with_mock_db():
    """
    Test that query_trend_tool works with a mock DuckDB.
    Creates an in-memory DuckDB with minimal test data.
    """
    try:
        import duckdb
    except ImportError:
        print("SKIP: duckdb not installed")
        return


    # Create temp DuckDB files — use paths that don't exist yet
    v4_path = tempfile.mktemp(suffix=".duckdb")
    v31_path = tempfile.mktemp(suffix=".duckdb")

    v4_file = duckdb.connect(v4_path)
    v4_file.execute("""
        CREATE TABLE market_data_multitf (
            timestamp TEXT, index_name TEXT, timeframe_min INTEGER,
            sma20 FLOAT, sma50 FLOAT, sma200 FLOAT,
            open FLOAT, high FLOAT, low FLOAT, close FLOAT,
            st_consensus TEXT, adx FLOAT, di_plus FLOAT, di_minus FLOAT
        )
    """)
    v4_file.execute("""
        INSERT INTO market_data_multitf VALUES
        ('2026-05-17T10:30', 'NIFTY', 5, 23650.0, 23620.0, 23500.0, 23640.0, 23670.0, 23630.0, 23660.0, 'BULLISH', 28.5, 32.1, 18.2),
        ('2026-05-17T10:30', 'NIFTY', 15, 23645.0, 23615.0, 23500.0, 23655.0, 23670.0, 23640.0, 23660.0, 'BULLISH', 30.2, 34.0, 16.5)
    """)
    v4_file.close()

    v31_file = duckdb.connect(v31_path)
    v31_file.execute("""
        CREATE TABLE market_data (
            id INTEGER, timestamp TEXT, index_name TEXT,
            ema_5 FLOAT, ema_20 FLOAT, ema_50 FLOAT, spot FLOAT,
            supertrend_value FLOAT, supertrend_direction TEXT,
            st_5min_direction TEXT, st_15min_direction TEXT,
            st_consensus TEXT, adx FLOAT
        )
    """)
    v31_file.execute("""
        INSERT INTO market_data VALUES
        (1, '2026-05-17T10:30:00', 'NIFTY', 23655.0, 23640.0, 23610.0, 23660.0,
         23500.0, 'bullish', 'bullish', 'bullish', 'BULLISH', 27.0)
    """)
    v31_file.close()

    # Override paths
    os.environ["ENTRY_V31_DB"] = v31_path
    os.environ["ENTRY_V4_DB"] = v4_path

    try:
        result = query_trend("NIFTY")
        data = json.loads(result)

        # Assert structure
        assert data["family"] == "Trend", f"Expected Trend, got {data.get('family')}"
        assert data["index"] == "NIFTY"
        assert "timeframes" in data, "Missing timeframes key"

        tfs = data["timeframes"]
        # Check v4 timeframes
        assert "5m" in tfs, "Missing 5m"
        assert tfs["5m"]["sma_position"] == "bullish", (
            f"Expected bullish, got {tfs['5m'].get('sma_position')}"
        )
        assert tfs["5m"]["st_consensus"] == "BULLISH"

        # Check v3.1 1m
        assert "1m_v3.1" in tfs, "Missing 1m_v3.1"
        assert tfs["1m_v3.1"]["ema_position"] == "bullish"

        print("PASS: test_trend_tool_with_mock_db")
    finally:
        os.environ.pop("ENTRY_V31_DB", None)
        os.environ.pop("ENTRY_V4_DB", None)
        Path(v4_path).unlink(missing_ok=True)
        Path(v31_path).unlink(missing_ok=True)


def test_trend_tool_handles_missing_db():
    """query_trend should return valid JSON even when DBs don't exist."""

    os.environ["ENTRY_V31_DB"] = "/nonexistent/path.duckdb"
    os.environ["ENTRY_V4_DB"] = "/nonexistent/path.duckdb"

    try:
        result = query_trend("NIFTY")
        data = json.loads(result)
        assert data["family"] == "Trend"
        assert "timeframes" in data
        print("PASS: test_trend_tool_handles_missing_db")
    finally:
        os.environ.pop("ENTRY_V31_DB", None)
        os.environ.pop("ENTRY_V4_DB", None)


def test_trend_agent_output_schema():
    """
    Verify the Trend agent produces output matching the expected schema.
    Runs against live DuckDB if available, otherwise uses mock mode.
    """
    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("SKIP: test_trend_agent_output_schema (no DEEPSEEK_API_KEY)")
        return

    _setup_env()
    if not os.environ.get("DEEPSEEK_API_KEY"):
        print(
            "SKIP: test_trend_agent_output_schema (no DEEPSEEK_API_KEY after .env load)"
        )
        return


    result = run_trend_analysis("NIFTY")

    # Schema validation
    assert "family" in result, "Missing family"
    assert result["family"] == "Trend"
    assert "signal" in result, "Missing signal"
    assert result["signal"] in ("BULLISH", "BEARISH", "NEUTRAL"), (
        f"Invalid signal: {result['signal']}"
    )
    assert "score" in result, "Missing score"
    assert -10 <= result["score"] <= 10, f"Score out of range: {result['score']}"
    assert "confidence" in result, "Missing confidence"
    assert 0 <= result["confidence"] <= 100, (
        f"Confidence out of range: {result['confidence']}"
    )
    assert "reasoning" in result, "Missing reasoning"
    assert "key_indicators" in result, "Missing key_indicators"

    print(
        f"PASS: test_trend_agent_output_schema — signal={result['signal']}, score={result['score']}, conf={result['confidence']}"
    )


if __name__ == "__main__":
    _setup_env()

    print("=" * 50)
    print("TEST 1: Trend Tool with Mock DB")
    test_trend_tool_with_mock_db()

    print("=" * 50)
    print("TEST 2: Trend Tool Handles Missing DB")
    test_trend_tool_handles_missing_db()

    print("=" * 50)
    print("TEST 3: Trend Agent Output Schema (needs DEEPSEEK_API_KEY)")
    test_trend_agent_output_schema()

    print("=" * 50)
    print("All tests completed.")
