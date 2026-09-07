import pytest
from src import data_tools
import src.data_tools as dt

def test_json():
    # Small json
    res = dt._json({"a": 1})
    assert res == '{"a":1}'

    # Truncated json
    large_obj = {"a": "x" * 10000}
    res = dt._json(large_obj)
    assert len(res) == dt._LIMIT + 12 # 12 for "…[truncated]"
    assert res.endswith("…[truncated]")

def test_run_tool(monkeypatch):
    monkeypatch.setattr(dt, "stock_research", lambda t: {"research": t})
    monkeypatch.setattr(dt, "stock_predictions", lambda t: {"predictions": t})
    monkeypatch.setattr(dt, "stock_thesis", lambda t: {"thesis": t})

    res, is_err = dt.run_tool("get_stock_fundamentals", {"ticker": "aapl"})
    assert not is_err
    assert res == '{"research":"AAPL"}'

    res, is_err = dt.run_tool("get_predictions", {"ticker": "aapl"})
    assert not is_err
    assert res == '{"predictions":"AAPL"}'

    res, is_err = dt.run_tool("get_thesis", {"ticker": "aapl"})
    assert not is_err
    assert res == '{"thesis":"AAPL"}'

    assert dt.run_tool("unknown_tool", {"ticker": "aapl"}) is None

def test_run_tool_error(monkeypatch):
    def boom(t):
        raise ValueError("Boom")

    monkeypatch.setattr(dt, "stock_research", boom)

    res, is_err = dt.run_tool("get_stock_fundamentals", {"ticker": "aapl"})
    assert is_err
    assert "Tool error: Boom" in res
