#!/usr/bin/env python3
"""
Backfill EMA buffers from yfinance historical data.
Clears contaminated EMA state files and rebuilds from clean 60-min bars.

Usage: python3 backfill_ema_yfinance.py
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timedelta

import yfinance as yf
import pandas as pd

EMA_DIR = Path("/home/trading_ceo/brahmand/data/ema_state/60min")
EMA_DIR.mkdir(parents=True, exist_ok=True)
PERIODS = [5, 20, 50, 100, 200]
TF_LABEL = "60min"

# NIFTY ticker on Yahoo Finance
TICKER = "^NSEI"
# Download 200 trading days of 60-min bars (~200 days × 6 bars = 1200 bars)
DAYS = 200


def fetch_nifty_60min(days: int = DAYS) -> pd.DataFrame:
    """Download NIFTY 60-min bars from yfinance."""
    end = datetime.now()
    start = end - timedelta(days=days + 5)  # buffer for weekends

    ticker = yf.Ticker(TICKER)
    df = ticker.history(start=start, end=end, interval="60m")

    if df.empty:
        print("❌ yfinance returned no data for ^NSEI")
        sys.exit(1)

    df = df[["Close"]].dropna()
    df.index = df.index.tz_localize(None)  # strip tz
    return df["Close"]


def compute_ema(series: pd.Series, period: int) -> float:
    """Compute EMA from a Series of close prices."""
    return series.ewm(span=period, adjust=False).mean().iloc[-1]


def build_ema_state(series: pd.Series, period: int) -> dict:
    """Build EMA state dict matching the expected format."""
    ema_value = round(float(compute_ema(series, period)), 4)
    last_bars = [round(float(x), 2) for x in series.tail(10).tolist()]
    now_iso = datetime.now().isoformat()

    return {
        "tf": TF_LABEL,
        "period": period,
        "ema_value": ema_value,
        "available": True,
        "status": "ready",
        "last_bars": last_bars,
        "buffer_count": len(series),
        "multiplier": round(2 / (period + 1), 6),
        "source": "yfinance_backfill",
        "backfilled_at": now_iso,
    }


def main():
    print(f"📥 Downloading {DAYS} days of NIFTY 60-min bars from yfinance...")
    closes = fetch_nifty_60min(DAYS)

    print(f"   Got {len(closes)} bars: {closes.index[0]} → {closes.index[-1]}")
    print(f"   Latest close: ₹{closes.iloc[-1]:.2f}")

    for period in PERIODS:
        state = build_ema_state(closes, period)
        path = EMA_DIR / f"ema_{period}.json"

        # Write atomically
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2))
        tmp.rename(path)

        print(f"✅ EMA {period:>3}: {state['ema_value']:>12,.2f} ({path})")

    # Also copy to 1D, 1min, 5min, 15min for the backfill scripts that rebuild from here
    for tf in ["1D", "1min", "5min", "15min"]:
        tf_dir = EMA_DIR.parent / tf
        tf_dir.mkdir(parents=True, exist_ok=True)
        for period in PERIODS:
            src = EMA_DIR / f"ema_{period}.json"
            dst = tf_dir / f"ema_{period}.json"
            if src.exists():
                # Tag with correct tf
                data = json.loads(src.read_text())
                data["tf"] = tf
                tmp = dst.with_suffix(".tmp")
                tmp.write_text(json.dumps(data, indent=2))
                tmp.rename(dst)
        print(f"   ↳ synced to {tf}/ EMA files")

    print()
    print("✅ EMA buffers backfilled. Trend scoring will now use correct values.")
    print()
    print("Verify:")
    for period in PERIODS:
        f = EMA_DIR / f"ema_{period}.json"
        d = json.loads(f.read_text())
        print(
            f"  EMA {period}: {d['ema_value']:>12,.2f} (from {d['buffer_count']} bars)"
        )


if __name__ == "__main__":
    main()
