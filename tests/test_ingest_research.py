import pytest
import datetime as dt
import pandas as pd
from src.ingest import research as res
import src.ingest.research as res_mod
from src.model import cache

def test_helpers():
    assert res._num("1.5") == 1.5
    assert res._num("abc") is None

    assert res._money(1500000) == "$1.5M"
    assert res._money(0) == "$0"

    assert res._pct(15.0, 1) == "+15.0%"
    assert res._pct(-15, 0) == "-15%"

    assert res._qlabel("2023-03-31") == "1Q23"
    assert res._qlabel("2023-06-30") == "2Q23"

def test_ago():
    now = dt.datetime(2023, 1, 2, tzinfo=dt.timezone.utc)

    # 5 minutes ago
    ts = now - dt.timedelta(minutes=5)
    assert res._ago(ts, now) == "5m ago"

    # 2 hours ago
    ts2 = now - dt.timedelta(hours=2)
    assert res._ago(ts2, now) == "2h ago"

    # 3 days ago
    ts3 = now - dt.timedelta(days=3)
    assert res._ago(ts3, now) == "3d ago"

def test_financials(monkeypatch):
    class MockTicker:
        @property
        def quarterly_income_stmt(self):
            return pd.DataFrame({
                "2023-06-30": [200.0, 100.0, 50.0, 2.0],
                "2023-03-31": [180.0, 90.0, 45.0, 1.8],
                "2022-12-31": [160.0, 80.0, 40.0, 1.6],
                "2022-09-30": [150.0, 75.0, 35.0, 1.5],
                "2022-06-30": [100.0, 50.0, 25.0, 1.0] # Year ago
            }, index=["Total Revenue", "Gross Profit", "Net Income", "Diluted EPS"])

        @property
        def quarterly_cashflow(self):
            return pd.DataFrame({
                "2023-06-30": [60.0],
                "2023-03-31": [55.0],
                "2022-12-31": [50.0],
                "2022-09-30": [45.0],
                "2022-06-30": [40.0]
            }, index=["Free Cash Flow"])

    tk = MockTicker()
    fin, rev_sum = res._financials(tk)

    assert fin is not None
    assert "Revenue" in [r["label"] for r in fin["rows"]]
    assert rev_sum["revActual"] == "$200"
    assert rev_sum["revYoY"] == "+100%" # (200-100)/100

def test_earnings():
    class MockTicker:
        @property
        def earnings_dates(self):
            return pd.DataFrame({
                "EPS Estimate": [1.5, 1.4],
                "Reported EPS": [1.6, 1.3],
                "Surprise(%)": [0.066, -0.071]
            }, index=pd.DatetimeIndex(["2023-06-30", "2023-03-31"]))

        @property
        def calendar(self):
            return {"Earnings Date": ["2023-09-30"]}

    tk = MockTicker()
    earn = res._earnings(tk, {"revActual": "$200", "revYoY": "+10%"})

    assert earn is not None
    assert earn["beat"] == 0.066
    assert earn["epsActual"] == "$1.60"
    assert earn["next"] == "Sep 30, 2023"
    assert earn["revActual"] == "$200"

def test_news():
    class MockTicker:
        @property
        def news(self):
            return [
                {
                    "content": {
                        "title": "Good News",
                        "provider": {"displayName": "Reuters"},
                        "pubDate": "2023-01-01T12:00:00Z",
                        "canonicalUrl": {"url": "http://example.com/news"}
                    }
                }
            ]

    tk = MockTicker()
    news = res._news(tk)

    assert news is not None
    assert len(news) == 1
    assert news[0]["title"] == "Good News"
    assert news[0]["publisher"] == "Reuters"
    assert news[0]["link"] == "http://example.com/news"

def test_research():
    class MockTicker:
        @property
        def recommendations(self):
            return pd.DataFrame({
                "strongBuy": [5],
                "buy": [10],
                "hold": [3],
                "sell": [1],
                "strongSell": [0]
            })

        @property
        def analyst_price_targets(self):
            return {"mean": 150.0, "low": 100.0, "high": 200.0, "current": 140.0}

        @property
        def earnings_estimate(self):
            return pd.DataFrame({
                "avg": [1.5, 1.8],
                "numberOfAnalysts": [15, 12]
            }, index=["0q", "+1q"])

        @property
        def revenue_estimate(self):
            return pd.DataFrame({
                "avg": [1000000000.0, 1100000000.0],
                "growth": [0.1, 0.15]
            }, index=["0q", "+1q"])

        @property
        def upgrades_downgrades(self):
            return pd.DataFrame({
                "FromGrade": ["Hold", "Buy"],
                "ToGrade": ["Buy", "Hold"],
                "Action": ["up", "down"],
                "Firm": ["Goldman", "Morgan"],
                "currentPriceTarget": [160.0, 140.0]
            }, index=pd.DatetimeIndex(["2023-01-02", "2023-01-01"]))

    tk = MockTicker()
    rs = res._research(tk)

    assert rs is not None
    assert rs["consensus"]["strongBuy"] == 5
    assert rs["consensus"]["mean"] == 150.0

    assert len(rs["estimates"]) == 2
    assert rs["estimates"][0]["eps"] == "$1.50"

    assert len(rs["actions"]) == 2
    assert rs["actions"][0]["action"] == "Upgrade"

def test_stock_research(monkeypatch):
    class MockTicker:
        @property
        def quarterly_income_stmt(self): return None
        @property
        def earnings_dates(self): return None
        @property
        def news(self): return None
        @property
        def recommendations(self): return None

    monkeypatch.setattr(res_mod, "yf_ticker", lambda t: MockTicker())
    monkeypatch.setattr(cache, "get", lambda *args: cache.MISS)
    monkeypatch.setattr(cache, "set", lambda *args: None)

    res_mod._CACHE.clear()

    data = res_mod.stock_research("AAPL")
    assert data["ticker"] == "AAPL"
    assert data["financials"] is None
    assert data["earnings"] is None
