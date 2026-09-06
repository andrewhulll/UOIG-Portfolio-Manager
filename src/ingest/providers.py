"""Legacy Yahoo symbol formatting used by non-price research integrations.

Price data is provided by :mod:`src.ingest.capital_iq`; this helper remains for
the fundamentals, holders, and research tabs that are outside the Layer 1 price
cache migration.
"""
from __future__ import annotations


def to_yf(ticker: str) -> str:
    """Map the portfolio convention to Yahoo's legacy symbol convention."""
    return ticker.replace(".", "-")
