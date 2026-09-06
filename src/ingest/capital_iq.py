"""S&P Global Capital IQ price adapter.

The licensed ``spgmi_api_sdk`` distribution is intentionally imported lazily:
local analytics and unit tests do not need vendor credentials, while the nightly
job and live, off-portfolio lookups fail with an actionable configuration error.
"""
from __future__ import annotations

import datetime as dt
import math
import os
import re
from functools import lru_cache

import pandas as pd

PRICE_COLS = ["ticker", "date", "open", "high", "low", "close", "volume"]
MAX_IDENTIFIERS = 10  # Capital IQ SDK limit per function call.


class CapitalIQConfigurationError(RuntimeError):
    """The Capital IQ SDK or its credentials are unavailable."""


def validate_ticker(ticker: str) -> str:
    """Return a normalized ticker or reject it before any vendor API call."""
    value = (ticker or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9.\-]{0,14}", value):
        raise ValueError("ticker must contain only letters, numbers, periods, or hyphens")
    return value


def _identifier(ticker: str) -> str:
    # The SDK guide uses ``AAPL:`` for an exchange-agnostic ticker identifier.
    return f"{validate_ticker(ticker)}:"


@lru_cache(maxsize=1)
def sdk_client():
    username = (os.environ.get("SDK_USERNAME") or
                os.environ.get("CAPITAL_IQ_USERNAME") or "").strip()
    password = (os.environ.get("SDK_PASSWORD") or
                os.environ.get("CAPITAL_IQ_PASSWORD") or "").strip()
    if not username or not password:
        raise CapitalIQConfigurationError(
            "Capital IQ credentials are missing; set SDK_USERNAME and SDK_PASSWORD"
        )
    try:
        from spgmi_api_sdk.ciq.services import SDKDataServices
    except ImportError as exc:
        raise CapitalIQConfigurationError(
            "the licensed S&P Capital IQ Python SDK is not installed; install the "
            "spgmi_api_sdk_python tarball from the S&P support portal"
        ) from exc
    return SDKDataServices(username=username, password=password)


def _norm(value) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _frame(payload) -> pd.DataFrame:
    """Coerce SDK v2 response objects and v3 DataFrames to one DataFrame."""
    if isinstance(payload, pd.DataFrame):
        out = payload.copy()
    else:
        data = getattr(payload, "data", payload)
        if isinstance(data, pd.DataFrame):
            out = data.copy()
        elif isinstance(data, dict):
            nested = next((data[k] for k in ("data", "results", "result")
                           if isinstance(data.get(k), list)), None)
            out = pd.DataFrame(nested if nested is not None else [data])
        elif isinstance(data, (list, tuple)):
            out = pd.DataFrame(data)
        else:
            out = pd.DataFrame()
    if out.empty:
        return out
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = ["_".join(str(x) for x in c if str(x) != "") for c in out.columns]
    # SDK versions differ on whether identifier/date live in the index.
    if out.index.name or isinstance(out.index, pd.MultiIndex):
        out = out.reset_index()
    return out


def _column(df: pd.DataFrame, *aliases: str):
    cols = {_norm(c): c for c in df.columns}
    wanted = [_norm(a) for a in aliases]
    for alias in wanted:
        if alias in cols:
            return cols[alias]
    for alias in wanted:
        for key, original in cols.items():
            if alias and alias in key:
                return original
    return None


def _number(value):
    if isinstance(value, dict):
        value = value.get("value", value.get("Value"))
    if isinstance(value, (list, tuple)) and len(value) == 1:
        value = value[0]
    try:
        result = float(str(value).replace(",", ""))
        return None if math.isnan(result) or math.isinf(result) else result
    except (TypeError, ValueError):
        return None


def _iso_date(value, fallback: str | None = None) -> str | None:
    if isinstance(value, (int, float)) or (
            isinstance(value, str) and not re.search(r"\d{1,4}[-/]\d{1,2}[-/]\d{1,4}", value)):
        return fallback
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return fallback
    return parsed.date().isoformat()


def _text(row, column) -> str:
    if column is None:
        return ""
    value = row.get(column)
    return "" if value is None or pd.isna(value) else str(value).strip()


def _ticker_for(value, requested: list[str]) -> str | None:
    raw = str(value or "").strip().upper().rstrip(":")
    exact = {t: t for t in requested}
    identifiers = {_identifier(t).upper().rstrip(":"): t for t in requested}
    if raw in exact:
        return exact[raw]
    if raw in identifiers:
        return identifiers[raw]
    # A returned identifier may retain an exchange suffix (MSFT:NASDAQGS).
    before_exchange = raw.split(":", 1)[0]
    if before_exchange in exact:
        return exact[before_exchange]
    return requested[0] if len(requested) == 1 else None


def normalize_prices(payload, requested: list[str], default_date: str | None = None) -> pd.DataFrame:
    """Normalize Capital IQ's wide or long pricing DataFrame into OHLCV rows.

    S&P has shipped both response-object and direct-DataFrame SDKs. Supporting
    the common wide and mnemonic/value shapes keeps the cache boundary stable
    across those client versions.
    """
    requested = [validate_ticker(t) for t in requested]
    df = _frame(payload)
    if df.empty:
        return pd.DataFrame(columns=PRICE_COLS)

    id_col = _column(df, "identifier", "inputidentifier", "ticker", "symbol")
    date_col = _column(df, "pricingdate", "pricedate", "asofdate", "date", "perioddate")
    mnemonic_col = _column(df, "mnemonic", "dataitemmnemonic", "dataitem", "item")
    value_col = _column(df, "dataitemvalue", "value")

    # Long response: one row per identifier/date/mnemonic.
    if mnemonic_col is not None and value_col is not None:
        grouped: dict[tuple[str, str], dict] = {}
        for _, row in df.iterrows():
            ticker = _ticker_for(row.get(id_col) if id_col is not None else None, requested)
            date = _iso_date(row.get(date_col) if date_col is not None else None, default_date)
            if not ticker or not date:
                continue
            item = _norm(row.get(mnemonic_col))
            field = next((name for key, name in (
                ("iqopenprice", "open"), ("iqhighprice", "high"),
                ("iqlowprice", "low"), ("iqclosepriceadj", "_adjusted_close"),
                ("iqcloseprice", "close"), ("iqvolume", "volume"),
            ) if key in item), None)
            if field:
                grouped.setdefault((ticker, date), {"ticker": ticker, "date": date})[field] = _number(row[value_col])
        rows = list(grouped.values())
        for row in rows:
            if row.get("close") is None:
                row["close"] = row.get("_adjusted_close")
    elif mnemonic_col is not None:
        # Some time-series SDK responses put dates in column headers, with one
        # row per mnemonic (the classic Capital IQ GDST shape).
        date_columns = [(column, _iso_date(column)) for column in df.columns]
        date_columns = [(column, date) for column, date in date_columns if date]
        grouped = {}
        for _, row in df.iterrows():
            ticker = _ticker_for(row.get(id_col) if id_col is not None else None, requested)
            item = _norm(row.get(mnemonic_col))
            field = next((name for key, name in (
                ("iqopenprice", "open"), ("iqhighprice", "high"),
                ("iqlowprice", "low"), ("iqclosepriceadj", "_adjusted_close"),
                ("iqcloseprice", "close"), ("iqvolume", "volume"),
            ) if key in item), None)
            if not ticker or not field:
                continue
            for column, date in date_columns:
                grouped.setdefault((ticker, date), {"ticker": ticker, "date": date})[field] = _number(row[column])
        rows = list(grouped.values())
        for row in rows:
            if row.get("close") is None:
                row["close"] = row.get("_adjusted_close")
    else:
        fields = {
            "open": _column(df, "iqopenprice", "openprice", "open"),
            "high": _column(df, "iqhighprice", "highprice", "high"),
            "low": _column(df, "iqlowprice", "lowprice", "low"),
            "close": (_column(df, "iqcloseprice", "closeprice", "close") or
                      _column(df, "iqclosepriceadj", "adjustedclose", "adjclose")),
            "volume": _column(df, "iqvolume", "volume"),
        }
        rows = []
        for _, row in df.iterrows():
            ticker = _ticker_for(row.get(id_col) if id_col is not None else None, requested)
            date = _iso_date(row.get(date_col) if date_col is not None else None, default_date)
            if not ticker or not date:
                continue
            item = {"ticker": ticker, "date": date}
            for field, col in fields.items():
                item[field] = _number(row.get(col)) if col is not None else None
            rows.append(item)

    out = pd.DataFrame(rows, columns=PRICE_COLS)
    if out.empty:
        return out
    out = out.dropna(subset=["close"]).drop_duplicates(["ticker", "date"], keep="last")
    out["volume"] = out["volume"].map(lambda x: int(x) if x is not None and not pd.isna(x) else None)
    return out.sort_values(["ticker", "date"]).reset_index(drop=True)


class CapitalIQProvider:
    def __init__(self, client=None):
        self._client = client

    @property
    def client(self):
        if self._client is None:
            self._client = sdk_client()
        return self._client

    def get_price_history(self, tickers, start, end=None) -> pd.DataFrame:
        names = [validate_ticker(t) for t in tickers]
        if not names:
            return pd.DataFrame(columns=PRICE_COLS)
        frames = []
        finish = dt.date.fromisoformat(str(end)) if end else dt.date.today()
        begin = dt.date.fromisoformat(str(start))
        properties = {
            "startDate": begin.strftime("%m/%d/%Y"),
            "endDate": finish.strftime("%m/%d/%Y"),
            "frequency": "D",
            "currencyId": "USD",
            "currencyConversionModeId": "HISTORICAL",
        }
        for offset in range(0, len(names), MAX_IDENTIFIERS):
            chunk = names[offset:offset + MAX_IDENTIFIERS]
            payload = self.client.get_pricing_info_time_series(
                identifiers=[_identifier(t) for t in chunk], properties=properties
            )
            frames.append(normalize_prices(payload, chunk))
        frames = [f for f in frames if not f.empty]
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=PRICE_COLS)

    def get_latest_prices(self, tickers) -> dict[str, float]:
        start = (dt.date.today() - dt.timedelta(days=10)).isoformat()
        frame = self.get_price_history(tickers, start=start)
        if frame.empty:
            return {}
        return frame.sort_values("date").groupby("ticker")["close"].last().to_dict()

    def search_companies(self, query: str, limit: int = 8) -> list[dict]:
        q = (query or "").strip()
        if not q:
            return []
        payload = self.client.get_company_name_to_id(companies=[q], identifier_type="ciq")
        df = _frame(payload)
        if df.empty:
            return []
        symbol_col = _column(df, "ticker", "tradingsymbol", "symbol")
        name_col = _column(df, "companyname", "name", "entityname")
        exchange_col = _column(df, "exchange", "exchangename")
        out = []
        for _, row in df.iterrows():
            symbol = _text(row, symbol_col).upper()
            if not symbol:
                continue
            symbol = symbol.split(":", 1)[0]
            try:
                symbol = validate_ticker(symbol)
            except ValueError:
                continue
            out.append({
                "symbol": symbol,
                "name": _text(row, name_col) or symbol,
                "exchange": _text(row, exchange_col),
            })
            if len(out) >= limit:
                break
        return out


def get_provider(_cfg: dict | None = None) -> CapitalIQProvider:
    return CapitalIQProvider()
