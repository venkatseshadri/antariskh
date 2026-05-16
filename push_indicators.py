#!/usr/bin/env python3
"""
Generate latest indicator snapshot from DuckDB and push to Telegram via Kubera/Picoclaw.
Usage: python3 push_indicators.py
"""

import os
import sys
import json
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT.parent / "python-trader" / "Shoonya_oAuthAPI-py"))
sys.path.insert(0, str(PROJECT_ROOT.parent / "python-trader"))
sys.path.insert(0, str(PROJECT_ROOT.parent / "python-trader" / "varaha"))

import duckdb
from telegram_bridge import TelegramBridge

IST = timezone(timedelta(hours=5, minutes=30))
DUCKDB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "python-trader/varaha/data/varaha_data.duckdb",
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
logger = logging.getLogger("IndicatorsPush")


def fmt(v, decimals=2):
    if v is None:
        return "—"
    return f"{float(v):.{decimals}f}"


def generate_report():
    db = duckdb.connect(DUCKDB_PATH, read_only=True)

    row = db.execute(
        "SELECT timestamp, spot, india_vix, adx, supertrend_direction, "
        "rsi, atr, ema_5, ema_20, ema_50, vwap, "
        "bb_pct_b, bb_width, gap_pct, "
        "iv_current, iv_rank, iv_regime, hv_20, "
        "agg_delta, agg_gamma, agg_vega, agg_theta, "
        "wings_delta, body_delta, "
        "pcr_total, pcr_atm, max_pain_strike, oi_skew, sentiment, "
        "cluster_support, cluster_resistance, smc_strength, "
        "pivot_pp, pivot_r1, pivot_s1, session_phase "
        "FROM market_data ORDER BY id DESC LIMIT 1"
    ).fetchone()

    db.close()

    if not row:
        return None, "No data in DuckDB"

    (
        ts,
        spot,
        vix,
        adx,
        st,
        rsi,
        atr,
        e5,
        e20,
        e50,
        vwap,
        bb_b,
        bb_w,
        gap,
        iv,
        iv_rank,
        iv_regime,
        hv20,
        agd,
        agg,
        agv,
        agt,
        wd,
        bd,
        pcr_t,
        pcr_a,
        mp,
        ois,
        sent,
        cs,
        cr,
        smc_s,
        pp,
        r1,
        s1,
        phase,
    ) = row

    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M IST")

    # Regime classification
    if vix is None or adx is None:
        regime = "INSUFFICIENT_DATA"
    elif vix > 20:
        regime = "VOLATILE/HALT"
    elif adx and adx > 25 and st and "bull" in str(st).lower():
        regime = "TRENDING_BULL"
    elif adx and adx > 25 and st and "bear" in str(st).lower():
        regime = "TRENDING_BEAR"
    else:
        regime = "SIDEWAYS"

    # Build message
    lines = [
        f"Antariksh Indicators — {now}",
        f"",
        f"NIFTY: {fmt(spot, 1)} | VIX: {fmt(vix, 1)} | Regime: {regime}",
        f"─────────────────────────",
        f"TREND",
        f"  ADX: {fmt(adx, 1)} | ST: {st or '—'} | ATR: {fmt(atr, 1)}",
        f"  EMA5: {fmt(e5, 1)} | EMA20: {fmt(e20, 1)} | EMA50: {fmt(e50, 1)}",
        f"  VWAP: {fmt(vwap, 1)}",
        f"",
        f"MOMENTUM",
        f"  RSI: {fmt(rsi, 1)} | BB %B: {fmt(bb_b, 1)} | BB W: {fmt(bb_w, 2)}",
        f"  Gap: {fmt(gap, 2)}%",
        f"",
        f"VOLATILITY & GREEKS",
        f"  IV: {fmt(iv, 1)}% | IV Rank: {fmt(iv_rank, 0)}% | Regime: {iv_regime or '—'}",
        f"  HV20: {fmt(hv20, 1)}% | Agg Δ: {fmt(agd, 3)} Γ: {fmt(agg, 3)} Θ: {fmt(agt, 1)}",
        f"  Wings Δ: {fmt(wd, 3)} | Body Δ: {fmt(bd, 3)}",
        f"",
        f"FLOW & SENTIMENT",
        f"  PCR: {fmt(pcr_t, 2)} | ATM PCR: {fmt(pcr_a, 2)} | Sent: {sent or '—'}",
        f"  MaxPain: {mp or '—'} | OI Skew: {fmt(ois, 2)}",
        f"",
        f"PRICE LEVELS",
        f"  PP: {fmt(pp, 1)} | R1: {fmt(r1, 1)} | S1: {fmt(s1, 1)}",
        f"  SMC: {fmt(smc_s, 1)} | Clusters: S={fmt(cs, 1)} R={fmt(cr, 1)}",
        f"",
        f"SESSION",
        f"  Phase: {phase or '—'} | Entry Window: 10:30–11:30",
    ]

    text = "\n".join(lines)

    # Also save to file
    outdir = PROJECT_ROOT / "logs"
    outdir.mkdir(exist_ok=True)
    outfile = outdir / f"indicators_{datetime.now(IST).strftime('%Y%m%d_%H%M')}.txt"
    outfile.write_text(text)
    logger.info(f"Saved: {outfile}")

    return text, outfile


if __name__ == "__main__":
    text, result = generate_report()

    if text is None:
        logger.error(f"No data: {result}")
        sys.exit(1)

    print(text)
    print()

    # Send via Telegram
    sent = TelegramBridge().send(text=text, message_type="indicators")
    if sent:
        logger.info("Sent to Telegram via Picoclaw/Kubera")
    else:
        logger.warning("Telegram send failed — check Picoclaw")
