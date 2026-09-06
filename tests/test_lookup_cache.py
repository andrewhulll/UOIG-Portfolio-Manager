"""Regression coverage for durable caching after the Capital IQ merge."""
import pandas as pd
import pytest

from src.ingest import lookup
from src.model import cache


@pytest.fixture
def cached_lookup(monkeypatch, tmp_path):
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.setattr(cache, '_dbpath', str(tmp_path / 'cache.db'))
    monkeypatch.setattr(cache, '_ensured', False)
    for name in ('_QUOTE_CACHE', '_SERIES_CACHE', '_SEARCH_CACHE', '_HOLDERS_CACHE'):
        monkeypatch.setattr(lookup, name, {})

    class Provider:
        def get_price_history(self, *args, **kwargs):
            return pd.DataFrame([
                {'date': '2026-08-30', 'close': 100.0},
                {'date': '2026-08-31', 'close': 110.0},
            ])

        def search_companies(self, *args, **kwargs):
            return [{'symbol': 'AAPL', 'name': 'Apple', 'exchange': 'NASDAQ'}]

    monkeypatch.setattr(lookup, '_ciq_provider', Provider)


@pytest.mark.parametrize('kind', ['quote', 'series', 'search', 'holders'])
def test_durable_cache_survives_memory_reset(cached_lookup, monkeypatch, kind):
    class Yahoo:
        institutional_holders = pd.DataFrame([
            {'Holder': 'Fund', 'pctHeld': 0.1, 'Shares': 10, 'Value': 1000},
        ])

    monkeypatch.setattr(lookup.yf, 'Ticker', lambda _: Yahoo())
    fetch, memory = {
        'quote': (lambda: lookup.quote_overview('AAPL'), lookup._QUOTE_CACHE),
        'series': (lambda: lookup.live_series('AAPL'), lookup._SERIES_CACHE),
        'search': (lambda: lookup.search_symbols('AAPL'), lookup._SEARCH_CACHE),
        'holders': (lambda: lookup.institutional_holders('AAPL'), lookup._HOLDERS_CACHE),
    }[kind]
    expected = fetch()
    assert expected
    if kind == 'quote':
        assert expected['px'] == 110.0
        assert cache.get('quote', 'AAPL') is cache.MISS
    if kind == 'series':
        assert expected['close'] == [100.0, 110.0]
    memory.clear()

    def unavailable(*args, **kwargs):
        raise AssertionError('A durable cache hit must not call a provider')

    monkeypatch.setattr(lookup, '_ciq_provider', unavailable)
    monkeypatch.setattr(lookup.yf, 'Ticker', unavailable)
    assert fetch() == expected
