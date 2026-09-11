"""The API must not start a recurring market-hours quote poller."""
import asyncio

from api import main
from src.ingest import live_prices


def test_app_does_not_start_quote_poller(monkeypatch):
    calls = []
    monkeypatch.setattr(live_prices, "start", lambda *_a, **_kw: calls.append(True))

    async def exercise():
        async with main.app.router.lifespan_context(main.app):
            pass

    asyncio.run(exercise())
    assert calls == []
