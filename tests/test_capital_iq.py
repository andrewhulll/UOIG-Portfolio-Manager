from __future__ import annotations

import sqlite3

import pandas as pd
import pytest

from src.ingest.capital_iq import CapitalIQProvider, normalize_prices, validate_ticker
from src.ingest.refresh import refresh
from src.model import schema


def test_validate_ticker_rejects_before_request():
    assert validate_ticker(" brk.b ") == "BRK.B"
    with pytest.raises(ValueError):
        validate_ticker("AAPL; DROP TABLE prices")


def test_normalize_wide_sdk_dataframe():
    source = pd.DataFrame([{
        "Identifier": "AAPL:", "Pricing Date": "08/31/2026",
        "IQ_OPENPRICE": "226.10", "IQ_HIGHPRICE": 230.0,
        "IQ_LOWPRICE": 225.0, "IQ_CLOSEPRICE": 229.4,
        "IQ_CLOSEPRICE_ADJ": 228.9, "IQ_VOLUME": "51,200,000",
    }])
    result = normalize_prices(source, ["AAPL"])
    assert result.to_dict("records") == [{
        "ticker": "AAPL", "date": "2026-08-31", "open": 226.1,
        "high": 230.0, "low": 225.0, "close": 229.4,
        "volume": 51_200_000,
    }]


def test_normalize_long_sdk_response_object():
    class Response:
        data = pd.DataFrame([
            {"Identifier": "MSFT:", "Date": "2026-08-31", "Mnemonic": "IQ_OPENPRICE", "Value": 500},
            {"Identifier": "MSFT:", "Date": "2026-08-31", "Mnemonic": "IQ_HIGHPRICE", "Value": 510},
            {"Identifier": "MSFT:", "Date": "2026-08-31", "Mnemonic": "IQ_LOWPRICE", "Value": 495},
            {"Identifier": "MSFT:", "Date": "2026-08-31", "Mnemonic": "IQ_CLOSEPRICE", "Value": 507},
            {"Identifier": "MSFT:", "Date": "2026-08-31", "Mnemonic": "IQ_VOLUME", "Value": 1200},
        ])

    result = normalize_prices(Response(), ["MSFT"])
    assert result.iloc[0].to_dict() == {
        "ticker": "MSFT", "date": "2026-08-31", "open": 500.0,
        "high": 510.0, "low": 495.0, "close": 507.0, "volume": 1200,
    }


def test_provider_uses_sdk_date_properties_and_ticker_identifier():
    class Client:
        called = None

        def get_pricing_info_time_series(self, **kwargs):
            self.called = kwargs
            return pd.DataFrame([{
                "Identifier": "AAPL:", "Date": "2026-08-31",
                "IQ_OPENPRICE": 1, "IQ_HIGHPRICE": 2, "IQ_LOWPRICE": 0.5,
                "IQ_CLOSEPRICE": 1.5, "IQ_VOLUME": 10,
            }])

    client = Client()
    result = CapitalIQProvider(client).get_price_history(
        ["AAPL"], start="2026-08-01", end="2026-08-31")
    assert len(result) == 1
    assert client.called["identifiers"] == ["AAPL:"]
    assert client.called["properties"]["startDate"] == "08/01/2026"
    assert client.called["properties"]["frequency"] == "D"


def test_refresh_upserts_cache_and_logs_run():
    conn = sqlite3.connect(":memory:")
    schema.create_schema(conn)
    conn.executemany(
        "INSERT INTO securities (ticker, name, sector, cap_class, sec_type) VALUES (?, ?, '', '', ?)",
        [("AAA", "AAA Inc", "stock"), ("BENCH", "Benchmark", "etf")],
    )
    conn.execute(
        "INSERT INTO holdings (fund, ticker, shares, entry_price) VALUES ('Fund', 'AAA', 1, 1)"
    )
    conn.commit()

    class Provider:
        def get_price_history(self, tickers, start, end=None):
            ticker = tickers[0]
            return pd.DataFrame([{
                "ticker": ticker, "date": "2026-08-31", "open": 10,
                "high": 12, "low": 9, "close": 11, "volume": 100,
            }])

    cfg = {
        "funds": [{"name": "Fund", "benchmark": "BENCH"}],
        "market_data": {"history_years": 1}, "risk": {}, "sectors": [],
    }
    first = refresh(cfg, full=True, conn=conn, provider=Provider())
    second = refresh(cfg, full=True, conn=conn, provider=Provider())
    assert first["status"] == second["status"] == "success"
    assert conn.execute("SELECT COUNT(*) FROM daily_prices").fetchone()[0] == 2
    runs = conn.execute(
        "SELECT status, tickers_succeeded, rows_upserted FROM price_refresh_runs ORDER BY started_at"
    ).fetchall()
    assert len(runs) == 2
    assert all(row == ("success", 2, 2) for row in runs)
    conn.close()
