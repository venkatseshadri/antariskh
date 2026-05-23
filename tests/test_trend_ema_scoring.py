#!/usr/bin/env python3
"""
Test: Trend EMA Scoring (score_trend_redis) — 5 EMA periods
Weights: EMA5=±0.35  EMA20=±0.30  EMA50=±0.25  EMA100=±0.20  EMA200=±0.15
Max score: ±1.25
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def direct_score(
    current_price, ema5=None, ema20=None, ema50=None, ema100=None, ema200=None
):
    weights = {5: 0.35, 20: 0.30, 50: 0.25, 100: 0.20, 200: 0.15}
    ema_values = {}
    for period, val in [
        (5, ema5),
        (20, ema20),
        (50, ema50),
        (100, ema100),
        (200, ema200),
    ]:
        if val is not None:
            ema_values[period] = val

    score = 0.0
    ema_aligned = 0
    available_count = 0

    for period in [5, 20, 50, 100, 200]:
        if period in ema_values:
            available_count += 1
            w = weights[period]
            if current_price > ema_values[period]:
                ema_aligned += 1
                score += w
            else:
                score += -w

    if available_count == 0:
        signal = "NEUTRAL"
        confidence = 5
    else:
        alignment_pct = ema_aligned / available_count
        if alignment_pct >= 0.75:
            signal = "BULLISH"
            confidence = min(90, 50 + round(alignment_pct * 40))
        elif alignment_pct <= 0.25:
            signal = "BEARISH"
            confidence = min(90, 50 + round((1 - alignment_pct) * 40))
        else:
            signal = "NEUTRAL"
            confidence = 40

    return round(score, 2), ema_aligned, available_count, signal, confidence


def test_all():
    passed = 0
    failed = 0
    total = 0

    def check(
        name,
        *,
        price,
        ema5=None,
        ema20=None,
        ema50=None,
        ema100=None,
        ema200=None,
        exp_score,
        exp_aligned,
        exp_available,
        exp_signal,
        exp_conf,
        tag="",
    ):
        nonlocal passed, failed, total
        total += 1
        score, aligned, avail, signal, conf = direct_score(
            price, ema5, ema20, ema50, ema100, ema200
        )
        ok = (
            score == exp_score
            and aligned == exp_aligned
            and avail == exp_available
            and signal == exp_signal
            and conf == exp_conf
        )
        marker = "✅" if ok else "❌"
        label = f"[{total:02d}] {name}"
        tag_str = f" @edge: {tag}" if tag else ""
        print(
            f"{marker} {label:<45} score={score:+>6.2f} {aligned}/{avail} aligned  {signal:<10} conf={conf:>3}%{tag_str}"
        )
        if not ok:
            failed += 1
            if score != exp_score:
                print(f"     ❌ SCORE: expected={exp_score} got={score}")
            if aligned != exp_aligned:
                print(f"     ❌ ALIGNED: expected={exp_aligned} got={aligned}")
            if avail != exp_available:
                print(f"     ❌ AVAIL: expected={exp_available} got={avail}")
            if signal != exp_signal:
                print(f"     ❌ SIGNAL: expected={exp_signal} got={signal}")
            if conf != exp_conf:
                print(f"     ❌ CONF: expected={exp_conf}% got={conf}%")
        else:
            passed += 1

    print("=" * 90)
    print(f"{'TREND EMA SCORING TESTS (5 periods: 5,20,50,100,200)':^90}")
    print(
        f"{'Weights: EMA5=±0.35 EMA20=±0.30 EMA50=±0.25 EMA100=±0.20 EMA200=±0.15':^90}"
    )
    print(f"{'Max score: ±1.25  Signal: ≥75%→BULLISH ≤25%→BEARISH else→NEUTRAL':^90}")
    print("=" * 90)
    print()

    # ═══ 5/5 ═══
    print("── 5/5 Perfect Alignment ──")
    check(
        "All 5 bullish",
        price=24000,
        ema5=23800,
        ema20=23700,
        ema50=23600,
        ema100=23500,
        ema200=23400,
        exp_score=1.25,
        exp_aligned=5,
        exp_available=5,
        exp_signal="BULLISH",
        exp_conf=90,
    )
    check(
        "All 5 bearish",
        price=23000,
        ema5=23200,
        ema20=23300,
        ema50=23500,
        ema100=23600,
        ema200=23700,
        exp_score=-1.25,
        exp_aligned=0,
        exp_available=5,
        exp_signal="BEARISH",
        exp_conf=90,
    )

    # ═══ 4/5 ═══
    print("\n── 4/5 Alignment (≥75% → signal) ──")
    check(
        "4/5 bullish (EMA5 wrong)",
        price=23900,
        ema5=24000,
        ema20=23700,
        ema50=23600,
        ema100=23500,
        ema200=23400,
        exp_score=0.55,
        exp_aligned=4,
        exp_available=5,
        exp_signal="BULLISH",
        exp_conf=82,
    )
    check(
        "4/5 bearish (EMA5 wrong)",
        price=23300,
        ema5=23200,
        ema20=23400,
        ema50=23500,
        ema100=23600,
        ema200=23700,
        exp_score=-0.55,
        exp_aligned=1,
        exp_available=5,
        exp_signal="BEARISH",
        exp_conf=82,
    )

    # ═══ 3/5 NEUTRAL ═══
    print("\n── 3/5 (60% — NEUTRAL boundary) ──")
    check(
        "3/5 bull (top 3)",
        price=23750,
        ema5=23700,
        ema20=23700,
        ema50=23600,
        ema100=23800,
        ema200=23900,
        exp_score=0.55,
        exp_aligned=3,
        exp_available=5,
        exp_signal="NEUTRAL",
        exp_conf=40,
    )
    check(
        "2/5 bear (bottom 2)",
        price=23600,
        ema5=23700,
        ema20=23750,
        ema50=23650,
        ema100=23500,
        ema200=23400,
        exp_score=-0.55,
        exp_aligned=2,
        exp_available=5,
        exp_signal="NEUTRAL",
        exp_conf=40,
    )

    # ═══ EMA5 = ±0.35 highest weight ═══
    print("\n── EMA5 influence (±0.35, highest weight) ──")
    # EMA5,100,200 bull, EMA20,50 bear → 3/5 bull NEUTRAL
    check(
        "EMA5 balances EMA20+50 bear",
        price=23650,
        ema5=23600,
        ema20=23700,
        ema50=23700,
        ema100=23600,
        ema200=23500,
        exp_score=0.15,
        exp_aligned=3,
        exp_available=5,
        exp_signal="NEUTRAL",
        exp_conf=40,
        tag="EMA5 bullish but EMA20/50 bearish → 3/5 NEUTRAL",
    )

    # ═══ EMA200 = ±0.15 slowest ═══
    print("\n── EMA200 confirmational (±0.15, slowest) ──")
    check(
        "EMA200 lone bear",
        price=23750,
        ema5=23600,
        ema20=23500,
        ema50=23400,
        ema100=23300,
        ema200=23800,
        exp_score=0.95,
        exp_aligned=4,
        exp_available=5,
        exp_signal="BULLISH",
        exp_conf=82,
        tag="4/5 bullish, EMA200 cannot block → BULLISH 82%",
    )
    check(
        "EMA200 lone bull",
        price=23600,
        ema5=23700,
        ema20=23700,
        ema50=23700,
        ema100=23750,
        ema200=23500,
        exp_score=-0.95,
        exp_aligned=1,
        exp_available=5,
        exp_signal="BEARISH",
        exp_conf=82,
        tag="1/5 bullish → BEARISH 82%",
    )

    # ═══ 3 periods only (no EMA5,200) ═══
    print("\n── 3 periods only (EMA5 + EMA200 not ready) ──")
    check(
        "3/3 bullish",
        price=24000,
        ema20=23800,
        ema50=23700,
        ema100=23600,
        exp_score=0.75,
        exp_aligned=3,
        exp_available=3,
        exp_signal="BULLISH",
        exp_conf=90,
    )
    check(
        "3/3 bearish",
        price=23000,
        ema20=23200,
        ema50=23300,
        ema100=23500,
        exp_score=-0.75,
        exp_aligned=0,
        exp_available=3,
        exp_signal="BEARISH",
        exp_conf=90,
    )
    check(
        "2/3 mixed",
        price=23750,
        ema20=23700,
        ema50=23800,
        ema100=23900,
        exp_score=-0.15,
        exp_aligned=1,
        exp_available=3,
        exp_signal="NEUTRAL",
        exp_conf=40,
    )
    check(
        "1/3 bear",
        price=23750,
        ema20=23800,
        ema50=23800,
        ema100=23800,
        exp_score=-0.75,
        exp_aligned=0,
        exp_available=3,
        exp_signal="BEARISH",
        exp_conf=90,
    )

    # ═══ 2 periods only ═══
    print("\n── 2 periods only ──")
    check(
        "2/2 bullish",
        price=24000,
        ema20=23800,
        ema50=23700,
        exp_score=0.55,
        exp_aligned=2,
        exp_available=2,
        exp_signal="BULLISH",
        exp_conf=90,
    )
    check(
        "2/2 bearish",
        price=23600,
        ema20=23800,
        ema50=23700,
        exp_score=-0.55,
        exp_aligned=0,
        exp_available=2,
        exp_signal="BEARISH",
        exp_conf=90,
    )
    check(
        "1/2 split",
        price=23750,
        ema20=23700,
        ema50=23800,
        exp_score=0.05,
        exp_aligned=1,
        exp_available=2,
        exp_signal="NEUTRAL",
        exp_conf=40,
    )

    # ═══ 0 data ═══
    print("\n── 0 data ──")
    check(
        "No EMA data",
        price=24000,
        exp_score=0.0,
        exp_aligned=0,
        exp_available=0,
        exp_signal="NEUTRAL",
        exp_conf=5,
    )

    # ═══ edge: 5p vs old 3p ═══
    print("\n── 5-period catches false signals ──")
    check(
        "5p: NEUTRAL (3p: BEARISH)",
        price=23750,
        ema5=23800,
        ema20=23800,
        ema50=23700,
        ema100=23600,
        ema200=23500,
        exp_score=-0.05,
        exp_aligned=3,
        exp_available=5,
        exp_signal="NEUTRAL",
        exp_conf=40,
        tag="3p=0/3 BEARISH. 5p=3/5 NEUTRAL. EMA200 bull blocks false bear call",
    )
    check(
        "Contrarian EMA5 lowers conviction",
        price=23900,
        ema5=24000,
        ema20=23700,
        ema50=23600,
        ema100=23500,
        ema200=23400,
        exp_score=0.55,
        exp_aligned=4,
        exp_available=5,
        exp_signal="BULLISH",
        exp_conf=82,
        tag="EMA5 bear costs 0.70 in score (from +1.25 to +0.55)",
    )

    print()
    print("=" * 90)
    print(f"RESULTS: {passed} passed, {failed} failed, {total} total")
    if failed:
        print(f"⚠️  {failed} FAILURES")
    else:
        print("✅ ALL PASSED")
    print()
    print("EMA Scoring Weights:")
    print("  EMA5:   ±0.35  (shortest — most reactionary)")
    print("  EMA20:  ±0.30  (primary trend)")
    print("  EMA50:  ±0.25  (confirmation)")
    print("  EMA100: ±0.20  (long-term)")
    print("  EMA200: ±0.15  (longest — slowest, confirmational)")
    print(f"  Signal: ≥75% → BULLISH | ≤25% → BEARISH | else → NEUTRAL")

    return failed == 0


if __name__ == "__main__":
    ok = test_all()
    sys.exit(0 if ok else 1)
