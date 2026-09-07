"""Legacy Yahoo symbol formatting used by non-price research integrations.

Price data is provided by :mod:`src.ingest.capital_iq`; this helper remains for
the fundamentals, holders, and research tabs that are outside the Layer 1 price
cache migration.
"""
from __future__ import annotations

import time

import yfinance as yf


def to_yf(ticker: str) -> str:
    """Map the portfolio convention to Yahoo's legacy symbol convention."""
    return ticker.replace(".", "-")

# ---- yfinance resilience: a shared browser-impersonating session + retry ------
# Yahoo aggressively rate-limits (HTTP 429) plain datacenter requests. A curl_cffi
# session with a real Chrome TLS fingerprint is far less likely to be blocked, and
# a small retry/backoff rides out the transient 429s that remain. Both are
# best-effort: any failure falls back to yfinance's default behavior, so a call
# never breaks — it only degrades to the prior behavior.
_YF_SESSION = None
_YF_SESSION_TRIED = False


def yf_session():
    """A shared curl_cffi Session impersonating Chrome, or None if unavailable."""
    global _YF_SESSION, _YF_SESSION_TRIED
    if not _YF_SESSION_TRIED:
        _YF_SESSION_TRIED = True
        try:
            from curl_cffi import requests as _cffi
            _YF_SESSION = _cffi.Session(impersonate="chrome")
        except Exception:  # noqa: BLE001 — fall back to yfinance's default session
            _YF_SESSION = None
    return _YF_SESSION


def yf_ticker(ticker: str):
    """yf.Ticker for our ticker, using the impersonating session when available."""
    sess = yf_session()
    if sess is not None:
        try:
            return yf.Ticker(to_yf(ticker), session=sess)
        except Exception:  # noqa: BLE001 — some yfinance versions reject a session
            pass
    return yf.Ticker(to_yf(ticker))


def _nonempty(x) -> bool:
    if x is None:
        return False
    try:
        if hasattr(x, "empty"):      # pandas DataFrame / Series
            return not x.empty
    except Exception:  # noqa: BLE001
        return True
    if isinstance(x, (list, dict, str)):
        return len(x) > 0
    return True


def yf_retry(fn, *, tries: int = 3, base: float = 0.6, retry_empty: bool = True):
    """Call fn() with exponential backoff. Retries on exception, and (when
    retry_empty) on a falsy/empty result — the common shapes a 429 takes. Returns
    the last result (None if every attempt raised); never raises."""
    last = None
    for i in range(tries):
        try:
            last = fn()
        except Exception:  # noqa: BLE001
            last = None
        else:
            if not retry_empty or _nonempty(last):
                return last
        if i < tries - 1:
            time.sleep(base * (2 ** i))
    return last
