import pytest
import pandas as pd
from src.ingest.providers import YFinanceProvider, get_provider, to_yf, yf_session, yf_ticker, _nonempty, yf_retry

def test_to_yf():
    assert to_yf("AAPL") == "AAPL"
    assert to_yf("BRK.B") == "BRK-B"

def test_yf_session_fallback():
    # Calling this directly should return None if curl_cffi isn't there, or session object
    # In CI, if we don't have curl_cffi, it won't break
    sess = yf_session()
    assert True # Just asserting it doesn't crash

def test_yf_ticker():
    # Calling yf_ticker returns a yf.Ticker object
    tk = yf_ticker("AAPL")
    assert tk.ticker == "AAPL"

def test_nonempty():
    assert _nonempty(None) is False
    assert _nonempty([]) is False
    assert _nonempty("") is False
    assert _nonempty({}) is False
    assert _nonempty([1]) is True
    assert _nonempty("a") is True
    assert _nonempty({"a": 1}) is True
    assert _nonempty(pd.DataFrame()) is False
    assert _nonempty(pd.DataFrame({"a": [1]})) is True
    assert _nonempty(1) is True # fallback

def test_yf_retry():
    def success():
        return 1

    assert yf_retry(success, tries=2, base=0.01) == 1

    count = 0
    def fails_once():
        nonlocal count
        count += 1
        if count == 1:
            raise ValueError()
        return 2

    assert yf_retry(fails_once, tries=2, base=0.01) == 2

    def always_fails():
        raise ValueError()

    assert yf_retry(always_fails, tries=2, base=0.01) is None

    empty_count = 0
    def empty_once():
        nonlocal empty_count
        empty_count += 1
        if empty_count == 1:
            return []
        return [1]

    assert yf_retry(empty_once, tries=2, base=0.01) == [1]

def test_get_provider():
    cfg = {}
    p = get_provider(cfg)
    assert isinstance(p, YFinanceProvider)

    with pytest.raises(ValueError):
        get_provider({"market_data": {"provider": "unknown"}})

def test_yfinance_provider_history(monkeypatch):
    class MockTicker:
        def __init__(self, ticker, *args, **kwargs):
            self.ticker = ticker

        def history(self, start, end, auto_adjust, actions):
            if self.ticker == "ERR-B":
                raise ValueError("Fetch failed")

            df = pd.DataFrame({
                "Close": [100.0, 101.0],
                "Adj Close": [99.0, 100.0],
                "Dividends": [0.5, 0.0]
            }, index=pd.DatetimeIndex(["2023-01-01", "2023-01-02"]))

            # Unfinalized day simulation (no Close)
            if self.ticker == "UNFIN":
                df = pd.DataFrame({"Dividends": [0.5]}, index=pd.DatetimeIndex(["2023-01-01"]))

            return df

    def mock_yf_ticker(ticker, *args, **kwargs):
        return MockTicker(ticker)

    monkeypatch.setattr("src.ingest.providers.yf.Ticker", mock_yf_ticker)

    p = YFinanceProvider(retries=0)

    # Test get_price_history
    ph = p.get_price_history(["AAPL", "UNFIN", "ERR.B"], start="2023-01-01")
    assert len(ph) == 2 # 2 days * 1 ticker (AAPL)
    assert ph.iloc[0]["ticker"] == "AAPL"

    # Test get_dividends
    dv = p.get_dividends(["AAPL", "ERR.B"], start="2023-01-01")
    assert len(dv) == 1 # only AAPL, only > 0
    assert dv.iloc[0]["ticker"] == "AAPL"
    assert dv.iloc[0]["amount"] == 0.5

    # Empty cases
    assert p.get_price_history(["ERR.B"], start="2023").empty
    assert p.get_dividends(["ERR.B"], start="2023").empty

    # Test get_latest_prices
    lp = p.get_latest_prices(["AAPL"])
    assert lp["AAPL"] == 101.0

    assert p.get_latest_prices(["ERR.B"]) == {}
