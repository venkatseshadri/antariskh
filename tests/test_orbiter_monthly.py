"""Gate1 regression tests for orbiter_monthly.py (HYDROGEN+ T3, NEUTRON+ T4).

Not full module coverage — this file exists because orbiter_monthly.py had
zero tests before 2026-07-18, and the structural pre-open window added that
day (see orbiter_weekly.py's gate1_regime for the full rationale) is a
real-money-adjacent behavior change worth locking down.
"""

import orbiter_monthly as om


def _row(adx=15.0, cpr_width_pct=0.30, cpr_width=None, bb_width=0.02, timestamp=None):
    row = {
        "adx": adx,
        "cpr_width_pct": cpr_width_pct,
        "cpr_width": cpr_width,
        "bb_width": bb_width,
    }
    if timestamp is not None:
        row["timestamp"] = timestamp
    return row


def test_gate1_passes_low_adx_wide_cpr():
    g = om.gate1_regime(_row(adx=18, cpr_width_pct=0.35, timestamp="2026-07-20T10:30:00"))
    assert g.passed and g.gate == "GATE1_REGIME"


def test_gate1_blocks_high_adx():
    g = om.gate1_regime(_row(adx=30.0, cpr_width_pct=0.30, timestamp="2026-07-20T10:30:00"))
    assert not g.passed and "ADX" in g.reason


def test_gate1_blocks_narrow_cpr():
    g = om.gate1_regime(_row(adx=15.0, cpr_width_pct=0.05, timestamp="2026-07-20T10:30:00"))
    assert not g.passed


def test_gate1_structural_window_passes_on_wide_cpr_despite_elevated_adx():
    g = om.gate1_regime(_row(adx=35.0, cpr_width_pct=0.30, timestamp="2026-07-20T09:20:00"))
    assert g.passed and g.details.get("structural_window")


def test_gate1_structural_window_blocks_extreme_adx_even_pre_warmup():
    """Independent review (2026-07-19): a sustained real trend at open can
    push ADX past 60 immediately and keep it there all day — CPR-alone
    would wrongly let that through."""
    g = om.gate1_regime(_row(adx=75.0, cpr_width_pct=0.30, timestamp="2026-07-20T09:20:00"))
    assert not g.passed and g.details.get("structural_window")
    assert "ADX" in g.reason


def test_gate1_structural_window_halts_on_narrow_cpr_regardless_of_adx():
    g = om.gate1_regime(_row(adx=5.0, cpr_width_pct=0.05, timestamp="2026-07-20T09:20:00"))
    assert not g.passed and "HALT" in g.reason


def test_gate1_structural_window_ends_at_configured_cutoff():
    """At/after 09:45 (2x14-bar Wilder warm-up, not the original 09:30)."""
    g = om.gate1_regime(_row(adx=60.0, cpr_width_pct=0.30, timestamp="2026-07-20T09:45:00"))
    assert not g.passed and "structural_window" not in g.details
    assert "ADX" in g.reason


def test_gate1_missing_timestamp_does_not_enter_structural_window():
    g = om.gate1_regime(_row(adx=60.0, cpr_width_pct=0.30, timestamp=None))
    assert not g.passed and "structural_window" not in g.details
