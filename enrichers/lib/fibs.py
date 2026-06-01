"""Fibonacci retracement levels — pure function, no DB."""

from typing import Dict, Optional


def compute_fibs(
    prev_day_high: Optional[float],
    prev_day_low: Optional[float],
) -> Dict:
    if not prev_day_high or not prev_day_low:
        return {
            "fib_0": None,
            "fib_236": None,
            "fib_382": None,
            "fib_50": None,
            "fib_618": None,
            "fib_786": None,
            "fib_100": None,
        }
    rng = prev_day_high - prev_day_low
    return {
        "fib_0": prev_day_low,
        "fib_236": round(prev_day_low + 0.236 * rng, 2),
        "fib_382": round(prev_day_low + 0.382 * rng, 2),
        "fib_50": round(prev_day_low + 0.5 * rng, 2),
        "fib_618": round(prev_day_low + 0.618 * rng, 2),
        "fib_786": round(prev_day_low + 0.786 * rng, 2),
        "fib_100": prev_day_high,
    }
