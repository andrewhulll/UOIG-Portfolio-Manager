import sqlite3

from src.ingest.universe import is_owned, owned_tickers


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE securities (ticker TEXT PRIMARY KEY, sec_type TEXT)")
    conn.execute("CREATE TABLE holdings (fund TEXT, ticker TEXT, shares REAL)")
    conn.executemany("INSERT INTO securities VALUES (?, ?)", [
        ("AAPL", "stock"), ("MSFT", "stock"), ("OLD", "stock"), ("CASH", "cash")])
    conn.executemany("INSERT INTO holdings VALUES (?, ?, ?)", [
        ("A", "AAPL", 5), ("B", "AAPL", 2), ("A", "MSFT", 1),
        ("A", "OLD", 0), ("A", "CASH", 100)])
    return conn


def test_owned_tickers_are_positive_non_cash_and_deduplicated():
    conn = _conn()
    assert owned_tickers(conn) == ["AAPL", "MSFT"]
    assert is_owned(conn, "aapl") is True
    assert is_owned(conn, "OLD") is False
    assert is_owned(conn, "CASH") is False
