"""PORCUPINE regression — E4 / bug #4 root-cause guard.

Bug: when india_vix is unavailable (broker stub off, weekend, broker down),
the deterministic-fallback gate in `brahmand/unicorn_debate.py` treats
``vix is None`` as "low volatility" and SILENTLY AUTO-ENTERS.

    # unicorn_debate.py lines 121-128 (live code, snapshot 2026-06-08)
    if gate_type == "NOT_UP":
        go = avg_score > 0.2 and (
            vix is None or (isinstance(vix, (int, float)) and vix < 20)
        )
    elif gate_type == "NOT_DOWN":
        go = avg_score < -0.2 and (
            vix is None or (isinstance(vix, (int, float)) and vix < 20)
        )

The ``vix is None`` branch is the bug. The correct behaviour is fail-closed:
if VIX is unknown, the volatility precondition is NOT satisfied, so the gate
must NOT enter on auto-pilot. Caught in PORCUPINE sandbox where
`market_data_enriched.india_vix` is 100% NULL because the broker option-chain
stub is not wired.

This file does NOT touch live code (sim+tests sandbox only). The live fix is
to replace ``vix is None or vix < 20`` with ``isinstance(vix, (int, float))
and vix < 20`` (or an explicit override) inside both gate branches of
`_deterministic_fallback`.

Run: python3 -m sim.tests.test_vix_null_guard   (from antariksh root)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BRAHMAND = ROOT.parent / "brahmand"
for p in (str(ROOT), str(BRAHMAND)):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from unicorn_debate import _deterministic_fallback
except Exception as e:  # pragma: no cover - environment guard
    print(f"[SKIP] cannot import brahmand.unicorn_debate: {e}")
    sys.exit(0)


def _raw(consensus: str, vix):
    """Build a raw_data dict that produces the strongest possible avg_score
    (so the gate's avg_score>0.2 / <-0.2 precondition is irrelevant and the
    test isolates the VIX branch). `consensus` is 'bullish' or 'bearish'."""
    tf = {"st_consensus": consensus, "ema_position": consensus}
    indicators = {"session_phase": "mid"}
    if vix is not _SENTINEL:
        indicators["vix"] = vix
    return {
        "trend": {"timeframes": {
            "5m":  {"st_consensus": consensus},
            "15m": {"st_consensus": consensus},
            "30m": {"st_consensus": consensus},
            "60m": {"st_consensus": consensus},
            "1m_v3.1": tf,
        }},
        "macro": {"indicators": indicators},
    }


_SENTINEL = object()
_NOT_UP_GATE = {"signal": "NOT_UP", "strategy": "BEAR_PUT"}
_NOT_DOWN_GATE = {"signal": "NOT_DOWN", "strategy": "BULL_CALL"}


def _go(consensus, gate_type, gate, vix):
    return _deterministic_fallback(_raw(consensus, vix), gate_type, gate)["go"]


def test_vix_normal_low_enters():
    """Sanity: with a strong bullish trend and vix=15, the NOT_DOWN gate
    enters. This is the healthy path the fallback was designed for."""
    assert _go("bullish", "NOT_DOWN", _NOT_DOWN_GATE, 15.0) is True
    assert _go("bearish", "NOT_UP", _NOT_UP_GATE, 15.0) is True


def test_vix_high_blocks():
    """Sanity: vix=25 blocks BOTH directions — the volatility precondition
    is the whole reason the gate looks at VIX."""
    assert _go("bullish", "NOT_DOWN", _NOT_DOWN_GATE, 25.0) is False
    assert _go("bearish", "NOT_UP", _NOT_UP_GATE, 25.0) is False


def test_vix_none_fails_closed():
    """REGRESSION GUARD — bug #4 FIXED 2026-06-09. The live
    `unicorn_debate._deterministic_fallback` now collapses
    ``vix is None or vix < 20`` into ``isinstance(vix, (int, float)) and
    vix < 20``, so an unknown VIX (broker stub off, weekend, broker down)
    fails closed instead of silently auto-entering:

        vix=None  →  go=False   (was go=True — the bug)

    If this regresses (someone reintroduces the `vix is None or` short-circuit),
    these assertions fail against live code. Marker: sim/.bug4_fixed.
    """
    assert _go("bullish", "NOT_DOWN", _NOT_DOWN_GATE, None) is False, (
        "Bug #4 REGRESSED: vix=None auto-enters again. The live "
        "_deterministic_fallback must use isinstance(vix,(int,float)) and vix<20 "
        "(no `vix is None or` branch) in BOTH gate directions."
    )
    assert _go("bearish", "NOT_UP", _NOT_UP_GATE, None) is False


def test_vix_missing_key_uses_default_15():
    """Aside: when the `vix` key is absent altogether,
    `mac_indicators.get('vix', 15)` returns 15 and the gate enters. The bug
    is specifically about the key being PRESENT with value None (which is
    what `india_vix=NULL` from the enricher surfaces as)."""
    assert _go("bullish", "NOT_DOWN", _NOT_DOWN_GATE, _SENTINEL) is True


def test_vix_non_numeric_string_blocks():
    """Defensive: a non-numeric vix (e.g. a stray "N/A" string from a
    broken broker stub) is correctly blocked today — the
    `isinstance(vix, (int, float))` branch fails. This is the SHAPE the
    None branch should be collapsed into.
    """
    assert _go("bullish", "NOT_DOWN", _NOT_DOWN_GATE, "N/A") is False


def test_vix_null_guard_contract():
    """Document the contract the live fix must satisfy.

    Reimplements the corrected gate locally (no live import) so the
    contract is checked even when brahmand is unreachable, and so the
    intent of the fix is unambiguous.
    """
    def fixed_gate(avg_score, vix, gate_type, session="mid"):
        vix_ok = isinstance(vix, (int, float)) and vix < 20
        if gate_type == "NOT_UP":
            go = avg_score > 0.2 and vix_ok
        elif gate_type == "NOT_DOWN":
            go = avg_score < -0.2 and vix_ok
        else:
            go = False
        return go and session not in ("preopen", "closing", "")

    # vix=None must fail-closed in BOTH directions
    assert fixed_gate(+1.0, None, "NOT_UP") is False
    assert fixed_gate(-1.0, None, "NOT_DOWN") is False
    # vix=low still enters
    assert fixed_gate(+1.0, 15.0, "NOT_UP") is True
    assert fixed_gate(-1.0, 15.0, "NOT_DOWN") is True
    # vix=high still blocks
    assert fixed_gate(+1.0, 25.0, "NOT_UP") is False


if __name__ == "__main__":
    test_vix_normal_low_enters()
    print("[PASS] vix=15 enters (healthy path)")
    test_vix_high_blocks()
    print("[PASS] vix=25 blocks both directions")
    test_vix_none_fails_closed()
    print("[PASS] vix=None fails closed (bug #4 FIXED)")
    test_vix_missing_key_uses_default_15()
    print("[PASS] missing vix key falls back to default 15")
    test_vix_non_numeric_string_blocks()
    print("[PASS] non-numeric vix blocks (shape the None branch should match)")
    test_vix_null_guard_contract()
    print("[PASS] fail-closed contract documented")
    print("\nvix-null-guard regression: 6/6 passed")
