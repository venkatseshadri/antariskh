"""
Verification test: manual calculation vs query_trend tool output.
Controlled mock data — every field compared to expected value.
"""

import sys, os, json, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))  # antariksh root
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "python-trader"))

import duckdb
from tools.entry_tools import query_trend


def build_mock_dbs():
    """Create v4 + v3.1 DBs with complete, known test data."""
    v4_path = tempfile.mktemp(suffix=".duckdb")
    v31_path = tempfile.mktemp(suffix=".duckdb")

    v4 = duckdb.connect(v4_path)
    v4.execute("""
        CREATE TABLE market_data_multitf (
            timestamp TEXT, index_name TEXT, timeframe_min INTEGER,
            sma20 FLOAT, sma50 FLOAT, sma200 FLOAT, close FLOAT,
            open FLOAT, high FLOAT, low FLOAT,
            st_consensus TEXT, adx FLOAT, di_plus FLOAT, di_minus FLOAT
        )
    """)
    # Scenario: strong uptrend on higher TFs, pullback on 5m/15m
    v4.execute("""
        INSERT INTO market_data_multitf VALUES
        ('2026-05-17T10:30', 'NIFTY', 5,   23650, 23620, 23500, 23645,  23660, 23670, 23640, 'BULLISH', 28.5, 32.1, 18.2),
        ('2026-05-17T10:30', 'NIFTY', 15,  23655, 23610, 23500, 23640,  23655, 23665, 23630, 'BULLISH', 30.2, 34.0, 16.5),
        ('2026-05-17T10:30', 'NIFTY', 30,  23640, 23630, 23500, 23655,  23635, 23670, 23630, 'BULLISH', 22.0, 28.0, 22.0),
        ('2026-05-17T10:30', 'NIFTY', 60,  23680, 23550, 23500, 23700,  23500, 23710, 23480, 'BULLISH', 35.0, 42.0, 10.0),
        ('2026-05-17T10:30', 'NIFTY', 240, 23750, 23700, 23450, 23680,  23750, 23800, 23650, 'BULLISH', 32.0, 38.0, 14.0),
        ('2026-05-17T10:30', 'NIFTY', 1440,23800, 23650, 23000, 23750,  23400, 23850, 23350, 'BULLISH', 28.0, 35.0, 16.0)
    """)
    v4.close()

    v31 = duckdb.connect(v31_path)
    v31.execute("""
        CREATE TABLE market_data (
            id INTEGER, timestamp TEXT, index_name TEXT,
            ema_5 FLOAT, ema_20 FLOAT, ema_50 FLOAT, spot FLOAT,
            supertrend_value FLOAT, supertrend_direction TEXT,
            st_5min_direction TEXT, st_15min_direction TEXT,
            st_consensus TEXT, adx FLOAT
        )
    """)
    v31.execute("""
        INSERT INTO market_data VALUES
        (1, '2026-05-17T10:30', 'NIFTY',
         23660, 23655, 23600, 23660,
         23550, 'bullish', 'bullish', 'bullish', 'BULLISH', 27.0)
    """)
    v31.close()

    return v4_path, v31_path


def manual_expected():
    """Calculate expected output by hand from the known test data."""
    return {
        "5m": {
            "sma_position": "bullish",  # 23650 > 23620
            "st_consensus": "BULLISH",
            "adx": 28.5,
            "candle": "RED",  # close=23645 < open=23660 → RED (pullback)
        },
        "15m": {
            "sma_position": "bullish",  # 23655 > 23610
            "st_consensus": "BULLISH",
            "adx": 30.2,
            "candle": "RED",  # close=23640 < open=23655 → RED (pullback)
        },
        "30m": {
            "sma_position": "bullish",  # 23640 > 23630
            "st_consensus": "BULLISH",
            "adx": 22.0,
            "candle": "GREEN",  # close=23655 > open=23635 → GREEN
        },
        "60m": {
            "sma_position": "bullish",  # 23680 > 23550
            "st_consensus": "BULLISH",
            "adx": 35.0,
            "candle": "GREEN",  # close=23700 > open=23500 → GREEN
        },
        "240m": {
            "sma_position": "bullish",  # 23750 > 23700
            "st_consensus": "BULLISH",
            "adx": 32.0,
            "candle": "RED",  # close=23680 < open=23750 → RED
        },
        "1440m": {
            "sma_position": "bullish",  # 23800 > 23650
            "st_consensus": "BULLISH",
            "adx": 28.0,
            "candle": "GREEN",  # close=23750 > open=23400 → GREEN
        },
        "1m_v3.1": {
            "ema_position": "bullish",  # ema20=23655 > ema50=23600
            "st_direction": "bullish",
            "st_5m_direction": "bullish",
            "st_15m_direction": "bullish",
            "st_consensus": "BULLISH",
            "adx": 27.0,
        },
    }


def run_verification():
    v4_path, v31_path = build_mock_dbs()
    os.environ["ENTRY_V4_DB"] = v4_path
    os.environ["ENTRY_V31_DB"] = v31_path

    try:
        result = json.loads(query_trend("NIFTY"))
        expected = manual_expected()

        print("=" * 70)
        print("TREND TOOL — FIELD-BY-FIELD VERIFICATION")
        print("=" * 70)

        errors = []
        tfs = result["timeframes"]

        for tf_key, exp_fields in expected.items():
            print(f"\n--- {tf_key} ---")
            if tf_key not in tfs:
                errors.append(f"MISSING: {tf_key}")
                print(f"  ❌ NOT FOUND in tool output")
                continue

            actual = tfs[tf_key]
            for field, exp_val in exp_fields.items():
                act_val = actual.get(field)
                if field == "candle":
                    # candle might not exist yet (part of traffic light addition)
                    if act_val != exp_val:
                        print(
                            f"  ⚠️  {field}: expected={exp_val}, got={act_val} (traffic light may need update)"
                        )
                    else:
                        print(f"  ✅ {field} = {act_val}")
                elif act_val != exp_val:
                    errors.append(
                        f"{tf_key}.{field}: expected={exp_val}, got={act_val}"
                    )
                    print(f"  ❌ {field}: expected={exp_val}, got={act_val}")
                else:
                    print(f"  ✅ {field} = {act_val}")

        print(f"\n{'=' * 70}")
        if errors:
            print(f"❌ {len(errors)} FIELD MISMATCHES:")
            for e in errors:
                print(f"   {e}")
        else:
            print("✅ ALL SMA/ST/ADX FIELDS MATCH — tool calculates correctly")

        # Traffic light summary
        print(f"\n{'=' * 70}")
        print("TRAFFIC LIGHT SUMMARY (manual):")
        print(
            "  1D GREEN | 4H RED (pullback) | 1H GREEN (resuming) | 30m GREEN | 15m RED | 5m RED"
        )
        print(
            "  Interpretation: Bullish day, 4H pullback, 1H/30m resuming, lower TFs still red"
        )
        print("  This is TYPICAL: higher TF bullish structure with short-term pullback")

    finally:
        os.environ.pop("ENTRY_V4_DB", None)
        os.environ.pop("ENTRY_V31_DB", None)
        Path(v4_path).unlink(missing_ok=True)
        Path(v31_path).unlink(missing_ok=True)


if __name__ == "__main__":
    run_verification()
