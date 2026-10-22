"""Per-stock data tools for the Ask-Claude co-pilot.

Exposes the same enriched data the terminal's stock-detail tabs use — live
yfinance fundamentals/earnings/news/analyst research, Kalshi prediction markets,
and the team's written thesis — as read-only tools the model can pull on demand.
Payloads are JSON, trimmed to bound token cost.
"""
from __future__ import annotations

import json

from src.config import db_path, load_config
from src.ingest.predictions import stock_predictions
from src.ingest.research import closed_snapshot, stock_news, stock_research
from src.ingest.thesis import stock_thesis
from src.ingest.universe import is_owned
from src.model.schema import get_connection

_LIMIT = 9000


def _stock_bundle(ticker: str) -> dict:
    conn = get_connection(db_path(load_config()))
    try:
        owned = is_owned(conn, ticker)
    finally:
        conn.close()
    payload = closed_snapshot(ticker) if owned else stock_research(ticker)
    # News is deliberately the only short-lived holding datum.
    news = stock_news(ticker)
    return {**payload, "news": news.get("news") or [], "owned": owned}


def _json(obj) -> str:
    s = json.dumps(obj, default=str, separators=(",", ":"))
    return s if len(s) <= _LIMIT else s[:_LIMIT] + "…[truncated]"


TOOLS = [
    {"name": "get_stock_fundamentals",
     "description": "Latest stored data for a holding: quarterly financials (revenue, "
                    "margins, net income, FCF, EPS), the most recent earnings report "
                    "(actual vs estimate, surprise, next date), recent news headlines, and "
                    "analyst research (consensus rating, price-target low/mean/high, forward "
                    "estimates, recent upgrades/downgrades). Use for any question about a "
                    "holding's financials, earnings, news, or the Street's view.",
     "input_schema": {"type": "object", "properties": {
         "ticker": {"type": "string", "description": "Ticker, e.g. NVDA."}}, "required": ["ticker"]}},
    {"name": "get_predictions",
     "description": "Kalshi prediction-market cards mapped to a holding (curated). Each card "
                    "has the market question, top outcomes with implied probability, and "
                    "volume. Use for forward-looking, market-implied odds on a name.",
     "input_schema": {"type": "object", "properties": {
         "ticker": {"type": "string"}}, "required": ["ticker"]}},
    {"name": "get_thesis",
     "description": "The team's most recent investment thesis (three points, with date and "
                    "analyst) for a holding, from THESIS.md. Use when asked why we own a name "
                    "or what the pitch is.",
     "input_schema": {"type": "object", "properties": {
         "ticker": {"type": "string"}}, "required": ["ticker"]}},
    {"name": "search_thesis_points",
     "description": "Semantic search over UOIG's archive of historical student equity-research "
                    "theses (651 reports, ~396 tickers, 2013-2026). Use for thematic or "
                    "comparative questions ('moat plays in healthcare', 'who argued margin "
                    "expansion since 2024'). Results are historical analysis, not current fact: "
                    "cite ticker, report_date and version_rank, and flag views with "
                    "version_rank > 1 as superseded. Older rows have a null title.",
     "input_schema": {"type": "object", "properties": {
         "query": {"type": "string", "description": "Natural-language description of the thesis."},
         "k": {"type": "integer", "description": "Results to return (default 8, max 20)."},
         "ticker": {"type": "string", "description": "Restrict to one ticker."},
         "since": {"type": "string", "description": "Earliest report date, YYYY-MM-DD (excludes undated reports)."},
         "until": {"type": "string", "description": "Latest report date, YYYY-MM-DD (excludes undated reports)."},
         "latest_only": {"type": "boolean", "description": "Only each ticker's most recent report (use for 'current view')."}},
         "required": ["query"]}},
    {"name": "get_ticker_history",
     "description": "Every archived UOIG thesis point for a ticker across all pitches and "
                    "updates, oldest to newest. Use when asked what UOIG thought of a company "
                    "or how the view changed. Returns nothing for tickers UOIG never covered; "
                    "say so rather than inventing a thesis.",
     "input_schema": {"type": "object", "properties": {
         "ticker": {"type": "string"}}, "required": ["ticker"]}},
]


def run_tool(name: str, inp: dict):
    """Execute a data tool. Returns (content, is_error), or None if not handled here."""
    ticker = str((inp or {}).get("ticker", "")).upper().strip()
    try:
        if name == "search_thesis_points":
            from src.ingest import thesis_rag
            return (_json(thesis_rag.search_thesis_points(
                str(inp.get("query", "")), inp.get("k", 8), ticker or None,
                inp.get("since"), inp.get("until"), bool(inp.get("latest_only")))), False)
        if name == "get_ticker_history":
            from src.ingest import thesis_rag
            return (_json(thesis_rag.ticker_history(ticker)), False)
        if name == "get_stock_fundamentals":
            return (_json(_stock_bundle(ticker)), False)
        if name == "get_predictions":
            return (_json(stock_predictions(ticker)), False)
        if name == "get_thesis":
            return (_json(stock_thesis(ticker)), False)
    except Exception as exc:  # noqa: BLE001
        return (f"Tool error: {exc}", True)
    return None
