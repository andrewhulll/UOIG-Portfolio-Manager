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
    conn.execute("INSERT INTO holdings (fund, ticker, shares) VALUES ('Fund', 'AAPL', 1)")
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
            return pd.DataFrame(columns=["ticker", "date", "ratio"])

    def mock_get_provider(cfg):
        return MockProvider()

    monkeypatch.setattr(refresh, "get_provider", mock_get_provider)

    conn = sqlite3.connect(":memory:")
    schema.create_schema(conn)
    conn.execute("INSERT INTO securities (ticker, name, sec_type) VALUES ('AAPL', 'Apple', 'stock')")
    conn.execute("INSERT INTO securities (ticker, name, sec_type) VALUES ('ERR', 'Error', 'stock')")
    conn.execute("INSERT INTO holdings (fund, ticker, shares) VALUES ('Fund', 'AAPL', 1)")
    conn.execute("INSERT INTO holdings (fund, ticker, shares) VALUES ('Fund', 'ERR', 1)")

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


def test_refresh_applies_only_post_import_splits_once(monkeypatch):
    class MockProvider:
        def get_price_history(self, tickers, start):
            return pd.DataFrame({
                "ticker": tickers,
                "date": ["2023-01-03"],
                "close": [50.0],
                "adj_close": [50.0],
            })

        def get_dividends(self, tickers, start):
            return pd.DataFrame()

        def get_splits(self, tickers, start):
            if tickers[0] != "AAPL":
                return pd.DataFrame(columns=["ticker", "date", "ratio"])
            return pd.DataFrame({
                "ticker": ["AAPL", "AAPL"],
                "date": ["2022-07-01", "2023-01-02"],
                "ratio": [4.0, 2.0],
            })

    monkeypatch.setattr(refresh, "get_provider", lambda _cfg: MockProvider())
    conn = sqlite3.connect(":memory:")
    schema.create_schema(conn)
    conn.execute("INSERT INTO securities (ticker, name, sec_type) VALUES ('AAPL', 'Apple', 'stock')")
    conn.execute(
        "INSERT INTO holdings (fund, ticker, shares, entry_price, entry_date) "
        "VALUES ('Fund', 'AAPL', 10, 100, '2020-01-01')"
    )
    conn.execute("INSERT INTO import_meta (key, value) VALUES ('import_date', '2023-01-01')")
    conn.execute(
        "INSERT INTO prices (ticker, date, close, adj_close, source) "
        "VALUES ('AAPL', '2022-06-30', 400, 100, 'yfinance')"
    )
    conn.execute("INSERT INTO dividends (ticker, ex_date, amount) VALUES ('AAPL', '2022-06-01', 4)")
    conn.commit()
    cfg = {"funds": [{"benchmark": "SPY"}], "market_data": {"history_years": 5}}

    refresh.refresh(cfg, conn=conn)

    # The 4:1 split predates the current-position snapshot and is ignored; only
    # the genuinely new 2:1 split adjusts the holding. Provider price/dividend
    # history is already split-aware and must not be divided a second time.
    assert conn.execute("SELECT shares, entry_price FROM holdings").fetchone() == (20.0, 50.0)
    assert conn.execute(
        "SELECT close, adj_close FROM prices WHERE ticker='AAPL' AND date='2022-06-30'"
    ).fetchone() == (400.0, 100.0)
    assert conn.execute("SELECT amount FROM dividends WHERE ticker='AAPL'").fetchone() == (4.0,)

    refresh.refresh(cfg, conn=conn)

    assert conn.execute("SELECT shares, entry_price FROM holdings").fetchone() == (20.0, 50.0)
