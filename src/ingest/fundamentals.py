"""Pull company fundamentals from yfinance into the `fundamentals` table.

Captures the richer fields the redesigned UI needs and that we don't compute
ourselves: GICS/Yahoo sector, P/E (forward, falling back to trailing),
price/book, market cap, 52-week range, and a business summary. Dividend yield
is computed from our own dividends table elsewhere, not taken from here.
"""
from __future__ import annotations

import datetime as dt
import sqlite3

import yfinance as yf

from src.config import db_path
from src.ingest.providers import to_yf
from src.ingest.universe import owned_tickers
from src.model import db, schema


def _f(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _info(ticker: str) -> dict:
    try:
        return yf.Ticker(to_yf(ticker)).info or {}
    except Exception:
        return {}


def _provider_yield(info: dict) -> float | None:
    """TTM dividend yield straight from the provider (#43 fallback).

    Used when our own dividends table has no payouts for the ticker; mirrors
    the quote path's logic (rate/price preferred, reported yield field as backup).
    """
    px = _f(info.get("currentPrice")) or _f(info.get("regularMarketPrice"))
    rate = _f(info.get("trailingAnnualDividendRate")) or _f(info.get("dividendRate"))
    if rate is not None and px:
        return rate / px * 100
    raw = _f(info.get("dividendYield"))
    if raw is None:
        return None
    return raw if raw > 1 else raw * 100


def pull_fundamentals(cfg: dict, conn: sqlite3.Connection | None = None,
                      tickers: list[str] | None = None) -> dict:
    own = conn is None
    if own:
        conn = schema.get_connection(db_path(cfg))
    schema.create_schema(conn)
    if tickers is None:
        tickers = owned_tickers(conn)

    today = dt.date.today().isoformat()
    summary = {"updated": 0, "failed": []}
    rows = []
    for t in tickers:
        info = _info(t)
        if not info:
            summary["failed"].append(t)
            continue
        rows.append(
            (t, info.get("sector"),
             _f(info.get("forwardPE") or info.get("trailingPE")),
             _f(info.get("priceToBook")), _f(info.get("enterpriseToEbitda")),
             _f(info.get("marketCap")),
             _f(info.get("fiftyTwoWeekLow")), _f(info.get("fiftyTwoWeekHigh")),
             (info.get("longBusinessSummary") or "")[:600], today,
             _provider_yield(info), _f(info.get("forwardPE")),
             _f(info.get("revenueGrowth")),
             info.get("fullExchangeName") or info.get("exchange"),
             _f(info.get("regularMarketVolume") or info.get("volume")),
             _f(info.get("averageVolume")))
        )
        summary["updated"] += 1
    if rows:
        db.executemany(
            conn,
            db.upsert_sql(conn, "fundamentals",
                          ["ticker", "gics_sector", "pe", "pb", "ev_ebitda", "market_cap",
                           "week52_low", "week52_high", "description", "updated",
                           "div_yield_provider", "forward_pe", "revenue_growth",
                           "exchange", "volume", "average_volume"], ["ticker"]),
            rows
        )
    conn.commit()
    if own:
        conn.close()
    return summary
