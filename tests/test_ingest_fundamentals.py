import pytest
import sqlite3
from src.ingest import fundamentals
from src.model import schema

def test_fundamentals(monkeypatch):
    def mock_info(ticker):
        if ticker == "AAPL":
            return {
                "sector": "Technology",
                "forwardPE": 28.5,
                "priceToBook": 45.2,
                "enterpriseToEbitda": 20.1,
                "marketCap": 3000000000000,
                "fiftyTwoWeekLow": 150.0,
                "fiftyTwoWeekHigh": 198.0,
                "longBusinessSummary": "Apple makes stuff"
            }
        return {}
    monkeypatch.setattr(fundamentals, "_info", mock_info)

    conn = sqlite3.connect(":memory:")
    schema.create_schema(conn)
    conn.execute("INSERT INTO securities (ticker, name, sec_type) VALUES ('AAPL', 'Apple', 'stock')")
    conn.execute("INSERT INTO securities (ticker, name, sec_type) VALUES ('MSFT', 'Microsoft', 'stock')")
    conn.commit()

    cfg = {}
    summary = fundamentals.pull_fundamentals(cfg, conn)

    assert summary["updated"] == 1
    assert summary["failed"] == ["MSFT"]

    cur = conn.execute("SELECT gics_sector, pe, pb, ev_ebitda, market_cap, week52_low, week52_high, description FROM fundamentals WHERE ticker='AAPL'")
    row = cur.fetchone()
    assert row[0] == "Technology"
    assert row[1] == 28.5
    assert row[2] == 45.2
    assert row[3] == 20.1
    assert row[4] == 3000000000000
    assert row[5] == 150.0
    assert row[6] == 198.0
    assert row[7] == "Apple makes stuff"

def test_f():
    assert fundamentals._f(1.5) == 1.5
    assert fundamentals._f("2.0") == 2.0
    assert fundamentals._f(None) is None
    assert fundamentals._f("abc") is None
