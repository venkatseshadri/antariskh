"""
Shared data-access tools for the 7-family entry agents.

Reads from:
  - v3.1: varaha_data.duckdb  → 104 cols (spot, vix, EMA, RSI, ATR, IV, PCR, OI, sentiment, greeks, SMC, fib, pivots)
  - v4:   market_data_multitf.duckdb → 26 cols (OHLCV + SMA/RSI/ATR/MACD/ADX/BB per 6 TFs)

All tools are CrewAI @tool functions that return formatted text for LLM consumption.
"""

import json
import os
from pathlib import Path
from datetime import datetime

from crewai.tools import tool

# Project-relative DB paths
_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
_SANDBOX = os.environ.get("BRAHMAND_SANDBOX", "")
if _SANDBOX:
    _V31_DB = Path(_SANDBOX) / "varaha_data.duckdb"
    _V4_NIFTY_DB = Path(_SANDBOX) / "market_data_multitf_nifty.duckdb"
    _V4_SENSEX_DB = Path(_SANDBOX) / "market_data_multitf_sensex.duckdb"
    _V31_SENSEX_DB = Path(_SANDBOX) / "varaha_data_sensex.duckdb"
else:
    _V31_DB = _PROJECT_ROOT / "python-trader" / "varaha" / "data" / "varaha_data.duckdb"
    _V4_NIFTY_DB = (
        _PROJECT_ROOT
        / "python-trader"
        / "varaha"
        / "data"
        / "market_data_multitf_nifty.duckdb"
    )
    _V4_SENSEX_DB = (
        _PROJECT_ROOT
        / "python-trader"
        / "varaha"
        / "data"
        / "market_data_multitf_sensex.duckdb"
    )
    _V31_SENSEX_DB = (
        _PROJECT_ROOT
        / "python-trader"
        / "varaha"
        / "data"
        / "varaha_data_sensex.duckdb"
    )
_V4_SENSEX_DB = (
    _PROJECT_ROOT
    / "python-trader"
    / "varaha"
    / "data"
    / "market_data_multitf_sensex.duckdb"
)
_V31_SENSEX_DB = (
    _PROJECT_ROOT / "python-trader" / "varaha" / "data" / "varaha_data_sensex.duckdb"
)

# Allow override via env for testing
V31_DB_PATH = os.environ.get("ANTARIKSH_V31_DB", str(_V31_DB))
V31_SENSEX_DB_PATH = os.environ.get("ANTARIKSH_V31_SENSEX_DB", str(_V31_SENSEX_DB))
V4_DB_PATH = os.environ.get("ANTARIKSH_V4_NIFTY_DB", str(_V4_NIFTY_DB))
V4_SENSEX_DB_PATH = os.environ.get("ANTARIKSH_V4_SENSEX_DB", str(_V4_SENSEX_DB))


def _db_connect(db_path: str, read_only: bool = True):
    """Lazy DuckDB connection. Returns None if DB doesn't exist."""
    try:
        import duckdb

        if not Path(db_path).exists():
            return None
        return duckdb.connect(db_path, read_only=read_only)
    except ImportError:
        return None


def _safe_fetch(cursor, default="N/A"):
    """Fetch one value or return default."""
    try:
        row = cursor.fetchone()
        return row[0] if row else default
    except Exception:
        return default


# ============================================================
# Trend & Multi-TF Data (v4 + v3.1)
# ============================================================


@tool
def query_multi_tf_trend(
    index: str = "NIFTY",
    include_raw: bool = False,
) -> str:
    """
    Query v4 multi-timeframe DuckDB for SMA20, SMA50, SuperTrend consensus
    across all 6 timeframes (5, 15, 30, 60, 240, 1440 min).
    Also queries v3.1 for 1-min EMA and SuperTrend.

    Args:
        index: NIFTY or SENSEX
        include_raw: if True, include raw numeric values. Default False.
    Returns:
        JSON string with trend analysis per timeframe.
    """
    v4_db = _db_connect(V4_DB_PATH)
    v31_db = _db_connect(V31_DB_PATH)

    result = {
        "family": "Trend",
        "index": index,
        "timestamp": datetime.now().isoformat(),
        "timeframes": {},
        "data_sources": {"v4_ok": v4_db is not None, "v3.1_ok": v31_db is not None},
    }

    # --- v4: multi-TF SMA + ST consensus ---
    if v4_db:
        timings = [5, 15, 30, 60, 240, 1440]
        for minut in timings:
            query = """
                SELECT sma20, sma50, sma200, rsi, close, st_consensus, adx, di_plus, di_minus
                FROM market_data_multitf
                WHERE index_name = ? AND timeframe_min = ?
                ORDER BY timestamp DESC LIMIT 1
            """
            try:
                row = v4_db.execute(query, [index, minut]).fetchone()
                if row is None:
                    result["timeframes"][f"{minut}m"] = {
                        "status": "no_data",
                        "ema_position": "unknown",
                    }
                    continue

                sma20, sma50, sma200, rsi, close, st, adx, di_p, di_m = row

                if sma20 and sma50:
                    position = "bullish" if sma20 > sma50 else "bearish"
                else:
                    position = "unknown"

                entry = {
                    "status": "ok",
                    "ema_position": position,
                    "st_consensus": st or "NEUTRAL",
                    "adx": round(adx, 1) if adx else None,
                }

                if include_raw:
                    entry["sma20"] = round(sma20, 2) if sma20 else None
                    entry["sma50"] = round(sma50, 2) if sma50 else None
                    entry["sma200"] = round(sma200, 2) if sma200 else None
                    entry["close"] = round(close, 2) if close else None
                    entry["rsi"] = round(rsi, 1) if rsi else None
                    entry["di_plus"] = round(di_p, 1) if di_p else None
                    entry["di_minus"] = round(di_m, 1) if di_m else None

                result["timeframes"][f"{minut}m"] = entry
            except Exception:
                result["timeframes"][f"{minut}m"] = {
                    "status": "error",
                    "ema_position": "unknown",
                }
        v4_db.close()

    # --- v3.1: 1-min EMA + ST detail ---
    if v31_db:
        try:
            query = """
                SELECT ema_5, ema_20, ema_50, spot, supertrend_value, supertrend_direction,
                       st_5min_direction, st_15min_direction, st_consensus, adx
                FROM market_data
                WHERE index_name = ?
                ORDER BY id DESC LIMIT 1
            """
            row = v31_db.execute(query, [index]).fetchone()
            if row:
                (
                    ema5,
                    ema20,
                    ema50,
                    spot,
                    st_val,
                    st_dir,
                    st5_dir,
                    st15_dir,
                    st_cons,
                    adx,
                ) = row
                pos = "bullish" if (ema20 and ema50 and ema20 > ema50) else "bearish"

                result["timeframes"]["1m_v3.1"] = {
                    "status": "ok",
                    "ema_position": pos,
                    "st_direction": st_dir or "neutral",
                    "st_5m_direction": st5_dir or "neutral",
                    "st_15m_direction": st15_dir or "neutral",
                    "st_consensus": st_cons or "NEUTRAL",
                    "adx": round(adx, 1) if adx else None,
                }
                if include_raw:
                    result["timeframes"]["1m_v3.1"]["spot"] = (
                        round(spot, 2) if spot else None
                    )
                    result["timeframes"]["1m_v3.1"]["ema5"] = (
                        round(ema5, 2) if ema5 else None
                    )
                    result["timeframes"]["1m_v3.1"]["ema20"] = (
                        round(ema20, 2) if ema20 else None
                    )
                    result["timeframes"]["1m_v3.1"]["ema50"] = (
                        round(ema50, 2) if ema50 else None
                    )
                    result["timeframes"]["1m_v3.1"]["supertrend_value"] = (
                        round(st_val, 2) if st_val else None
                    )
        except Exception:
            pass
        v31_db.close()

    return json.dumps(result, indent=2)


# ============================================================
# Options, Flow & Macro Data (v3.1 only)
# ============================================================


@tool
def query_option_flow_macro(index: str = "NIFTY") -> str:
    """
    Query v3.1 DuckDB for options flow, sentiment, IV, VIX, and macro indicators.
    Covers: Options family, Flow family, Macro family.

    Returns JSON with: VIX, IV, PCR, OI, sentiment, greeks, max_pain, pivot, fib, gap.
    """
    v31_db = _db_connect(V31_DB_PATH)

    result = {
        "index": index,
        "timestamp": datetime.now().isoformat(),
        "data_source_ok": v31_db is not None,
        "macro": {},
        "options": {},
        "flow": {},
    }

    if not v31_db:
        return json.dumps(result, indent=2)

    try:
        query = """
            SELECT
                india_vix, spot, open_price, prev_close, gap_pct,
                iv_current, iv_rank, iv_regime, hv_20, hv_60,
                pcr_total, pcr_atm, sentiment, max_pain_strike,
                call_oi_concentration, put_oi_concentration, oi_skew,
                agg_delta, agg_gamma, agg_vega, agg_theta,
                rsi, atr, adx, ema20_slope,
                pivot_pp, pivot_r1, pivot_r2, pivot_s1, pivot_s2,
                fib_0, fib_236, fib_382, fib_50, fib_618, fib_786, fib_100,
                session_phase, open_to_current_pct
            FROM market_data
            WHERE index_name = ?
            ORDER BY id DESC LIMIT 1
        """
        row = v31_db.execute(query, [index]).fetchone()
        if row is None:
            v31_db.close()
            return json.dumps(result, indent=2)

        (
            vix,
            spot,
            open_p,
            prev_c,
            gap,
            iv_cur,
            iv_rank,
            iv_reg,
            hv20,
            hv60,
            pcr_t,
            pcr_atm,
            sent,
            max_pain,
            call_oi,
            put_oi,
            oi_sk,
            delta,
            gamma,
            vega,
            theta,
            rsi,
            atr,
            adx,
            slope,
            pp,
            r1,
            r2,
            s1,
            s2,
            f0,
            f236,
            f382,
            f50,
            f618,
            f786,
            f100,
            sess_phase,
            open_pct,
        ) = row

        result["macro"] = {
            "vix": round(vix, 2) if vix else None,
            "vix_change": None,  # needs prev bar for diff
            "gift_premium": None,  # not yet captured
            "banknifty_nifty_ratio": None,  # not yet captured
            "gap_pct": round(gap, 2) if gap else None,
            "session_phase": sess_phase or "unknown",
            "open_to_current_pct": round(open_pct, 2) if open_pct else None,
        }

        result["options"] = {
            "iv_current": round(iv_cur, 2) if iv_cur else None,
            "iv_percentile": round(iv_rank, 2) if iv_rank else None,
            "iv_regime": iv_reg or "unknown",
            "hv_20": round(hv20, 2) if hv20 else None,
            "pcr_total": round(pcr_t, 2) if pcr_t else None,
            "pcr_atm": round(pcr_atm, 2) if pcr_atm else None,
            "sentiment": sent or "neutral",
            "max_pain_strike": max_pain,
            "call_oi_conc": round(call_oi, 2) if call_oi else None,
            "put_oi_conc": round(put_oi, 2) if put_oi else None,
            "oi_skew": round(oi_sk, 2) if oi_sk else None,
            "agg_delta": round(delta, 3) if delta else None,
            "agg_gamma": round(gamma, 3) if gamma else None,
            "agg_vega": round(vega, 2) if vega else None,
            "agg_theta": round(theta, 2) if theta else None,
        }

        result["flow"] = {
            "fii_fut_5d_change": None,  # not yet captured
            "pcr_change": None,  # needs prev bar for diff
        }

        result["technicals"] = {
            "rsi": round(rsi, 1) if rsi else None,
            "atr": round(atr, 2) if atr else None,
            "adx": round(adx, 1) if adx else None,
            "ema20_slope": round(slope, 4) if slope else None,
            "pivot_pp": round(pp, 2) if pp else None,
            "pivot_r1": round(r1, 2) if r1 else None,
            "pivot_s1": round(s1, 2) if s1 else None,
        }

        v31_db.close()
    except Exception:
        pass

    return json.dumps(result, indent=2)


# ============================================================
# Composite Entry Query (all families, single call)
# ============================================================


@tool
def query_all_family_data(index: str = "NIFTY") -> str:
    """
    Master query combining multi-TF trend + options/flow/macro data.
    Use this for the entry aggregator and full-session analysis.

    Returns JSON with all family data.
    """
    trend_raw = query_multi_tf_trend.func(index=index, include_raw=True)
    ofm_raw = query_option_flow_macro.func(index=index)

    try:
        trend_data = json.loads(trend_raw)
        ofm_data = json.loads(ofm_raw)
    except json.JSONDecodeError:
        return json.dumps({"error": "Failed to parse sub-queries"})

    combined = {**ofm_data, "trend": trend_data.get("timeframes", {})}
    combined["family"] = "All"
    combined["timestamp"] = datetime.now().isoformat()

    return json.dumps(combined, indent=2)
