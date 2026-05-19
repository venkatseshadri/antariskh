"""
Entry Agent Tools — deterministic data-access for the 7-family entry crew.

Each family gets a focused tool that queries the relevant DuckDB (v3.1 or v4),
pre-processes indicator data, and returns structured JSON for the LLM agent.

Families:
  1. Trend      — EMA/SMA alignment across 6 TFs + SuperTrend
  2. Momentum   — RSI14 per TF
  3. Volatility — ATR14, ATR_percentile per TF
  4. Volume     — VWAP_distance, volume_ratio, OBV, CMF
  5. Options    — IV_percentile, IV_regime, PCR, OI_skew, max_pain, greeks
  6. Flow       — FII_fut_5d_change (marked as pending), PCR_change
  7. Macro      — VIX_level, VIX_change, GIFT_premium (pending), gap_pct

Design rule (CHARTER Rule 2): deterministic, no LLM in tool execution.
Each tool returns pure data — the agent applies judgment.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

# DB paths — project-normalized
_PROJECT_ROOT = Path("/home/trading_ceo/python-trader")
_V31_NIFTY = _PROJECT_ROOT / "varaha" / "data" / "varaha_data.duckdb"
_V4_MULTITF = _PROJECT_ROOT / "varaha" / "data" / "market_data_multitf.duckdb"


# Allow test override via env — lazy so tests can set env after import
def _v4_db_path():
    return os.environ.get("ENTRY_V4_DB", str(_V4_MULTITF))


def _v31_db_path():
    return os.environ.get("ENTRY_V31_DB", str(_V31_NIFTY))


# Multi-TF windows
TF_WINDOWS = [5, 15, 30, 60, 240, 1440]


def _open_db(path: str):
    """Lazy duckdb connect with retry on lock. Returns None if DB missing."""
    try:
        import duckdb
    except ImportError:
        return None
    if not Path(path).exists():
        return None
    # Retry up to 3 times with short backoff for write-lock contention
    for attempt in range(3):
        try:
            return duckdb.connect(path, read_only=True)
        except duckdb.IOException:
            if attempt < 2:
                import time as _time

                _time.sleep(0.5)
            else:
                return None
    return None


def _r(val, precision=2):
    """Round val if not None, else return None."""
    return round(val, precision) if val is not None else None


# ============================================================
# 1. TREND — EMA/SMA + SuperTrend per TF
# ============================================================


def query_trend(index: str = "NIFTY") -> str:
    """
    Query multi-TF trend indicators from v4 + v3.1 DuckDB.

    Returns JSON:
      { family, timestamp, timeframes: { 5m: {sma20,sma50,position,st,...}, ... } }
    """
    v4 = _open_db(_v4_db_path())
    v31 = _open_db(_v31_db_path())

    result = {
        "family": "Trend",
        "index": index,
        "timestamp": datetime.now().isoformat(),
        "timeframes": {},
    }

    # ── v4: SMA20/50 + ST consensus per TF ──
    if v4:
        for minut in TF_WINDOWS:
            try:
                row = v4.execute(
                    """SELECT sma20, sma50, sma200, open, high, low, close,
                              st_consensus, adx, di_plus, di_minus
                       FROM market_data_multitf
                       WHERE index_name = ? AND timeframe_min = ?
                       ORDER BY timestamp DESC LIMIT 1""",
                    [index, minut],
                ).fetchone()
                if row:
                    (
                        sma20,
                        sma50,
                        sma200,
                        open_p,
                        high,
                        low,
                        close,
                        st,
                        adx,
                        di_p,
                        di_m,
                    ) = row
                    pos = (
                        "bullish"
                        if (sma20 and sma50 and sma20 > sma50)
                        else ("bearish" if (sma20 and sma50) else "neutral")
                    )
                    candle = (
                        "GREEN"
                        if (open_p and close and close > open_p)
                        else "RED"
                        if (open_p and close)
                        else "neutral"
                    )
                    result["timeframes"][f"{minut}m"] = {
                        "sma20": _r(sma20),
                        "sma50": _r(sma50),
                        "sma_position": pos,
                        "candle": candle,
                        "st_consensus": (st or "NEUTRAL").strip(),
                        "adx": _r(adx, 1),
                        "di_plus": _r(di_p, 1),
                        "di_minus": _r(di_m, 1),
                    }
                else:
                    result["timeframes"][f"{minut}m"] = {
                        "sma_position": "no_data",
                        "candle": "no_data",
                    }
            except Exception:
                result["timeframes"][f"{minut}m"] = {
                    "sma_position": "error",
                    "candle": "error",
                }
        v4.close()

    # ── v3.1: 1-min EMA + ST granular detail ──
    if v31:
        try:
            row = v31.execute(
                """SELECT ema_5, ema_20, ema_50, spot, supertrend_value, supertrend_direction,
                          st_5min_direction, st_15min_direction, st_consensus, adx
                   FROM market_data WHERE index_name = ? ORDER BY id DESC LIMIT 1""",
                [index],
            ).fetchone()
            if row:
                ema5, ema20, ema50, spot, st_val, st_dir, st5, st15, st_cons, adx = row
                pos = (
                    "bullish"
                    if (ema20 and ema50 and ema20 > ema50)
                    else ("bearish" if (ema20 and ema50) else "neutral")
                )
                result["timeframes"]["1m_v3.1"] = {
                    "spot": _r(spot),
                    "ema5": _r(ema5),
                    "ema20": _r(ema20),
                    "ema50": _r(ema50),
                    "ema_position": pos,
                    "st_direction": (st_dir or "neutral").strip(),
                    "st_5m_direction": (st5 or "neutral").strip(),
                    "st_15m_direction": (st15 or "neutral").strip(),
                    "st_consensus": (st_cons or "NEUTRAL").strip(),
                    "adx": _r(adx, 1),
                }
        except Exception:
            pass
        v31.close()

    return json.dumps(result, indent=2)


# ============================================================
# 2. MOMENTUM — RSI14 per TF
# ============================================================


def query_momentum(index: str = "NIFTY") -> str:
    """Query RSI14 across all timeframes from v4 + v3.1."""
    v4 = _open_db(_v4_db_path())
    v31 = _open_db(_v31_db_path())

    result = {
        "family": "Momentum",
        "index": index,
        "timestamp": datetime.now().isoformat(),
        "timeframes": {},
    }

    if v4:
        for minut in TF_WINDOWS:
            try:
                row = v4.execute(
                    """SELECT rsi, close, macd, macd_signal, macd_histogram, cci
                       FROM market_data_multitf
                       WHERE index_name = ? AND timeframe_min = ?
                       ORDER BY timestamp DESC LIMIT 1""",
                    [index, minut],
                ).fetchone()
                if row:
                    rsi, close, macd, macd_sig, macd_hist, cci = row
                    result["timeframes"][f"{minut}m"] = {
                        "rsi": _r(rsi, 1),
                        "rsi_zone": (
                            "oversold"
                            if rsi and rsi < 30
                            else "overbought"
                            if rsi and rsi > 70
                            else "neutral"
                            if rsi
                            else "unknown"
                        ),
                        "macd": _r(macd, 2) if macd else None,
                        "macd_histogram": _r(macd_hist, 2) if macd_hist else None,
                        "cci": _r(cci, 1) if cci else None,
                    }
            except Exception:
                pass
        v4.close()

    if v31:
        try:
            row = v31.execute(
                "SELECT rsi, bb_pct_b, bb_width FROM market_data WHERE index_name = ? ORDER BY id DESC LIMIT 1",
                [index],
            ).fetchone()
            if row:
                rsi, bb_b, bb_w = row
                result["timeframes"]["1m_v3.1"] = {
                    "rsi": _r(rsi, 1),
                    "rsi_zone": (
                        "oversold"
                        if rsi and rsi < 30
                        else "overbought"
                        if rsi and rsi > 70
                        else "neutral"
                        if rsi
                        else "unknown"
                    ),
                    "bb_pct_b": _r(bb_b, 2),
                    "bb_width": _r(bb_w, 2),
                }
        except Exception:
            pass
        v31.close()

    return json.dumps(result, indent=2)


# ============================================================
# 3. VOLATILITY — ATR14, ATR_percentile per TF
# ============================================================


def query_volatility(index: str = "NIFTY") -> str:
    """Query ATR14, BB width, and volatility context across TFs."""
    v4 = _open_db(_v4_db_path())
    v31 = _open_db(_v31_db_path())

    result = {
        "family": "Volatility",
        "index": index,
        "timestamp": datetime.now().isoformat(),
        "timeframes": {},
    }

    if v4:
        for minut in TF_WINDOWS:
            try:
                row = v4.execute(
                    """SELECT atr, close, bb_upper, bb_lower, bb_middle
                       FROM market_data_multitf
                       WHERE index_name = ? AND timeframe_min = ?
                       ORDER BY timestamp DESC LIMIT 1""",
                    [index, minut],
                ).fetchone()
                if row:
                    atr, close, bb_u, bb_l, bb_m = row
                    result["timeframes"][f"{minut}m"] = {
                        "atr": _r(atr, 2),
                        "atr_pct": _r(atr / close * 100, 2) if atr and close else None,
                        "bb_upper": _r(bb_u, 2),
                        "bb_lower": _r(bb_l, 2),
                    }
            except Exception:
                pass
        v4.close()

    if v31:
        try:
            row = v31.execute(
                """SELECT atr, spot, bb_width, hv_20, hv_60, iv_current, iv_rank
                   FROM market_data WHERE index_name = ? ORDER BY id DESC LIMIT 1""",
                [index],
            ).fetchone()
            if row:
                atr, spot, bb_w, hv20, hv60, iv_cur, iv_rank = row
                result["timeframes"]["1m_v3.1"] = {
                    "atr": _r(atr, 2),
                    "atr_pct": _r(atr / spot * 100, 2) if atr and spot else None,
                    "hv_20": _r(hv20, 2),
                    "hv_60": _r(hv60, 2),
                    "iv_current": _r(iv_cur, 2),
                    "iv_rank": _r(iv_rank, 1),
                }
        except Exception:
            pass
        v31.close()

    return json.dumps(result, indent=2)


# ============================================================
# 4. VOLUME — VWAP_distance, volume_ratio, OBV, CMF
# ============================================================


def query_volume(index: str = "NIFTY") -> str:
    """Query volume indicators from v4 (OBV/CMF) + v3.1 (VWAP/volume)."""
    v4 = _open_db(_v4_db_path())
    v31 = _open_db(_v31_db_path())

    result = {
        "family": "Volume",
        "index": index,
        "timestamp": datetime.now().isoformat(),
        "indicators": {},
    }

    if v4:
        for minut in [5, 15, 30]:
            try:
                row = v4.execute(
                    "SELECT volume, obv, cmf FROM market_data_multitf WHERE index_name = ? AND timeframe_min = ? ORDER BY timestamp DESC LIMIT 1",
                    [index, minut],
                ).fetchone()
                if row:
                    vol, obv, cmf = row
                    result["indicators"][f"{minut}m"] = {
                        "volume": _r(vol, 0),
                        "obv": _r(obv, 0) if obv else None,
                        "cmf": _r(cmf, 3) if cmf else None,
                        "cmf_signal": (
                            "accumulation"
                            if cmf and cmf > 0.05
                            else "distribution"
                            if cmf and cmf < -0.05
                            else "neutral"
                            if cmf
                            else "unknown"
                        ),
                    }
            except Exception:
                pass
            # Only fetch nearest for higher TFs
            try:
                row = v4.execute(
                    "SELECT volume, obv, cmf FROM market_data_multitf WHERE index_name = ? AND timeframe_min = ? ORDER BY timestamp DESC LIMIT 1",
                    [index, minut],
                ).fetchone()
            except Exception:
                pass
        v4.close()

    if v31:
        try:
            row = v31.execute(
                "SELECT vwap, spot, volume FROM market_data WHERE index_name = ? ORDER BY id DESC LIMIT 1",
                [index],
            ).fetchone()
            if row:
                vwap, spot, vol = row
                vwap_dist = _r((spot - vwap) / vwap * 100, 2) if vwap and spot else None
                result["indicators"]["1m_v3.1"] = {
                    "spot": _r(spot),
                    "vwap": _r(vwap),
                    "vwap_distance_pct": vwap_dist,
                    "vwap_position": "above"
                    if vwap_dist and vwap_dist > 0
                    else "below"
                    if vwap_dist and vwap_dist < 0
                    else "at",
                }
        except Exception:
            pass
        v31.close()

    return json.dumps(result, indent=2)


# ============================================================
# 5. OPTIONS — IV, PCR, OI_signal, max_pain, greeks
# ============================================================


def query_options(index: str = "NIFTY") -> str:
    """Query options market sentiment from v3.1 DuckDB."""
    v31 = _open_db(_v31_db_path())
    result = {
        "family": "Options",
        "index": index,
        "timestamp": datetime.now().isoformat(),
        "indicators": {},
    }

    if not v31:
        return json.dumps(result, indent=2)

    try:
        row = v31.execute(
            """SELECT iv_current, iv_rank, iv_regime, iv_52w_high, iv_52w_low,
                      pcr_total, pcr_atm, sentiment, max_pain_strike,
                      call_oi_concentration, put_oi_concentration, oi_skew,
                      agg_delta, agg_gamma, agg_vega, agg_theta,
                      wings_delta, body_delta
               FROM market_data WHERE index_name = ? ORDER BY id DESC LIMIT 1""",
            [index],
        ).fetchone()
        if row:
            (
                iv_cur,
                iv_rank,
                iv_reg,
                iv_h,
                iv_l,
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
                w_delta,
                b_delta,
            ) = row
            result["indicators"] = {
                "iv_current": _r(iv_cur, 2),
                "iv_percentile": _r(iv_rank, 1),
                "iv_regime": str(iv_reg).strip() if iv_reg else "unknown",
                "pcr_total": _r(pcr_t, 2),
                "pcr_atm": _r(pcr_atm, 2),
                "pcr_signal": (
                    "bullish"
                    if pcr_t and pcr_t > 1.2
                    else "bearish"
                    if pcr_t and pcr_t < 0.8
                    else "neutral"
                ),
                "sentiment": str(sent).strip() if sent else "neutral",
                "max_pain_strike": max_pain,
                "call_oi_concentration": _r(call_oi, 2),
                "put_oi_concentration": _r(put_oi, 2),
                "oi_skew": _r(oi_sk, 2),
                "oi_price_signal": (
                    "bullish"
                    if put_oi and call_oi and put_oi > call_oi
                    else "bearish"
                    if call_oi and put_oi and call_oi > put_oi
                    else "neutral"
                ),
                "greeks": {
                    "agg_delta": _r(delta, 3),
                    "agg_gamma": _r(gamma, 3),
                    "agg_vega": _r(vega, 2),
                    "agg_theta": _r(theta, 2),
                },
            }
    except Exception:
        pass
    v31.close()
    return json.dumps(result, indent=2)


# ============================================================
# 6. FLOW — FII_fut_5d_change, PCR_change
# ============================================================


def query_flow(index: str = "NIFTY") -> str:
    """
    Query institutional flow indicators.
    FII_fut_5d_change: requires external FII/DII data feed (currently unavailable).
    PCR_change: computed from sequential v3.1 rows.
    """
    v31 = _open_db(_v31_db_path())
    result = {
        "family": "Flow",
        "index": index,
        "timestamp": datetime.now().isoformat(),
        "indicators": {},
    }

    if not v31:
        return json.dumps(result, indent=2)

    try:
        # PCR_change: diff between latest and 30-min-ago PCR
        rows = v31.execute(
            """SELECT pcr_total, timestamp FROM market_data
               WHERE index_name = ? AND pcr_total IS NOT NULL
               ORDER BY id DESC LIMIT 2""",
            [index],
        ).fetchall()
        if len(rows) >= 2:
            pcr_now = rows[0][0]
            pcr_prev = rows[1][0]
            result["indicators"]["pcr_change"] = (
                _r(pcr_now - pcr_prev, 3) if pcr_now and pcr_prev else None
            )

        # Latest PCR
        result["indicators"]["pcr_total"] = _r(rows[0][0], 2) if rows else None
    except Exception:
        pass

    # FII data not captured yet — mark clearly
    result["indicators"]["fii_fut_5d_change"] = None
    result["indicators"]["fii_data_note"] = (
        "FII futures data not yet captured by v3.1 pipeline"
    )

    v31.close()
    return json.dumps(result, indent=2)


# ============================================================
# 7. MACRO — VIX_level, VIX_change, GIFT_premium, gap, ratio
# ============================================================


def query_macro(index: str = "NIFTY") -> str:
    """Query macro indicators: VIX, gap, session state, pivots."""
    v31 = _open_db(_v31_db_path())
    result = {
        "family": "Macro",
        "index": index,
        "timestamp": datetime.now().isoformat(),
        "indicators": {},
    }

    if not v31:
        return json.dumps(result, indent=2)

    try:
        row = v31.execute(
            """SELECT india_vix, spot, open_price, prev_close, gap_pct,
                      session_phase, open_to_current_pct,
                      prev_day_high, prev_day_low, prev_day_range,
                      pivot_pp, pivot_r1, pivot_r2, pivot_s1, pivot_s2,
                      distance_to_pivot_pct, distance_to_r1_pct, distance_to_s1_pct
               FROM market_data WHERE index_name = ? ORDER BY id DESC LIMIT 1""",
            [index],
        ).fetchone()
        if row:
            (
                vix,
                spot,
                open_p,
                prev_c,
                gap,
                phase,
                open_pct,
                pd_h,
                pd_l,
                pd_range,
                pp,
                r1,
                r2,
                s1,
                s2,
                dst_pp,
                dst_r1,
                dst_s1,
            ) = row

            # VIX level classification
            vix_level = (
                "low"
                if vix and vix < 14
                else "normal"
                if vix and vix < 20
                else "elevated"
                if vix and vix < 25
                else "extreme"
                if vix
                else "unknown"
            )

            result["indicators"] = {
                "vix": _r(vix, 2),
                "vix_level": vix_level,
                "spot": _r(spot),
                "gap_pct": _r(gap, 2),
                "open_price": _r(open_p),
                "prev_close": _r(prev_c),
                "session_phase": str(phase).strip() if phase else "unknown",
                "open_to_current_pct": _r(open_pct, 2),
                "prev_day_high": _r(pd_h),
                "prev_day_low": _r(pd_l),
                "prev_day_range": _r(pd_range),
                "pivot_pp": _r(pp),
                "pivot_r1": _r(r1),
                "pivot_s1": _r(s1),
                "distance_to_pivot_pct": _r(dst_pp, 2),
            }

            # VIX_change needs sequential query
            rows = v31.execute(
                "SELECT india_vix FROM market_data WHERE index_name = ? AND india_vix IS NOT NULL ORDER BY id DESC LIMIT 2",
                [index],
            ).fetchall()
            if len(rows) >= 2:
                result["indicators"]["vix_change"] = (
                    _r(rows[0][0] - rows[1][0], 2)
                    if rows[0][0] and rows[1][0]
                    else None
                )
    except Exception:
        pass

    # Data not yet captured
    result["indicators"]["gift_premium"] = None
    result["indicators"]["gift_premium_note"] = "GIFT NIFTY data not yet captured"
    result["indicators"]["banknifty_nifty_ratio"] = None
    result["indicators"]["banknifty_nifty_ratio_note"] = (
        "BANKNIFTY dual capture not yet active"
    )

    v31.close()
    return json.dumps(result, indent=2)


# ============================================================
# 8. TRAFFIC LIGHT — multi-TF candle color patterns
# ============================================================


def query_traffic_light(index: str = "NIFTY") -> str:
    """
    Multi-TF traffic light: candle color (GREEN/RED) per timeframe with pattern analysis.
    Detects: continuation, pullback, resumption, exhaustion, reversal.

    Green = close > open (bullish candle). Red = close < open (bearish).

    Patterns detected:
      - Green daily + Green 4H + Green 1H = STRONG BULL CONTINUATION
      - Green daily + Red 4H + Green 1H/30m = BULLISH PULLBACK (resuming)
      - Green daily + Red 4H + Red 1H = DEEP PULLBACK (caution)
      - Red daily + Green lower TFs = DEAD CAT BOUNCE (sceptical)
      - All Green across all TFs = MOMENTUM PEAK (possible exhaustion)
      - All Red = STRONG BEAR CONTINUATION
        - Shifting from all-Green → mixed = EXHAUSTION / TOPPING
      - Shifting from all-Red → mixed = BOTTOMING / REVERSAL SIGNAL
    """
    v4 = _open_db(_v4_db_path())

    result = {
        "family": "TrafficLight",
        "index": index,
        "timestamp": datetime.now().isoformat(),
        "candles": {},
        "pattern": "unknown",
        "confidence": 0,
    }

    if not v4:
        return json.dumps(result, indent=2)

    tf_order = [
        (5, "5m"),
        (15, "15m"),
        (30, "30m"),
        (60, "60m"),
        (240, "240m"),
        (1440, "1440m"),
    ]

    for minut, label in tf_order:
        try:
            row = v4.execute(
                "SELECT open, close, high, low FROM market_data_multitf WHERE index_name = ? AND timeframe_min = ? ORDER BY timestamp DESC LIMIT 1",
                [index, minut],
            ).fetchone()
            if row:
                o, c, h, l = row
                candle = (
                    "GREEN"
                    if (o and c and c > o)
                    else ("RED" if (o and c) else "neutral")
                )
                body = abs(c - o) if (c and o) else 0
                range_pct = ((h - l) / l * 100) if (h and l and l > 0) else 0
                result["candles"][label] = {
                    "color": candle,
                    "body_pct": round(body / o * 100, 2) if o and o > 0 else None,
                    "range_pct": round(range_pct, 2),
                    "upper_wick_pct": round((h - max(c, o)) / body * 100, 1)
                    if body > 0 and h
                    else None,
                    "lower_wick_pct": round((min(c, o) - l) / body * 100, 1)
                    if body > 0 and l
                    else None,
                }
            else:
                result["candles"][label] = {"color": "no_data"}
        except Exception:
            result["candles"][label] = {"color": "error"}

    v4.close()

    # ── Pattern detection ──
    colors = {
        k: result["candles"].get(k, {}).get("color", "neutral")
        for k in ["5m", "15m", "30m", "60m", "240m", "1440m"]
    }
    green_c = sum(1 for c in colors.values() if c == "GREEN")
    red_c = sum(1 for c in colors.values() if c == "RED")
    daily_c = colors.get("1440m")
    h4_c = colors.get("240m")
    h1_c = colors.get("60m")
    m30_c = colors.get("30m")
    m15_c = colors.get("15m")
    m5_c = colors.get("5m")

    pattern = "mixed"
    confidence = 30

    if green_c == 6:
        pattern = "MOMENTUM_PEAK"
        confidence = 70
    elif red_c == 6:
        pattern = "STRONG_BEAR_CONTINUATION"
        confidence = 90
    elif daily_c == "GREEN" and h4_c == "RED" and h1_c == "GREEN":
        pattern = "BULLISH_PULLBACK_RESUMING"
        confidence = 70
    elif (
        daily_c == "GREEN"
        and h4_c == "RED"
        and h1_c == "RED"
        and (m30_c == "GREEN" or m15_c == "GREEN")
    ):
        pattern = "BULLISH_DEEP_PULLBACK_BOUNCING"
        confidence = 55
    elif daily_c == "GREEN" and h4_c == "GREEN" and h1_c == "RED":
        pattern = "BULLISH_MILD_PULLBACK"
        confidence = 65
    elif daily_c == "RED" and h1_c == "GREEN" and m15_c == "GREEN":
        pattern = "DEAD_CAT_BOUNCE"
        confidence = 60
    elif daily_c == "GREEN" and green_c >= 4:
        pattern = "BULLISH_STRUCTURE"
        confidence = 65
    elif daily_c == "RED" and red_c >= 4:
        pattern = "BEARISH_STRUCTURE"
        confidence = 65
    elif green_c == 3 and red_c == 3:
        pattern = "CHOPPY_INDECISION"
        confidence = 20

    # Exhaustion: 5-6 green but 5m/15m turning red (momentum fading)
    exhaustion = green_c >= 4 and (m5_c == "RED" or m15_c == "RED")
    # Reversal: daily red but 1-2 lower TFs turning green consistently
    reversal_signal = daily_c == "RED" and h1_c == "GREEN" and m30_c == "GREEN"

    story_parts = []
    if exhaustion:
        story_parts.append("⚠️ EXHAUSTION: momentum fading on lower TFs")
    if reversal_signal:
        story_parts.append(
            "🔄 POTENTIAL REVERSAL: lower TFs turning green against daily red"
        )

    result["pattern"] = pattern
    result["confidence"] = confidence
    result["summary"] = {
        "daily": daily_c,
        "four_hour": h4_c,
        "one_hour": h1_c,
        "thirty_min": m30_c,
        "fifteen_min": m15_c,
        "five_min": m5_c,
        "green_count": green_c,
        "red_count": red_c,
        "story": f"D={daily_c} | 4H={h4_c} | 1H={h1_c} | 30m={m30_c} | 15m={m15_c} | 5m={m5_c} | G={green_c}/6 R={red_c}/6 {' | '.join(story_parts)}",
    }
    result["exhaustion"] = exhaustion
    result["reversal_signal"] = reversal_signal

    return json.dumps(result, indent=2)


# ============================================================
# REDIS READER — live 1-min OHLCV for entry gate
# ============================================================


def _redis_connect():
    """Connect to local Redis. Returns client or None."""
    try:
        import redis as _redis

        r = _redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
        r.ping()
        return r
    except Exception:
        return None


def get_live_candles(index: str = "NIFTY", lookback_bars: int = 360) -> dict:
    """
    Read live 1-min OHLCV bars from Redis `v3_ohlcv_queue`.
    Returns dict of per-TF candle colors + recent 1-min bar.
    No DuckDB dependency — pure Redis.

    Args:
        index: NIFTY or SENSEX
        lookback_bars: how many 1-min bars to fetch for SMA/aggregation (default 360 = 6h)
    Returns:
        {latest_1m: {open,high,low,close,volume}, candles_by_tf: {5m:GREEN/RED,...}, n_bars}
    """
    from datetime import datetime as _dt

    r = _redis_connect()
    if not r:
        return {
            "latest_1m": None,
            "candles_by_tf": {},
            "n_bars": 0,
            "error": "redis_unavailable",
        }

    try:
        bars_raw = r.lrange("v3_ohlcv_queue", 0, lookback_bars - 1)
        if not bars_raw:
            return {
                "latest_1m": None,
                "candles_by_tf": {},
                "n_bars": 0,
                "error": "empty_queue",
            }

        # Parse bars, filter by index
        import json as _json

        bars = []
        for b in bars_raw:
            try:
                d = _json.loads(b)
                if d.get("index") == index:
                    bars.append(
                        {
                            "timestamp": d.get("timestamp"),
                            "open": float(d["open"]),
                            "high": float(d["high"]),
                            "low": float(d["low"]),
                            "close": float(d["close"]),
                        }
                    )
            except (json.JSONDecodeError, KeyError, ValueError):
                continue

        if not bars:
            return {
                "latest_1m": None,
                "candles_by_tf": {},
                "n_bars": 0,
                "error": "no_bars_for_index",
            }

        latest = bars[0]  # newest is at head (LPUSH)

        # Aggregate to multi-TF candles
        candles_by_tf = {}
        tf_minutes = {"5m": 5, "15m": 15, "30m": 30, "60m": 60, "240m": 240}

        for tf_label, tf_mins in tf_minutes.items():
            agg = _aggregate_redis_bars(bars, tf_mins)
            if agg:
                candles_by_tf[tf_label] = (
                    "GREEN" if agg["close"] > agg["open"] else "RED"
                )
            else:
                candles_by_tf[tf_label] = "no_data"

        # Daily candle: from all bars today
        candles_by_tf["1440m"] = (
            "GREEN"
            if latest["close"] > bars[-1]["open"]
            else "RED"
            if len(bars) > 1
            else "no_data"
        )

        return {
            "latest_1m": latest,
            "candles_by_tf": candles_by_tf,
            "n_bars": len(bars),
            "latest_timestamp": latest["timestamp"],
        }
    except Exception as e:
        return {"latest_1m": None, "candles_by_tf": {}, "n_bars": 0, "error": str(e)}


def _aggregate_redis_bars(bars: list, tf_minutes: int) -> dict:
    """Aggregate 1-min bars to multi-TF candle from Redis data."""
    if not bars:
        return None
    # Take the last N minutes of bars
    count = min(tf_minutes, len(bars))
    bucket = bars[:count]
    if not bucket:
        return None
    return {
        "open": bucket[-1]["open"],
        "high": max(b["high"] for b in bucket),
        "low": min(b["low"] for b in bucket),
        "close": bucket[0]["close"],
    }


def score_trend_redis(index: str = "NIFTY", lookback: int = 500) -> dict:
    """
    Score trend using persistent EMA buffers (0 DuckDB calls).
    Reads EMA values from /tmp/ema_state/*.json files.
    Once EMA threshold crossed, always has data (rolling calculation).
    Before threshold: returns None (not_enough_data).

    Args:
        index: NIFTY or SENSEX
        lookback: (unused, kept for API compatibility)
    Returns:
        {family, signal, score, confidence, reasoning, key_indicators}
    """
    import json as _json
    from datetime import datetime as _dt
    from pathlib import Path as _Path

    cfg = _load_weights().get("trend", {})
    tf_weights = cfg.get(
        "tf_weights",
        {"5m": 0.1, "15m": 0.15, "30m": 0.15, "60m": 0.2, "240m": 0.2, "1440m": 0.2},
    )
    st_boost = cfg.get("st_boost", 2.0)
    thresholds = cfg.get("signal_thresholds", {"bullish": 3.0, "bearish": -3.0})

    # Load EMA values from persistent files
    ema_dir = _Path("/tmp/ema_state")
    ema_values = {}
    ema_status = {}

    for period in [5, 20, 50, 100, 200]:
        ema_file = ema_dir / f"ema_{period}.json"
        if ema_file.exists():
            try:
                state = _json.loads(ema_file.read_text())
                if state.get("available"):
                    ema_values[period] = state.get("ema_value")
                    ema_status[period] = "ready"
                else:
                    ema_status[period] = f"not_enough_data ({state.get('buffer_count', 0)}/{period})"
            except Exception:
                ema_status[period] = "error_reading_file"
        else:
            ema_status[period] = "file_not_found"

    # Get latest price from Redis
    r = _redis_connect()
    if not r:
        return {
            "family": "Trend",
            "signal": "NEUTRAL",
            "score": 0,
            "confidence": 5,
            "reasoning": "redis_unavailable",
            "ema_status": ema_status,
            "timestamp": _dt.now().isoformat(),
            "_method": "ema_file_based",
        }

    try:
        bars_raw = r.lrange("v3_ohlcv_queue", 0, 0)  # Just get latest bar
        if not bars_raw:
            return {
                "family": "Trend",
                "signal": "NEUTRAL",
                "score": 0,
                "confidence": 5,
                "reasoning": "empty_queue",
                "ema_status": ema_status,
                "timestamp": _dt.now().isoformat(),
                "_method": "ema_file_based",
            }

        latest_bar = _json.loads(bars_raw[0])
        current_price = float(latest_bar.get("close", 0))

        if current_price == 0:
            return {
                "family": "Trend",
                "signal": "NEUTRAL",
                "score": 0,
                "confidence": 5,
                "reasoning": "invalid_price",
                "ema_status": ema_status,
                "timestamp": _dt.now().isoformat(),
                "_method": "ema_file_based",
            }
    except Exception as e:
        return {
            "family": "Trend",
            "signal": "NEUTRAL",
            "score": 0,
            "confidence": 5,
            "reasoning": f"redis_error:{e}",
            "ema_status": ema_status,
            "timestamp": _dt.now().isoformat(),
            "_method": "ema_file_based",
        }

    # Score based on EMA values
    score = 0.0
    ema_aligned = 0
    available_count = 0
    reasoning_parts = []

    # EMA20 scoring (primary)
    if 20 in ema_values:
        ema20 = ema_values[20]
        available_count += 1
        if current_price > ema20:
            ema_aligned += 1
            tf_score = 0.30
            reasoning_parts.append(f"EMA20:BULLISH(+0.30)")
        else:
            tf_score = -0.30
            reasoning_parts.append(f"EMA20:BEARISH(-0.30)")
        score += tf_score
    else:
        reasoning_parts.append(f"EMA20:not_ready")

    # EMA50 scoring (confirmation)
    if 50 in ema_values:
        ema50 = ema_values[50]
        available_count += 1
        if current_price > ema50:
            ema_aligned += 1
            tf_score = 0.25
            reasoning_parts.append(f"EMA50:BULLISH(+0.25)")
        else:
            tf_score = -0.25
            reasoning_parts.append(f"EMA50:BEARISH(-0.25)")
        score += tf_score
    else:
        reasoning_parts.append(f"EMA50:not_ready")

    # EMA100 scoring (long-term)
    if 100 in ema_values:
        ema100 = ema_values[100]
        available_count += 1
        if current_price > ema100:
            ema_aligned += 1
            tf_score = 0.20
            reasoning_parts.append(f"EMA100:BULLISH(+0.20)")
        else:
            tf_score = -0.20
            reasoning_parts.append(f"EMA100:BEARISH(-0.20)")
        score += tf_score
    else:
        reasoning_parts.append(f"EMA100:not_ready")

    # Determine signal
    if available_count == 0:
        signal = "NEUTRAL"
        confidence = 5
        reason_str = "no_ema_data_yet"
    else:
        alignment_pct = ema_aligned / available_count

        if alignment_pct >= 0.75:
            signal = "BULLISH"
            confidence = min(90, 50 + (alignment_pct * 40))
        elif alignment_pct <= 0.25:
            signal = "BEARISH"
            confidence = min(90, 50 + ((1 - alignment_pct) * 40))
        else:
            signal = "NEUTRAL"
            confidence = 40

        reason_str = f"EMA alignment {int(ema_aligned)}/{available_count}"

    return {
        "family": "Trend",
        "signal": signal,
        "score": round(score, 2),
        "confidence": int(confidence),
        "reasoning": reason_str,
        "key_indicators": {
            "ema_aligned": f"{ema_aligned}/{available_count}",
            "raw_score": round(score, 2),
            "current_price": round(current_price, 2),
            "ema_values": {k: round(v, 2) for k, v in ema_values.items()},
        },
        "ema_status": ema_status,
        "timestamp": _dt.now().isoformat(),
        "_method": "ema_file_based",
    }


def _compute_sma_from_bars(bars: list, tf_minutes: int, periods: list = None) -> tuple:
    """Compute SMA from 1-min bar closes aggregated to a timeframe."""
    if periods is None:
        periods = [20, 50]
    if len(bars) < tf_minutes * max(periods):
        return None, None

    # Group bars by TF buckets, take last close of each bucket
    bucket_closes = []
    for i in range(0, len(bars) - tf_minutes + 1, tf_minutes):
        bucket = bars[i : i + tf_minutes]
        bucket_closes.append(float(bucket[0]["close"]))

    if len(bucket_closes) < max(periods):
        return None, None

    import numpy as np

    closes = np.array(
        bucket_closes[: min(len(bucket_closes), max(periods))], dtype=float
    )
    results = []
    for p in periods:
        if len(closes) >= p:
            results.append(round(float(np.mean(closes[-p:])), 2))
        else:
            results.append(None)
    return tuple(results) if len(results) == 2 else (None, None)


def _get_latest_indicator(bars: list, key: str):
    """Get the latest available indicator value from Redis bars."""
    for b in bars[:1]:
        v = b.get(key)
        if v is not None:
            return float(v)
    return None


def _aggregate_to_tf(bars: list, tf_minutes: int) -> dict:
    """Aggregate 1-min bars to a multi-TF candle."""
    if len(bars) < tf_minutes:
        return None
    bucket = bars[:tf_minutes]
    return {
        "open": float(bucket[-1]["open"]),
        "high": max(float(b["high"]) for b in bucket),
        "low": min(float(b["low"]) for b in bucket),
        "close": float(bucket[0]["close"]),
    }


def _get_gap_from_redis(index: str, latest_1m: dict) -> dict:
    """
    Calculate gap direction and size from Redis data.

    Gap = today's market open vs yesterday's close
    GREEN if open > prev_close (gap up)
    RED if open < prev_close (gap down)
    """
    try:
        r = _redis_connect()
        if not r:
            return {"direction": "unknown", "reason": "redis_unavailable"}

        # Get today's market open price from latest 1m bar
        # (first bar of the day at 9:15 market open)
        today_open = latest_1m.get("open")
        if not today_open:
            return {"direction": "unknown", "reason": "no_latest_1m"}

        # Try to get previous day's close from Redis
        # Look for a special key or read from historical data
        prev_close_key = f"prev_close_{index}"
        prev_close_str = r.get(prev_close_key)

        if prev_close_str:
            try:
                prev_close = float(prev_close_str)
            except ValueError:
                return {"direction": "unknown", "reason": "invalid_prev_close"}
        else:
            # Fallback: assume no prev close available
            # In production, this should be set by v3.1 at 9:15
            return {"direction": "unknown", "reason": "prev_close_not_in_redis"}

        gap_size = float(today_open) - float(prev_close)
        gap_pct = (gap_size / float(prev_close) * 100) if prev_close != 0 else 0

        direction = "GREEN" if gap_size > 0 else ("RED" if gap_size < 0 else "FLAT")

        return {
            "direction": direction,
            "today_open": round(float(today_open), 2),
            "prev_close": round(float(prev_close), 2),
            "gap_size_points": round(gap_size, 2),
            "gap_size_pct": round(gap_pct, 3),
            "status": "complete"
        }

    except Exception as e:
        return {"direction": "unknown", "reason": f"error: {str(e)}"}


def score_traffic_light_redis(index: str = "NIFTY") -> dict:
    """
    Score traffic light from REDIS (0 DuckDB calls).
    Uses get_live_candles() for per-TF candle colors, pattern matches.
    Includes 7th parameter: gap direction (GREEN if gap up, RED if gap down).
    """
    import json as _json
    from datetime import datetime as _dt

    cfg = _load_weights().get("traffic_light", {})
    pattern_cfg = cfg.get("patterns", {})
    thresholds = cfg.get("signal_thresholds", {"bullish": 3.0, "bearish": -3.0})

    live = get_live_candles(index)
    candles = live.get("candles_by_tf", {})

    if not candles or live.get("error"):
        return {
            "family": "TrafficLight",
            "signal": "NEUTRAL",
            "score": 0,
            "confidence": 5,
            "reasoning": f"Redis error: {live.get('error', 'no data')}",
            "key_indicators": {"story": "no_data", "gap": "unknown"},
            "timestamp": _dt.now().isoformat(),
            "_method": "redis",
        }

    # ── 7th Parameter: Gap Direction ──
    gap_info = _get_gap_from_redis(index, live.get("latest_1m", {}))

    colors = {}
    for tf in ["5m", "15m", "30m", "60m", "240m", "1440m"]:
        c = candles.get(tf, "no_data")
        colors[tf] = c if c in ("GREEN", "RED") else "neutral"

    green_c = sum(1 for c in colors.values() if c == "GREEN")
    red_c = sum(1 for c in colors.values() if c == "RED")
    daily_c = colors.get("1440m", "neutral")
    h4_c = colors.get("240m", "neutral")
    h1_c = colors.get("60m", "neutral")
    m30_c = colors.get("30m", "neutral")

    pattern = "mixed"
    if green_c == 6:
        pattern = "MOMENTUM_PEAK"
    elif red_c == 6:
        pattern = "STRONG_BEAR_CONTINUATION"
    elif daily_c == "GREEN" and h4_c == "RED" and h1_c == "GREEN":
        pattern = "BULLISH_PULLBACK_RESUMING"
    elif daily_c == "GREEN" and h4_c == "GREEN" and h1_c == "RED":
        pattern = "BULLISH_MILD_PULLBACK"
    elif (
        daily_c == "GREEN"
        and h4_c == "RED"
        and h1_c == "RED"
        and (m30_c == "GREEN" or colors.get("15m") == "GREEN")
    ):
        pattern = "BULLISH_DEEP_PULLBACK_BOUNCING"
    elif daily_c == "RED" and h1_c == "GREEN" and colors.get("15m") == "GREEN":
        pattern = "DEAD_CAT_BOUNCE"
    elif daily_c == "GREEN" and green_c >= 4:
        pattern = "BULLISH_CONTINUATION"
    elif daily_c == "RED" and red_c >= 4:
        pattern = "BEARISH_CONTINUATION"
    elif green_c >= 4:
        pattern = "BULLISH_STRUCTURE"
    elif red_c >= 4:
        pattern = "BEARISH_STRUCTURE"
    elif green_c == 3 and red_c == 3:
        pattern = "CHOPPY_INDECISION"

    pat_data = pattern_cfg.get(
        pattern, pattern_cfg.get("mixed", {"score": 0, "confidence": 30})
    )
    score = pat_data["score"]
    confidence = pat_data.get("confidence", 30)

    # ── Apply gap weighting (7th parameter) ──
    gap_weight = cfg.get("gap_weight", 0.2)  # Default 0.2 (20% influence)
    gap_boost = 0
    gap_conf_adjust = 0

    if gap_info.get("status") == "complete":
        gap_dir = gap_info.get("direction")

        # Boost/penalty based on gap alignment with pattern
        if gap_dir == "GREEN":
            # Gap up context
            if green_c >= 4:  # Bullish pattern + gap up = strong
                gap_boost = gap_weight * 2.0
                gap_conf_adjust = 15
            elif red_c >= 4:  # Bearish pattern + gap up = conflict
                gap_boost = -gap_weight * 1.5
                gap_conf_adjust = -20
        elif gap_dir == "RED":
            # Gap down context
            if red_c >= 4:  # Bearish pattern + gap down = strong
                gap_boost = -gap_weight * 2.0
                gap_conf_adjust = 15
            elif green_c >= 4:  # Bullish pattern + gap down = conflict/recovery
                gap_boost = gap_weight * 1.5
                gap_conf_adjust = 10

        score += gap_boost
        confidence += gap_conf_adjust

    signal = (
        "BULLISH"
        if score >= thresholds["bullish"]
        else ("BEARISH" if score <= thresholds["bearish"] else "NEUTRAL")
    )

    story = " | ".join(
        f"{tf}={colors.get(tf, '?')}"
        for tf in ["1440m", "240m", "60m", "30m", "15m", "5m"]
    )
    story += f" | G={green_c}/6 R={red_c}/6 | GAP={gap_info.get('direction', '?')}"

    confidence = max(5, min(100, confidence))  # Clamp to 5-100

    return {
        "family": "TrafficLight",
        "signal": signal,
        "score": round(score, 2),
        "confidence": confidence,
        "reasoning": f"pattern={pattern} (Redis, no DuckDB) + gap_weighted",
        "key_indicators": {
            "pattern": pattern,
            "story": story,
            "n_bars": live.get("n_bars", 0),
            "gap": gap_info.get("direction"),  # 7th parameter
            "gap_boost": round(gap_boost, 2),
            "gap_conf_adjust": gap_conf_adjust,
        },
        "gap": gap_info,  # Include full gap details
        "timestamp": _dt.now().isoformat(),
        "_method": "redis",
    }



def _load_weights():
    """Load entry_weights.json from config dir."""
    import json as _json
    from pathlib import Path as _Path

    cfg = _Path(__file__).parent.parent / "config" / "entry_weights.json"
    if cfg.exists():
        return _json.loads(cfg.read_text())
    return {}


def score_trend(index: str = "NIFTY") -> dict:
    """
    Score trend deterministically — no LLM.
    Reads DuckDB, applies TF weights + ADX gates + ST boost from config.
    Returns {family, signal, score, confidence, reasoning}.
    """
    import json as _json
    from datetime import datetime as _dt

    cfg = _load_weights().get("trend", {})
    tf_weights = cfg.get(
        "tf_weights",
        {"5m": 0.1, "15m": 0.15, "30m": 0.15, "60m": 0.2, "240m": 0.2, "1440m": 0.2},
    )
    adx_cfg = cfg.get("adx", {})
    st_boost = cfg.get("st_boost", 2.0)
    thresholds = cfg.get("signal_thresholds", {"bullish": 3.0, "bearish": -3.0})
    conf_cfg = cfg.get("confidence", {})

    raw = _json.loads(query_trend(index))
    tfs = raw.get("timeframes", {})

    score = 0.0
    tf_count = 0
    aligned_count = 0
    reasoning_parts = []

    # TF-score loop
    for tf_key, weight in tf_weights.items():
        d = tfs.get(tf_key, {})
        sma_pos = d.get("sma_position", "neutral")
        if sma_pos in ("no_data", "error", "neutral"):
            reasoning_parts.append(f"{tf_key}:neutral(×{weight})")
            continue
        tf_count += 1
        tf_score = weight if sma_pos == "bullish" else -weight
        # ADX gate per TF
        adx_val = d.get("adx")
        if adx_val is not None:
            if adx_val < adx_cfg.get("noise_threshold", 10):
                tf_score *= adx_cfg.get("noise_penalty", 0.0)
                reasoning_parts.append(f"{tf_key}:{sma_pos}(×{weight},noise={adx_val})")
            elif adx_val < adx_cfg.get("weak_threshold", 20):
                tf_score *= adx_cfg.get("weak_multiplier", 0.5)
                reasoning_parts.append(f"{tf_key}:{sma_pos}(×{weight},weak={adx_val})")
            elif adx_val >= adx_cfg.get("strong_threshold", 35):
                tf_score *= adx_cfg.get("strong_multiplier", 1.3)
                aligned_count += 1
                reasoning_parts.append(
                    f"{tf_key}:{sma_pos}(×{weight},strong={adx_val})"
                )
            else:
                aligned_count += 1
                reasoning_parts.append(f"{tf_key}:{sma_pos}(×{weight},adx={adx_val})")
        else:
            reasoning_parts.append(f"{tf_key}:{sma_pos}(×{weight},no_adx)")
            aligned_count += 1

        # ST boost
        st = d.get("st_consensus", "").upper()
        if st in ("BULLISH", "BEARISH"):
            tf_score += (
                st_boost
                if (sma_pos == "bullish" and st == "BULLISH")
                else (-st_boost if (sma_pos == "bearish" and st == "BEARISH") else 0)
            )
        score += tf_score

    # v3.1 1m layer
    d31 = tfs.get("1m_v3.1", {})
    ema_pos = d31.get("ema_position")
    if ema_pos and ema_pos not in ("neutral", "no_data"):
        tf_score = 0.05 if ema_pos == "bullish" else -0.05
        adx31 = d31.get("adx")
        if adx31 and adx31 > 25:
            tf_score *= 1.5
        score += tf_score
        reasoning_parts.append(f"1m_v3.1:{ema_pos}(×0.05)")

    if tf_count == 0:
        signal = "NEUTRAL"
        score = 0.0

    # Signal
    signal = (
        "BULLISH"
        if score >= thresholds["bullish"]
        else ("BEARISH" if score <= thresholds["bearish"] else "NEUTRAL")
    )

    # Confidence
    max_tfs = len(tf_weights) + 1  # 6 v4 + 1 v3.1
    missing = max_tfs - tf_count
    penalty_per = conf_cfg.get("penalty_per_missing_tf", 12)
    if missing == max_tfs:
        confidence = conf_cfg.get("no_data", 15)
    elif aligned_count >= 5:
        confidence = conf_cfg.get("full_alignment", 90) - missing * penalty_per
    elif aligned_count >= 3:
        confidence = conf_cfg.get("high_alignment", 70) - missing * penalty_per
    else:
        confidence = conf_cfg.get("mixed", 40) - missing * penalty_per
    confidence = max(5, min(100, confidence))

    return {
        "family": "Trend",
        "signal": signal,
        "score": round(score, 2),
        "confidence": confidence,
        "reasoning": " | ".join(reasoning_parts) if reasoning_parts else "no_tf_data",
        "key_indicators": {
            "aligned_tfs": f"{aligned_count}/{max_tfs}",
            "raw_score": round(score, 2),
        },
        "timestamp": _dt.now().isoformat(),
        "_method": "deterministic",
    }


def score_traffic_light(index: str = "NIFTY") -> dict:
    """
    Score traffic light deterministically — no LLM.
    Reads pattern from query_traffic_light, applies pattern scores from config.
    Returns {family, signal, score, confidence, reasoning}.
    """
    import json as _json
    from datetime import datetime as _dt

    cfg = _load_weights().get("traffic_light", {})
    pattern_cfg = cfg.get("patterns", {})
    thresholds = cfg.get("signal_thresholds", {"bullish": 3.0, "bearish": -3.0})

    raw = _json.loads(query_traffic_light(index))
    pattern = raw.get("pattern", "mixed")
    pat_data = pattern_cfg.get(
        pattern, pattern_cfg.get("mixed", {"score": 0, "confidence": 30})
    )
    raw_score = pat_data["score"]
    raw_conf = pat_data.get("confidence", 30)

    score = raw_score
    confidence = raw_conf

    # Adjust for exhaustion/reversal flags
    flags = []
    if raw.get("exhaustion"):
        score = max(-3, score - 3)
        confidence -= 15
        flags.append("exhaustion_discount")
    if raw.get("reversal_signal"):
        score = min(3, score + 3)
        confidence -= 10
        flags.append("reversal_add")

    signal = (
        "BULLISH"
        if score >= thresholds["bullish"]
        else ("BEARISH" if score <= thresholds["bearish"] else "NEUTRAL")
    )
    confidence = max(5, min(100, confidence))

    return {
        "family": "TrafficLight",
        "signal": signal,
        "score": score,
        "confidence": confidence,
        "reasoning": f"pattern={pattern} score={raw_score}{' flags=' + ','.join(flags) if flags else ''}",
        "key_indicators": {
            "pattern": pattern,
            "story": raw.get("summary", {}).get("story", ""),
            "exhaustion": raw.get("exhaustion", False),
            "reversal": raw.get("reversal_signal", False),
        },
        "timestamp": _dt.now().isoformat(),
        "_method": "deterministic",
    }


def combine_entry_scores(trend_score: dict, tl_score: dict) -> dict:
    """
    Merge deterministic Trend + Traffic Light scores into GO/NO-GO.
    Pure Python — no LLM. Reads weights from config.
    """
    from datetime import datetime as _dt

    cfg = _load_weights().get("combine", {})
    rules = cfg.get("rules", {})
    go_thresh = cfg.get("go_threshold", {}).get("min_confidence", 35)

    t_sig = trend_score.get("signal", "NEUTRAL").upper()
    tl_sig = tl_score.get("signal", "NEUTRAL").upper()
    t_conf = trend_score.get("confidence", 50)
    tl_conf = tl_score.get("confidence", 50)
    t_score = trend_score.get("score", 0)
    tl_score_val = tl_score.get("score", 0)

    if t_sig == "BULLISH" and tl_sig == "BULLISH":
        rule = rules.get("both_bullish", {})
        go, mult = rule.get("go", True), rule.get("confidence_mult", 1.0)
        signal = "BULLISH"
        reason = "Trend + TL both BULLISH"
    elif t_sig == "BEARISH" and tl_sig == "BEARISH":
        rule = rules.get("both_bearish", {})
        go, mult = rule.get("go", True), rule.get("confidence_mult", 1.0)
        signal = "BEARISH"
        reason = "Trend + TL both BEARISH"
    elif t_sig == "BULLISH" and tl_sig == "NEUTRAL":
        rule = rules.get("bullish_plus_neutral", {})
        go, mult = rule.get("go", True), rule.get("confidence_mult", 0.75)
        signal = "BULLISH"
        reason = "Trend BULLISH, TL NEUTRAL"
    elif t_sig == "NEUTRAL" and tl_sig == "BULLISH":
        rule = rules.get("bullish_plus_neutral", {})
        go, mult = rule.get("go", True), rule.get("confidence_mult", 0.75)
        signal = "BULLISH"
        reason = "TL BULLISH, Trend NEUTRAL"
    elif t_sig == "BEARISH" and tl_sig == "NEUTRAL":
        rule = rules.get("bearish_plus_neutral", {})
        go, mult = rule.get("go", True), rule.get("confidence_mult", 0.75)
        signal = "BEARISH"
        reason = "Trend BEARISH, TL NEUTRAL"
    elif t_sig == "NEUTRAL" and tl_sig == "BEARISH":
        rule = rules.get("bearish_plus_neutral", {})
        go, mult = rule.get("go", True), rule.get("confidence_mult", 0.75)
        signal = "BEARISH"
        reason = "TL BEARISH, Trend NEUTRAL"
    elif t_sig == "BULLISH" and tl_sig == "BEARISH":
        rule = rules.get("conflict", {})
        go, mult = rule.get("go", False), rule.get("confidence_mult", 0.3)
        signal = "NEUTRAL"
        reason = "CONFLICT: Trend BULLISH vs TL BEARISH"
    elif t_sig == "BEARISH" and tl_sig == "BULLISH":
        rule = rules.get("conflict", {})
        go, mult = rule.get("go", False), rule.get("confidence_mult", 0.3)
        signal = "NEUTRAL"
        reason = "CONFLICT: Trend BEARISH vs TL BULLISH"
    else:
        rule = rules.get("both_neutral", {})
        go, mult = rule.get("go", True), rule.get("confidence_mult", 0.5)
        signal = "NEUTRAL"
        reason = "Both NEUTRAL — Iron Butterfly"

    # Confidence-weighted: low-confidence families contribute less
    # A family with 5% confidence saying NEUTRAL is "I don't know", not a bearish signal
    total_weight = t_conf + tl_conf
    if total_weight > 0:
        confidence = int((t_conf * t_conf + tl_conf * tl_conf) / total_weight * mult)
    else:
        confidence = 0

    # Compute combined score (weighted by confidence)
    if total_weight > 0:
        combined_score = (t_score * t_conf + tl_score_val * tl_conf) / total_weight
    else:
        combined_score = 0

    # Override: low confidence = NO-GO
    if go and confidence < go_thresh:
        go = False
        reason += f" (conf={confidence}% < min={go_thresh}%)"

    return {
        "go": go,
        "signal": signal,
        "score": round(combined_score, 2),
        "confidence": confidence,
        "trend_signal": t_sig,
        "traffic_light_signal": tl_sig,
        "trend_confidence": t_conf,
        "traffic_light_confidence": tl_conf,
        "trend_score": round(t_score, 2),
        "traffic_light_score": round(tl_score_val, 2),
        "reasoning": reason,
        "suggested_trade": (
            "SELL_PUT"
            if (go and signal == "BULLISH")
            else "SELL_CALL"
            if (go and signal == "BEARISH")
            else "IRON_BUTTERFLY"
            if (go and signal == "NEUTRAL")
            else "NONE"
        ),
        "timestamp": _dt.now().isoformat(),
        "_method": "deterministic",
    }


# ============================================================
# RL WEIGHT LEARNER — LLM adjusts weights post-session from P&L
# ============================================================


def rl_update_weights(session_results: list[dict]) -> dict:
    """
    Post-session RL: LLM analyzes today's trades and proposes updated weights.

    session_results = [{
        "entry_time": "...",
        "trend_score": {...},
        "tl_score": {...},
        "decision": {"go": true/false, "signal": "...", "confidence": ...},
        "pnl": 1250.50,        # <0 = loss, >0 = profit
        "exit_reason": "TP_HIT|SL_HIT|TIME_EXIT",
    }, ...]

    The LLM receives the full session ledger and outputs proposed weights.
    The proposed weights are stored in config/entry_weights.json.

    LLM task: "Which weights would have made better decisions?"
    - If trend calls were wrong → adjust TF weights
    - If ADX thresholds let through bad trades → raise thresholds
    - If pattern scores misranked → reorder patterns
    """
    import json as _json
    from pathlib import Path as _Path
    from datetime import datetime as _dt

    cfg_path = _Path(__file__).parent.parent / "config" / "entry_weights.json"
    current_weights = _json.loads(cfg_path.read_text()) if cfg_path.exists() else {}

    # No trades this session → no update
    if not session_results:
        return {
            "status": "skipped",
            "reason": "no_trades_today",
            "weights_changed_at": _dt.now().isoformat(),
        }

    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        return {
            "status": "skipped",
            "reason": "no_api_key",
            "weights_changed_at": _dt.now().isoformat(),
        }

    try:
        from crewai import Agent, Task, Crew, Process
        from crewai.llm import LLM

        llm = LLM(
            model="deepseek/deepseek-chat",
            base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
            api_key=api_key,
            temperature=0.1,
        )

        agent = Agent(
            role="RL Weight Tuner — Post-Session Performance Optimizer",
            goal=(
                "Analyze today's trade ledger. Determine which weights or thresholds "
                "would have produced better entry decisions. Propose minimal, data-backed changes."
            ),
            backstory=(
                "You receive today's complete trade ledger with entry-time scores (Trend, Traffic Light) "
                "and actual P&L outcomes. Your job:\n\n"
                "1. For each trade, compare the deterministic entry scores against the outcome.\n"
                "   - Did a Trend score of +5 lead to a loss? → Perhaps Trend TF weights are too bullish-heavy.\n"
                "   - Did a BULLISH_MILD_PULLBACK pattern lead to a loss? → Perhaps that pattern needs lower confidence.\n"
                "   - Did a NO-GO (both NEUTRAL) prevent a trade that would have won? → Maybe thresholds are too strict.\n\n"
                "2. Identify which family was WRONG and propose weight adjustments.\n"
                "   - Small adjustments only (max ±15% per TF weight). No wild swings.\n"
                "   - If Trend called BULLISH but we lost → reduce bullish TF weights slightly.\n"
                "   - If ADX was <15 but trade won → maybe noise_threshold can be lower.\n\n"
                "3. Output ONLY valid JSON:\n"
                '{"trend":{"tf_weights":{"5m":0.10,...},"adx":{"noise_threshold":10,...}},"traffic_light":{"patterns":{...}},"analysis":"summary of what changed and why"}'
            ),
            llm=llm,
            verbose=False,
            allow_delegation=False,
        )

        task = Task(
            description=(
                f"Current weights:\n{_json.dumps(current_weights, indent=2)}\n\n"
                f"Today's trade ledger ({len(session_results)} trades):\n"
                f"{_json.dumps(session_results, indent=2)}\n\n"
                "Analyze which weights produced good vs bad decisions. "
                "Propose adjustments. Output updated weight JSON."
            ),
            expected_output="JSON with updated weights and analysis",
            agent=agent,
        )

        crew = Crew(
            agents=[agent], tasks=[task], process=Process.sequential, verbose=False
        )
        result = crew.kickoff()

        # Parse LLM output
        raw = str(result).strip()
        if raw.startswith("```"):
            raw = raw.lstrip("```json").lstrip("```").rstrip("```").strip()

        try:
            proposed = _json.loads(raw)
        except _json.JSONDecodeError:
            return {
                "status": "parse_error",
                "reason": "LLM output not valid JSON",
                "raw": raw[:500],
                "weights_changed_at": _dt.now().isoformat(),
            }

        # Validate proposed weights structure (minimal sanity)
        if "trend" in proposed and "traffic_light" in proposed:
            new_weights = {**current_weights, **proposed}
            new_weights["_last_rl_update"] = _dt.now().isoformat()
            new_weights["_rl_analysis"] = proposed.get("analysis", "")

            # Save
            cfg_path.write_text(_json.dumps(new_weights, indent=2))
            return {
                "status": "updated",
                "analysis": proposed.get("analysis", ""),
                "weights_changed_at": _dt.now().isoformat(),
                "previous": {
                    k: current_weights.get(k, {}) for k in ["trend", "traffic_light"]
                },
                "new": {k: proposed.get(k, {}) for k in ["trend", "traffic_light"]},
            }
        else:
            return {
                "status": "invalid_structure",
                "reason": "Missing trend or traffic_light keys",
                "weights_changed_at": _dt.now().isoformat(),
            }

    except Exception as e:
        return {
            "status": "error",
            "reason": str(e),
            "weights_changed_at": _dt.now().isoformat(),
        }


# ============================================================
# COMPOSITE — all-family data in one call (for post-mortem RL)
# ============================================================


def llm_entry_decision(trend_score: dict, tl_score: dict) -> dict:
    """
    Single LLM call — receives pre-computed deterministic scores.
    The LLM adds WHAT THE DETERMINISTIC CODE CAN'T:
      - Edge-case judgment: "deterministic says GO but VIX is elevated"
      - Override reasoning: "Trend is borderline, TL says pullback has long wick"
      - Context: knows about news events, session phase, etc.

    Returns: same decision dict but with LLM-annotated reasoning.
    """
    import json as _json
    from datetime import datetime as _dt

    # Only call LLM if API key is configured
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        det = combine_entry_scores(trend_score, tl_score)
        det["_llm_override"] = False
        det["_llm_reasoning"] = "No API key — deterministic only"
        return det

    try:
        from crewai import Agent, Task, Crew, Process
        from crewai.llm import LLM

        llm = LLM(
            model="deepseek/deepseek-chat",
            base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
            api_key=api_key,
            temperature=0.2,
        )

        agent = Agent(
            role="Entry Gate Judge",
            goal="Review deterministic entry scores. Override only if you have a clear edge-case reason. Default to the deterministic decision.",
            backstory=(
                "You get pre-computed Trend + Traffic Light scores. Your job:\n"
                "1. Trust the deterministic recommendation UNLESS you see a specific reason to override.\n"
                "2. Valid overrides: VIX spike, gap risk, session phase (avoid late entries), conflicting candle shapes.\n"
                "3. If you override, explain EXACTLY why — cite specific values.\n"
                "4. Never override just because confidence is borderline.\n"
                'Output JSON: {"go":bool,"signal":"...","confidence":0-100,"override":false,"override_reason":"","note":"..."}'
            ),
            llm=llm,
            verbose=False,
            allow_delegation=False,
        )

        task = Task(
            description=(
                f"Deterministic entry decision:\n"
                f"  GO: {combine_entry_scores(trend_score, tl_score).get('go')}\n"
                f"  Signal: {combine_entry_scores(trend_score, tl_score).get('signal')}\n"
                f"  Confidence: {combine_entry_scores(trend_score, tl_score).get('confidence')}%\n\n"
                f"Trend score: {_json.dumps(trend_score, indent=2)}\n\n"
                f"Traffic Light score: {_json.dumps(tl_score, indent=2)}\n\n"
                f"Review and output final JSON decision. Override ONLY with clear reason."
            ),
            expected_output="JSON with go, signal, confidence, override, override_reason, note",
            agent=agent,
        )

        crew = Crew(
            agents=[agent], tasks=[task], process=Process.sequential, verbose=False
        )
        result = crew.kickoff()

        llm_parsed = _json.loads(str(result).strip().lstrip("```json").rstrip("```"))
        det = combine_entry_scores(trend_score, tl_score)
        det["_llm_override"] = llm_parsed.get("override", False)
        det["_llm_reasoning"] = llm_parsed.get(
            "override_reason", llm_parsed.get("note", "")
        )

        if llm_parsed.get("override"):
            det["go"] = llm_parsed.get("go", det["go"])
            det["signal"] = llm_parsed.get("signal", det["signal"])
            det["confidence"] = llm_parsed.get("confidence", det["confidence"])
            det["reasoning"] += (
                f" | LLM OVERRIDE: {llm_parsed.get('override_reason', '')}"
            )

        return det
    except Exception as e:
        det = combine_entry_scores(trend_score, tl_score)
        det["_llm_override"] = False
        det["_llm_reasoning"] = f"LLM call failed: {e} — deterministic fallback"
        return det


def query_all_families(index: str = "NIFTY") -> str:
    """
    Run all 7 family queries and merge into a single composite dict.
    Used by the Entry Aggregator and the RL weight learner.
    """
    families = {}
    for name, fn in [
        ("trend", query_trend),
        ("momentum", query_momentum),
        ("volatility", query_volatility),
        ("volume", query_volume),
        ("options", query_options),
        ("flow", query_flow),
        ("macro", query_macro),
        ("traffic_light", query_traffic_light),
    ]:
        try:
            raw = fn(index)
            families[name] = json.loads(raw)
        except Exception as e:
            families[name] = {"error": str(e)}

    return json.dumps(
        {
            "index": index,
            "timestamp": datetime.now().isoformat(),
            "families": families,
        },
        indent=2,
    )
