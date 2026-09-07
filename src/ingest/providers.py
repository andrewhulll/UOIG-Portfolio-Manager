"""Market-data provider adapter.

A thin, swappable interface so the rest of the system never depends on a
specific vendor. Phase 1 ships the yfinance implementation; Tiingo/FMP/Bloomberg
can be added later by implementing the same three methods.
"""
from __future__ import annotations

import datetime as dt
import time
from typing import Protocol

import pandas as pd
import yfinance as yf

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


class MarketDataProvider(Protocol):
    def get_price_history(self, tickers, start, end=None) -> pd.DataFrame: ...
    def get_dividends(self, tickers, start, end=None) -> pd.DataFrame: ...
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
        for attempt in range(self.retries + 1):
            try:
                h = yf.Ticker(to_yf(ticker)).history(
                    start=start, end=end, auto_adjust=False, actions=True
                )
                self._cache[key] = h
                return h
            except Exception:
                time.sleep(self.pause * (attempt + 1))
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
