"""Ticker search and off-portfolio pricing.

Held names are resolved from the local database and ``daily_prices`` cache.
Non-held search, quote, and chart requests call Capital IQ and are cached for
five minutes. Yahoo remains only for the separate institutional-holders panel.
"""
from __future__ import annotations

import datetime as dt
import math
import time

import yfinance as yf

from src.ingest.capital_iq import CapitalIQProvider, validate_ticker
from src.ingest.providers import to_yf
from src.model import cache

_SEARCH_CACHE: dict[str, tuple[float, list]] = {}
_QUOTE_CACHE: dict[str, tuple[float, dict | None]] = {}
_SERIES_CACHE: dict[str, tuple[float, dict]] = {}
_HOLDERS_CACHE: dict[str, tuple[float, list]] = {}
_TTL = 300
_CIQ_DAYS = {"1M": 30, "3M": 91, "6M": 182, "1Y": 365, "5Y": 1826}


class HeldPriceCacheMiss(RuntimeError):
    pass


def _num(value):
    try:
        result = float(value)
        return None if math.isnan(result) or math.isinf(result) else result
    except (TypeError, ValueError):
        return None


def _ciq_provider() -> CapitalIQProvider:
    return CapitalIQProvider()


def _search_query(value: str) -> str:
    query = (value or "").strip()
    if not query or len(query) > 80 or not all(c.isalnum() or c in " .&-'" for c in query):
        raise ValueError("search must be 1-80 letters, numbers, spaces, or basic punctuation")
    return query


def search_symbols(query: str, limit: int = 8, conn=None) -> list[dict]:
    """Return held names locally first; otherwise query Capital IQ company search."""
    q = _search_query(query)
    limit = max(1, min(int(limit), 20))
    key = f"ciq|{q.lower()}|{limit}"
    now = time.time()
    hit = _SEARCH_CACHE.get(key)
    if hit and (now - hit[0]) < _TTL:
        return hit[1]
    cached = cache.get("search", key)
    if cached is not cache.MISS:
        _SEARCH_CACHE[key] = (now, cached)
        return cached

    out: list[dict] = []
    if conn is not None:
        like = f"%{q.upper()}%"
        sql = (
            "SELECT DISTINCT s.ticker, s.name FROM securities s "
            "JOIN holdings h ON h.ticker=s.ticker "
            "WHERE UPPER(s.ticker) LIKE ? OR UPPER(s.name) LIKE ? "
            "ORDER BY s.ticker"
        )
        from src.model import db as _db
        for ticker, name in conn.execute(_db.q(conn, sql), (like, like)).fetchall():
            out.append({"symbol": ticker, "name": name or ticker, "exchange": ""})
            if len(out) >= limit:
                break

    # A local match is sufficient: held-name search must not depend on vendor
    # uptime, credentials, or consume a live request merely to fill the menu.
    if out:
        _SEARCH_CACHE[key] = (now, out[:limit])
        return out[:limit]

    out = _ciq_provider().search_companies(q, limit=limit)
    _SEARCH_CACHE[key] = (now, out)
    if out:
        cache.set("search", key, out, _TTL)
    return out


def _cached_quote(conn, ticker: str) -> dict | None:
    from src.model import db as _db
    security = conn.execute(_db.q(conn,
        "SELECT s.name, s.sector FROM securities s WHERE s.ticker=? "
        "AND EXISTS (SELECT 1 FROM holdings h WHERE h.ticker=s.ticker)"),
        (ticker,)).fetchone()
    if not security:
        return None
    rows = conn.execute(_db.q(conn,
        "SELECT date, close FROM daily_prices WHERE ticker=? ORDER BY date DESC LIMIT 2"),
        (ticker,)).fetchall()
    if not rows:
        return None
    price = _num(rows[0][1])
    previous = _num(rows[1][1]) if len(rows) > 1 else None
    if price is None:
        return None
    fundamentals = conn.execute(_db.q(conn,
        "SELECT pe, pb, ev_ebitda, market_cap, week52_low, week52_high, description "
        "FROM fundamentals WHERE ticker=?"), (ticker,)).fetchone()
    values = fundamentals or [None] * 7
    change = ((price / previous - 1) * 100) if previous else None
    return {
        "t": ticker, "n": security[0] or ticker, "s": security[1],
        "industry": None, "exchange": "", "px": round(price, 2),
        "chg": round(change, 2) if change is not None else None,
        "mc": round(float(values[3]) / 1e9, 2) if values[3] else None,
        "pe": _num(values[0]), "pb": _num(values[1]), "evEbitda": _num(values[2]),
        "dy": None, "beta": None, "lo": _num(values[4]), "hi": _num(values[5]),
        "desc": values[6], "currency": "USD", "held": True,
    }


def quote_overview(ticker: str, conn=None) -> dict | None:
    """Use the database cache for a holding and Capital IQ live EOD otherwise."""
    name = validate_ticker(ticker)
    if conn is not None:
        cached = _cached_quote(conn, name)
        if cached is not None:
            return cached
        from src.model import db as _db
        held = conn.execute(_db.q(conn, "SELECT 1 FROM holdings WHERE ticker=? LIMIT 1"),
                            (name,)).fetchone()
        if held:
            raise HeldPriceCacheMiss(f"{name} is held but its nightly price cache is empty")

    now = time.time()
    key = f"ciq|{name}"
    hit = _QUOTE_CACHE.get(key)
    if hit and (now - hit[0]) < _TTL:
        return hit[1]
    cached = cache.get("quote", key)
    if cached is not cache.MISS:
        _QUOTE_CACHE[key] = (now, cached)
        return cached

    frame = _ciq_provider().get_price_history(
        [name], start=(dt.date.today() - dt.timedelta(days=14)).isoformat())
    if frame.empty:
        _QUOTE_CACHE[key] = (now, None)
        cache.set("quote", key, None, _TTL)
        return None
    closes = frame.sort_values("date")["close"].dropna().tolist()
    price = float(closes[-1])
    previous = float(closes[-2]) if len(closes) > 1 else None
    change = ((price / previous - 1) * 100) if previous else None
    meta = next((row for row in _ciq_provider().search_companies(name, limit=5)
                 if row["symbol"] == name), {})
    payload = {
        "t": name, "n": meta.get("name", name), "s": None,
        "industry": None, "exchange": meta.get("exchange", ""),
        "px": round(price, 2), "chg": round(change, 2) if change is not None else None,
        "mc": None, "pe": None, "pb": None, "evEbitda": None,
        "dy": None, "beta": None, "lo": None, "hi": None, "desc": None,
        "currency": "USD", "held": False,
    }
    _QUOTE_CACHE[key] = (now, payload)
    cache.set("quote", key, payload, _TTL)
    return payload


def live_series(ticker: str, period: str = "YTD", points: int = 64) -> dict:
    """Capital IQ EOD series for a validated, non-held ticker."""
    name = validate_ticker(ticker)
    period = period if period in {*_CIQ_DAYS, "YTD"} else "YTD"
    key = f"ciq|{name}|{period}"
    now = time.time()
    hit = _SERIES_CACHE.get(key)
    if hit and (now - hit[0]) < _TTL:
        return hit[1]
    cached = cache.get("series", key)
    if cached is not cache.MISS:
        _SERIES_CACHE[key] = (now, cached)
        return cached
    today = dt.date.today()
    start = (dt.date(today.year, 1, 1) if period == "YTD"
             else today - dt.timedelta(days=_CIQ_DAYS[period]))
    frame = _ciq_provider().get_price_history([name], start=start.isoformat())
    if frame.empty:
        out = {"dates": [], "close": [], "ret": None}
    else:
        frame = frame.sort_values("date")
        if len(frame) > points:
            indexes = sorted({round(i * (len(frame) - 1) / (points - 1)) for i in range(points)})
            frame = frame.iloc[indexes]
        closes = [round(float(value), 2) for value in frame["close"]]
        dates = frame["date"].tolist()
        ret = closes[-1] / closes[0] - 1 if len(closes) >= 2 and closes[0] else None
        out = {"dates": dates, "close": closes, "ret": ret}
    _SERIES_CACHE[key] = (now, out)
    cache.set("series", key, out, _TTL)
    return out


def institutional_holders(ticker: str, limit: int = 5) -> list[dict]:
    """Legacy Yahoo 13F panel; intentionally outside the price-data boundary."""
    ticker = validate_ticker(ticker)
    key = f"{ticker}|{limit}"
    now = time.time()
    hit = _HOLDERS_CACHE.get(key)
    if hit and (now - hit[0]) < _TTL:
        return hit[1]
    cached = cache.get("holders", key)
    if cached is not cache.MISS:
        _HOLDERS_CACHE[key] = (now, cached)
        return cached
    try:
        frame = yf.Ticker(to_yf(ticker)).institutional_holders
    except Exception:  # best-effort auxiliary research data
        frame = None

    out: list[dict] = []
    if frame is not None and not frame.empty:
        columns = {str(column).lower(): column for column in frame.columns}

        def pick(*names):
            return next((columns[name] for name in names if name in columns), None)

        holder_col = pick("holder")
        percent_col = pick("pctheld", "% out")
        shares_col = pick("shares")
        value_col = pick("value")
        rows = frame.sort_values(shares_col, ascending=False) if shares_col else frame
        for _, row in rows.head(limit).iterrows():
            percent = _num(row.get(percent_col)) if percent_col else None
            if percent is not None and percent_col and str(percent_col).lower() == "pctheld":
                percent *= 100
            shares = _num(row.get(shares_col)) if shares_col else None
            value = _num(row.get(value_col)) if value_col else None
            holder = row.get(holder_col) if holder_col else None
            out.append({
                "holder": str(holder) if holder is not None else "—",
                "pct": round(percent, 2) if percent is not None else None,
                "shares": int(shares) if shares is not None else None,
                "value": round(value / 1e6, 1) if value is not None else None,
            })
    _HOLDERS_CACHE[key] = (now, out)
    cache.set("holders", key, out, _TTL)
    return out
