"""Coverage/movers/watchlist regression checks; no live services or production DB."""
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api import main, coverage as routes
from src.analytics.coverage import context, position_facts, movers
from src.ingest import fundamentals, lookup, providers
from src.model import schema, cache

CFG = {"funds": [{"name": "Tall Firs", "benchmark": "IWV"}, {"name": "Alumni Fund", "benchmark": "IWM"}]}


def seed(conn):
    schema.create_schema(conn)
    conn.executemany("INSERT INTO securities (ticker,name,sector,sec_type) VALUES (?,?,?,?)", [
        ("A", "Alpha", "TMT", "stock"), ("B", "Beta", "TMT", "stock"), ("IWV", "Index", None, "etf"), ("CASH", "Cash", None, "cash")])
    conn.executemany("INSERT INTO holdings (fund,ticker,shares,entry_price,passive_weight) VALUES (?,?,?,?,?)", [
        ("Tall Firs", "A", 10, 80, .1), ("Alumni Fund", "A", 5, 100, .2), ("Tall Firs", "B", 10, 110, .15),
        ("Tall Firs", "IWV", 2, None, None), ("Tall Firs", "CASH", 10000, 1, 0)])
    for t, last in [("A", 120), ("B", 80), ("IWV", 100), ("CASH", 1)]:
        conn.executemany("INSERT INTO prices (ticker,date,close,adj_close,source) VALUES (?,?,?,?,?)", [
            (t, "2026-06-30", 80 if t != "CASH" else 1, 80 if t != "CASH" else 1, "yfinance"),
            (t, "2026-08-31", 100 if t != "CASH" else 1, 100 if t != "CASH" else 1, "yfinance"),
            (t, "2026-09-03", 100 if t != "CASH" else 1, 100 if t != "CASH" else 1, "yfinance"),
            (t, "2026-09-10", last, last, "yfinance")])
    conn.executemany("INSERT INTO fundamentals (ticker,pe,forward_pe,revenue_growth,market_cap,week52_low,week52_high,volume,average_volume,exchange,updated) VALUES (?,?,?,?,?,?,?,?,?,?,?)", [
        ("A", 99, 20, .14, 3e12, 80, 160, 1400, 1000, "NASDAQ", "2026-09-10"),
        ("B", 50, 40, None, 1e12, 60, 100, 0, 0, "NYSE", "2026-09-10")])
    conn.executemany("INSERT INTO benchmark_holdings (index_ticker,ticker,weight) VALUES (?,?,?)", [("IWV", "A", .1), ("IWV", "B", .15), ("IWM", "A", .2)])
    conn.commit()


@pytest.fixture
def conn():
    conn = sqlite3.connect(":memory:")
    seed(conn)
    yield conn
    conn.close()


def test_combined_statistics_and_selected_fund(conn):
    facts = position_facts(context(CFG, conn), "A", "TMT")
    assert facts["weight"] == pytest.approx(1800 / 2800 * 100)
    assert facts["costBasis"] == pytest.approx(1300 / 15)
    assert facts["unrealized"] == 500
    assert facts["activeWeightBp"] == pytest.approx((1800 / 2800 - (2200 * .1 + 600 * .2) / 2800) * 10000)
    assert facts["sectorForwardPE"] == pytest.approx((1800 * 20 + 800 * 40) / 2600)
    single = position_facts(context(CFG, conn, "tallfirs"), "A", "TMT")
    assert single["weight"] == pytest.approx(1200 / 2200 * 100)
    assert single["costBasis"] == 80
    other = position_facts(context(CFG, conn, "alumni"), "B", "TMT")
    assert other["heldInFund"] is False and other["unrealized"] is None


def test_missing_basis_benchmark_and_true_forward_pe(conn):
    conn.execute("UPDATE holdings SET entry_price=NULL WHERE fund='Alumni Fund' AND ticker='A'")
    conn.execute("DELETE FROM benchmark_holdings")
    conn.execute("UPDATE holdings SET passive_weight=NULL WHERE fund='Alumni Fund'")
    conn.execute("UPDATE fundamentals SET forward_pe=NULL")
    facts = position_facts(context(CFG, conn), "A", "TMT")
    assert facts["costBasis"] is None and facts["unrealized"] is None
    assert facts["activeWeightBp"] is None and facts["sectorForwardPE"] is None
    conn.execute("UPDATE holdings SET passive_weight=.2 WHERE fund='Alumni Fund'")
    assert position_facts(context(CFG, conn), "A")["activeWeightBp"] is not None


@pytest.mark.parametrize("window,boundary,ret", [("1W", "2026-09-03", 20), ("MTD", "2026-08-31", 20), ("QTD", "2026-06-30", 50)])
def test_movers_windows_and_duplicate_funds(conn, window, boundary, ret):
    result = movers(CFG, conn, window=window)
    assert result["startDate"] == boundary
    alpha = next(r for r in result["contributors"] if r["ticker"] == "A")
    assert alpha["pct"] == pytest.approx(ret)
    assert alpha["contribution_bp"] == pytest.approx(round(1800 / 2800 * ret * 100, 4))
    assert result["totalCount"] == 3 and result["includedCount"] == 3  # ETF yes, cash no
    assert len([r for r in result["contributors"] if r["ticker"] == "A"]) == 1
    assert all(r["contribution_bp"] < 0 for r in result["detractors"])


def test_movers_missing_data_is_not_renormalized(conn):
    conn.execute("DELETE FROM prices WHERE ticker='B' AND date < '2026-09-10'")
    result = movers(CFG, conn)
    assert result["missingTickers"] == ["B"]
    assert result["contributors"][0]["contribution_bp"] == pytest.approx(round(1800 / 2800 * .2 * 10000, 4))


def test_period_boundary_uses_prior_trading_close(conn):
    conn.execute("UPDATE prices SET date='2026-08-28' WHERE date='2026-08-31'")
    result = movers(CFG, conn)
    assert result["contributors"][0]["startDate"] == "2026-08-28"


@pytest.fixture
def api(monkeypatch, tmp_path):
    path = tmp_path / 'coverage.db'
    conn = sqlite3.connect(path); seed(conn); conn.close()
    monkeypatch.setattr(main, '_conn', lambda: sqlite3.connect(path))
    monkeypatch.setattr(main, 'CFG', CFG)
    monkeypatch.setattr(main.wc, 'auth_disabled', lambda: False)
    monkeypatch.setattr(main, '_current', lambda req: (SimpleNamespace(user={'id': req.headers['x-user']}, role='member'), None) if 'x-user' in req.headers else (None, None))
    monkeypatch.setattr(routes, 'closed_snapshot', lambda t: {'earnings': {'next': 'Oct 28, 2026'}})
    monkeypatch.setattr(routes, 'search_symbols', lambda t, **k: [{'symbol': t}] if t != 'INVALID' else [])
    monkeypatch.setattr(routes, 'quote_overview', lambda t, **k: {'n': 'External equity', 'px': 100, 'chg': 1, 'mc': 10, 'forwardPE': 25, 'lo': 50, 'hi': 150, 'volume': 120, 'averageVolume': 100, 'asOf': '2026-09-10'})
    client = TestClient(main.app)  # No lifespan/background services.
    def call(method, path, user='a', body=None):
        return client.request(method, '/api' + path, headers={'x-user': user} if user else {}, **({'json': body} if body is not None else {}))
    yield SimpleNamespace(call=call, path=path)
    client.close()


def test_watchlist_roundtrip_user_isolation_and_duplicate_alias(api):
    assert api.call('GET', '/watchlist', user=None).status_code == 401
    assert api.call('POST', '/watchlist', body={'ticker': 'brk.b'}).status_code == 200
    assert api.call('POST', '/watchlist', body={'ticker': 'BRK-B'}).status_code == 200
    items = api.call('GET', '/watchlist').json()['items']
    assert len(items) == 1 and items[0]['ticker'] == 'BRK-B'
    assert items[0]['rangePct'] == 50 and items[0]['volumeRatio'] == 1.2
    assert api.call('GET', '/watchlist', 'b').json()['items'] == []
    api.call('DELETE', '/watchlist/BRK-B', 'b')
    assert len(api.call('GET', '/watchlist').json()['items']) == 1
    api.call('DELETE', '/watchlist/BRK-B')
    assert api.call('GET', '/watchlist').json()['items'] == []


def test_owned_watchlist_and_other_fund_never_lookup_live(api, monkeypatch):
    def prohibited(*args, **kwargs): raise AssertionError('Owned equity reached live Yahoo')
    monkeypatch.setattr(routes, 'quote_overview', prohibited)
    monkeypatch.setattr(routes, 'search_symbols', prohibited)
    item = api.call('POST', '/watchlist', body={'ticker': 'A'}).json()
    assert item['held'] and item['price'] == 120 and item['forwardPE'] == 20
    assert item['marketCap'] == 3e12 and item['volumeRatio'] == 1.4
    assert item['nextEarnings'] == 'Oct 28, 2026'
    assert api.call('GET', '/movers?fund=alumni').json()['totalCount'] == 1


def test_invalid_and_throttled_search_are_distinct(api, monkeypatch):
    assert api.call('POST', '/watchlist', body={'ticker': 'INVALID'}).status_code == 404
    def throttle(*a, **kw): raise providers.MarketDataRateLimited('Try later')
    monkeypatch.setattr(routes, 'search_symbols', throttle)
    assert api.call('POST', '/watchlist', body={'ticker': 'XYZ'}).status_code == 429
    assert api.call('GET', '/watchlist').json()['items'] == []


def test_quote_failure_preserves_membership_and_is_row_local(api, monkeypatch):
    def throttle(*a, **kw): raise providers.MarketDataRateLimited('Try later')
    monkeypatch.setattr(routes, 'quote_overview', throttle)
    response = api.call('POST', '/watchlist', body={'ticker': 'XYZ'})
    assert response.status_code == 200 and response.json()['error']
    api.call('POST', '/watchlist', body={'ticker': 'A'})
    items = api.call('GET', '/watchlist').json()['items']
    assert len(items) == 2 and items[0]['error'] and items[1]['price'] == 120
    conn = sqlite3.connect(api.path); schema.truncate_all(conn)
    assert conn.execute('SELECT COUNT(*) FROM watchlist').fetchone()[0] == 2
    conn.close()


def test_coverage_route_enriched_without_changing_thesis(api, monkeypatch):
    monkeypatch.setattr(main.auth_organization, 'user_coverage', lambda uid: [{'ticker': 'B', 'sector': 'TMT'}])
    monkeypatch.setattr(main, 'closed_snapshot', lambda t: {'earnings': {'next': 'Oct 28, 2026'}})
    monkeypatch.setattr(main, 'stock_news', lambda t: pytest.fail('headlines must not block coverage'))
    monkeypatch.setattr(main, 'stock_thesis', lambda t: {'thesis': {'date': '2026-09-10', 'points': ['One', 'Two', 'Three']}})
    monkeypatch.setattr(main, 'quote_overview', lambda t: pytest.fail('owned live lookup'))
    response = api.call('GET', '/coverage/me?fund=alumni')
    assert response.status_code == 200, response.text
    card = response.json()['tickers'][0]
    assert card['held'] and not card['heldInFund']
    assert card['price'] == 80 and card['forwardPE'] == 40
    assert card['exchange'] == 'NYSE' and card['closeDate'] == '2026-09-10'
    assert card['news'] == []
    assert card['thesis']['points'] == ['One', 'Two', 'Three']
    assert api.call('GET', '/coverage/me?fund=bogus').status_code == 422


def test_refresh_stores_true_forward_separately(monkeypatch, conn):
    monkeypatch.setattr(fundamentals, '_info', lambda t: {'trailingPE': 35, 'revenueGrowth': .2, 'volume': 100, 'averageVolume': 200})
    fundamentals.pull_fundamentals({}, conn, ['A'])
    assert conn.execute("SELECT pe,forward_pe,revenue_growth,volume,average_volume FROM fundamentals WHERE ticker='A'").fetchone() == (35, None, .2, 100, 200)


def test_retry_typed_failure_is_opt_in():
    def throttle(): raise RuntimeError('429 Too Many Requests')
    assert providers.yf_retry(throttle) is None
    with pytest.raises(providers.MarketDataRateLimited): providers.yf_retry(throttle, strict=True)


def test_quote_cache_reused_and_no_trailing_forward_fallback(monkeypatch):
    lookup._QUOTE_CACHE.clear()
    monkeypatch.setattr(cache, 'get', lambda *a: cache.MISS)
    monkeypatch.setattr(cache, 'set', lambda *a: None)
    calls = []
    def ticker(t):
        calls.append(t)
        return SimpleNamespace(info={'quoteType': 'EQUITY', 'currentPrice': 100, 'previousClose': 90, 'trailingPE': 99}, fast_info=None)
    monkeypatch.setattr(lookup, 'yf_ticker', ticker)
    first = lookup.quote_overview('EXT', strict=True)
    second = lookup.quote_overview('EXT', strict=True)
    assert first == second and calls == ['EXT']
    assert first['pe'] == 99 and first['forwardPE'] is None
