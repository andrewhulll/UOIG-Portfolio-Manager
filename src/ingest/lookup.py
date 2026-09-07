"""Live Yahoo Finance lookup for arbitrary equities (search + quote + series).

Powers the terminal's global search box and lets any equity ticker — not just a
portfolio holding — open a populated stock page. Everything here is read-only
yfinance; results are cached in-process for a few minutes so re-querying is cheap.

Three public helpers:
  search_symbols(q)   -> [{symbol, name, exchange}]  (equities only)
  quote_overview(t)   -> overview dict mirroring api/build.py holding fields
  live_series(t, per) -> {dates, close, ret}  (same shape as analytics.series)
"""
from __future__ import annotations

import math
import time

import pandas as pd
import yfinance as yf

from src.ingest.providers import yf_ticker, yf_retry, yf_session
from src.model import cache

_SEARCH_CACHE: dict[str, tuple[float, list]] = {}
_QUOTE_CACHE: dict[str, tuple[float, dict]] = {}
_SERIES_CACHE: dict[str, tuple[float, dict]] = {}
_HOLDERS_CACHE: dict[str, tuple[float, list]] = {}
_TTL = 300  # seconds

# yfinance history() period / interval per terminal period button.
_YF_PERIOD = {"1M": "1mo", "3M": "3mo", "6M": "6mo", "YTD": "ytd", "1Y": "1y", "5Y": "5y"}


def _num(v):
    try:
        f = float(v)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return None


# ---------- search ----------
def search_symbols(query: str, limit: int = 8) -> list[dict]:
    """Yahoo Finance search, restricted to equities. Empty list on any failure."""
    q = (query or "").strip()
    if len(q) < 1:
        return []
    key = f"{q.lower()}|{limit}"
    hit = _SEARCH_CACHE.get(key)
    now = time.time()
    if hit and (now - hit[0]) < _TTL:
        return hit[1]
    cached = cache.get("search", key)
    if cached is not cache.MISS:
        value, age = cached
        _SEARCH_CACHE[key] = (now - age, value)
        return value

    out: list[dict] = []

    def _do_search():
        sess = yf_session()
        if sess is not None:
            try:
                return yf.Search(q, max_results=max(limit * 3, 12), news_count=0, session=sess)
            except Exception:  # noqa: BLE001
                pass
        return yf.Search(q, max_results=max(limit * 3, 12), news_count=0)

    try:
        res = yf_retry(_do_search, retry_empty=False)
        for r in ((res.quotes if res else None) or []):
            if r.get("quoteType") != "EQUITY":
                continue
            sym = r.get("symbol")
            if not sym:
                continue
            name = r.get("longname") or r.get("shortname") or sym
            exch = r.get("exchDisp") or r.get("exchange") or ""
            out.append({
                "symbol": sym, "name": name, "exchange": exch,
                # Yahoo's search endpoint carries sector/industry too — quote_overview
                # uses these as a fallback when the heavier .info endpoint is empty.
                "sector": r.get("sector"), "industry": r.get("industry"),
            })
            if len(out) >= limit:
                break
    except Exception:  # noqa: BLE001 — search is best-effort
        out = []

    _SEARCH_CACHE[key] = (now, out)
    if out:
        cache.set("search", key, out, _TTL)
    return out


# ---------- quote / overview ----------
def quote_overview(ticker: str) -> dict | None:
    """Overview fields for any equity, shaped like a holding row so the stock
    page can render off-portfolio names. Returns None if not a real equity."""
    t = ticker.upper()
    now = time.time()
    hit = _QUOTE_CACHE.get(t)
    if hit and (now - hit[0]) < _TTL:
        return hit[1]
    cached = cache.get("quote", t)
    if cached is not cache.MISS:
        value, age = cached
        _QUOTE_CACHE[t] = (now - age, value)
        return value

    tk = yf_ticker(t)
    info = yf_retry(lambda: tk.info) or {}

    # fast_info is chart-API-backed and stays reachable even when the heavier
    # .info/quoteSummary endpoint comes back empty (e.g. throttled in prod).
    # Attribute access applies its snake_case aliasing; .get() does not.
    try:
        fi = tk.fast_info
    except Exception:  # noqa: BLE001
        fi = None

    def _fi(name):
        try:
            return getattr(fi, name) if fi is not None else None
        except Exception:  # noqa: BLE001
            return None

    # yf.Search stays reachable too, and carries name/sector/industry — use it
    # to fill those in when .info is empty (an exact-symbol hit only).
    search_hit: dict = {}
    if not info:
        search_hit = next(
            (r for r in search_symbols(t, limit=5) if r.get("symbol", "").upper() == t),
            {},
        )

    qtype = info.get("quoteType") or _fi("quote_type")
    px = (_num(info.get("currentPrice")) or _num(info.get("regularMarketPrice"))
          or _num(_fi("last_price")))

    # Reject non-equities and dead symbols (no price / no type from any source).
    if qtype is not None and qtype != "EQUITY":
        _QUOTE_CACHE[t] = (now, None)
        cache.set("quote", t, None, _TTL)   # confirmed non-equity: cache the None hit
        return None
    if px is None:
        _QUOTE_CACHE[t] = (now, None)
        return None

    prev = (_num(info.get("regularMarketPreviousClose")) or _num(info.get("previousClose"))
            or _num(_fi("previous_close")) or _num(_fi("regular_market_previous_close")))
    chg = ((px - prev) / prev * 100) if (prev and px is not None) else _num(info.get("regularMarketChangePercent"))

    mc = _num(info.get("marketCap")) or _num(_fi("market_cap"))
    pe = _num(info.get("forwardPE")) or _num(info.get("trailingPE"))
    pb = _num(info.get("priceToBook"))
    ev_ebitda = _num(info.get("enterpriseToEbitda"))
    beta = _num(info.get("beta"))

    # Dividend yield -> percent. yfinance has used both fractions and percents;
    # prefer the trailing rate / price, fall back to the reported yield field.
    rate = _num(info.get("trailingAnnualDividendRate")) or _num(info.get("dividendRate"))
    if rate is not None and px:
        dy = rate / px * 100
    else:
        raw = _num(info.get("dividendYield"))
        dy = (raw if (raw is not None and raw > 1) else (raw * 100 if raw is not None else None))

    lo = _num(info.get("fiftyTwoWeekLow")) or _num(_fi("year_low"))
    hi = _num(info.get("fiftyTwoWeekHigh")) or _num(_fi("year_high"))

    payload = {
        "t": t,
        "n": info.get("longName") or info.get("shortName") or search_hit.get("name") or t,
        "s": info.get("sector") or search_hit.get("sector"),
        "industry": info.get("industry") or search_hit.get("industry"),
        "exchange": (info.get("fullExchangeName") or info.get("exchange")
                     or _fi("exchange") or search_hit.get("exchange") or ""),
        "px": round(px, 2),
        "chg": round(chg, 2) if chg is not None else None,
        "mc": round(mc / 1e9, 2) if mc is not None else None,  # billions
        "pe": round(pe, 2) if pe is not None else None,
        "pb": round(pb, 2) if pb is not None else None,
        "evEbitda": round(ev_ebitda, 2) if ev_ebitda is not None else None,
        "dy": round(dy, 2) if dy is not None else None,
        "beta": round(beta, 2) if beta is not None else None,
        "lo": round(lo, 2) if lo is not None else None,
        "hi": round(hi, 2) if hi is not None else None,
        "desc": info.get("longBusinessSummary"),
        "currency": info.get("currency") or _fi("currency") or "USD",
        "held": False,
    }
    _QUOTE_CACHE[t] = (now, payload)
    cache.set("quote", t, payload, _TTL)
    return payload


# ---------- institutional holders ----------
def institutional_holders(ticker: str, limit: int = 5) -> list[dict]:
    """Top institutional shareholders from yfinance's institutional_holders
    endpoint. Returns up to `limit` rows [{holder, pct, shares, value}], largest
    by shares first. Empty list when Yahoo has no 13F data for the symbol."""
    t = ticker.upper()
    key = f"{t}|{limit}"
    now = time.time()
    hit = _HOLDERS_CACHE.get(key)
    if hit and (now - hit[0]) < _TTL:
        return hit[1]
    cached = cache.get("holders", key)
    if cached is not cache.MISS:
        value, age = cached
        _HOLDERS_CACHE[key] = (now - age, value)
        return value

    tk = yf_ticker(t)
    df = yf_retry(lambda: tk.institutional_holders)

    out: list[dict] = []
    if df is not None and not df.empty:
        # yfinance has shipped a few column spellings; resolve each defensively.
        cols = {str(c).lower(): c for c in df.columns}

        def pick(*names):
            for n in names:
                if n in cols:
                    return cols[n]
            return None

        c_holder = pick("holder")
        c_pct = pick("pctheld", "% out")
        c_shares = pick("shares")
        c_value = pick("value")

        rows = df.sort_values(c_shares, ascending=False) if c_shares else df
        for _, r in rows.head(limit).iterrows():
            pct = _num(r.get(c_pct)) if c_pct else None
            # pctHeld comes as a fraction (0.083); legacy "% Out" already a percent.
            if pct is not None and c_pct and str(c_pct).lower() == "pctheld":
                pct *= 100
            shares = _num(r.get(c_shares)) if c_shares else None
            value = _num(r.get(c_value)) if c_value else None
            holder = r.get(c_holder) if c_holder else None
            out.append({
                "holder": str(holder) if holder is not None else "—",
                "pct": round(pct, 2) if pct is not None else None,
                "shares": int(shares) if shares is not None else None,
                "value": round(value / 1e6, 1) if value is not None else None,  # $M
            })

    _HOLDERS_CACHE[key] = (now, out)
    if df is not None:   # only persist a real fetch, not a transient failure's []
        cache.set("holders", key, out, _TTL)
    return out


# ---------- live price series ----------
def live_series(ticker: str, period: str = "YTD", points: int = 64) -> dict:
    """Live yfinance price series for any ticker (charts off-portfolio names)."""
    t = ticker.upper()
    per = period if period in _YF_PERIOD else "YTD"
    key = f"{t}|{per}"
    now = time.time()
    hit = _SERIES_CACHE.get(key)
    if hit and (now - hit[0]) < _TTL:
        return hit[1]
    cached = cache.get("series", key)
    if cached is not cache.MISS:
        value, age = cached
        _SERIES_CACHE[key] = (now - age, value)
        return value

    tk = yf_ticker(t)
    h = yf_retry(lambda: tk.history(period=_YF_PERIOD[per], interval="1d", auto_adjust=False))
    if h is None:
        h = pd.DataFrame()

    if h is None or h.empty or "Close" not in h:
        out = {"dates": [], "close": [], "ret": None}
        _SERIES_CACHE[key] = (now, out)
        return out

    sub = h.dropna(subset=["Close"])
    closes = [round(float(x), 2) for x in sub["Close"].to_numpy()]
    dates = [d.date().isoformat() for d in sub.index]
    if len(closes) > points:
        step = (len(closes) - 1) / (points - 1)
        idx = sorted({round(i * step) for i in range(points)})
        closes = [closes[i] for i in idx]
        dates = [dates[i] for i in idx]
    ret = (closes[-1] / closes[0] - 1) if len(closes) >= 2 and closes[0] else None

    out = {"dates": dates, "close": closes, "ret": ret}
    _SERIES_CACHE[key] = (now, out)
    cache.set("series", key, out, _TTL)
    return out
