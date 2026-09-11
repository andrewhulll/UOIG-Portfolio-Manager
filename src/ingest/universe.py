"""Authoritative owned-security queries shared by API and refresh jobs."""
from __future__ import annotations

from src.model import db


def is_owned(conn, ticker: str) -> bool:
    """Whether ``ticker`` is a current positive-share, non-cash holding."""
    row = conn.execute(
        db.q(conn, "SELECT 1 FROM holdings h "
                   "JOIN securities s ON s.ticker = h.ticker "
                   "WHERE UPPER(h.ticker) = UPPER(?) AND COALESCE(h.shares, 0) > 0 "
                   "AND s.sec_type != 'cash' LIMIT 1"),
        (ticker,),
    ).fetchone()
    return row is not None


def owned_tickers(conn) -> list[str]:
    """Sorted, de-duplicated current non-cash holdings across all funds."""
    rows = conn.execute(
        "SELECT DISTINCT h.ticker FROM holdings h "
        "JOIN securities s ON s.ticker = h.ticker "
        "WHERE COALESCE(h.shares, 0) > 0 AND s.sec_type != 'cash' "
        "ORDER BY h.ticker"
    ).fetchall()
    return [r[0] for r in rows]
