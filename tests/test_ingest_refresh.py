import pytest
import sqlite3
import pandas as pd
from src.ingest import refresh
from src.model import schema

def test_universe():
    conn = sqlite3.connect(":memory:")
    schema.create_schema(conn)
    conn.execute("INSERT INTO securities (ticker, name, sec_type) VALUES ('AAPL', 'Apple', 'stock')")
    conn.execute("INSERT INTO securities (ticker, name, sec_type) VALUES ('CASH', 'Cash', 'cash')")
    conn.commit()

    cfg = {
        "funds": [{"benchmark": "SPY"}],
        "risk": {"market_proxy": "SPY", "risk_free": "BIL"},
        "sectors": [{"benchmarks": ["XLK"]}]
    }

    tickers, bench = refresh._universe(conn, cfg)
    assert set(tickers) == {"AAPL", "SPY", "BIL", "XLK"}
    assert bench == {"SPY", "BIL"}

def test_refresh(monkeypatch):
    class MockProvider:
        def get_price_history(self, tickers, start):
            if tickers[0] == "ERR":
                return pd.DataFrame()
            return pd.DataFrame({
                "ticker": tickers,
                "date": ["2023-01-01"],
                "close": [100.0],
                "adj_close": [99.0]
            })

        def get_dividends(self, tickers, start):
            if tickers[0] == "AAPL":
                return pd.DataFrame({
                    "ticker": tickers,
                    "ex_date": ["2023-01-01"],
                    "amount": [0.5]
                })
            return pd.DataFrame()

        def get_splits(self, tickers, start):
            return pd.DataFrame()


    def mock_get_provider(cfg):
        return MockProvider()

    monkeypatch.setattr(refresh, "get_provider", mock_get_provider)

    conn = sqlite3.connect(":memory:")
    schema.create_schema(conn)
    conn.execute("INSERT INTO securities (ticker, name, sec_type) VALUES ('AAPL', 'Apple', 'stock')")
    conn.execute("INSERT INTO securities (ticker, name, sec_type) VALUES ('ERR', 'Error', 'stock')")

    # Pre-seed a price to test incremental logic
    conn.execute("INSERT INTO prices (ticker, date, close, adj_close, source) VALUES ('AAPL', '2022-12-31', 99.0, 99.0, 'yfinance')")
    conn.commit()

    cfg = {
        "funds": [{"benchmark": "SPY"}],
        "market_data": {"history_years": 1}
    }

    summary = refresh.refresh(cfg, conn=conn)

    assert summary["tickers"] == 3 # AAPL, ERR, SPY
    assert summary["prices"] == 2  # AAPL, SPY
    assert summary["dividends"] == 1 # AAPL
    assert summary["failed"] == ["ERR"]

    c = conn.cursor()
    c.execute("SELECT close FROM prices WHERE ticker='AAPL' AND date='2023-01-01'")
    assert c.fetchone()[0] == 100.0

    c.execute("SELECT close FROM benchmarks WHERE index_ticker='SPY' AND date='2023-01-01'")
    assert c.fetchone()[0] == 100.0

    c.execute("SELECT amount FROM dividends WHERE ticker='AAPL' AND ex_date='2023-01-01'")
    assert c.fetchone()[0] == 0.5
