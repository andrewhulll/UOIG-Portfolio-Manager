import pytest
import time
import pandas as pd
from src.ingest import live_prices as lp

def test_num():
    assert lp._num("1.5") == 1.5
    assert lp._num("abc") is None
    assert lp._num(None) is None
    assert lp._num(float("inf")) is None
    assert lp._num(float("nan")) is None

def test_market_open():
    # Test typical hours
    # Friday, open
    ts = pd.Timestamp("2023-11-03 10:00:00", tz="America/New_York")
    assert lp.market_open(ts) is True

    # Friday, pre-market
    ts = pd.Timestamp("2023-11-03 09:00:00", tz="America/New_York")
    assert lp.market_open(ts) is False

    # Friday, post-market
    ts = pd.Timestamp("2023-11-03 16:30:00", tz="America/New_York")
    assert lp.market_open(ts) is False

    # Saturday
    ts = pd.Timestamp("2023-11-04 12:00:00", tz="America/New_York")
    assert lp.market_open(ts) is False

def test_fetch_one(monkeypatch):
    class MockFastInfo:
        def __init__(self, last, prev):
            self.last_price = last
            self.previous_close = prev

    class MockTicker:
        def __init__(self, ticker):
            self.ticker = ticker
            if ticker == "ERR":
                raise ValueError("Fail")
            elif ticker == "BAD":
                self.fast_info = MockFastInfo(None, None)
            elif ticker == "ZERO":
                self.fast_info = MockFastInfo(10, 0)
            else:
                self.fast_info = MockFastInfo(100.0, 99.0)

    monkeypatch.setattr("src.ingest.live_prices.yf.Ticker", MockTicker)

    assert lp._fetch_one("AAPL") == (100.0, 99.0)
    assert lp._fetch_one("ERR") is None
    assert lp._fetch_one("BAD") is None
    assert lp._fetch_one("ZERO") is None

def test_poll_and_overrides(monkeypatch):
    def mock_fetch_one(ticker):
        if ticker == "AAPL":
            return (100.0, 99.0)
        return None

    monkeypatch.setattr(lp, "_fetch_one", mock_fetch_one)
    lp._LIVE.clear()

    # Test empty poll
    assert lp.poll_once([]) == 0

    # Test real poll
    assert lp.poll_once(["AAPL", "ERR", "AAPL"]) == 1 # unique tickers

    overrides = lp.overrides()
    assert "AAPL" in overrides
    assert overrides["AAPL"] == {"price": 100.0, "prev_close": 99.0}

    # Force stale
    lp._LIVE["AAPL"]["ts"] = time.time() - lp._STALE - 10
    assert lp.overrides() == {}

def test_loop_and_start(monkeypatch):
    calls = 0
    def mock_poll(tickers):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise Exception("Fail once")

    monkeypatch.setattr(lp, "poll_once", mock_poll)
    monkeypatch.setattr(lp, "market_open", lambda ts=None: True)

    tickers = ["AAPL"]

    # Start and wait for at least two cycles (very fast intervals)
    lp.start(lambda: tickers, interval=0.01, idle_interval=0.01)

    time.sleep(0.05)
    lp.stop()

    # Ensure it's idempotent
    lp.start(lambda: tickers, interval=0.01, idle_interval=0.01)

    # Should be running again
    assert lp._thread.is_alive()
    lp.stop()

    # Join the thread to cleanly exit
    lp._thread.join(timeout=1.0)
    assert calls >= 2
