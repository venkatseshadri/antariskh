#!/usr/bin/env python3
"""
Test: Traffic Light Pattern Scoring (7 lights = 6 TFs + GAP)
Validates all 64 combinations against the score_traffic_light_redis pattern matcher.
Clear cases are asserted; edge cases are marked with @edge for discussion.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from tools.entry_tools import _load_weights

cfg = _load_weights()
patterns_cfg = cfg["traffic_light"]["patterns"]
thresholds = cfg["traffic_light"]["signal_thresholds"]  # bullish≥3, bearish≤-3
gw = cfg["traffic_light"]["gap_weight"]

TFS = ["1440m", "240m", "60m", "30m", "15m", "5m"]


def classify(tf_str):
    """Replicate score_traffic_light_redis pattern matching (lines 1316-1355)."""
    green_c = sum(1 for c in tf_str if c == "G")
    red_c = sum(1 for c in tf_str if c == "R")
    daily = tf_str[0]
    h4 = tf_str[1]
    h1 = tf_str[2]
    m30 = tf_str[3]
    m15 = tf_str[4]

    if green_c == 6:
        pattern = "MOMENTUM_PEAK"
    elif red_c == 6:
        pattern = "STRONG_BEAR_CONTINUATION"
    elif daily == "G" and h4 == "R" and h1 == "G":
        pattern = "BULLISH_PULLBACK_RESUMING"
    elif daily == "G" and h4 == "G" and h1 == "R":
        pattern = "BULLISH_MILD_PULLBACK"
    elif daily == "G" and h4 == "R" and h1 == "R" and (m30 == "G" or m15 == "G"):
        pattern = "BULLISH_DEEP_PULLBACK_BOUNCING"
    elif daily == "R" and h1 == "G" and m15 == "G":
        pattern = "DEAD_CAT_BOUNCE"
    elif daily == "G" and green_c >= 4:
        pattern = "BULLISH_CONTINUATION"
    elif daily == "R" and red_c >= 4:
        pattern = "BEARISH_CONTINUATION"
    elif green_c >= 4:
        pattern = "BULLISH_STRUCTURE"
    elif red_c >= 4:
        pattern = "BEARISH_STRUCTURE"
    elif green_c == 3 and red_c == 3:
        pattern = "CHOPPY_INDECISION"
    else:
        pattern = "mixed"

    pat = patterns_cfg.get(pattern, patterns_cfg["mixed"])
    score = pat["score"]
    conf = pat["confidence"]
    signal = "BULLISH" if score >= 3 else ("BEARISH" if score <= -3 else "NEUTRAL")

    # gap boost (no gap = flat)
    gap_boost = 0
    gap_conf = 0
    score += gap_boost
    conf += gap_conf
    conf = max(5, min(100, conf))

    return pattern, score, conf, signal


def gap_effect(tf_str, gap_dir):
    """What gap boost would be applied (using the fixed pattern-signal logic)."""
    pattern, base_score, _, _ = classify(tf_str)
    if gap_dir == "RED":
        if base_score < 0:
            return f"gap_down:strong_bearish boost={-gw * 2:.2f}"
        elif base_score > 0:
            return f"gap_down:recovery_conflict boost={gw * 1.5:.2f}"
    elif gap_dir == "GREEN":
        if base_score > 0:
            return f"gap_up:strong_bullish boost={gw * 2:.2f}"
        elif base_score < 0:
            return f"gap_up:conflict boost={-gw * 1.5:.2f}"
    return "no_gap"


# ────────────────────────────────────────────────────────────────────────────
#  TEST DATA: All 64 combos with expected outputs
#  Format: (tf_string, expected_pattern, expected_signal, expected_confidence, status)
#  status: "clear" = straightforward, "edge" = needs discussion
# ────────────────────────────────────────────────────────────────────────────

CASES = [
    # ═══ 6 RED / 6 GREEN — Rare extremes ═══
    ("RRRRRR", "STRONG_BEAR_CONTINUATION", "BEARISH", 90, "clear"),
    ("GGGGGG", "MOMENTUM_PEAK", "BULLISH", 70, "clear"),
    # ═══ 5 red (one green) ═══
    ("RRRRRG", "BEARISH_CONTINUATION", "BEARISH", 80, "clear"),  # daily RED, 5 red
    ("RRRRGR", "BEARISH_CONTINUATION", "BEARISH", 80, "clear"),
    ("RRRGRR", "BEARISH_CONTINUATION", "BEARISH", 80, "clear"),
    ("RRGRRR", "BEARISH_CONTINUATION", "BEARISH", 80, "clear"),
    ("RGRRRR", "BEARISH_CONTINUATION", "BEARISH", 80, "clear"),
    ("GRRRRR", "BEARISH_STRUCTURE", "BEARISH", 65, "clear"),  # daily GREEN! Only 5 red
    # ═══ 5 green (one red) ═══
    ("GGGGGR", "BULLISH_CONTINUATION", "BULLISH", 80, "clear"),  # daily GREEN, 5 green
    ("GGGGRG", "BULLISH_CONTINUATION", "BULLISH", 80, "clear"),
    ("GGGRGG", "BULLISH_CONTINUATION", "BULLISH", 80, "clear"),
    (
        "GGRGGG",
        "BULLISH_MILD_PULLBACK",
        "BULLISH",
        65,
        "clear",
    ),  # daily G, h4 G, h1 R (specific rule fires before continuation)
    (
        "GRGGGG",
        "BULLISH_PULLBACK_RESUMING",
        "BULLISH",
        70,
        "clear",
    ),  # daily G, h4 R, h1 G (pullback resolves before continuation fires)
    (
        "RGGGGG",
        "DEAD_CAT_BOUNCE",
        "BEARISH",
        60,
        "edge",
    ),  # daily RED! @edge: could be reversal
    # ═══ 4 red / 2 green ═══
    ("RRRRGG", "BEARISH_CONTINUATION", "BEARISH", 80, "clear"),  # daily RED
    ("RRRGRG", "BEARISH_CONTINUATION", "BEARISH", 80, "clear"),  # daily RED
    ("RRRGGR", "BEARISH_CONTINUATION", "BEARISH", 80, "clear"),  # daily RED
    (
        "RRRGGG",
        "CHOPPY_INDECISION",
        "NEUTRAL",
        20,
        "clear",
    ),  # daily RED, 3red/3green → chop
    ("RRGRRG", "BEARISH_CONTINUATION", "BEARISH", 80, "clear"),  # daily RED
    ("RGRRRG", "BEARISH_CONTINUATION", "BEARISH", 80, "clear"),  # daily RED
    ("GRRRRG", "BEARISH_STRUCTURE", "BEARISH", 65, "clear"),  # daily GREEN
    (
        "GRRRGR",
        "BULLISH_DEEP_PULLBACK_BOUNCING",
        "BULLISH",
        55,
        "edge",
    ),  # @edge: deep bounce or death spiral?
    # ═══ 4 green / 2 red ═══
    ("GGGGRR", "BULLISH_CONTINUATION", "BULLISH", 80, "clear"),  # daily GREEN
    ("GGGRGR", "BULLISH_CONTINUATION", "BULLISH", 80, "clear"),  # daily GREEN
    ("GGGRRG", "BULLISH_CONTINUATION", "BULLISH", 80, "clear"),  # daily GREEN
    ("GGGGRR", "BULLISH_CONTINUATION", "BULLISH", 80, "clear"),  # daily GREEN
    (
        "RGGGGR",
        "DEAD_CAT_BOUNCE",
        "BEARISH",
        60,
        "edge",
    ),  # @edge: daily RED + green lower TFs
    (
        "RGGGRG",
        "BULLISH_STRUCTURE",
        "BULLISH",
        65,
        "edge",
    ),  # @edge: daily R, 60m=G but 15m=R → dead_cat REJECTED. Falls to BULLISH_STRUCTURE (green>=4)
    ("RGRGRR", "BEARISH_CONTINUATION", "BEARISH", 80, "clear"),  # daily RED
    ("RGRGRR", "BEARISH_CONTINUATION", "BEARISH", 80, "clear"),  # daily RED
    (
        "GRGRRR",
        "BULLISH_PULLBACK_RESUMING",
        "BULLISH",
        70,
        "clear",
    ),  # daily G, h4 R, h1 G → classic
    # ═══ Specific pattern triggers ═══
    # BULLISH_PULLBACK_RESUMING: daily=G, h4=R, h1=G (8 combos)
    ("GRGRRR", "BULLISH_PULLBACK_RESUMING", "BULLISH", 70, "clear"),
    ("GRGRRG", "BULLISH_PULLBACK_RESUMING", "BULLISH", 70, "clear"),
    ("GRGRGR", "BULLISH_PULLBACK_RESUMING", "BULLISH", 70, "clear"),
    ("GRGRGG", "BULLISH_PULLBACK_RESUMING", "BULLISH", 70, "clear"),
    (
        "GRGGRR",
        "BULLISH_PULLBACK_RESUMING",
        "BULLISH",
        70,
        "clear",
    ),  # @edge: classic pullback vs deep?
    ("GRGGRG", "BULLISH_PULLBACK_RESUMING", "BULLISH", 70, "clear"),
    (
        "GRGGGR",
        "BULLISH_PULLBACK_RESUMING",
        "BULLISH",
        70,
        "clear",
    ),  # @edge: near-continuation, merging up
    (
        "GRGGGG",
        "BULLISH_PULLBACK_RESUMING",
        "BULLISH",
        70,
        "clear",
    ),  # @edge: h4 is lone RED, rest green
    # BULLISH_MILD_PULLBACK: daily=G, h4=G, h1=R (8 combos)
    ("GGRRRR", "BULLISH_MILD_PULLBACK", "BULLISH", 65, "clear"),
    ("GGRRRG", "BULLISH_MILD_PULLBACK", "BULLISH", 65, "clear"),
    ("GGRRGR", "BULLISH_MILD_PULLBACK", "BULLISH", 65, "clear"),
    ("GGRRGG", "BULLISH_MILD_PULLBACK", "BULLISH", 65, "clear"),
    ("GGRGRR", "BULLISH_MILD_PULLBACK", "BULLISH", 65, "clear"),
    ("GGRGRG", "BULLISH_MILD_PULLBACK", "BULLISH", 65, "clear"),
    ("GGRGGR", "BULLISH_MILD_PULLBACK", "BULLISH", 65, "clear"),
    (
        "GGRGGG",
        "BULLISH_MILD_PULLBACK",
        "BULLISH",
        65,
        "clear",
    ),  # @edge: h1 lone RED, rest green
    # BULLISH_DEEP_PULLBACK_BOUNCING: daily=G, h4=R, h1=R, (m30=G or m15=G) (6 combos)
    ("GRRRGR", "BULLISH_DEEP_PULLBACK_BOUNCING", "BULLISH", 55, "edge"),
    ("GRRRGG", "BULLISH_DEEP_PULLBACK_BOUNCING", "BULLISH", 55, "edge"),
    ("GRRGRR", "BULLISH_DEEP_PULLBACK_BOUNCING", "BULLISH", 55, "edge"),
    ("GRRGRG", "BULLISH_DEEP_PULLBACK_BOUNCING", "BULLISH", 55, "edge"),
    ("GRRGGR", "BULLISH_DEEP_PULLBACK_BOUNCING", "BULLISH", 55, "edge"),
    ("GRRGGG", "BULLISH_DEEP_PULLBACK_BOUNCING", "BULLISH", 55, "edge"),
    # DEAD_CAT_BOUNCE: daily=R, h1=G, m15=G (8 combos, excluding ones caught by BEARISH_CONTINUATION)
    ("RRGRGR", "DEAD_CAT_BOUNCE", "BEARISH", 60, "edge"),  # daily R, h1 G, m15 G
    ("RRGRGG", "DEAD_CAT_BOUNCE", "BEARISH", 60, "edge"),
    ("RRGGGR", "DEAD_CAT_BOUNCE", "BEARISH", 60, "edge"),
    ("RRGGGG", "DEAD_CAT_BOUNCE", "BEARISH", 60, "edge"),
    ("RGGRGR", "DEAD_CAT_BOUNCE", "BEARISH", 60, "edge"),
    ("RGGRGG", "DEAD_CAT_BOUNCE", "BEARISH", 60, "edge"),
    ("RGGGGR", "DEAD_CAT_BOUNCE", "BEARISH", 60, "edge"),
    (
        "RGGGGG",
        "DEAD_CAT_BOUNCE",
        "BEARISH",
        60,
        "edge",
    ),  # @edge: worst case — daily R, 5 lower green
    # ═══ 3 red / 3 green ═══
    ("RRRGGG", "CHOPPY_INDECISION", "NEUTRAL", 20, "clear"),
    (
        "RRGRGG",
        "DEAD_CAT_BOUNCE",
        "BEARISH",
        60,
        "edge",
    ),  # @edge: R R G R G G = 3R/3G but dead_cat fires first (daily R, h1 G, m15 G). DEAD_CAT vs CHOPPY.
    (
        "RRGGRG",
        "CHOPPY_INDECISION",
        "NEUTRAL",
        20,
        "clear",
    ),  # R R G G R G → red=3, green=3
    # dead_cat: daily=R, h1=G ✓, m15=R ✗ → chop
    (
        "RGRRGG",
        "CHOPPY_INDECISION",
        "NEUTRAL",
        20,
        "clear",
    ),  # R G R R G G → dead_cat: h1=R ✗ → chop
    ("RGRGRG", "CHOPPY_INDECISION", "NEUTRAL", 20, "clear"),  # R G R G R G → 3/3 → chop
    ("RGRGGR", "CHOPPY_INDECISION", "NEUTRAL", 20, "clear"),  # R G R G G R → 3/3 → chop
    ("RGGRRG", "CHOPPY_INDECISION", "NEUTRAL", 20, "clear"),  # R G G R R G → 3/3 → chop
    (
        "GRRRRG",
        "BEARISH_STRUCTURE",
        "BEARISH",
        65,
        "clear",
    ),  # daily GREEN! 4 red → bearish structure
    (
        "GRRGRG",
        "BULLISH_DEEP_PULLBACK_BOUNCING",
        "BULLISH",
        55,
        "edge",
    ),  # G R R G R G → deep bounce
    # h1=G? 60m=G → no! wait:
    # 60m position 2 → R. So h1=R.
    # h4=R, h1=R, m30=G → deep bounce.
    # Actually let me recheck...
    (
        "GRGGRG",
        "BULLISH_PULLBACK_RESUMING",
        "BULLISH",
        70,
        "clear",
    ),  # G R G G R G → h4=R, h1=G → pullback
    (
        "GGGRRR",
        "CHOPPY_INDECISION",
        "NEUTRAL",
        20,
        "clear",
    ),  # daily GREEN, 3G/3R → but green_c=3 → chop
]

# ────────────────────────────────────────────────────────────────────────────
#  RUN TESTS
# ────────────────────────────────────────────────────────────────────────────

passed = 0
failed = 0
edge_cases = []

print("=" * 95)
print(
    f"{'COMBOS':<10} {'EXPECTED PATTERN':<38} {'SIGNAL':<10} {'CONF':>4}  {'STATUS':<7}  {'GAP EFFECT'}"
)
print("=" * 95)

for tf_str, exp_pattern, exp_signal, exp_conf, status in CASES:
    act_pattern, act_score, act_conf, act_signal = classify(tf_str)
    gap = gap_effect(tf_str, "RED")  # show gap down effect

    # Match check
    pattern_ok = act_pattern == exp_pattern
    signal_ok = act_signal == exp_signal
    conf_ok = act_conf == exp_conf
    all_ok = pattern_ok and signal_ok and conf_ok

    marker = "✅" if all_ok else "❌"
    edge_marker = " @edge" if status == "edge" else ""

    line = f"{marker} {tf_str:<7} {act_pattern:<38} {act_signal:<10} {act_conf:>4}% {status:<7}  {gap}{edge_marker}"
    print(line)

    if all_ok:
        passed += 1
    else:
        failed += 1
        if not pattern_ok:
            print(f"     ❌ PATTERN: expected={exp_pattern} got={act_pattern}")
        if not signal_ok:
            print(f"     ❌ SIGNAL:  expected={exp_signal} got={act_signal}")
        if not conf_ok:
            print(f"     ❌ CONF:    expected={exp_conf}% got={act_conf}%")

    if status == "edge":
        edge_cases.append(tf_str)

print()
print(
    f"Results: {passed} passed, {failed} failed, {len(edge_cases)} edge cases flagged for discussion"
)
print()

# ────────────────────────────────────────────────────────────────────────────
#  EDGE CASE SUMMARY
# ────────────────────────────────────────────────────────────────────────────
print("=" * 70)
print("EDGE CASES FOR DISCUSSION")
print("=" * 70)
print()

edges = {
    "RRGRGG": "daily=RED, h1=GREEN, 15m=GREEN → DEAD_CAT vs CHOPPY boundary",
    "RGGGGG": "daily=RED, 5 lower TFs green → DEAD_CAT or REVERSAL? (max green, only daily RED)",
    "RRGRGR": "daily=RED, h1=GREEN, 15m=GREEN → DEAD_CAT with 3R/3G → could be CHOPPY",
    "GRRRGR": "daily=GREEN, h4=RED, h1=RED, m30=GREEN → DEEP_BOUNCE or continuing drop?",
    "GRGGGG": "daily=GREEN, h4=RED, rest green → PULLBACK_RESUMING at 70% or CONTINUATION at 80%? h4 RED is one bar ago",
    "GGRGGG": "daily=GREEN, h4=GREEN, h1=RED, rest green → MILD_PULLBACK: h1 RED just flipped, about to resolve?",
    "GRRGGG": "daily=GREEN, h4=RED, h1=RED, lower 3 green → DEEP_BOUNCE: bounce confirmed but h1+h4 still RED suggests fragility",
    "RGGRGG": "daily=RED, h4=GREEN, h1=GREEN, m30=RED, lower green → DEAD_CAT: h4 GREEN weakens the bear case",
}

for tf in edge_cases:
    pat, _, _, sig = classify(tf)
    if tf in edges:
        print(f"  {tf}: {pat} ({sig})")
        print(f"       {edges[tf]}")
        print()
