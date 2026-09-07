"""Time-series helpers for the terminal UI: price series for charts, period and
month-to-date returns, trailing dividend yield, and a synthetic current-weights
fund index (reconstructed because we have no historical NAV).
"""
from __future__ import annotations

import datetime as dt
import sqlite3

import numpy as np
import pandas as pd

from src.model import db as _db

PERIODS = ["1M", "3M", "6M", "YTD", "1Y", "5Y"]
_DAYS = {"1M": 30, "3M": 91, "6M": 182, "1Y": 365, "5Y": 1826}


def period_start(last: dt.date, period: str) -> dt.date:
    if period == "YTD":
        return dt.date(last.year, 1, 1)
    return last - dt.timedelta(days=_DAYS.get(period, 365))


def price_frame(conn: sqlite3.Connection) -> pd.DataFrame:
    p = pd.read_sql("SELECT ticker, date, close, adj_close FROM prices "
                    "WHERE source = 'yfinance'", conn)
    p["date"] = pd.to_datetime(p["date"])
    return p.sort_values(["ticker", "date"])


def _window(pf: pd.DataFrame, ticker: str, period: str) -> pd.DataFrame:
    s = pf[pf.ticker == ticker]
    if s.empty:
        return s
    start = pd.Timestamp(period_start(s["date"].max().date(), period))
    w = s[s["date"] >= start]
    return w if len(w) >= 2 else s.tail(2)


def ticker_series(pf: pd.DataFrame, ticker: str, period: str, points: int = 64) -> dict:
    w = _window(pf, ticker, period)
    if w.empty:
        return {"dates": [], "close": []}
    if len(w) > points:
        idx = np.linspace(0, len(w) - 1, points).round().astype(int)
        w = w.iloc[idx]
    return {"dates": [d.strftime("%Y-%m-%d") for d in w["date"]],
            "close": [round(float(x), 2) for x in w["close"]]}


def period_return(pf: pd.DataFrame, ticker: str, period: str, col: str = "adj_close"):
    w = _window(pf, ticker, period)
    if len(w) < 2 or w[col].iloc[0] == 0:
        return None
    return float(w[col].iloc[-1] / w[col].iloc[0] - 1)


def trailing_return(pf: pd.DataFrame, ticker: str, days: int):
    """Simple price return over the trailing `days` calendar window (e.g. 7 for a
    one-week move). Returns None if the ticker has too little history."""
    s = pf[pf.ticker == ticker]
    if len(s) < 2:
        return None
    last = s["date"].max()
    w = s[s["date"] >= last - pd.Timedelta(days=days)]
    if len(w) < 2:
        w = s.tail(2)
    base = w["close"].iloc[0]
    return float(w["close"].iloc[-1] / base - 1) if base else None


def mtd_return(pf: pd.DataFrame, ticker: str):
    s = pf[pf.ticker == ticker]
    if len(s) < 2:
        return None
    last = s["date"].max()
    mstart = pd.Timestamp(dt.date(last.year, last.month, 1))
    prior = s[s["date"] < mstart]
    base = prior["adj_close"].iloc[-1] if len(prior) else s["adj_close"].iloc[0]
    return float(s["adj_close"].iloc[-1] / base - 1) if base else None


def div_yield_ttm(conn: sqlite3.Connection, ticker: str, price: float):
    if not price:
        return None
    last = conn.execute(_db.q(conn, "SELECT MAX(date) FROM prices WHERE ticker=? AND source='yfinance'"),
                        (ticker,)).fetchone()[0]
    if not last:
        return None
    cutoff = (dt.date.fromisoformat(last) - dt.timedelta(days=365)).isoformat()
    total = conn.execute(_db.q(conn, "SELECT COALESCE(SUM(amount),0) FROM dividends "
                                     "WHERE ticker=? AND ex_date>=?"), (ticker, cutoff)).fetchone()[0]
    return float(total) / price * 100 if total else 0.0


def synthetic_index(rets: pd.DataFrame, weights: dict, period: str) -> dict:
    """Reconstructed current-weights fund index (base 100) over the period."""
    cols = [t for t in weights if t in rets.columns]
    if not cols:
        return {"dates": [], "values": [], "ret": None}
    last = rets.index.max()
    start = pd.Timestamp(period_start(last.date(), period))
    win = rets.loc[rets.index >= start, cols]
    if win.empty:
        return {"dates": [], "values": [], "ret": None}
    w = pd.Series({t: weights[t] for t in cols})
    w = w / w.sum()
    port = win.mul(w, axis=1).sum(axis=1, min_count=1).fillna(0.0)
    idx = (1 + port).cumprod() * 100
    return {"dates": [d.strftime("%Y-%m-%d") for d in idx.index],
            "values": [round(float(v), 3) for v in idx.values],
            "ret": float(idx.iloc[-1] / 100 - 1)}
