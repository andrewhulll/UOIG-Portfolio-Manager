"""The merged lifespan refactors retain a lazy, non-cash ticker provider."""
import asyncio
import sqlite3

import pytest

from api import main
from src.ingest import live_prices


def test_lifespan_supplies_fresh_tickers_and_closes_connections(monkeypatch):
    connections = []
    callbacks = []

    def connect():
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE securities (ticker TEXT, sec_type TEXT)")
        conn.executemany("INSERT INTO securities VALUES (?, ?)", [
            ("AAPL", "stock"), ("SPY", "etf"), ("BGNXX", "cash"),
        ])
        connections.append(conn)
        return conn

    def start(get_tickers, interval):
        assert interval == 12
        callbacks.append(get_tickers)

    monkeypatch.setattr(main, "_conn", connect)
    monkeypatch.setattr(main, "CFG", {"market_data": {"live_interval_seconds": 12}})
    monkeypatch.setattr(live_prices, "start", start)

    async def exercise():
        async with main.app.router.lifespan_context(main.app):
            assert len(callbacks) == 1
            assert connections == []
            assert callbacks[0]() == ["AAPL", "SPY"]
            assert callbacks[0]() == ["AAPL", "SPY"]

    asyncio.run(exercise())
    assert len(connections) == 2
    for conn in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            conn.execute("SELECT 1")
