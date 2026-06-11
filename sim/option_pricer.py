"""PORCUPINE toy option pricer — maps a spot level to an option mark so the
path-driver can re-mark a trade's legs as the underlying moves through a scripted
intraday path.

This is NOT Black-Scholes. It only needs the right *sign and shape* to exercise
the deterministic exit logic in position_manager.run_bridge:
  • a sold leg's mark must RISE on an adverse spot move (→ SL) and FALL on a
    favourable one (→ TP),
  • extrinsic value must decay toward ~0 at the cash close (→ theta / EOD),
  • marks must be deterministic (no RNG) so scenarios are reproducible.

Model: ltp = intrinsic + extrinsic
  intrinsic = max(0, spot-strike)  (CE)  |  max(0, strike-spot)  (PE)
  extrinsic = atm_premium · tent(|spot-strike|/width) · t_frac
where tent(x)=max(0, 1-x) is a linear decay to 0 at `width` points OTM/ITM and
t_frac∈[0,1] is the fraction of the session still remaining (1 at open, 0 close).
"""
from __future__ import annotations

# Session clock (IST), used to derive the remaining-time fraction for theta.
_OPEN_MIN = 9 * 60 + 15   # 09:15
_CLOSE_MIN = 15 * 60 + 30  # 15:30
_SESSION_SPAN = _CLOSE_MIN - _OPEN_MIN  # 375 minutes


def time_fraction(hhmm: str) -> float:
    """Fraction of the trading session still remaining at HH:MM (1.0 at the open,
    0.0 at/after the close). Clamped to [0, 1]."""
    h, m = hhmm.split(":")
    mins = int(h) * 60 + int(m)
    frac = (_CLOSE_MIN - mins) / _SESSION_SPAN
    return max(0.0, min(1.0, frac))


def option_ltp(spot: float, strike: float, opt_type: str, t_frac: float,
               *, atm_premium: float = 120.0, width: float = 400.0) -> float:
    """Toy option mark. See module docstring. `t_frac` from time_fraction()."""
    ot = (opt_type or "").upper()
    intrinsic = max(0.0, spot - strike) if ot == "CE" else max(0.0, strike - spot)
    moneyness = abs(spot - strike)
    extrinsic = atm_premium * max(0.0, 1.0 - moneyness / width) * max(0.0, min(1.0, t_frac))
    return round(intrinsic + extrinsic, 2)
