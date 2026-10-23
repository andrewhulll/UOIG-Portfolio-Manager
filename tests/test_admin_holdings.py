"""Admin position changes: preview/apply parity, cash settlement, and admin-only access."""
import pytest

from tests.test_submissions import api  # noqa: F401  (fixture)
from src.model.schema import create_schema

FUND = 'Tall Firs'


@pytest.fixture
def seeded(api):  # noqa: F811
    conn = api.connect()
    create_schema(conn)
    for row in [('AAPL', 'Apple', 'TMT', 'Large Cap', 'stock'), ('IWV', 'Russell 3000', 'Index', 'Index ETF', 'etf'),
                ('BGNXX', 'Cash', 'Cash', 'Cash', 'cash')]:
        conn.execute('INSERT INTO securities VALUES (?,?,?,?,?)', row)
    conn.execute("INSERT INTO holdings (fund,ticker,shares,entry_price,entry_date) VALUES (?, 'AAPL', 100, 100, '2022-01-01')", (FUND,))
    conn.execute("INSERT INTO holdings (fund,ticker,shares,entry_price) VALUES (?, 'IWV', 50, 1)", (FUND,))
    conn.execute("INSERT INTO holdings (fund,ticker,shares,entry_price) VALUES (?, 'BGNXX', 10000, 1)", (FUND,))
    conn.execute("INSERT INTO securities VALUES ('IWM','Russell 2000','Index ETF','Index ETF','etf')")
    conn.execute("INSERT INTO securities VALUES ('BNGXX','Cash','Cash','Cash','cash')")
    for tk, sh, ep in (('IWM', 200, 1), ('BNGXX', 5000, 1)):
        conn.execute("INSERT INTO holdings (fund,ticker,shares,entry_price) VALUES ('Alumni Fund', ?, ?, ?)", (tk, sh, ep))
    for tk, px in (('IWV', 400), ('IWM', 200), ('AAPL', 100)):
        conn.execute("INSERT INTO prices (ticker,date,close,adj_close,source) VALUES (?, '2026-06-26', ?, ?, 'yfinance')", (tk, px, px))
    conn.commit()
    conn.close()
    return api


def shares(api, ticker, fund=FUND):
    conn = api.connect()
    try:
        row = conn.execute('SELECT shares, entry_price FROM holdings WHERE fund=? AND ticker=?', (fund, ticker)).fetchone()
        return row
    finally:
        conn.close()


def post(api, path, changes, user='admin', **extra):
    return api.call('POST', '/admin/holdings' + path, user=user, body={'changes': changes, **extra})


def test_only_admins(seeded):
    change = [{'fund': FUND, 'kind': 'cash', 'direction': 'deposit', 'amount': 5}]
    assert seeded.call('GET', '/admin/holdings', user='a').status_code == 403
    assert seeded.call('GET', '/admin/holdings', user='lead').status_code == 403
    assert post(seeded, '/preview', change, user='a').status_code == 403
    assert post(seeded, '/apply', change, user='a', confirm=True).status_code == 403
    assert seeded.call('GET', '/admin/holdings', user='nobody').status_code == 401
    assert shares(seeded, 'BGNXX')[0] == 10000


def test_apply_needs_confirm_and_preview_writes_nothing(seeded):
    trim = [{'fund': FUND, 'kind': 'trim', 'ticker': 'aapl', 'shares': 40, 'price': 200}]
    preview = post(seeded, '/preview', trim).json()
    assert preview['positions'][0]['before'] == 100 and preview['positions'][0]['after'] == 60
    assert shares(seeded, 'AAPL')[0] == 100
    assert post(seeded, '/apply', trim).status_code == 400
    assert shares(seeded, 'AAPL')[0] == 100


def test_trim_add_sell_buy_new_and_cash(seeded):
    changes = [
        {'fund': FUND, 'kind': 'trim', 'ticker': 'AAPL', 'shares': 40, 'price': 200},       # +8000 cash
        {'fund': FUND, 'kind': 'buy', 'ticker': 'AAPL', 'shares': 40, 'price': 100},        # -4000, avg cost 100
        {'fund': FUND, 'kind': 'buy', 'ticker': 'IWV', 'shares': 10, 'price': 400},         # -4000
        {'fund': FUND, 'kind': 'buy_new', 'ticker': 'NVDA', 'shares': 5, 'price': 100,
         'name': 'NVIDIA', 'sector': 'TMT', 'cap_class': 'Large Cap'},                      # -500
        {'fund': FUND, 'kind': 'cash', 'direction': 'deposit', 'amount': 1000},
    ]
    assert post(seeded, '/apply', changes, confirm=True, note='rebalance').status_code == 200
    assert shares(seeded, 'AAPL')[0] == 100 and shares(seeded, 'IWV')[0] == 60
    assert shares(seeded, 'NVDA')[0] == 5 and shares(seeded, 'NVDA')[1] == 100
    assert shares(seeded, 'BGNXX')[0] == pytest.approx(10000 + 8000 - 4000 - 4000 - 500 + 1000)

    sell = [{'fund': FUND, 'kind': 'sell_all', 'ticker': 'NVDA', 'price': 120}]
    assert post(seeded, '/apply', sell, confirm=True).status_code == 200
    assert shares(seeded, 'NVDA') is None
    assert shares(seeded, 'BGNXX')[0] == pytest.approx(10500 + 600)
    conn = seeded.connect()
    assert conn.execute('SELECT count(*) FROM transactions').fetchone()[0] >= 8
    conn.close()


def test_validation_is_atomic(seeded):
    bad = [{'fund': FUND, 'kind': 'trim', 'ticker': 'AAPL', 'shares': 10, 'price': 100},
           {'fund': FUND, 'kind': 'buy', 'ticker': 'AAPL', 'shares': 1000, 'price': 1000}]  # exceeds cash
    response = post(seeded, '/apply', bad, confirm=True)
    assert response.status_code == 422 and 'Not enough cash' in response.json()['detail']
    assert shares(seeded, 'AAPL')[0] == 100 and shares(seeded, 'BGNXX')[0] == 10000
    for change in ({'kind': 'trim', 'ticker': 'AAPL', 'shares': 100, 'price': 1},
                   {'kind': 'sell_all', 'ticker': 'IWV', 'price': 1},
                   {'kind': 'buy_new', 'ticker': 'AAPL', 'shares': 1, 'price': 1},
                   {'kind': 'buy_new', 'ticker': 'ZZZZ', 'shares': 1, 'price': 1},
                   {'kind': 'buy', 'ticker': 'AAPL', 'shares': -1, 'price': 1}):
        assert post(seeded, '/preview', [{'fund': FUND, **change}]).status_code == 422


def test_sale_proceeds_route_into_the_index(seeded):
    sell = [{'fund': FUND, 'kind': 'trim', 'ticker': 'AAPL', 'shares': 40, 'price': 100, 'route': 'IWV'}]  # $4000 / $400
    preview = post(seeded, '/preview', sell).json()
    assert {p['ticker']: p['after'] for p in preview['positions']} == {'AAPL': 60, 'IWV': 60}
    assert post(seeded, '/apply', sell, confirm=True).status_code == 200
    assert shares(seeded, 'IWV')[0] == 60 and shares(seeded, 'BGNXX')[0] == 10000

    # Selling out of the index to fund a buy instead of cash.
    buy = [{'fund': FUND, 'kind': 'buy', 'ticker': 'AAPL', 'shares': 10, 'price': 100, 'route': 'IWV'}]
    assert post(seeded, '/apply', buy, confirm=True).status_code == 200
    assert shares(seeded, 'IWV')[0] == pytest.approx(60 - 2.5) and shares(seeded, 'BGNXX')[0] == 10000


def test_route_validation(seeded):
    base = {'fund': FUND, 'kind': 'trim', 'ticker': 'AAPL', 'shares': 1, 'price': 100}
    assert post(seeded, '/preview', [{**base, 'route': 'IWM'}]).status_code == 422       # other fund's index
    assert post(seeded, '/preview', [{**base, 'route': 'BGNXX'}]).status_code == 422
    assert post(seeded, '/preview', [{**base, 'kind': 'buy', 'shares': 5000, 'route': 'IWV'}]).status_code == 422
    assert post(seeded, '/preview', [{**base, 'ticker': 'IWV', 'route': 'IWV'}]).status_code == 422
    assert post(seeded, '/preview', [{**base, 'route': 'none'}]).status_code == 200


def test_same_stock_in_both_funds(seeded):
    new = {'kind': 'buy_new', 'ticker': 'NVDA', 'price': 100, 'name': 'NVIDIA', 'sector': 'TMT', 'cap_class': 'Large Cap'}
    changes = [{**new, 'fund': FUND, 'shares': 10, 'route': 'cash'},
               {**new, 'fund': 'Alumni Fund', 'shares': 20, 'route': 'IWM'}]
    assert post(seeded, '/apply', changes, confirm=True).status_code == 200
    assert shares(seeded, 'NVDA')[0] == 10 and shares(seeded, 'NVDA', 'Alumni Fund')[0] == 20
    assert shares(seeded, 'BGNXX')[0] == 9000
    assert shares(seeded, 'IWM', 'Alumni Fund')[0] == pytest.approx(200 - 10)
