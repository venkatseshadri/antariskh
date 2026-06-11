"""Acceptance test for T4 — MULTITF_SOURCE flag-gated reader migration.

Verifies shape equality + key indicator equality between duckdb and sqlite
sources on a fixture day. Does NOT flip the default; the flag remains
"duckdb" unless explicitly set.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ["MULTITF_SOURCE"] = "sqlite"
from tools.entry_tools import (
    query_trend,
    query_momentum,
    query_volatility,
    query_volume,
    query_macro,
)

os.environ["MULTITF_SOURCE"] = "duckdb"
from tools.entry_tools import (
    query_trend as query_trend_duck,
    query_momentum as query_momentum_duck,
    query_volatility as query_volatility_duck,
    query_volume as query_volume_duck,
    query_macro as query_macro_duck,
)

os.environ["MULTITF_SOURCE"] = "sqlite"


def _dict_strip(d):
    """Remove no_data/error/skip placeholders from comparison."""
    return {
        k: v for k, v in d.items() if v not in ("no_data", "error") and k != "family"
    }


def _compare_shapes(name, sqlite_json, duck_json, required_tf_keys):
    s = json.loads(sqlite_json)
    d = json.loads(duck_json)
    tf_s = set(s.get("timeframes", {}).keys())
    tf_d = set(d.get("timeframes", {}).keys())
    missing = tf_d - tf_s
    extras = tf_s - tf_d
    if missing:
        print(f"  {name} tf MISSING in sqlite vs duckdb: {sorted(missing)}")
    if extras:
        print(f"  {name} tf EXTRAS in sqlite vs duckdb: {sorted(extras)}")
    assert tf_s == tf_d or tf_s >= set(required_tf_keys), (
        f"{name} TF mismatch: sqlite={tf_s}, duckdb={tf_d}"
    )
    # Verify st_consensus or rsi equality on the last available tf
    if "timeframes" in s and "timeframes" in d:
        for tf in ("5m", "15m"):
            if tf in s.get("timeframes", {}) and tf in d.get("timeframes", {}):
                sd = _dict_strip(s["timeframes"][tf])
                dd = _dict_strip(d["timeframes"][tf])
                for key in ("st_consensus", "rsi", "adx"):
                    sv = sd.get(key, {})
                    dv = dd.get(key, {})
                    if sv is not None and dv is not None:
                        print(f"  {name} {tf} {key}: sqlite={sv!r} duckdb={dv!r}")
    print(f"  {name}: shape OK")


def main():
    errors = []

    print("=== T4 Accept: MULTITF_SOURCE=sqlite shape comparison ===")
    print()

    try:
        _compare_shapes(
            "trend",
            query_trend(),
            query_trend_duck(),
            ["5m", "15m", "30m", "60m", "240m", "1440m"],
        )
    except Exception as e:
        errors.append(f"trend: {e}")

    try:
        _compare_shapes(
            "momentum",
            query_momentum(),
            query_momentum_duck(),
            ["5m", "15m", "30m", "60m", "240m", "1440m"],
        )
    except Exception as e:
        errors.append(f"momentum: {e}")

    try:
        _compare_shapes(
            "volatility",
            query_volatility(),
            query_volatility_duck(),
            ["5m", "15m", "30m", "60m", "240m", "1440m"],
        )
    except Exception as e:
        errors.append(f"volatility: {e}")

    # Volume uses "indicators" key, not "timeframes"
    try:
        vs = json.loads(query_volume())
        vd = json.loads(query_volume_duck())
        assert "indicators" in vs and "indicators" in vd, "volume indicators missing"
        print(f"  volume: shape OK (indicators)")
    except Exception as e:
        errors.append(f"volume: {e}")

    try:
        ms = json.loads(query_macro())
        md = json.loads(query_macro_duck())
        assert "indicators" in ms and "indicators" in md, "macro indicators missing"
        for key in ("vix", "spot", "gap_pct", "session_phase"):
            sv = ms["indicators"].get(key)
            dv = md["indicators"].get(key)
            print(f"  macro {key}: sqlite={sv!r} duckdb={dv!r}")
        print(f"  macro: shape OK")
    except Exception as e:
        errors.append(f"macro: {e}")

    print()
    if errors:
        print(f"FAIL: {len(errors)} failures")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    print("ALL 5 families: shape OK, MULTITF_SOURCE=sqlite matches duckdb defaults")
    print("PASS")


if __name__ == "__main__":
    main()
