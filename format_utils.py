#!/usr/bin/env python3
"""
Indian rupee formatting utilities.
Formats numbers in Indian numbering system (lakhs, crores).
"""


def format_inr(amount: float, decimals: int = 2) -> str:
    """
    Format amount in Indian rupee format.

    Examples:
        1000.50 → ₹1,000.50
        100000 → ₹1,00,000.00
        1234567.89 → ₹12,34,567.89
        10000000 → ₹1,00,00,000.00

    Args:
        amount: Number to format
        decimals: Decimal places (default 2)

    Returns:
        Formatted string with ₹ symbol
    """
    if amount is None:
        return "₹0.00"

    # Handle negative numbers
    is_negative = amount < 0
    amount = abs(amount)

    # Format with decimals
    formatted = f"{amount:,.{decimals}f}"

    # Convert to Indian numbering system
    # Split into integer and decimal parts
    if "." in formatted:
        int_part, dec_part = formatted.split(".")
    else:
        int_part = formatted
        dec_part = "00" if decimals == 2 else "0" * decimals

    # Remove existing commas
    int_part = int_part.replace(",", "")

    # Apply Indian comma placement
    if len(int_part) <= 3:
        indian_format = int_part
    else:
        # Split into groups: last 3 digits, then 2-digit groups from right
        last_three = int_part[-3:]
        remaining = int_part[:-3]

        # Add commas every 2 digits from right in remaining part
        groups = []
        while len(remaining) > 2:
            groups.insert(0, remaining[-2:])
            remaining = remaining[:-2]
        if remaining:
            groups.insert(0, remaining)

        indian_format = ",".join(groups) + "," + last_three

    # Reconstruct with decimals
    result = f"₹{indian_format}.{dec_part}"

    # Add negative sign if needed
    if is_negative:
        result = "-" + result

    return result


def format_inr_compact(amount: float) -> str:
    """
    Format amount in compact Indian notation (with Lakh/Crore).

    Examples:
        100000 → ₹1.00 L (lakh)
        1000000 → ₹10.00 L
        10000000 → ₹1.00 Cr (crore)

    Args:
        amount: Number to format

    Returns:
        Formatted string with unit (L/Cr)
    """
    if amount is None or amount == 0:
        return "₹0"

    is_negative = amount < 0
    amount = abs(amount)

    if amount >= 1_00_00_000:  # Crore (1 crore = 10 million)
        value = amount / 1_00_00_000
        unit = "Cr"
    elif amount >= 1_00_000:  # Lakh (1 lakh = 100k)
        value = amount / 1_00_000
        unit = "L"
    elif amount >= 1_000:  # Thousand (use K for consistency)
        value = amount / 1_000
        unit = "K"
    else:
        return format_inr(amount)

    result = f"₹{value:.2f} {unit}"
    if is_negative:
        result = "-" + result

    return result


# Test
if __name__ == "__main__":
    test_values = [
        1000.50,
        100000,
        1234567.89,
        10000000,
        515255.25,
        62885.51,
        2257.11,
        0,
        -1000,
    ]

    print("Indian Rupee Formatting Examples:")
    print("=" * 60)
    print(f"{'Amount':<20} {'Standard':<25} {'Compact':<20}")
    print("=" * 60)

    for val in test_values:
        std = format_inr(val)
        compact = format_inr_compact(val)
        print(f"{val:<20} {std:<25} {compact:<20}")
