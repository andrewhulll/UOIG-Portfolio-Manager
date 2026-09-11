"""Market-data provider adapter.

A thin, swappable interface so the rest of the system never depends on a
specific vendor. Phase 1 ships the yfinance implementation; Tiingo/FMP/Bloomberg
can be added later by implementing the same three methods.
"""
from __future__ import annotations

import datetime as dt
import logging
import time
from typing import Protocol

import pandas as pd
import yfinance as yf

log = logging.getLogger("uoig.market_data")

PRICE_COLS = ["ticker", "date", "close", "adj_close"]
DIV_COLS = ["ticker", "ex_date", "amount"]


def to_yf(ticker: str) -> str:
    """Map our ticker convention to Yahoo's (e.g. BRK.B -> BRK-B)."""
    return ticker.replace(".", "-")


def _days_ago(n: int) -> str:
    return (dt.date.today() - dt.timedelta(days=n)).isoformat()


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


def _is_auth_error(exc: Exception) -> bool:
    """True for yfinance's 'Invalid Crumb' 401 — a stuck cookie/crumb, not a
    transient network blip. yfinance caches the crumb in a process-wide
    singleton (one session for every ticker/thread), so once it goes bad every
    call fails identically until something clears it."""
    msg = str(exc)
    return "Invalid Crumb" in msg or "401" in msg


def reset_yf_auth() -> None:
    """Clear yfinance's cached crumb/cookie so the next call re-negotiates
    both from scratch, instead of repeating the same failed auth forever."""
    try:
        from yfinance.data import YfData
        data = YfData()
        with data._cookie_lock:
            data._crumb = None
            data._cookie = None
    except Exception:  # noqa: BLE001 — best-effort; never break the caller over this
        log.warning("failed to reset yfinance auth state", exc_info=True)


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


def yf_retry(fn, *, tries: int = 3, base: float = 0.6, retry_empty: bool = True, label: str = ""):
    """Call fn() with exponential backoff. Retries on exception, and (when
    retry_empty) on a falsy/empty result — the common shapes a 429 takes. Returns
    the last result (None if every attempt raised); never raises."""
    last = None
    last_exc = None
    for i in range(tries):
        try:
            last = fn()
            last_exc = None
        except Exception as exc:  # noqa: BLE001
            last = None
            last_exc = exc
            log.warning("yfinance call failed (attempt %d/%d)%s: %s", i + 1, tries,
                        f" [{label}]" if label else "", exc, extra={"yf_label": label})
            if _is_auth_error(exc):
                reset_yf_auth()
        else:
            if not retry_empty or _nonempty(last):
                return last
        if i < tries - 1:
            time.sleep(base * (2 ** i))
    if last_exc is not None:
        log.error("yfinance call exhausted retries%s: %s", f" [{label}]" if label else "",
                   last_exc, extra={"yf_label": label})
    elif retry_empty:
        log.error("yfinance call returned empty after %d attempts%s", tries,
                  f" [{label}]" if label else "", extra={"yf_label": label})
    return last


class MarketDataProvider(Protocol):
    def get_price_history(self, tickers, start, end=None) -> pd.DataFrame: ...
    def get_dividends(self, tickers, start, end=None) -> pd.DataFrame: ...
    def get_splits(self, tickers, start, end=None) -> pd.DataFrame: ...
    def get_latest_prices(self, tickers) -> dict[str, float]: ...


class YFinanceProvider:
    """Yahoo Finance via yfinance. Per-ticker fetch (robust parsing), with a
    small in-instance cache so price + dividend pulls share one download."""

    def __init__(self, retries: int = 2, pause: float = 0.6):
        self.retries = retries
        self.pause = pause
        self._cache: dict[tuple, pd.DataFrame] = {}

    def _history(self, ticker, start, end) -> pd.DataFrame:
        key = (ticker, str(start), str(end))
        if key in self._cache:
            return self._cache[key]
        last_exc = None
        for attempt in range(self.retries + 1):
            try:
                h = yf.Ticker(to_yf(ticker)).history(
                    start=start, end=end, auto_adjust=False, actions=True
                )
                self._cache[key] = h
                return h
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                log.warning("yfinance history fetch failed (attempt %d/%d) for %s: %s",
                            attempt + 1, self.retries + 1, ticker, exc, extra={"ticker": ticker})
                if attempt < self.retries:
                    time.sleep(self.pause * (attempt + 1))
        log.error("yfinance history fetch exhausted retries for %s: %s", ticker, last_exc,
                   extra={"ticker": ticker})
        self._cache[key] = pd.DataFrame()
        return self._cache[key]

    def get_price_history(self, tickers, start, end=None) -> pd.DataFrame:
        frames = []
        for t in tickers:
            h = self._history(t, start, end)
            if h.empty or "Close" not in h:
                continue
            sub = h.dropna(subset=["Close"])  # drop the unfinalized current-day bar
            if sub.empty:
                continue
            adj = sub["Adj Close"] if "Adj Close" in sub else sub["Close"]
            frames.append(pd.DataFrame({
                "ticker": t,
                "date": [d.date().isoformat() for d in sub.index],
                "close": sub["Close"].to_numpy(),
                "adj_close": adj.to_numpy(),
            }))
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=PRICE_COLS)

    def get_dividends(self, tickers, start, end=None) -> pd.DataFrame:
        frames = []
        for t in tickers:
            h = self._history(t, start, end)
            if h.empty or "Dividends" not in h:
                continue
            d = h[h["Dividends"] > 0]
            if d.empty:
                continue
            frames.append(pd.DataFrame({
                "ticker": t,
                "ex_date": [x.date().isoformat() for x in d.index],
                "amount": d["Dividends"].to_numpy(),
            }))
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=DIV_COLS)

    def get_splits(self, tickers, start, end=None) -> pd.DataFrame:
        frames = []
        for t in tickers:
            h = self._history(t, start, end)
            if h.empty or "Stock Splits" not in h:
                continue
            s = h[h["Stock Splits"] > 0]
            if s.empty:
                continue
            frames.append(pd.DataFrame({
                "ticker": t,
                "date": [x.date().isoformat() for x in s.index],
                "ratio": s["Stock Splits"].to_numpy(),
            }))
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["ticker", "date", "ratio"])

    def get_latest_prices(self, tickers) -> dict[str, float]:
        ph = self.get_price_history(tickers, start=_days_ago(7))
        if ph.empty:
            return {}
        ph = ph.sort_values("date")
        return ph.groupby("ticker")["close"].last().to_dict()


def get_provider(cfg: dict) -> MarketDataProvider:
    name = (cfg.get("market_data") or {}).get("provider", "yfinance")
    if name == "yfinance":
        return YFinanceProvider()
    raise ValueError(f"Unknown market-data provider: {name!r}")
