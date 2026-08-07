"""IndicatorBuffer — rolling candle buffer for enrichment computations.

Lifted from varaha/data_capture_combined.py IndicatorBuffer class.
Pure data structure — no DB, no Redis, no broker calls.
"""

import math
from collections import deque
from datetime import datetime
from typing import Dict, Optional

import numpy as np


class IndicatorBuffer:
    def __init__(self, maxlen: int = 200, max_gap_minutes: float = 2.0):
        self.buf = deque(maxlen=maxlen)
        self._cum_vol = 0.0
        self._cum_vp = 0.0
        self.max_gap_minutes = max_gap_minutes

    def append(self, o: float, h: float, l: float, c: float, v: float = 0, ts: str = None):
        self.buf.append({"open": o, "high": h, "low": l, "close": c, "volume": v, "ts": ts})
        self._cum_vol += v
        self._cum_vp += c * v

    def has_min_bars(self, n: int) -> bool:
        return len(self.buf) >= n

    def latest_contiguous_candles(self, max_gap_minutes: float = None) -> list:
        """The trailing run of buffer entries that are genuinely close together in
        real time — discards everything before the most recent gap (session
        boundary, missed data, or an entry with no timestamp at all).

        Any consumer that slices `self.buf` directly for a SHORT, recency-sensitive
        window (multi-timeframe SuperTrend aggregation, SMC/structure detection) must
        go through this instead, or risk silently blending a stale prior-session tail
        into "current" data — confirmed live 2026-07-07: at market open, both the
        15-min SuperTrend consensus and the 10-bar structure_type window were built
        from a mix of yesterday's last few bars plus the first minute(s) of today,
        reporting yesterday's trend/structure as if freshly computed. `compute_
        indicators()`'s own EMA/RSI/ADX/ATR/VWAP are NOT changed by this — those are
        intentionally continuous rolling indicators, not session-relative.

        max_gap_minutes defaults to the buffer's own self.max_gap_minutes (set at
        construction) when not explicitly overridden by the caller."""
        if max_gap_minutes is None:
            max_gap_minutes = self.max_gap_minutes
        candles = list(self.buf)
        if not candles:
            return candles
        start = 0
        for i in range(1, len(candles)):
            prev, cur = candles[i - 1], candles[i]
            gap_ok = False
            if prev.get("ts") and cur.get("ts"):
                try:
                    t1 = datetime.fromisoformat(prev["ts"])
                    t2 = datetime.fromisoformat(cur["ts"])
                    gap_ok = 0 <= (t2 - t1).total_seconds() <= max_gap_minutes * 60
                except (ValueError, TypeError):
                    gap_ok = False
            if not gap_ok:
                start = i
        return candles[start:]

    def compute_indicators(self) -> Dict:
        if len(self.buf) < 5:
            return {
                "ema_5": None,
                "ema_20": None,
                "ema_50": None,
                "supertrend_value": None,
                "supertrend_direction": None,
                "adx": None,
                "atr": None,
                "rsi": None,
                "vwap": None,
                "bb_pct_b": None,
                "bb_width": None,
                "ema20_slope": None,
            }

        closes = np.array([b["close"] for b in self.buf], dtype=float)
        highs = np.array([b["high"] for b in self.buf], dtype=float)
        lows = np.array([b["low"] for b in self.buf], dtype=float)

        ema_5 = self._ema(closes, 5)
        ema_20 = self._ema(closes, 20)
        ema_50 = self._ema(closes, 50)

        atr = self._atr(highs, lows, closes, 14)
        rsi = self._rsi(closes, 14)
        adx = self._adx(highs, lows, closes, 14)

        vwap = round(self._cum_vp / self._cum_vol, 2) if self._cum_vol > 0 else None

        bb_mid = ema_20
        bb_std = float(np.std(closes[-20:])) if len(closes) >= 20 else 0
        bb_upper = bb_mid + 2 * bb_std if bb_mid else None
        bb_lower = bb_mid - 2 * bb_std if bb_mid else None
        bb_pct_b = None
        bb_width = None
        if bb_upper and bb_lower and (bb_upper - bb_lower) > 0:
            bb_pct_b = round((closes[-1] - bb_lower) / (bb_upper - bb_lower), 4)
            bb_width = round((bb_upper - bb_lower) / bb_mid, 4) if bb_mid else None

        ema20_slope = None
        if len(closes) >= 22:
            prev_ema20 = self._ema(closes[:-2], 20)
            if prev_ema20 and ema_20:
                ema20_slope = round(ema_20 - prev_ema20, 4)

        st_val, st_dir = self._supertrend(highs, lows, closes, 10, 3.0)

        return {
            "ema_5": ema_5,
            "ema_20": ema_20,
            "ema_50": ema_50,
            "supertrend_value": st_val,
            "supertrend_direction": st_dir,
            "adx": adx,
            "atr": atr,
            "rsi": rsi,
            "vwap": vwap,
            "bb_pct_b": bb_pct_b,
            "bb_width": bb_width,
            "ema20_slope": ema20_slope,
        }

    def _ema(self, data: np.ndarray, period: int) -> Optional[float]:
        if len(data) < period:
            return None
        multiplier = 2.0 / (period + 1)
        ema = float(np.mean(data[:period]))
        for val in data[period:]:
            ema = (val - ema) * multiplier + ema
        return round(ema, 2)

    def _atr(self, highs, lows, closes, period: int) -> Optional[float]:
        if len(closes) < period + 1:
            return None
        tr = np.zeros(len(closes))
        tr[0] = highs[0] - lows[0]
        for i in range(1, len(closes)):
            tr[i] = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
        atr = float(np.mean(tr[-period:]))
        return round(atr, 2)

    def _rsi(self, closes: np.ndarray, period: int) -> Optional[float]:
        if len(closes) < period + 1:
            return None
        deltas = np.diff(closes[-(period + 1) :])
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = float(np.mean(gains))
        avg_loss = float(np.mean(losses))
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return round(100 - (100 / (1 + rs)), 2)

    def _adx(self, highs, lows, closes, period: int) -> Optional[float]:
        """True Wilder ADX(period, period) — matches the standard "ADX 14 14"
        convention (e.g. Zerodha/TradingView): DI period AND a second
        smoothing pass over the DX series itself. A single-pass DX snapshot
        (the previous implementation here) is NOT ADX — it's noisy and can
        legitimately jump 40+ points in one bar, which real Wilder-smoothed
        ADX physically cannot do (each new DX only contributes 1/period
        weight). Recomputes the full cascade from the buffer every call
        (stateless, like the other indicators here) rather than persisting
        EMA state across process restarts — the buffer already carries
        `maxlen` bars of warmup history, which is enough for the smoothing
        to have converged well before the values reported here are read."""
        n = len(closes)
        if n < period * 3 + 1:
            return None
        plus_dm = np.zeros(n)
        minus_dm = np.zeros(n)
        tr = np.zeros(n)
        for i in range(1, n):
            up = highs[i] - highs[i - 1]
            down = lows[i - 1] - lows[i]
            plus_dm[i] = up if (up > down and up > 0) else 0
            minus_dm[i] = down if (down > up and down > 0) else 0
            tr[i] = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )

        # Stage 1: Wilder-smooth TR/+DM/-DM (RMA), seeded by a plain sum
        # over the first `period` bars, then recursive thereafter.
        tr_smooth = float(np.sum(tr[1 : period + 1]))
        plus_smooth = float(np.sum(plus_dm[1 : period + 1]))
        minus_smooth = float(np.sum(minus_dm[1 : period + 1]))

        dx_list = []
        for i in range(period + 1, n):
            tr_smooth = tr_smooth - tr_smooth / period + tr[i]
            plus_smooth = plus_smooth - plus_smooth / period + plus_dm[i]
            minus_smooth = minus_smooth - minus_smooth / period + minus_dm[i]
            if tr_smooth == 0:
                continue
            plus_di = 100 * plus_smooth / tr_smooth
            minus_di = 100 * minus_smooth / tr_smooth
            di_sum = plus_di + minus_di
            if di_sum == 0:
                continue
            dx_list.append(abs(plus_di - minus_di) / di_sum * 100)

        if len(dx_list) < period:
            return None

        # Stage 2: Wilder-smooth DX itself into ADX (the second "14").
        adx = float(np.mean(dx_list[:period]))
        for dx in dx_list[period:]:
            adx = (adx * (period - 1) + dx) / period

        return round(adx, 2)

    def _supertrend(self, highs, lows, closes, period=10, multiplier=3.0):
        if len(closes) < period:
            return None, None
        atr_vals = np.zeros(len(closes))
        tr = np.zeros(len(closes))
        tr[0] = highs[0] - lows[0]
        for i in range(1, len(closes)):
            tr[i] = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
        atr_vals[:period] = np.mean(tr[:period])
        for i in range(period, len(tr)):
            atr_vals[i] = (atr_vals[i - 1] * (period - 1) + tr[i]) / period

        hl2 = (highs + lows) / 2.0
        basic_ub = hl2 + multiplier * atr_vals
        basic_lb = hl2 - multiplier * atr_vals
        final_ub = np.copy(basic_ub)
        final_lb = np.copy(basic_lb)
        for i in range(1, len(closes)):
            if basic_ub[i] < final_ub[i - 1] or closes[i - 1] > final_ub[i - 1]:
                final_ub[i] = basic_ub[i]
            else:
                final_ub[i] = final_ub[i - 1]
            if basic_lb[i] > final_lb[i - 1] or closes[i - 1] < final_lb[i - 1]:
                final_lb[i] = basic_lb[i]
            else:
                final_lb[i] = final_lb[i - 1]

        st = np.zeros(len(closes))
        direction = np.zeros(len(closes), dtype=int)
        st[0] = final_ub[0]
        direction[0] = -1
        for i in range(1, len(closes)):
            if st[i - 1] == final_ub[i - 1]:
                st[i] = final_ub[i] if closes[i] <= final_ub[i] else final_lb[i]
                direction[i] = -1 if closes[i] <= final_ub[i] else 1
            else:
                st[i] = final_lb[i] if closes[i] >= final_lb[i] else final_ub[i]
                direction[i] = 1 if closes[i] >= final_lb[i] else -1

        val = round(float(st[-1]), 2) if not np.isnan(st[-1]) else None
        d = "bullish" if direction[-1] > 0 else "bearish"
        return val, d
