import pytest
import sqlite3
from src.ingest import benchmark_holdings as bh
from src.model import schema

def test_parse_key():
    assert bh._parse_key("sk-test") == "sk-test"
    assert bh._parse_key("ALPHAVANTAGE_API_KEY=sk-test") == "sk-test"
    assert bh._parse_key("#comment\nsk-test") == "sk-test"
    assert bh._parse_key("") is None

def test_api_key(monkeypatch, tmp_path):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "env-key")
    assert bh.api_key() == "env-key"

    monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
    kf = tmp_path / "alphavantage.key.txt"
    kf.write_text("file-key")
    monkeypatch.setattr(bh, "_KEY_FILE", kf)
    assert bh.api_key() == "file-key"

def test_num():
    assert bh._num(1.5) == 1.5
    assert bh._num("2.0") == 2.0
    assert bh._num("abc") is None
    assert bh._num(None) is None

def test_clean_holdings():
    payload = {
        "holdings": [
            {"symbol": "AAPL", "weight": "0.05", "sector": "Technology"},
            {"symbol": "N/A", "weight": "0.10", "sector": "Cash"},
            {"symbol": " MSFT ", "weight": 0.04, "sector": " Technology "},
            {"symbol": "BAD", "weight": "abc", "sector": "Tech"}
        ]
    }
    holds = bh._clean_holdings(payload)
    assert len(holds) == 2
    assert holds[0] == ("AAPL", 0.05, "TECHNOLOGY")
    assert holds[1] == ("MSFT", 0.04, "TECHNOLOGY")

def test_clean_sectors():
    payload = {
        "sectors": [
            {"sector": "Technology", "weight": "0.25"},
            {"sector": "  Health  ", "weight": 0.15},
            {"sector": "Bad", "weight": "xyz"}
        ]
    }
    sects = bh._clean_sectors(payload)
    assert len(sects) == 2
    assert sects[0] == ("TECHNOLOGY", 0.25)
    assert sects[1] == ("HEALTH", 0.15)

def test_fetch_etf_profile(monkeypatch, tmp_path):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "dummy")

    class MockResponse:
        def __init__(self, json_data):
            self._json = json_data
        def raise_for_status(self):
            pass
        def json(self):
            return self._json

    def mock_get(*args, **kwargs):
        if kwargs.get("params", {}).get("symbol") == "ERR":
            return MockResponse({"Error Message": "Invalid symbol"})
        return MockResponse({"symbol": "SPY", "holdings": []})

    monkeypatch.setattr(bh.requests, "get", mock_get)

    res = bh.fetch_etf_profile("SPY")
    assert res["symbol"] == "SPY"

    with pytest.raises(RuntimeError, match="Alpha Vantage Error Message for ERR: Invalid symbol"):
        bh.fetch_etf_profile("ERR")

    with pytest.raises(RuntimeError, match="no Alpha Vantage API key"):
        monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
        monkeypatch.setattr(bh, "_KEY_FILE", tmp_path / "none.txt")
        bh.fetch_etf_profile("SPY")

def test_pull_benchmark_holdings(monkeypatch):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "dummy")
    def mock_fetch(symbol, key=None):
        if symbol == "SPY":
            return {
                "holdings": [{"symbol": "AAPL", "weight": "0.05", "sector": "Tech"}],
                "sectors": [{"sector": "Tech", "weight": "0.25"}]
            }
        raise Exception("Fetch failed")
    monkeypatch.setattr(bh, "fetch_etf_profile", mock_fetch)

    conn = sqlite3.connect(":memory:")
    schema.create_schema(conn)

    cfg = {"funds": [{"benchmark": "SPY"}, {"benchmark": "QQQ"}]}
    summary = bh.pull_benchmark_holdings(cfg, conn)

    assert summary["indexes"] == 1
    assert summary["holdings"] == 1
    assert summary["sectors"] == 1
    assert len(summary["failed"]) == 1
    assert "QQQ: Fetch failed" in summary["failed"][0]

    c = conn.cursor()
    c.execute("SELECT ticker, weight, sector FROM benchmark_holdings WHERE index_ticker = 'SPY'")
    assert c.fetchone() == ("AAPL", 0.05, "TECH")

    c.execute("SELECT sector, weight FROM benchmark_sectors WHERE index_ticker = 'SPY'")
    assert c.fetchone() == ("TECH", 0.25)
