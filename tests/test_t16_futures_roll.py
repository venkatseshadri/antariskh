"""T16: Futures auto-roll — nearest unexpired contract, T-2 roll, fail-closed.

Run: python3 -m pytest tests/test_t16_futures_roll.py -q
"""

from datetime import date
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.token_resolver import TokenResolver

_R = TokenResolver()


def test_resolves_nearest_future():
    c = _R.resolve_nearest_future("NIFTY", "NFO")
    assert "JUN" in c["tsym"].upper() or "JUL" in c["tsym"].upper()
    assert c["expiry"] >= date.today()


def test_roll_at_t_minus_2_to_july():
    c = _R.resolve_nearest_future("NIFTY", "NFO", _today=date(2026, 6, 28))
    assert c["tsym"] == "NIFTY28JUL26F", (
        f"Expected Jul roll at T-2, got {c['tsym']} (exp={c['expiry']})"
    )


def test_roll_at_t_minus_1():
    c = _R.resolve_nearest_future("NIFTY", "NFO", _today=date(2026, 6, 29))
    assert c["tsym"] == "NIFTY28JUL26F"


def test_roll_on_expiry_day():
    c = _R.resolve_nearest_future("NIFTY", "NFO", _today=date(2026, 6, 30))
    assert c["tsym"] == "NIFTY28JUL26F"


def test_no_roll_on_t_minus_3():
    c = _R.resolve_nearest_future("NIFTY", "NFO", _today=date(2026, 6, 27))
    assert c["tsym"] == "NIFTY30JUN26F", f"Should stay on Jun at T-3, got {c['tsym']}"


def test_expired_root_raises():
    try:
        _R.resolve_nearest_future("GOLDTEN", "MCX", _today=date(2026, 12, 1))
        assert False, "Should have raised for expired-only root"
    except ValueError as e:
        assert "unexpired" in str(e).lower()


def test_no_data_for_root_raises():
    try:
        _R.resolve_nearest_future("NONEXISTENT", "NFO")
        assert False, "Should have raised for missing root"
    except ValueError:
        pass


def test_mcx_futures_resolve():
    c = _R.resolve_nearest_future("SILVERMIC", "MCX")
    assert c["tsym"] == "SILVERMIC30JUN26"
    assert c["expiry"] == date(2026, 6, 30)


def test_mcx_roll_at_t_minus_2():
    # SILVERMIC skips July — nearest successors are Jun 30 → Aug 31
    c = _R.resolve_nearest_future("SILVERMIC", "MCX", _today=date(2026, 6, 28))
    assert c["tsym"] == "SILVERMIC31AUG26", (
        f"Expected Aug (no Jul contract), got {c['tsym']}"
    )


def test_sensex_futures_roll():
    c = _R.resolve_nearest_future("BSXFUT", "BFO", _today=date(2026, 6, 23))
    assert c["tsym"] == "SENSEX26JULFUT", (
        f"Expected Jul roll at T-2 (Jun 25 expiry), got {c['tsym']}"
    )
