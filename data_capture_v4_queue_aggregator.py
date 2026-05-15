#!/usr/bin/env python3
"""
v4 Multi-TF Aggregator with Queue + Log File Fallback

Reads 1-min OHLCV bars from:
1. Redis queue (primary, real-time)
2. Log file (backup, if queue fails)

Aggregates to 5/15/30/60/240/1440-min, writes to market_data_multitf table.
"""

import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
import duckdb
import redis
import json
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class MultiTFAggregatorQueue:
    """Aggregate 1-min OHLCV from queue to multiple timeframes."""

    def __init__(self, duckdb_path: str = None, verbose: bool = True):
        self.verbose = verbose

        if duckdb_path is None:
            # v4 uses SEPARATE database file (no locking conflict with v3)
            duckdb_path = "/home/trading_ceo/python-trader/varaha/data/market_data_multitf.duckdb"

        self.db_path = Path(duckdb_path)
        self.log(f"DuckDB (v4): {self.db_path}")

        # Initialize Redis connection
        self.redis_client = None
        try:
            self.redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
            self.redis_client.ping()
            self.log("✅ Redis queue connected")
        except Exception as e:
            self.log(f"⚠️ Redis connection failed: {e}")

        # Initialize log file path
        self.log_dir = Path("/home/trading_ceo/brahmand/logs")
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Initialize table if needed
        self._ensure_table_exists()

    def log(self, msg: str):
        if self.verbose:
            print(f"[V4] {msg}")

    def _ensure_table_exists(self):
        """Create market_data_multitf table with all indicator batches."""
        try:
            conn = duckdb.connect(str(self.db_path), read_only=False)

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS market_data_multitf (
                    timestamp TEXT,
                    index_name TEXT,
                    timeframe_min INTEGER,

                    open FLOAT,
                    high FLOAT,
                    low FLOAT,
                    close FLOAT,
                    volume FLOAT,

                    -- Batch 1: Gap-Capable Indicators
                    sma20 FLOAT,
                    sma50 FLOAT,
                    sma200 FLOAT,
                    rsi FLOAT,
                    atr FLOAT,
                    macd FLOAT,
                    macd_signal FLOAT,
                    macd_histogram FLOAT,

                    -- Batch 2: Gap-Sensitive Indicators (intraday buildup)
                    adx FLOAT,
                    di_plus FLOAT,
                    di_minus FLOAT,
                    bb_upper FLOAT,
                    bb_middle FLOAT,
                    bb_lower FLOAT,
                    obv FLOAT,
                    cmf FLOAT,
                    cci FLOAT,

                    -- Legacy (deprecated)
                    st_consensus TEXT,

                    PRIMARY KEY (timestamp, index_name, timeframe_min)
                )
                """
            )

            conn.close()
            self.log("✅ Table market_data_multitf ready (Batch 1 + Batch 2 indicators)")

        except Exception as e:
            self.log(f"⚠️ Table creation: {e}")

    def read_from_queue(self, index_name: str = "NIFTY") -> list:
        """Read 1-min bars from Redis queue."""
        bars = []

        if not self.redis_client:
            self.log("⚠️ Redis not available, skipping queue read")
            return bars

        try:
            # Get all bars from queue for this index
            queue_key = f"v3_ohlcv_queue"
            queue_length = self.redis_client.llen(queue_key)

            if queue_length == 0:
                self.log(f"Queue empty (0 bars)")
                return bars

            # Read bars from queue (get all, then filter by index)
            queue_data = self.redis_client.lrange(queue_key, 0, -1)

            for item in queue_data:
                try:
                    bar = json.loads(item)
                    if bar.get("index") == index_name:
                        bars.append(bar)
                except Exception as e:
                    self.log(f"Error parsing queue item: {e}")

            self.log(f"✅ Read {len(bars)} bars from queue")
            return bars

        except Exception as e:
            self.log(f"⚠️ Queue read failed: {e}")
            return bars

    def read_from_log(self, index_name: str = "NIFTY") -> list:
        """Read 1-min bars from log file (fallback)."""
        bars = []

        log_file_path = self.log_dir / f"v3_ohlcv_{index_name}.log"

        if not log_file_path.exists():
            self.log(f"Log file not found: {log_file_path}")
            return bars

        try:
            with open(log_file_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        bar = json.loads(line)
                        if bar.get("index") == index_name:
                            bars.append(bar)
                    except Exception as e:
                        self.log(f"Error parsing log line: {e}")

            self.log(f"✅ Read {len(bars)} bars from log file")
            return bars

        except Exception as e:
            self.log(f"⚠️ Log file read failed: {e}")
            return bars

    def read_bars(self, index_name: str = "NIFTY") -> list:
        """Read 1-min bars from queue (primary) or log file (fallback)."""
        # Try queue first
        bars = self.read_from_queue(index_name)

        # If queue has < 5 bars, fall back to log file
        if len(bars) < 5:
            self.log(f"Queue has {len(bars)} bars (< 5), checking log file for backup...")
            log_bars = self.read_from_log(index_name)

            if len(log_bars) > len(bars):
                self.log(f"Using log file ({len(log_bars)} bars) instead of queue")
                bars = log_bars
            else:
                self.log(f"Queue is more complete, using queue")

        return bars

    def aggregate_bars(self, bars: list, timeframe_min: int) -> list:
        """Aggregate 1-min bars to specific timeframe (rolling windows)."""
        if not bars:
            return []

        if timeframe_min == 1440:
            return self._aggregate_daily_bars(bars)
        else:
            return self._aggregate_intraday_bars(bars, timeframe_min)

    def _aggregate_daily_bars(self, bars: list) -> list:
        """Aggregate to daily bars (rolling throughout trading day)."""
        if not bars:
            return []

        aggregated = []
        current_day = None
        current_bucket = None

        for i, bar in enumerate(bars):
            bar_time = datetime.fromisoformat(bar["timestamp"])
            bar_day = bar_time.date()

            # New trading day - finalize previous day's bar if it exists
            if bar_day != current_day:
                if current_bucket:
                    # Pass all bars up to current for context (gap-capable indicators)
                    agg_bar = self._aggregate_bucket(current_bucket, 1440, all_bars=bars[:i])
                    if agg_bar:
                        aggregated.append(agg_bar)
                current_day = bar_day
                current_bucket = [bar]
            else:
                # Same day - add to current bucket (updates H/L/C)
                current_bucket.append(bar)

        # Finalize last day's bar (still open/in-progress for today)
        if current_bucket:
            agg_bar = self._aggregate_bucket(current_bucket, 1440, all_bars=bars)
            if agg_bar:
                aggregated.append(agg_bar)

        return aggregated

    def _aggregate_intraday_bars(self, bars: list, timeframe_min: int) -> list:
        """Aggregate to intraday bars (5/15/30/60/240 min)."""
        if timeframe_min == 60:
            return self._aggregate_hourly_bars(bars)
        else:
            return self._aggregate_fixed_tf_bars(bars, timeframe_min)

    def _aggregate_hourly_bars(self, bars: list) -> list:
        """Aggregate to hourly bars (rolling throughout each hour)."""
        if not bars:
            return []

        aggregated = []
        current_hour_key = None
        current_bucket = None

        for i, bar in enumerate(bars):
            bar_time = datetime.fromisoformat(bar["timestamp"])
            # Hour key: 2026-05-15 09:00 (start of the hour)
            hour_key = bar_time.replace(minute=0, second=0, microsecond=0)

            # New hour - finalize previous hour's bar if it exists
            if hour_key != current_hour_key:
                if current_bucket:
                    # Pass all bars up to current for context (gap-capable indicators)
                    agg_bar = self._aggregate_bucket(current_bucket, 60, all_bars=bars[:i])
                    if agg_bar:
                        aggregated.append(agg_bar)
                current_hour_key = hour_key
                current_bucket = [bar]
            else:
                # Same hour - add to current bucket (updates H/L/C)
                current_bucket.append(bar)

        # Finalize last hour's bar (still open/in-progress for current hour)
        if current_bucket:
            agg_bar = self._aggregate_bucket(current_bucket, 60, all_bars=bars)
            if agg_bar:
                aggregated.append(agg_bar)

        return aggregated

    def _aggregate_fixed_tf_bars(self, bars: list, timeframe_min: int) -> list:
        """Aggregate to fixed timeframe bars (5/15/30/240 min) with rolling windows."""
        if not bars:
            return []

        aggregated = []
        current_bucket_start = None
        current_bucket = None

        for i, bar in enumerate(bars):
            bar_time = datetime.fromisoformat(bar["timestamp"])

            # Determine which bucket this bar belongs to
            # Find the start of the timeframe bucket (align to market open 9:15)
            market_open = bar_time.replace(hour=9, minute=15, second=0, microsecond=0)
            if bar_time < market_open:
                # Before market open, shouldn't happen but handle gracefully
                bucket_start = bar_time.replace(second=0, microsecond=0)
            else:
                # Minutes elapsed since market open
                minutes_elapsed = int((bar_time - market_open).total_seconds() / 60)
                # Which bucket does this fall into?
                bucket_number = minutes_elapsed // timeframe_min
                bucket_start = market_open + timedelta(minutes=bucket_number * timeframe_min)

            # New bucket - finalize previous bucket if it exists
            if bucket_start != current_bucket_start:
                if current_bucket:
                    # Pass all bars up to current for context (gap-capable indicators)
                    agg_bar = self._aggregate_bucket(current_bucket, timeframe_min, all_bars=bars[:i])
                    if agg_bar:
                        aggregated.append(agg_bar)
                current_bucket_start = bucket_start
                current_bucket = [bar]
            else:
                # Same bucket - add to current bucket (updates H/L/C)
                current_bucket.append(bar)

        # Finalize last bucket (still open/in-progress for current timeframe)
        if current_bucket:
            agg_bar = self._aggregate_bucket(current_bucket, timeframe_min, all_bars=bars)
            if agg_bar:
                aggregated.append(agg_bar)

        return aggregated

    def _aggregate_bucket(self, bars: list, timeframe_min: int, all_bars: list = None) -> dict:
        """Aggregate bucket of bars to one timeframe bar with gap-capable indicators."""
        if not bars:
            return None

        opens = [b["open"] for b in bars]
        highs = [b["high"] for b in bars]
        lows = [b["low"] for b in bars]
        closes = [b["close"] for b in bars]
        volumes = [b["volume"] for b in bars]
        timestamps = [b["timestamp"] for b in bars]

        agg_open = opens[0]
        agg_high = max(highs)
        agg_low = min(lows)
        agg_close = closes[-1]
        agg_volume = sum(volumes)

        # Use all_bars for indicator context (gap-capable needs historical data)
        context_closes = closes if all_bars is None else [b["close"] for b in all_bars]
        context_highs = highs if all_bars is None else [b["high"] for b in all_bars]
        context_lows = lows if all_bars is None else [b["low"] for b in all_bars]

        # Batch 1: Gap-Capable Indicators (calculate from accumulated closes)
        sma20 = self._calculate_sma(context_closes, 20)
        sma50 = self._calculate_sma(context_closes, 50)
        sma200 = self._calculate_sma(context_closes, 200)
        rsi = self._calculate_rsi(context_closes, 14)
        atr = self._calculate_atr(context_highs, context_lows, context_closes, 14)
        macd_result = self._calculate_macd(context_closes)

        # Batch 2: Gap-Sensitive Indicators (need intraday buildup, return None if insufficient)
        adx_result = self._calculate_adx(context_highs, context_lows, context_closes, 14)
        bb_result = self._calculate_bollinger_bands(context_closes, 20)
        obv = self._calculate_obv(context_closes, [b.get("volume", 0) for b in (bars if all_bars is None else all_bars)])
        context_volumes = [b.get("volume", 0) for b in (bars if all_bars is None else all_bars)]
        cmf = self._calculate_cmf(context_highs, context_lows, context_closes, context_volumes, 20)
        cci = self._calculate_cci(context_highs, context_lows, context_closes, 20)

        return {
            "timestamp": timestamps[-1],
            "open": agg_open,
            "high": agg_high,
            "low": agg_low,
            "close": agg_close,
            "volume": agg_volume,
            # Batch 1: Gap-Capable
            "sma20": sma20,
            "sma50": sma50,
            "sma200": sma200,
            "rsi": rsi,
            "atr": atr,
            "macd": macd_result["macd"],
            "macd_signal": macd_result["signal"],
            "macd_histogram": macd_result["histogram"],
            # Batch 2: Gap-Sensitive
            "adx": adx_result["adx"],
            "di_plus": adx_result["di_plus"],
            "di_minus": adx_result["di_minus"],
            "bb_upper": bb_result["bb_upper"],
            "bb_middle": bb_result["bb_middle"],
            "bb_lower": bb_result["bb_lower"],
            "obv": obv,
            "cmf": cmf,
            "cci": cci,
            # Legacy
            "st_consensus": "NEUTRAL",
        }

    def _calculate_adx(self, closes: list, period: int = 14) -> float:
        if len(closes) < period:
            return -1.0

        recent = closes[-period:]
        up_bars = sum(1 for i in range(1, len(recent)) if recent[i] > recent[i - 1])
        trend_strength = abs(up_bars - (period - up_bars)) / period * 100

        if trend_strength > 70:
            return 35.0
        elif trend_strength > 50:
            return 28.0
        elif trend_strength > 30:
            return 22.0
        else:
            return 15.0

    def _calculate_rsi(self, closes: list, period: int = 14) -> float:
        if len(closes) < period:
            return 50.0

        gains = []
        losses = []

        for i in range(1, len(closes)):
            change = closes[i] - closes[i - 1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))

        avg_gain = sum(gains[-period:]) / period if gains else 0
        avg_loss = sum(losses[-period:]) / period if losses else 0

        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        return round(rsi, 1)

    def _calculate_supertrend(self, closes: list, highs: list, lows: list, period: int = 14) -> str:
        if len(closes) < period:
            return "NEUTRAL"

        recent_closes = closes[-period:]
        recent_high = highs[-1] if highs else max(recent_closes)
        recent_low = lows[-1] if lows else min(recent_closes)

        midpoint = (recent_high + recent_low) / 2
        current_close = recent_closes[-1]

        if current_close > midpoint:
            return "BULLISH"
        elif current_close < midpoint:
            return "BEARISH"
        else:
            return "NEUTRAL"

    def _calculate_sma(self, closes: list, period: int) -> float:
        """Calculate Simple Moving Average. Gap-capable (uses all data)."""
        if len(closes) < period:
            return None
        return round(sum(closes[-period:]) / period, 2)

    def _calculate_atr(self, highs: list, lows: list, closes: list, period: int = 14) -> float:
        """Calculate Average True Range. Gap-capable (gap is part of TR)."""
        if len(closes) < 2:
            return None

        trs = []
        for i in range(1, len(closes)):
            high_low = highs[i] - lows[i]
            high_close = abs(highs[i] - closes[i - 1])
            low_close = abs(lows[i] - closes[i - 1])
            tr = max(high_low, high_close, low_close)
            trs.append(tr)

        if len(trs) < period:
            return round(sum(trs) / len(trs), 2) if trs else None

        return round(sum(trs[-period:]) / period, 2)

    def _calculate_macd(self, closes: list, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
        """Calculate MACD. Gap-capable (uses all data)."""
        if len(closes) < slow:
            return {"macd": None, "signal": None, "histogram": None}

        # EMA calculation
        def ema(data, period):
            if len(data) < period:
                return None
            alpha = 2 / (period + 1)
            ema_val = sum(data[:period]) / period
            for val in data[period:]:
                ema_val = val * alpha + ema_val * (1 - alpha)
            return ema_val

        fast_ema = ema(closes, fast)
        slow_ema = ema(closes, slow)

        if fast_ema is None or slow_ema is None:
            return {"macd": None, "signal": None, "histogram": None}

        macd_line = fast_ema - slow_ema

        # Signal line (EMA of MACD)
        # For simplicity, use a simple approximation
        signal_line = macd_line  # Simplified; proper implementation would track MACD history
        histogram = macd_line - signal_line

        return {
            "macd": round(macd_line, 2),
            "signal": round(signal_line, 2),
            "histogram": round(histogram, 2),
        }

    def _calculate_adx(self, highs: list, lows: list, closes: list, period: int = 14) -> dict:
        """Calculate ADX and Directional Indicators. Gap-sensitive (needs continuous buildup)."""
        if len(closes) < period:
            return {"adx": None, "di_plus": None, "di_minus": None}

        # Calculate True Range
        trs = []
        for i in range(1, len(closes)):
            high_low = highs[i] - lows[i]
            high_close = abs(highs[i] - closes[i - 1])
            low_close = abs(lows[i] - closes[i - 1])
            tr = max(high_low, high_close, low_close)
            trs.append(tr)

        # Calculate Directional Movement
        plus_dm = []
        minus_dm = []
        for i in range(1, len(highs)):
            high_diff = highs[i] - highs[i - 1]
            low_diff = lows[i - 1] - lows[i]

            if high_diff > 0 and high_diff > low_diff:
                plus_dm.append(high_diff)
                minus_dm.append(0)
            elif low_diff > 0 and low_diff > high_diff:
                plus_dm.append(0)
                minus_dm.append(low_diff)
            else:
                plus_dm.append(0)
                minus_dm.append(0)

        # Calculate DI+ and DI-
        tr_sum = sum(trs[-period:]) if len(trs) >= period else sum(trs)
        plus_dm_sum = sum(plus_dm[-period:]) if len(plus_dm) >= period else sum(plus_dm)
        minus_dm_sum = sum(minus_dm[-period:]) if len(minus_dm) >= period else sum(minus_dm)

        di_plus = (100 * plus_dm_sum / tr_sum) if tr_sum > 0 else 0
        di_minus = (100 * minus_dm_sum / tr_sum) if tr_sum > 0 else 0

        # Calculate ADX (simplified)
        di_diff = abs(di_plus - di_minus)
        di_sum = di_plus + di_minus
        di_ratio = (100 * di_diff / di_sum) if di_sum > 0 else 0

        return {
            "adx": round(di_ratio, 2),
            "di_plus": round(di_plus, 2),
            "di_minus": round(di_minus, 2),
        }

    def _calculate_bollinger_bands(self, closes: list, period: int = 20, std_dev: float = 2.0) -> dict:
        """Calculate Bollinger Bands. Gap-sensitive (needs period bars)."""
        if len(closes) < period:
            return {"bb_upper": None, "bb_middle": None, "bb_lower": None}

        recent = closes[-period:]
        sma = sum(recent) / period
        variance = sum((x - sma) ** 2 for x in recent) / period
        std = variance ** 0.5

        upper = sma + (std_dev * std)
        lower = sma - (std_dev * std)

        return {
            "bb_upper": round(upper, 2),
            "bb_middle": round(sma, 2),
            "bb_lower": round(lower, 2),
        }

    def _calculate_obv(self, closes: list, volumes: list) -> float:
        """Calculate On-Balance Volume. Gap-sensitive (accumulates intraday)."""
        if len(closes) < 2 or len(volumes) < 2:
            return None

        obv = 0
        for i in range(1, len(closes)):
            if closes[i] > closes[i - 1]:
                obv += volumes[i]
            elif closes[i] < closes[i - 1]:
                obv -= volumes[i]

        return round(obv, 0) if obv != 0 else 0

    def _calculate_cmf(self, highs: list, lows: list, closes: list, volumes: list, period: int = 20) -> float:
        """Calculate Chaikin Money Flow. Gap-sensitive (needs period bars)."""
        if len(closes) < period or len(volumes) < period:
            return None

        mfv_sum = 0  # Money Flow Volume
        vol_sum = 0

        for i in range(len(closes) - period, len(closes)):
            hl_range = highs[i] - lows[i]
            if hl_range == 0:
                mfm = 0
            else:
                mfm = ((closes[i] - lows[i]) - (highs[i] - closes[i])) / hl_range
            mfv_sum += mfm * volumes[i]
            vol_sum += volumes[i]

        cmf = (mfv_sum / vol_sum) if vol_sum > 0 else 0
        return round(cmf, 4)

    def _calculate_cci(self, highs: list, lows: list, closes: list, period: int = 20) -> float:
        """Calculate Commodity Channel Index. Gap-sensitive (needs period bars)."""
        if len(closes) < period:
            return None

        recent_h = highs[-period:]
        recent_l = lows[-period:]
        recent_c = closes[-period:]

        # Typical Price
        tp = [(h + l + c) / 3 for h, l, c in zip(recent_h, recent_l, recent_c)]
        sma_tp = sum(tp) / period
        mean_dev = sum(abs(x - sma_tp) for x in tp) / period

        cci = (tp[-1] - sma_tp) / (0.015 * mean_dev) if mean_dev > 0 else 0
        return round(cci, 2)

    def write_aggregated_bars(self, bars: list, index_name: str, timeframe_min: int):
        """Write aggregated bars to database."""
        if not bars:
            return

        conn = duckdb.connect(str(self.db_path), read_only=False)

        for bar in bars:
            try:
                conn.execute(
                    """
                    INSERT INTO market_data_multitf
                    (timestamp, index_name, timeframe_min, open, high, low, close, volume,
                     sma20, sma50, sma200, rsi, atr, macd, macd_signal, macd_histogram,
                     adx, di_plus, di_minus, bb_upper, bb_middle, bb_lower, obv, cmf, cci, st_consensus)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (timestamp, index_name, timeframe_min) DO UPDATE SET
                        open = EXCLUDED.open,
                        high = EXCLUDED.high,
                        low = EXCLUDED.low,
                        close = EXCLUDED.close,
                        volume = EXCLUDED.volume,
                        sma20 = EXCLUDED.sma20,
                        sma50 = EXCLUDED.sma50,
                        sma200 = EXCLUDED.sma200,
                        rsi = EXCLUDED.rsi,
                        atr = EXCLUDED.atr,
                        macd = EXCLUDED.macd,
                        macd_signal = EXCLUDED.macd_signal,
                        macd_histogram = EXCLUDED.macd_histogram,
                        adx = EXCLUDED.adx,
                        di_plus = EXCLUDED.di_plus,
                        di_minus = EXCLUDED.di_minus,
                        bb_upper = EXCLUDED.bb_upper,
                        bb_middle = EXCLUDED.bb_middle,
                        bb_lower = EXCLUDED.bb_lower,
                        obv = EXCLUDED.obv,
                        cmf = EXCLUDED.cmf,
                        cci = EXCLUDED.cci,
                        st_consensus = EXCLUDED.st_consensus
                    """,
                    (
                        bar["timestamp"],
                        index_name,
                        timeframe_min,
                        bar["open"],
                        bar["high"],
                        bar["low"],
                        bar["close"],
                        bar["volume"],
                        bar["sma20"],
                        bar["sma50"],
                        bar["sma200"],
                        bar["rsi"],
                        bar["atr"],
                        bar["macd"],
                        bar["macd_signal"],
                        bar["macd_histogram"],
                        bar["adx"],
                        bar["di_plus"],
                        bar["di_minus"],
                        bar["bb_upper"],
                        bar["bb_middle"],
                        bar["bb_lower"],
                        bar["obv"],
                        bar["cmf"],
                        bar["cci"],
                        bar["st_consensus"],
                    ),
                )
            except Exception as e:
                self.log(f"Insert error: {e}")

        conn.close()

    def run_all_timeframes(self, index_name: str = "NIFTY"):
        """Aggregate all timeframes for an index."""
        timeframes = [5, 15, 30, 60, 240, 1440]

        self.log(f"Starting aggregation for {index_name}")

        # Read bars from queue or log
        bars = self.read_bars(index_name)

        if not bars:
            self.log("⚠️ No bars to aggregate")
            return

        self.log(f"Aggregating {len(bars)} 1-min bars")

        for tf in timeframes:
            agg_bars = self.aggregate_bars(bars, tf)
            self.write_aggregated_bars(agg_bars, index_name, tf)
            self.log(f"  {tf}-min: {len(agg_bars)} bars")

        self.log("Aggregation complete")


def main():
    import time
    from datetime import datetime

    aggregator = MultiTFAggregatorQueue(verbose=True)

    print("\n[V4] Starting continuous aggregation loop...")
    print("[V4] Aggregating every 60 seconds (9:15-15:30 IST)")

    while True:
        # Check if market hours (9:15 AM - 3:30 PM, weekdays only)
        now = datetime.now()
        hour = now.hour
        minute = now.minute
        weekday = now.weekday()

        # Stop after market hours
        if weekday >= 5 or (hour > 15) or (hour == 15 and minute >= 31):
            print(f"\n[V4] Market closed, exiting at {now.strftime('%H:%M:%S')}")
            break

        # Skip before market opens
        if hour < 9 or (hour == 9 and minute < 15):
            print(f"[V4] Market not open yet ({now.strftime('%H:%M:%S')}), waiting...")
            time.sleep(60)
            continue

        # Aggregate all timeframes for both indices
        aggregator.run_all_timeframes(index_name="NIFTY")
        aggregator.run_all_timeframes(index_name="SENSEX")

        print(f"[V4] Aggregation complete at {now.strftime('%H:%M:%S')}")

        # Wait 60 seconds before next aggregation
        time.sleep(60)


if __name__ == "__main__":
    main()
