import pytest
import math
import pandas as pd
from src.ingest.lookup import search_symbols, quote_overview, live_series, institutional_holders
import src.ingest.lookup as lookup_mod
from src.model import cache

def test_num_lookup():
    assert lookup_mod._num(1.5) == 1.5
    assert lookup_mod._num("2.0") == 2.0
    assert lookup_mod._num(float("inf")) is None
    assert lookup_mod._num(float("nan")) is None
    assert lookup_mod._num("abc") is None
    assert lookup_mod._num(None) is None

def test_search_symbols(monkeypatch):
    class MockSearchResponse:
        def __init__(self):
            self.quotes = [
                {"symbol": "AAPL", "longname": "Apple", "quoteType": "EQUITY", "exchange": "NMS"},
                {"symbol": "BTC-USD", "shortname": "Bitcoin", "quoteType": "CRYPTOCURRENCY"},
                {"symbol": "SPY", "shortname": "SPDR S&P 500 ETF Trust", "quoteType": "ETF", "exchange": "PCX"}
            ]

    def mock_retry(fn, *args, **kwargs):
        return MockSearchResponse()

    monkeypatch.setattr(lookup_mod, "yf_retry", mock_retry)
    monkeypatch.setattr(cache, "get", lambda *args: cache.MISS)
    monkeypatch.setattr(cache, "set", lambda *args: None)

    lookup_mod._SEARCH_CACHE.clear()

    res = search_symbols("Apple")
    assert len(res) == 1 # only AAPL (ETF is skipped, strictly EQUITY)
    assert res[0]["symbol"] == "AAPL"
    assert res[0]["name"] == "Apple"
    assert res[0]["exchange"] == "NMS"

    # Edge cases
    assert search_symbols("") == []
    assert search_symbols("   ") == []

def test_quote_overview(monkeypatch):
    class MockFastInfo:
        def get(self, key):
            return 175.0

    class MockTicker:
        @property
        def info(self):
            return {
                "shortName": "Apple Inc",
                "sector": "Technology",
                "industry": "Consumer Electronics",
                "marketCap": 3000000000000,
                "forwardPE": 28.5,
                "fiftyTwoWeekLow": 150.0,
                "fiftyTwoWeekHigh": 198.0,
                "longBusinessSummary": "Apple makes stuff",
                "quoteType": "EQUITY",
                "currentPrice": 175.0,
                "previousClose": 170.0
            }
        @property
        def fast_info(self):
            return MockFastInfo()

    def mock_yf_ticker(ticker):
        if ticker == "BTC":
            class BadTicker:
                @property
                def info(self):
                    return {"quoteType": "CRYPTOCURRENCY", "currentPrice": 40000.0}
            return BadTicker()
        return MockTicker()

    def mock_retry(fn, *args, **kwargs):
        return fn()

    monkeypatch.setattr(lookup_mod, "yf_ticker", mock_yf_ticker)
    monkeypatch.setattr(lookup_mod, "yf_retry", mock_retry)
    monkeypatch.setattr(cache, "get", lambda *args: cache.MISS)
    monkeypatch.setattr(cache, "set", lambda *args: None)

    lookup_mod._QUOTE_CACHE.clear()

    quote = quote_overview("AAPL")
    assert quote["t"] == "AAPL"
    assert quote["n"] == "Apple Inc"
    assert quote["s"] == "Technology"
    assert quote["px"] == 175.0
    assert math.isclose(quote["chg"], 5.0 / 170.0 * 100, abs_tol=1e-2)
    assert quote["pe"] == 28.5
    assert quote["mc"] == 3000.0 # B

    # Not an equity
    assert quote_overview("BTC") is None

def test_quote_overview_falls_back_to_fast_info_when_info_is_empty(monkeypatch):
    # Reproduces production: tk.info comes back empty (e.g. Yahoo throttling the
    # heavier quoteSummary endpoint) while the lighter chart-backed fast_info still
    # works. quote_overview must use attribute access (fast_info aliases
    # last_price/previous_close from Yahoo's camelCase) rather than .get(), which
    # does not apply that aliasing and always misses.
    class MockFastInfo:
        last_price = 230.36
        previous_close = 225.0

    class MockTicker:
        @property
        def info(self):
            return {}
        @property
        def fast_info(self):
            return MockFastInfo()

    def mock_retry(fn, *args, **kwargs):
        return fn()

    monkeypatch.setattr(lookup_mod, "yf_ticker", lambda t: MockTicker())
    monkeypatch.setattr(lookup_mod, "yf_retry", mock_retry)
    monkeypatch.setattr(cache, "get", lambda *args: cache.MISS)
    monkeypatch.setattr(cache, "set", lambda *args: None)

    lookup_mod._QUOTE_CACHE.clear()

    quote = quote_overview("NVDA")
    assert quote is not None
    assert quote["t"] == "NVDA"
    assert quote["px"] == 230.36

def test_institutional_holders(monkeypatch):
    class MockTicker:
        @property
        def institutional_holders(self):
            return pd.DataFrame({
                "Holder": ["Vanguard"],
                "pctHeld": [0.08],
                "Shares": [1000000],
                "Value": [150000000]
            })

    def mock_retry(fn, *args, **kwargs):
        return fn()

    monkeypatch.setattr(lookup_mod, "yf_ticker", lambda t: MockTicker())
    monkeypatch.setattr(lookup_mod, "yf_retry", mock_retry)
    monkeypatch.setattr(cache, "get", lambda *args: cache.MISS)
    monkeypatch.setattr(cache, "set", lambda *args: None)

    lookup_mod._HOLDERS_CACHE.clear()

    holders = institutional_holders("AAPL")
    assert len(holders) == 1
    assert holders[0]["holder"] == "Vanguard"
    assert holders[0]["pct"] == 8.0 # 0.08 * 100
    assert holders[0]["shares"] == 1000000
    assert holders[0]["value"] == 150.0

def test_live_series(monkeypatch):
    class MockTicker:
        def history(self, **kwargs):
            return pd.DataFrame({
                "Close": [100.0, 110.0]
            }, index=pd.DatetimeIndex(["2023-01-01", "2023-01-02"]))

    def mock_retry(fn, *args, **kwargs):
        return fn()

    monkeypatch.setattr(lookup_mod, "yf_ticker", lambda t: MockTicker())
    monkeypatch.setattr(lookup_mod, "yf_retry", mock_retry)
    monkeypatch.setattr(cache, "get", lambda *args: cache.MISS)
    monkeypatch.setattr(cache, "set", lambda *args: None)

    lookup_mod._SERIES_CACHE.clear()

    res = live_series("AAPL", "1M")
    assert len(res["close"]) == 2
    assert res["close"][0] == 100.0
    assert res["close"][1] == 110.0
    assert math.isclose(res["ret"], 0.1, abs_tol=1e-5)
