"""PORCUPINE intraday scenario catalogue — scripted market days + the trade the
system SHOULD take. Each spec drives sim/scenario_candles.generate() (and, once the
timed runner lands, asserts the `expect` action timeline against what the system
actually did).

Spec shape:
    prev_close, vix, instrument
    path:   [{t:'HH:MM', spot:<target>}]   waypoints (see scenario_candles for targets)
    expect: [{by:'HH:MM', action, ...}]    the hypothesis the harness verifies
    regime: human note of the regime each scenario should produce

Decision logic these expectations are grounded in:
  ADX<25→sideways→IRON_FLY; ADX≥25 + direction→credit spread.
  NOT_UP go needs bearish trend; NOT_DOWN go needs bullish; BOTH go = sideways→iron fly.
  VIX≥20 blocks; VIX None fails closed; VIX>18 = "caution".
  Guards: single-position, MAX_TRADES=4/day, 15-min cooldown, EOD square-off 15:30.
"""

PREV = 23250  # representative NIFTY prev close

SCENARIOS = {
    # ── 1. Directional trends → credit spread in the trend direction ──
    "trend_up_clean": {
        "prev_close": PREV, "vix": 13, "instrument": "NIFTY",
        "regime": "ADX≥25, bullish all session → NOT_DOWN",
        "path": [{"t": "09:15", "spot": "+10pts"}, {"t": "11:00", "spot": "+0.8%"},
                 {"t": "15:25", "spot": "+1.4%"}],
        "expect": [{"by": "10:30", "action": "ENTER", "strategy": "PUT_SPREAD", "signal": "NOT_DOWN"},
                   {"by": "15:30", "action": "CLOSE_ALL", "reason": "EOD"}],
    },
    "trend_down_clean": {
        "prev_close": PREV, "vix": 14, "instrument": "NIFTY",
        "regime": "ADX≥25, bearish all session → NOT_UP",
        "path": [{"t": "09:15", "spot": "-8pts"}, {"t": "11:00", "spot": "-0.8%"},
                 {"t": "15:25", "spot": "-1.5%"}],
        "expect": [{"by": "10:30", "action": "ENTER", "strategy": "CALL_SPREAD", "signal": "NOT_UP"},
                   {"by": "15:30", "action": "CLOSE_ALL", "reason": "EOD"}],
    },

    # ── 2. Sideways / rangebound → iron fly (both gates go) ──
    "sideways_range": {
        "prev_close": PREV, "vix": 12, "instrument": "NIFTY",
        "regime": "ADX<25, oscillating ±0.2% → both gates go → IRON_FLY",
        "path": [{"t": "09:15", "spot": "+3pts"}, {"t": "10:30", "spot": "+0.2%"},
                 {"t": "12:00", "spot": "-0.2%"}, {"t": "13:30", "spot": "+0.15%"},
                 {"t": "15:25", "spot": "-0.05%"}],
        "expect": [{"by": "10:30", "action": "ENTER", "strategy": "IRON_FLY"},
                   {"by": "15:30", "action": "CLOSE_ALL", "reason": "EOD"}],
    },

    # ── 3. THE user example: flat → rise → fade → morph → leg close → exit ──
    "flat_open_rise_fade": {
        "prev_close": PREV, "vix": 14, "instrument": "NIFTY",
        "regime": "open flat, +0.5% by 10:25 (bullish), then fade -1% off high (turns down)",
        "path": [{"t": "09:15", "spot": "+5pts"}, {"t": "10:25", "spot": "+0.5%"},
                 {"t": "14:25", "spot": "-1%_from_high"}],
        "expect": [{"by": "10:30", "action": "ENTER", "strategy": "PUT_SPREAD", "signal": "NOT_DOWN"},
                   {"by": "10:50", "action": "MORPH", "to": "IRON_FLY", "reason": "regime flattening"},
                   {"by": "11:00", "action": "CLOSE_SIDE", "side": "PE", "reason": "trend turned down"},
                   {"by": "14:30", "action": "CLOSE_ALL"}],
    },

    # ── 4. Gaps → enter on confirmation, not on the gap ──
    "gap_up_hold": {
        "prev_close": PREV, "vix": 15, "instrument": "NIFTY",
        "regime": "gap +0.7% at open, holds & drifts up → bullish (confirm, don't chase the gap)",
        "path": [{"t": "09:15", "spot": "+0.7%"}, {"t": "11:00", "spot": "+0.9%"},
                 {"t": "15:25", "spot": "+1.0%"}],
        "expect": [{"by": "10:35", "action": "ENTER", "strategy": "PUT_SPREAD", "signal": "NOT_DOWN"},
                   {"by": "15:30", "action": "CLOSE_ALL", "reason": "EOD"}],
    },
    "gap_down_hold": {
        "prev_close": PREV, "vix": 16, "instrument": "NIFTY",
        "regime": "gap -0.7%, holds lower → bearish",
        "path": [{"t": "09:15", "spot": "-0.7%"}, {"t": "11:00", "spot": "-0.9%"},
                 {"t": "15:25", "spot": "-1.0%"}],
        "expect": [{"by": "10:35", "action": "ENTER", "strategy": "CALL_SPREAD", "signal": "NOT_UP"},
                   {"by": "15:30", "action": "CLOSE_ALL", "reason": "EOD"}],
    },
    "gap_up_fade_to_flat": {
        "prev_close": PREV, "vix": 16, "instrument": "NIFTY",
        "regime": "gap +0.6% then fades back to flat → fake breakout; expect no directional entry / iron-fly bias",
        "path": [{"t": "09:15", "spot": "+0.6%"}, {"t": "11:00", "spot": "+0.1%"},
                 {"t": "15:25", "spot": "0.0%"}],
        "expect": [{"by": "11:30", "action": "ENTER_OR_SKIP", "note": "no clean trend; iron-fly or skip — under test"}],
    },

    # ── 5. Breakout / reversal / V ──
    "range_then_breakout": {
        "prev_close": PREV, "vix": 14, "instrument": "NIFTY",
        "regime": "range until 12:00 then breaks up → sideways then trending; iron-fly may morph to call-side",
        "path": [{"t": "09:15", "spot": "+2pts"}, {"t": "12:00", "spot": "+0.1%"},
                 {"t": "13:30", "spot": "+0.7%"}, {"t": "15:25", "spot": "+1.1%"}],
        "expect": [{"by": "10:30", "action": "ENTER", "strategy": "IRON_FLY"},
                   {"by": "13:00", "action": "MORPH", "note": "breakout → shift to bullish/credit-put"},
                   {"by": "15:30", "action": "CLOSE_ALL", "reason": "EOD"}],
    },
    "midday_reversal_up_to_down": {
        "prev_close": PREV, "vix": 17, "instrument": "NIFTY",
        "regime": "+0.6% by 11:00 then reverses to -0.8% → entered bullish must morph/exit, NO new wrong-way entry",
        "path": [{"t": "09:15", "spot": "+5pts"}, {"t": "11:00", "spot": "+0.6%"},
                 {"t": "15:25", "spot": "-0.8%"}],
        "expect": [{"by": "10:35", "action": "ENTER", "strategy": "PUT_SPREAD", "signal": "NOT_DOWN"},
                   {"by": "12:00", "action": "MORPH_OR_CLOSE_SIDE", "note": "reversal → cut the bullish side"},
                   {"by": "15:30", "action": "CLOSE_ALL", "reason": "EOD"}],
    },
    "v_recovery": {
        "prev_close": PREV, "vix": 18, "instrument": "NIFTY",
        "regime": "down -1% by 11:30 then V-recovers to +0.3% → SL on bearish side then recenter",
        "path": [{"t": "09:15", "spot": "-5pts"}, {"t": "11:30", "spot": "-1.0%"},
                 {"t": "15:25", "spot": "+0.3%"}],
        "expect": [{"by": "10:35", "action": "ENTER", "strategy": "CALL_SPREAD", "signal": "NOT_UP"},
                   {"by": "12:30", "action": "CLOSE_SIDE", "side": "CE", "reason": "SL on call side as it recovers"},
                   {"by": "15:30", "action": "CLOSE_ALL", "reason": "EOD"}],
    },

    # ── 6. Choppy / no-edge → skip ──
    "choppy_whipsaw": {
        "prev_close": PREV, "vix": 19, "instrument": "NIFTY",
        "regime": "ADX<20, rapid ±0.4% whipsaws, no persistent trend → low-confidence, expect SKIP",
        "path": [{"t": "09:15", "spot": "+3pts"}, {"t": "10:00", "spot": "+0.4%"},
                 {"t": "10:45", "spot": "-0.4%"}, {"t": "11:30", "spot": "+0.35%"},
                 {"t": "12:30", "spot": "-0.35%"}, {"t": "15:25", "spot": "+0.05%"}],
        "expect": [{"all_marks": "SKIP", "note": "no clean trend AND VIX elevated → no entry"}],
    },

    # ── 7. Volatility gating (the must-NOT-trade cases) ──
    "high_vix_block": {
        "prev_close": PREV, "vix": 24, "instrument": "NIFTY",
        "regime": "clean uptrend BUT VIX≥20 → gate must BLOCK (no entry)",
        "path": [{"t": "09:15", "spot": "+10pts"}, {"t": "11:00", "spot": "+0.9%"},
                 {"t": "15:25", "spot": "+1.4%"}],
        "expect": [{"all_marks": "SKIP", "reason": "VIX≥20 blocks regardless of trend"}],
    },
    "vix_null_fail_closed": {
        "prev_close": PREV, "vix": None, "instrument": "NIFTY",
        "regime": "good trend but VIX unavailable (broker/stub off) → must FAIL CLOSED (bug #4 regression)",
        "path": [{"t": "09:15", "spot": "+8pts"}, {"t": "11:00", "spot": "+0.8%"},
                 {"t": "15:25", "spot": "+1.3%"}],
        "expect": [{"all_marks": "SKIP", "reason": "VIX None → fail closed, no auto-enter"}],
    },

    # ── 8. Guards (should-not-trade) ──
    "post_close_no_entry": {
        "prev_close": PREV, "vix": 14, "instrument": "NIFTY",
        "regime": "signal fires after 15:30 → no entry; any open position squared off",
        "path": [{"t": "09:15", "spot": "+5pts"}, {"t": "15:25", "spot": "+0.6%"}],
        "expect": [{"after": "15:30", "action": "NO_ENTRY"}, {"by": "15:30", "action": "CLOSE_ALL"}],
    },

    # ── 9. Re-entry (iron-fly SL → recenter, ≤2 re-entries) ──
    "ironfly_sl_recenter": {
        "prev_close": PREV, "vix": 15, "instrument": "NIFTY",
        "regime": "iron fly entered, spot drifts to breach one wing → SL → close+recenter; ≤2 re-entries",
        "path": [{"t": "09:15", "spot": "+2pts"}, {"t": "10:30", "spot": "+0.1%"},
                 {"t": "12:00", "spot": "+0.6%"}, {"t": "13:30", "spot": "+0.2%"},
                 {"t": "15:25", "spot": "+0.1%"}],
        "expect": [{"by": "10:30", "action": "ENTER", "strategy": "IRON_FLY"},
                   {"by": "12:30", "action": "CLOSE_SIDE_OR_RECENTER", "note": "SL on call wing as it drifts up"},
                   {"by": "15:30", "action": "CLOSE_ALL", "reason": "EOD"},
                   {"invariant": "re_entries <= 2 AND single position at all times"}],
    },
}


def get(name: str) -> dict:
    return SCENARIOS[name]


def names() -> list:
    return list(SCENARIOS)


if __name__ == "__main__":
    from sim.scenario_candles import generate, summarize
    import sys
    for n in (sys.argv[1:] or names()):
        s = SCENARIOS[n]
        if s.get("vix") is None or "_from" in str(s["path"]):
            pass
        print(f"\n### {n} — {s['regime']}")
        print("   " + summarize(s, generate(s)))
        for e in s["expect"]:
            print("   expect:", e)
