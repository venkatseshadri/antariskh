"""Sentiment classification from PCR — pure function."""

from typing import Optional


def classify_sentiment(pcr_total: Optional[float]) -> Optional[str]:
    if pcr_total is None:
        return None
    if pcr_total > 1.0:
        return "bearish"
    elif pcr_total > 0.8:
        return "neutral"
    return "bullish"
