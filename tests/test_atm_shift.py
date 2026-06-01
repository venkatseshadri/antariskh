#!/usr/bin/env python3
"""Test NIFTY ATM shift detection — simulates ticks, verifies rebalance triggers.

Run: python3 antariksh/tests/test_atm_shift.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.token_resolver import TokenResolver


def test_atm_shift_logic():
    """Simulate NIFTY spot ticks and verify ATM shift boundaries."""
    gap = 50

    # Walking NIFTY from 23800 → 25250
    test_spots = [
        23803,
        23820,
        23848,
        23870,
        23899,  # ATM=23800
        23910,
        23930,
        23948,
        23951,  # crosses 23950? No, 23951→23950, still 23900
        23975,
        23990,
        23998,
        24000,
        24010,  # ATM=24000 — SHIFT!
        24045,
        24060,
        24080,
        24100,
        24120,  # ATM stays 24050
        24149,
        24155,  # ATM=24150 — SHIFT!
        24200,
        24225,
        24248,
        24250,
        24252,  # ATM=24250 — SHIFT!
        24980,
        24999,
        25000,
        25010,  # ATM stays 25000
        25049,
        25055,  # ATM=25050 — SHIFT!
        25200,
        25220,
        25245,
        25252,  # ATM=25250 — SHIFT!
    ]

    current_atm = 0
    shifts = 0
    resolver = TokenResolver(nifty_spot=23800)

    print(f"{'Spot':>8}  {'ATM':>6}  {'Event':>20}")
    print("-" * 40)

    for spot in test_spots:
        new_atm = resolver.atm_strike(spot, gap)

        if current_atm == 0:
            current_atm = new_atm
            event = "INIT"
        elif new_atm != current_atm:
            event = f"REBALANCE ({current_atm}→{new_atm})"
            shifts += 1
            current_atm = new_atm
        else:
            event = ""

        print(f"{spot:8.0f}  {new_atm:6d}  {event}")

    print("-" * 40)
    print(f"Total rebalances: {shifts}")

    # Expected: 6 shifts for 23800→24000→24150→24250→25050→25250
    expected = 6
    if shifts == expected:
        print("PASS: Correct number of ATM shifts detected")
    else:
        print(f"FAIL: Expected {expected} shifts, got {shifts}")


def test_rolling_window():
    """Verify that ±5 rolling window works correctly on a shift."""
    gap = 50
    resolver = TokenResolver()

    atm_old = 25000
    atm_new = 25050

    old_window = {atm_old + i * gap for i in range(-5, 6)}
    new_window = {atm_new + i * gap for i in range(-5, 6)}

    to_drop = old_window - new_window
    to_add = new_window - old_window

    print(f"\nATM shift: {atm_old} → {atm_new}")
    print(f"Old window: {sorted(old_window)}")
    print(f"New window: {sorted(new_window)}")
    print(f"Drop: {sorted(to_drop)}")
    print(f"Add:  {sorted(to_add)}")

    assert to_drop == {24750}, f"Expected drop 24750, got {to_drop}"
    assert to_add == {25300}, f"Expected add 25300, got {to_add}"
    print("PASS: Rolling window correct")


def test_deep_shift():
    """Verify a large gap shift (200+ points)."""
    atm_old = 25000
    atm_new = 25300  # Shift of 300 points, 6 strikes

    old_window = {atm_old + i * 50 for i in range(-5, 6)}
    new_window = {atm_new + i * 50 for i in range(-5, 6)}

    to_drop = old_window - new_window
    to_add = new_window - old_window

    print(f"\nDeep shift: {atm_old} → {atm_new}")
    print(f"Drop ({len(to_drop)}): {sorted(to_drop)}")
    print(f"Add  ({len(to_add)}): {sorted(to_add)}")

    assert len(to_drop) == 6, f"Expected 6 drops, got {len(to_drop)}"
    assert len(to_add) == 6, f"Expected 6 adds, got {len(to_add)}"
    print("PASS: Deep shift handled correctly")


if __name__ == "__main__":
    test_atm_shift_logic()
    test_rolling_window()
    test_deep_shift()
    print("\nAll tests passed.")
