import sqlite3

from api import main
from src.model import schema


def _database(tmp_path):
    path = tmp_path / "routing.db"
    conn = sqlite3.connect(path)
    schema.create_schema(conn)
    conn.executemany("INSERT INTO securities (ticker, name, sec_type) VALUES (?, ?, ?)", [
        ("AAPL", "Apple", "stock"), ("SPY", "SPDR", "etf")])
    conn.execute("INSERT INTO holdings (fund, ticker, shares) VALUES (?, ?, ?)",
                 ("Tall Firs", "AAPL", 10))
    conn.executemany(
        "INSERT INTO prices (ticker, date, close, adj_close, source) VALUES (?, ?, ?, ?, ?)",
        [("AAPL", "2026-09-08", 100, 100, "yfinance"),
         ("AAPL", "2026-09-09", 101, 101, "yfinance"),
         ("SPY", "2026-09-08", 500, 500, "yfinance"),
         ("SPY", "2026-09-09", 501, 501, "yfinance")])
    conn.commit()
    conn.close()
    return path


def test_owned_stock_detail_never_fetches_live(monkeypatch, tmp_path):
    path = _database(tmp_path)
    monkeypatch.setattr(main, "_conn", lambda: sqlite3.connect(path))
    monkeypatch.setattr(main, "closed_snapshot", lambda t: {"ticker": t, "financials": {}})
    monkeypatch.setattr(main, "stock_research", lambda _t: (_ for _ in ()).throw(
        AssertionError("owned ticker reached yfinance")))
    result = main.stock_detail("AAPL")
    assert result["owned"] is True


def test_unowned_stock_detail_fetches_full_bundle(monkeypatch, tmp_path):
    path = _database(tmp_path)
    monkeypatch.setattr(main, "_conn", lambda: sqlite3.connect(path))
    monkeypatch.setattr(main, "stock_research", lambda t: {"ticker": t, "news": []})
    result = main.stock_detail("JPM")
    assert result == {"ticker": "JPM", "news": [], "owned": False}


def test_unowned_series_uses_live_even_if_benchmark_is_stored(monkeypatch, tmp_path):
    path = _database(tmp_path)
    monkeypatch.setattr(main, "_conn", lambda: sqlite3.connect(path))
    monkeypatch.setattr(main, "live_series", lambda t, p: {
        "dates": ["2026-09-09"], "close": [999], "ret": None})
    result = main.series("SPY", "1M")
    assert result.body.find(b"999") >= 0
