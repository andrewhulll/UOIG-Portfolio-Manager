import pytest
import sqlite3
import pandas as pd
import datetime as dt
from src.analytics import series
from src.model import schema

def test_period_start():
    last = dt.date(2023, 10, 1)
    assert series.period_start(last, "1M") == dt.date(2023, 9, 1)
    assert series.period_start(last, "YTD") == dt.date(2023, 1, 1)
    assert series.period_start(last, "UNKNOWN") == last - dt.timedelta(days=365)

def test_price_frame():
    conn = sqlite3.connect(":memory:")
    schema.create_schema(conn)
    conn.execute("INSERT INTO prices (ticker, date, close, adj_close, source) VALUES ('AAPL', '2023-01-01', 100.0, 99.0, 'yfinance')")
    conn.execute("INSERT INTO prices (ticker, date, close, adj_close, source) VALUES ('AAPL', '2023-01-02', 110.0, 109.0, 'yfinance')")
    conn.execute("INSERT INTO prices (ticker, date, close, adj_close, source) VALUES ('MSFT', '2023-01-01', 200.0, 199.0, 'yfinance')")
    conn.commit()

    pf = series.price_frame(conn)
    assert len(pf) == 3
    assert set(pf["ticker"]) == {"AAPL", "MSFT"}
    assert pf.iloc[0]["ticker"] == "AAPL"

def test_window():
    pf = pd.DataFrame({
        "ticker": ["AAPL", "AAPL", "AAPL"],
        "date": pd.to_datetime(["2023-01-01", "2023-06-01", "2023-10-01"]),
        "close": [100.0, 110.0, 120.0]
    })

    # 1M window from 2023-10-01 is 2023-09-01
    w = series._window(pf, "AAPL", "1M")
    assert len(w) == 2 # Forces at least 2 points
    assert w["date"].iloc[0].strftime("%Y-%m-%d") == "2023-06-01"

    w2 = series._window(pf, "AAPL", "1Y")
    assert len(w2) == 3

    assert series._window(pf, "UNKNOWN", "1M").empty

def test_ticker_series():
    pf = pd.DataFrame({
        "ticker": ["AAPL", "AAPL", "AAPL", "AAPL"],
        "date": pd.to_datetime(["2023-01-01", "2023-06-01", "2023-08-01", "2023-10-01"]),
        "close": [100.0, 110.0, 115.0, 120.0]
    })

    res = series.ticker_series(pf, "AAPL", "1Y", points=2)
    assert len(res["close"]) == 2
    assert res["close"][0] == 100.0
    assert res["close"][1] == 120.0

    empty_res = series.ticker_series(pf, "UNKNOWN", "1Y")
    assert empty_res["close"] == []

def test_period_return():
    pf = pd.DataFrame({
        "ticker": ["AAPL", "AAPL", "AAPL"],
        "date": pd.to_datetime(["2023-01-01", "2023-06-01", "2023-10-01"]),
        "close": [100.0, 110.0, 120.0],
        "adj_close": [90.0, 100.0, 110.0]
    })

    assert series.period_return(pf, "AAPL", "1Y") == pytest.approx((110.0 / 90.0) - 1)

    # Zero base
    pf_zero = pd.DataFrame({
        "ticker": ["AAPL", "AAPL"],
        "date": pd.to_datetime(["2023-01-01", "2023-10-01"]),
        "close": [0.0, 120.0],
        "adj_close": [0.0, 110.0]
    })
    assert series.period_return(pf_zero, "AAPL", "1Y") is None

def test_trailing_return():
    pf = pd.DataFrame({
        "ticker": ["AAPL", "AAPL", "AAPL"],
        "date": pd.to_datetime(["2023-09-01", "2023-09-25", "2023-10-01"]),
        "close": [100.0, 110.0, 120.0]
    })

    # Trailing 7 days from 10-01
    assert series.trailing_return(pf, "AAPL", 7) == pytest.approx((120.0 / 110.0) - 1)

    assert series.trailing_return(pf, "UNKNOWN", 7) is None

def test_mtd_return():
    pf = pd.DataFrame({
        "ticker": ["AAPL", "AAPL", "AAPL"],
        "date": pd.to_datetime(["2023-09-25", "2023-10-05", "2023-10-15"]),
        "adj_close": [100.0, 110.0, 120.0]
    })

    # Base is 09-25
    assert series.mtd_return(pf, "AAPL") == pytest.approx((120.0 / 100.0) - 1)

    assert series.mtd_return(pf, "UNKNOWN") is None

    pf_short = pd.DataFrame({
        "ticker": ["AAPL"],
        "date": pd.to_datetime(["2023-10-15"]),
        "adj_close": [100.0]
    })
    assert series.mtd_return(pf_short, "AAPL") is None

def test_div_yield_ttm():
    conn = sqlite3.connect(":memory:")
    schema.create_schema(conn)
    conn.execute("INSERT INTO prices (ticker, date, close, adj_close, source) VALUES ('AAPL', '2023-10-01', 100.0, 99.0, 'yfinance')")
    conn.execute("INSERT INTO dividends (ticker, ex_date, amount) VALUES ('AAPL', '2023-05-01', 0.5)")
    conn.execute("INSERT INTO dividends (ticker, ex_date, amount) VALUES ('AAPL', '2022-01-01', 0.5)") # Too old
    conn.commit()

    assert series.div_yield_ttm(conn, "AAPL", 100.0) == 0.5
    assert series.div_yield_ttm(conn, "AAPL", 0.0) is None
    assert series.div_yield_ttm(conn, "UNKNOWN", 100.0) is None

def test_synthetic_index():
    rets = pd.DataFrame({
        "AAPL": [0.01, 0.02, -0.01],
        "MSFT": [0.02, 0.01, 0.01]
    }, index=pd.DatetimeIndex(["2023-09-01", "2023-09-02", "2023-09-03"]))

    weights = {"AAPL": 0.6, "MSFT": 0.4}

    idx = series.synthetic_index(rets, weights, "1M")
    assert len(idx["values"]) == 3
    assert idx["values"][0] == pytest.approx(100.0 * (1 + 0.6*0.01 + 0.4*0.02))
    # use a tolerance for float comparison or approx
    assert idx["ret"] == pytest.approx(idx["values"][-1] / 100.0 - 1, abs=1e-3)

    empty_idx = series.synthetic_index(rets, {"UNKNOWN": 1.0}, "1M")
    assert empty_idx["values"] == []

    empty_rets_idx = series.synthetic_index(pd.DataFrame(), weights, "1M")
    assert empty_rets_idx["values"] == []
