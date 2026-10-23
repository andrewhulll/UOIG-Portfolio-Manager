"""Admin position changes: buy new, add to, trim, sell out, and move cash.

``run`` replays an ordered batch of changes against an in-memory copy of the
affected funds' holdings. With ``write=False`` it is a preview (before/after per
position); with ``write=True`` the same replay is committed in one transaction,
so what an admin confirms is exactly what is applied.
"""
from datetime import datetime, timezone

from src.model import db
from src.model.submissions import execute, rows

SECTORS = ['TMT', 'IME', 'Healthcare', 'Financial', 'Consumer']
CAP_CLASSES = ['Large Cap', 'Mid Cap', 'Small Cap']
KINDS = ('buy_new', 'buy', 'trim', 'sell_all', 'cash')
EPS = 1e-9


class TradeError(ValueError):
    pass


def _num(change, key, positive=True):
    try:
        value = float(change.get(key))
    except (TypeError, ValueError):
        raise TradeError(f'{key} must be a number')
    if value != value or value in (float('inf'), float('-inf')) or (positive and value <= 0):
        raise TradeError(f'{key} must be greater than zero')
    return value


def latest_price(conn, ticker):
    """Most recent stored close (live data first, workbook snapshot as fallback)."""
    for where in ("source != 'xlsx_snapshot'", "1=1"):
        found = rows(conn, f'SELECT close FROM prices WHERE ticker=? AND {where} AND close IS NOT NULL '
                           'ORDER BY date DESC LIMIT 1', (ticker,))
        if found:
            return found[0]['close']
    return None


def overview(conn, funds):
    """Current positions per fund, for the admin editor."""
    out = []
    for fund in funds:
        positions = rows(conn, '''SELECT h.ticker, h.shares, h.entry_price, h.entry_date, s.name,
            s.sector, s.sec_type FROM holdings h JOIN securities s ON s.ticker=h.ticker
            WHERE h.fund=? ORDER BY h.ticker''', (fund['name'],))
        for p in positions:
            p['price'] = 1.0 if p['sec_type'] == 'cash' else latest_price(conn, p['ticker'])
        out.append({'name': fund['name'], 'benchmark': fund['benchmark'], 'positions': positions})
    return out


def _load(conn, fund):
    state = {}
    for r in rows(conn, '''SELECT h.*, s.name, s.sec_type FROM holdings h
            JOIN securities s ON s.ticker=h.ticker WHERE h.fund=?''', (fund,)):
        state[r['ticker']] = r
    return state


def run(conn, changes, funds, note='', actor='', write=False):
    if not isinstance(changes, list) or not changes:
        raise TradeError('Add at least one change')
    if len(changes) > 100:
        raise TradeError('Too many changes in one batch')
    bench = {f['name']: f['benchmark'] for f in funds}
    states, before, new_securities, price_marks, ledger, lines = {}, {}, {}, {}, [], []
    today = datetime.now(timezone.utc).date().isoformat()

    for n, change in enumerate(changes, 1):
        label = f'Change {n}'
        try:
            fund = change.get('fund')
            if fund not in bench:
                raise TradeError('Choose a fund')
            kind = change.get('kind')
            if kind not in KINDS:
                raise TradeError('Unknown change type')
            if fund not in states:
                states[fund] = _load(conn, fund)
                before[fund] = {t: dict(r) for t, r in states[fund].items()}
            state = states[fund]
            cash_row = next((r for r in state.values() if r['sec_type'] == 'cash'), None)
            if cash_row is None:
                raise TradeError(f'{fund} has no cash position to settle against')

            def move_cash(delta, why):
                if abs(delta) < EPS:
                    return
                new = cash_row['shares'] + delta
                if new < -0.005:
                    raise TradeError(f'Not enough cash in {fund}: needs ${-delta:,.2f}, has ${cash_row["shares"]:,.2f}')
                cash_row['shares'] = max(new, 0.0)
                ledger.append((fund, cash_row['ticker'], 'buy' if delta > 0 else 'sell', abs(delta), 1.0, abs(delta), why))

            def settle(delta, route, ticker, why):
                """Route trade cash (+ proceeds / - funding): to cash, an index ETF, or nowhere."""
                route = route or 'cash'
                if route == 'none':
                    return 'not adjusted'
                if route == 'cash':
                    move_cash(delta, why)
                    return 'cash'
                route = str(route).upper()
                index = state.get(route)
                if index is None or index['sec_type'] != 'etf':
                    raise TradeError(f'{fund} does not hold an index ETF called {route}')
                if route == ticker:
                    raise TradeError(f'Choose a different destination than {ticker} itself')
                px = latest_price(conn, route)
                if not px:
                    raise TradeError(f'No stored price for {route}')
                units = delta / px
                if index['shares'] + units < -EPS:
                    raise TradeError(f'Not enough {route} in {fund}: needs {-units:,.4f} sh, has {index["shares"]:,.4f}')
                index['shares'] = max(index['shares'] + units, 0.0)
                ledger.append((fund, route, 'buy' if units > 0 else 'sell', abs(units), px, abs(delta), why))
                return f'{route} ({abs(units):,.4f} sh @ ${px:,.2f})'

            if kind == 'cash':
                direction = change.get('direction')
                if direction not in ('deposit', 'withdraw'):
                    raise TradeError('Choose deposit or withdraw')
                amount = _num(change, 'amount')
                move_cash(amount if direction == 'deposit' else -amount, f'cash {direction}')
                lines.append({'fund': fund, 'ticker': cash_row['ticker'], 'kind': kind,
                              'summary': f'{direction.title()} ${amount:,.2f}'})
                continue

            ticker = str(change.get('ticker') or '').strip().upper()
            if not ticker or len(ticker) > 12 or not all(c.isalnum() or c in '.-' for c in ticker):
                raise TradeError('Enter a valid ticker')
            price = _num(change, 'price')
            holding = state.get(ticker)

            if kind == 'buy_new':
                shares = _num(change, 'shares')
                if holding is not None:
                    raise TradeError(f'{fund} already holds {ticker} — use Add to position')
                sec = rows(conn, 'SELECT * FROM securities WHERE ticker=?', (ticker,))
                if sec:
                    if sec[0]['sec_type'] != 'stock':
                        raise TradeError(f'{ticker} is not a stock')
                    name = sec[0]['name']
                else:
                    name = str(change.get('name') or '').strip()
                    sector, cap = change.get('sector'), change.get('cap_class')
                    if not name or sector not in SECTORS or cap not in CAP_CLASSES:
                        raise TradeError(f'{ticker} is new to the platform: enter its name, sector and cap class')
                    new_securities[ticker] = (ticker, name, sector, cap, 'stock')
                weight = rows(conn, 'SELECT weight FROM benchmark_holdings WHERE index_ticker=? AND ticker=?',
                              (bench[fund], ticker))
                bench_px = latest_price(conn, bench[fund])
                state[ticker] = {'fund': fund, 'ticker': ticker, 'shares': shares, 'entry_price': price,
                                 'entry_date': today, 'passive_weight': weight[0]['weight'] if weight else 0.0,
                                 'bench_ticker': bench[fund], 'bench_entry_price': bench_px,
                                 'name': name, 'sec_type': 'stock', 'new': True}
                price_marks[ticker] = (today, price)
                via = settle(-shares * price, change.get('route'), ticker, f'settlement: buy {ticker}')
                ledger.append((fund, ticker, 'buy', shares, price, shares * price, 'buy new position'))
                lines.append({'fund': fund, 'ticker': ticker, 'kind': kind,
                              'summary': f'Buy {shares:,.4f} @ ${price:,.2f} (new position), funded from {via}'})
                continue

            if holding is None:
                raise TradeError(f'{fund} does not hold {ticker}')
            if holding['sec_type'] == 'cash':
                raise TradeError('Use a cash change for the cash position')
            current = holding['shares'] or 0.0

            if kind == 'buy':
                shares = _num(change, 'shares')
                if holding['sec_type'] == 'stock' and holding['entry_price']:
                    holding['entry_price'] = (current * holding['entry_price'] + shares * price) / (current + shares)
                holding['shares'] = current + shares
                via = settle(-shares * price, change.get('route'), ticker, f'settlement: buy {ticker}')
                ledger.append((fund, ticker, 'buy', shares, price, shares * price, 'add to position'))
                lines.append({'fund': fund, 'ticker': ticker, 'kind': kind,
                              'summary': f'Buy {shares:,.4f} @ ${price:,.2f}, funded from {via}'})
            elif kind == 'trim':
                shares = _num(change, 'shares')
                if shares >= current - EPS:
                    raise TradeError(f'Trim must be less than the {current:,.4f} shares held — use Sell entire position')
                holding['shares'] = current - shares
                via = settle(shares * price, change.get('route'), ticker, f'settlement: sell {ticker}')
                ledger.append((fund, ticker, 'sell', shares, price, shares * price, 'trim position'))
                lines.append({'fund': fund, 'ticker': ticker, 'kind': kind,
                              'summary': f'Sell {shares:,.4f} @ ${price:,.2f}, proceeds to {via}'})
            else:  # sell_all
                if holding['sec_type'] != 'stock':
                    raise TradeError('Only stock positions can be sold out; trim the index instead')
                holding['shares'] = 0.0
                holding['closed'] = True
                via = settle(current * price, change.get('route'), ticker, f'settlement: sell {ticker}')
                ledger.append((fund, ticker, 'sell', current, price, current * price, 'sell entire position'))
                lines.append({'fund': fund, 'ticker': ticker, 'kind': kind,
                              'summary': f'Sell all {current:,.4f} @ ${price:,.2f}, proceeds to {via}'})
        except TradeError as exc:
            raise TradeError(f'{label}: {exc}') from None

    result = []
    for fund, state in states.items():
        for ticker, row in state.items():
            was = before[fund].get(ticker)
            b = was['shares'] if was else 0.0
            a = 0.0 if row.get('closed') else row['shares']
            if was is not None and abs(a - (b or 0.0)) < EPS and not row.get('closed'):
                continue
            result.append({'fund': fund, 'ticker': ticker, 'name': row['name'], 'secType': row['sec_type'],
                           'before': b or 0.0, 'after': a, 'new': bool(row.get('new')), 'closed': bool(row.get('closed'))})
    result.sort(key=lambda r: (r['fund'], r['secType'] != 'stock', r['ticker']))
    if not result:
        raise TradeError('These changes do not change any position')

    if write:
        _commit(conn, states, before, new_securities, price_marks, ledger, today, note, actor)
    return {'positions': result, 'changes': lines}


def _commit(conn, states, before, new_securities, price_marks, ledger, today, note, actor):
    try:
        for sec in new_securities.values():
            execute(conn, 'INSERT INTO securities (ticker, name, sector, cap_class, sec_type) VALUES (?, ?, ?, ?, ?)', sec)
        for ticker, (date, price) in price_marks.items():
            if latest_price(conn, ticker) is None:  # nightly refresh fills in real history
                execute(conn, 'INSERT INTO prices (ticker, date, close, adj_close, source) VALUES (?, ?, ?, ?, ?)',
                        (ticker, date, price, price, 'admin_trade'))
        for fund, state in states.items():
            for ticker, row in state.items():
                was = before[fund].get(ticker)
                if row.get('closed'):
                    execute(conn, 'DELETE FROM holdings WHERE fund=? AND ticker=?', (fund, ticker))
                elif row.get('new'):
                    execute(conn, '''INSERT INTO holdings (fund, ticker, shares, entry_price, entry_date,
                        passive_weight, bench_ticker, bench_entry_price) VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                        (fund, ticker, row['shares'], row['entry_price'], row['entry_date'],
                         row['passive_weight'], row['bench_ticker'], row['bench_entry_price']))
                elif was is not None and (row['shares'] != was['shares'] or row['entry_price'] != was['entry_price']):
                    execute(conn, 'UPDATE holdings SET shares=?, entry_price=? WHERE fund=? AND ticker=?',
                            (row['shares'], row['entry_price'], fund, ticker))
        tag = ' · '.join(x for x in (f'admin {actor}' if actor else '', note.strip()) if x)
        for fund, ticker, action, shares, price, amount, why in ledger:
            execute(conn, 'INSERT INTO transactions (date, fund, ticker, action, shares, price, amount, note) '
                          'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                    (today, fund, ticker, action, shares, price, amount, f'{why} · {tag}' if tag else why))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
