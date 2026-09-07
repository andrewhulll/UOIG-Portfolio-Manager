import pytest
from src.ingest.predictions import load_market_map, stock_predictions
import src.ingest.predictions as predictions_module
from src.model import cache

def test_load_market_map(monkeypatch, tmp_path):
    mock_md = tmp_path / "PREDICTION_MARKETS.md"
    mock_md.write_text("""
### AAPL
| Label | Kalshi | Type | Notes |
|---|---|---|---|
| 1 | Will Apple release AR glasses? | KXAPPLE | Tech | Yes |
| 2 | AAPL earnings beat | KXEARN | Earnings | |

### MSFT
| Label | Kalshi | Type | Notes |
|---|---|---|---|
| 1 | Will Microsoft buy Discord? | KXMSFT | Tech | |
""")
    monkeypatch.setattr(predictions_module, "_MAP_PATH", mock_md)
    predictions_module._map_cache = None

    market_map = load_market_map()
    assert "AAPL" in market_map
    assert len(market_map["AAPL"]) == 2
    assert market_map["AAPL"][0]["kalshi"] == "KXAPPLE"
    assert market_map["AAPL"][0]["label"] == "Will Apple release AR glasses?"

    assert "MSFT" in market_map
    assert len(market_map["MSFT"]) == 1

def test_load_market_map_no_file(monkeypatch, tmp_path):
    monkeypatch.setattr(predictions_module, "_MAP_PATH", tmp_path / "NONEXISTENT.md")
    predictions_module._map_cache = None
    assert load_market_map() == {}

def test_stock_predictions(monkeypatch, tmp_path):
    # Setup mock map
    mock_md = tmp_path / "PREDICTION_MARKETS.md"
    mock_md.write_text("""
### TEST
| Label | Kalshi | Type | Notes |
|---|---|---|---|
| 1 | Will it happen? | KXTEST | Tech | |
""")
    monkeypatch.setattr(predictions_module, "_MAP_PATH", mock_md)
    predictions_module._map_cache = None

    # Mock Kalshi API requests
    def mock_get(path, **params):
        if path == "/events":
            return {
                "events": [{
                    "series_ticker": "KXTEST",
                    "title": "Will it happen event",
                    "category": "Tech",
                    "markets": [
                        {"close_time": "2024-01-01T00:00:00Z", "last_price_dollars": 0.6, "volume": 100}
                    ]
                }]
            }
        return {}

    monkeypatch.setattr(predictions_module, "_get", mock_get)

    # Make sure cache is clean
    predictions_module._CACHE.clear()

    # Needs db_path initialization if cache isn't bypassed,
    # but predictions caches via `cache.get`, which we can mock or let run against a memory DB
    monkeypatch.setattr(cache, "get", lambda *args: cache.MISS)
    monkeypatch.setattr(cache, "set", lambda *args: None)

    res = stock_predictions("TEST")
    assert res["ticker"] == "TEST"
    assert len(res["cards"]) == 1

    card = res["cards"][0]
    assert card["label"] == "Will it happen?"
    assert card["title"] == "Will it happen event"
    assert card["category"] == "Tech"
    assert card["outcomes"][0]["pct"] == 60
    assert card["outcomes"][1]["pct"] == 40
    assert card["volume"] == 100

def test_mult():
    assert predictions_module._mult(0.5) == "2.00x"
    assert predictions_module._mult(0.1) == "10.0x"
    assert predictions_module._mult(-1) is None
    assert predictions_module._mult(0) is None

def test_f():
    assert predictions_module._f("1.5") == 1.5
    assert predictions_module._f(2) == 2.0
    assert predictions_module._f("abc") == 0.0
    assert predictions_module._f(None) == 0.0
