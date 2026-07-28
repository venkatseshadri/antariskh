"""Regression: buffer consumers (multi-timeframe SuperTrend, SMC/structure) must not
bridge a session gap into a fabricated "current" reading.

Found live 2026-07-07: `st_15min_direction` at 2026-07-07T09:15:00 (today's FIRST
bar) was identical to 2026-07-06T15:28:00 (yesterday's LAST bar) — because
`_aggregate_to_timeframe()` grouped buffer entries by raw list position, with no
timestamp/gap awareness at all, so a "15-minute chunk" could silently span an
18-hour overnight gap. ATOM's regime engine (highest-weighted "Trend" family) trusted
that stale value as if it were fresh, and opened a real (paper) trade 1-2 minutes
after market open based on it. `smc.py`'s structure_type (HH/HL/LH/LL) had the same
class of bug (10-bar window sliced from `buf.buf` with no gap awareness), consistent
with the wild HH/MIXED/HH/HH/LL flips observed live in the same window.

Fix: `IndicatorBuffer.latest_contiguous_candles()` — shared gap-detection, used by
both consumers instead of each duplicating (or lacking) their own.
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enrichers.lib.buffer import IndicatorBuffer
from enrichers.lib.smc import compute_smc_indicators
from enrichers.lib.supertrend import _aggregate_to_timeframe, compute_multiframe_supertrend


def _fill_contiguous(buf, start_ts, n, base_price=100.0):
    """n consecutive 1-min bars starting at start_ts, mildly trending up."""
    t = datetime.fromisoformat(start_ts)
    for i in range(n):
        price = base_price + i * 0.5
        buf.append(price, price + 0.5, price - 0.5, price, 1000, ts=(t + timedelta(minutes=i)).isoformat())


# ---- IndicatorBuffer.latest_contiguous_candles() -- the shared fix -------------

def test_latest_contiguous_candles_no_gap_returns_everything():
    buf = IndicatorBuffer(maxlen=200)
    _fill_contiguous(buf, "2026-07-07T09:15:00", 10)
    assert len(buf.latest_contiguous_candles()) == 10


def test_latest_contiguous_candles_discards_before_the_last_gap():
    buf = IndicatorBuffer(maxlen=200)
    _fill_contiguous(buf, "2026-07-06T13:29:00", 199)   # yesterday
    _fill_contiguous(buf, "2026-07-07T09:15:00", 1)      # today, 18h later
    result = buf.latest_contiguous_candles()
    assert len(result) == 1   # only today's bar survives


def test_latest_contiguous_candles_missing_timestamp_is_a_gap():
    buf = IndicatorBuffer(maxlen=200)
    buf.append(100, 101, 99, 100, 1000, ts=None)
    buf.append(101, 102, 100, 101, 1000, ts="2026-07-07T09:16:00")
    assert len(buf.latest_contiguous_candles()) == 1


# ---- SuperTrend consensus -------------------------------------------------------

def test_contiguous_candles_aggregate_normally():
    buf = IndicatorBuffer(maxlen=200)
    _fill_contiguous(buf, "2026-07-07T09:15:00", 20)
    opens, highs, lows, closes = _aggregate_to_timeframe(buf, 5)
    assert closes is not None
    assert len(closes) == 4   # 20 contiguous 1-min bars -> 4 clean 5-min chunks


def test_overnight_gap_is_not_bridged():
    buf = IndicatorBuffer(maxlen=200)
    _fill_contiguous(buf, "2026-07-06T15:14:00", 14)   # yesterday's last 14 minutes
    _fill_contiguous(buf, "2026-07-07T09:15:00", 1)     # today's first bar, 18h later
    opens, highs, lows, closes = _aggregate_to_timeframe(buf, 15)
    assert closes is None


def test_consensus_is_none_at_session_start_not_stale_yesterday():
    """The literal reproduction of what was observed live: at the first bar of a new
    session, st_15min_direction must be None (insufficient real data), never
    yesterday's leftover direction."""
    buf = IndicatorBuffer(maxlen=200)
    _fill_contiguous(buf, "2026-07-06T13:29:00", 199, base_price=200.0)   # yesterday
    _fill_contiguous(buf, "2026-07-07T09:15:00", 1, base_price=100.0)      # today's open
    result = compute_multiframe_supertrend(buf)
    assert result["st_15min_direction"] is None
    assert result["st_5min_direction"] is None
    assert result["st_consensus"] is None


def test_consensus_recovers_once_enough_of_todays_own_bars_exist():
    # _st_from_bars needs `period` (10) AGGREGATED closes, i.e. 10*5=50 real 1-min
    # bars for the 5-min read -- 60 gives a clean margin (12 five-min chunks).
    buf = IndicatorBuffer(maxlen=200)
    _fill_contiguous(buf, "2026-07-06T13:29:00", 199, base_price=200.0)   # yesterday
    _fill_contiguous(buf, "2026-07-07T09:15:00", 60, base_price=100.0)     # 60 min into today
    result = compute_multiframe_supertrend(buf)
    assert result["st_5min_direction"] is not None


# ---- SMC / structure_type -------------------------------------------------------

def test_structure_type_is_none_at_session_start_not_stale_yesterday():
    """Same bug class as SuperTrend, different consumer: structure_type's 10-bar
    window must not blend yesterday's close into today's open."""
    buf = IndicatorBuffer(maxlen=200)
    _fill_contiguous(buf, "2026-07-06T13:29:00", 199, base_price=200.0)   # yesterday
    _fill_contiguous(buf, "2026-07-07T09:15:00", 1, base_price=100.0)      # today's open
    result = compute_smc_indicators(buf)
    assert result["structure_type"] is None   # only 1 real bar since the gap -- insufficient
