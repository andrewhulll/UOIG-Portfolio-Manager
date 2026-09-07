"""Weekly draft -> lead inbox -> analyst acknowledgement, with no external services."""
import copy
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api import main
from api import submissions as routes
from src.model import submissions as store
from src.model.schema import create_schema, truncate_all


MEMBERS = [
    {'id': 'a', 'name': 'Alex Analyst', 'role': 'member', 'sectors': ['TMT', 'Healthcare'],
     'coverage': [{'ticker': 'AAPL', 'sector': 'TMT'}, {'ticker': 'LLY', 'sector': 'Healthcare'}]},
    {'id': 'b', 'name': 'Blair Analyst', 'role': 'analyst', 'sectors': ['TMT'], 'coverage': []},
    {'id': 'lead', 'name': 'Taylor Lead', 'role': 'sector-leader', 'sectors': ['TMT']},
    {'id': 'colead', 'name': 'Casey Lead', 'role': 'sector-leader', 'sectors': ['TMT']},
    {'id': 'health', 'name': 'Harper Lead', 'role': 'sector-leader', 'sectors': ['Healthcare']},
    {'id': 'admin', 'name': 'Admin', 'role': 'admin', 'sectors': []},
]


@pytest.fixture
def api(monkeypatch, tmp_path):
    path = tmp_path / 'weekly.db'
    members = copy.deepcopy(MEMBERS)

    def connect():
        conn = sqlite3.connect(path, timeout=20)
        conn.execute('PRAGMA foreign_keys=ON')
        return conn

    monkeypatch.setattr(main, '_conn', connect)
    monkeypatch.setattr(main.wc, 'auth_disabled', lambda: False)
    monkeypatch.setattr(routes, 'directory', lambda: members)
    monkeypatch.setattr(store, 'now', lambda: datetime(2026, 9, 10, 22, 0, tzinfo=timezone.utc))

    def session(request):
        uid = request.headers.get('x-test-user')
        member = next((m for m in members if m['id'] == uid), None)
        if not member:
            return None, None
        return SimpleNamespace(user={'id': uid, 'name': member['name']}, role=member['role']), None

    monkeypatch.setattr(main, '_current', session)
    client = TestClient(main.app)  # No lifespan: never start the quote poller.

    def call(method, url, user='a', body=None):
        return client.request(method, '/api' + url, headers={'x-test-user': user},
                              **({'json': body} if body is not None else {}))

    yield SimpleNamespace(call=call, connect=connect, members=members)
    client.close()


def flag(api, **changes):
    body = {'title': 'New product announcement', 'ticker': 'AAPL', 'sector': 'TMT',
            'url': 'https://example.com/news', 'note': 'Watch the margin impact.'}
    body.update(changes)
    response = api.call('POST', '/flags', body=body)
    assert response.status_code == 200, response.text
    return response.json()


def submit(api, sector='TMT'):
    response = api.call('POST', '/submissions', body={'sector': sector})
    assert response.status_code == 200, response.text
    return response.json()


def test_round_trip_delivers_to_all_leads_and_ack_to_analyst(api):
    article = flag(api)
    summary = flag(api, title='Weekly outlook', url=None, ticker=None, note='Our own research.')
    response = api.call('PATCH', '/flags/' + article['id'], body={
        'title': article['title'], 'ticker': 'AAPL', 'url': article['url'],
        'note': 'Updated analysis', 'sector': 'TMT'})
    assert response.status_code == 200
    sent = submit(api)
    assert sent['status'] == 'submitted'
    assert {item['id'] for item in sent['items']} == {article['id'], summary['id']}
    for lead in ('lead', 'colead'):
        inbox = api.call('GET', '/inbox', lead).json()
        assert inbox['unread'] == 1
        assert inbox['messages'][0]['analyst'] == 'Alex Analyst'
        received = {item['id']: item for item in inbox['messages'][0]['items']}
        assert received[article['id']]['note'] == 'Updated analysis'
    assert api.call('GET', '/inbox', 'health').json()['messages'] == []
    message_id = api.call('GET', '/inbox', 'lead').json()['messages'][0]['message_id']
    assert api.call('POST', f'/inbox/{message_id}/read', 'lead').status_code == 200
    assert api.call('GET', '/inbox', 'lead').json()['unread'] == 0
    # Reading is distinct from the explicit acknowledgement.
    assert api.call('GET', '/flags/mine').json()['submissions'][0]['status'] == 'submitted'
    ack = api.call('POST', f"/submissions/{sent['id']}/ack", 'lead')
    assert ack.status_code == 200
    assert ack.json()['acked_by'] == 'lead'
    incoming = api.call('GET', '/inbox').json()
    assert incoming['unread'] == 1
    assert incoming['messages'][0]['kind'] == 'ack'
    assert incoming['messages'][0]['ackedByName'] == 'Taylor Lead'
    assert api.call('GET', '/flags/mine').json()['submissions'][0]['status'] == 'acked'
    api.call('POST', f"/submissions/{sent['id']}/ack", 'colead')
    assert len(api.call('GET', '/inbox').json()['messages']) == 1
    assert api.call('GET', '/flags/mine').json()['submissions'][0]['acked_by'] == 'lead'


def test_duplicate_flag_and_submit_are_idempotent_and_submitted_items_immutable(api):
    article = flag(api)
    assert flag(api)['id'] == article['id']
    first, second = submit(api), submit(api)
    assert first['id'] == second['id']
    assert len(api.call('GET', '/inbox', 'lead').json()['messages']) == 1
    assert api.call('POST', '/flags', body={'title': 'Too late', 'sector': 'TMT'}).status_code == 409
    assert api.call('DELETE', '/flags/' + article['id']).status_code == 409
    assert api.call('PATCH', '/flags/' + article['id'], body={'title': 'Changed'}).status_code == 409


def test_sector_queue_board_and_cross_sector_denials(api):
    flag(api)
    sent = submit(api)
    health_flag = flag(api, sector='Healthcare', ticker='LLY', url=None)
    tmt = api.call('GET', '/submissions', 'lead').json()
    assert {r['sector'] for r in tmt['board']} == {'TMT'}
    assert {r['analyst']: r['status'] for r in tmt['board']} == {'Alex Analyst': 'submitted', 'Blair Analyst': 'pending'}
    assert len(tmt['submissions']) == 1
    assert health_flag['id'] not in [f['id'] for s in tmt['submissions'] for f in s['items']]
    assert api.call('GET', '/submissions?sector=Healthcare', 'lead').status_code == 403
    assert api.call('POST', f"/submissions/{sent['id']}/ack", 'health').status_code == 403
    assert api.call('GET', '/submissions', 'a').status_code == 403
    assert api.call('POST', f"/submissions/{sent['id']}/ack", 'a').status_code == 403
    assert len(api.call('GET', '/submissions', 'admin').json()['board']) == 3
    assert api.call('GET', '/submissions', 'health').json()['submissions'] == []
    submit(api, 'Healthcare')
    assert len(api.call('GET', '/inbox', 'health').json()['messages']) == 1


def test_ownership_roles_and_session_gate(api):
    article = flag(api)
    assert api.call('DELETE', '/flags/' + article['id'], 'b').status_code == 404
    assert api.call('PATCH', '/flags/' + article['id'], 'b', {'title': 'Hijack'}).status_code == 404
    assert api.call('GET', '/flags/mine', 'b').json()['flags'] == []
    for role in ('lead', 'admin'):
        assert api.call('POST', '/flags', role, {'title': 'No', 'sector': 'TMT'}).status_code == 403
        assert api.call('POST', '/submissions', role, {'sector': 'TMT'}).status_code == 403
    assert api.call('POST', '/flags', 'b', {'title': 'No', 'sector': 'Healthcare'}).status_code == 403
    assert api.call('POST', '/flags', 'b', {'title': 'Own summary', 'sector': 'TMT'}).status_code == 200
    for path in ('/flags/mine', '/inbox', '/submissions'):
        assert api.call('GET', path, 'unknown').status_code == 401
    sent = submit(api)
    message = api.call('GET', '/inbox', 'lead').json()['messages'][0]
    assert api.call('POST', f"/inbox/{message['message_id']}/read", 'b').status_code == 404
    api.members[2]['sectors'] = ['Healthcare']
    assert api.call('GET', '/inbox', 'lead').json()['messages'] == []
    assert api.call('POST', f"/submissions/{sent['id']}/ack", 'lead').status_code == 403


def test_empty_missing_lead_delete_and_past_weeks(api, monkeypatch):
    assert api.call('POST', '/submissions', body={'sector': 'TMT'}).status_code == 422
    article = flag(api)
    assert api.call('DELETE', '/flags/' + article['id']).status_code == 200
    assert api.call('GET', '/flags/mine').json()['flags'] == []
    article = flag(api)
    api.members[:] = [m for m in api.members if m['role'] != 'sector-leader']
    assert api.call('POST', '/submissions', body={'sector': 'TMT'}).status_code == 422
    assert api.call('GET', '/flags/mine').json()['submissions'][0]['status'] == 'draft'
    monkeypatch.setattr(store, 'now', lambda: datetime(2026, 9, 14, 8, tzinfo=timezone.utc))
    assert api.call('GET', '/flags/mine').json()['flags'] == []
    assert len(api.call('GET', '/flags/mine?week=2026-09-07').json()['flags']) == 1
    assert api.call('DELETE', '/flags/' + article['id']).status_code == 409


@pytest.mark.parametrize('url', ['javascript:alert(1)', 'data:text/html,hi', 'https://', '//example.com', 'https://user:pass@example.com', 'https://example.com/a b'])
def test_unsafe_links_rejected(api, url):
    assert api.call('POST', '/flags', body={'title': 'News', 'url': url, 'sector': 'TMT'}).status_code == 422


@pytest.mark.parametrize('body', [{'title': ' '}, {'title': 'x' * 501}, {'title': 'News', 'user_id': 'b'}, {'title': 'News', 'ticker': 'BAD TICKER'}])
def test_invalid_input_rejected(api, body):
    assert api.call('POST', '/flags', body=body).status_code == 422


def test_week_is_pacific_monday_with_dst():
    assert store.week_info(instant=datetime(2026, 9, 7, 6, 59, tzinfo=timezone.utc))['week'] == '2026-08-31'
    assert store.week_info(instant=datetime(2026, 9, 7, 7, tzinfo=timezone.utc))['week'] == '2026-09-07'
    assert store.week_info('2026-03-09')['dueAt'] == '2026-03-12T17:00:00-07:00'
    assert store.week_info('2026-11-02')['dueAt'] == '2026-11-05T17:00:00-08:00'
    with pytest.raises(ValueError):
        store.week_info('2026-09-08')


def test_parallel_submit_creates_one_digest_per_lead(api):
    flag(api)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: api.call('POST', '/submissions', body={'sector': 'TMT'}), range(2)))
    assert [r.status_code for r in results] == [200, 200]
    assert results[0].json()['id'] == results[1].json()['id']
    assert len(api.call('GET', '/inbox', 'lead').json()['messages']) == 1


def test_delivery_failure_rolls_back_submission_and_inbox_together(api, monkeypatch):
    flag(api)
    original = store.execute

    def fail(conn, sql, params=()):
        if 'INSERT INTO inbox_messages' in sql:
            raise RuntimeError('simulated write failure')
        return original(conn, sql, params)

    monkeypatch.setattr(store, 'execute', fail)
    with pytest.raises(RuntimeError, match='simulated write failure'):
        submit(api)
    conn = api.connect()
    assert conn.execute('SELECT status FROM submissions').fetchone()[0] == 'draft'
    assert conn.execute('SELECT COUNT(*) FROM submission_items').fetchone()[0] == 0
    assert conn.execute('SELECT COUNT(*) FROM inbox_messages').fetchone()[0] == 0
    conn.close()


def test_schema_idempotent_and_reseed_preserves_analyst_work(api):
    flag(api)
    submit(api)
    conn = api.connect()
    create_schema(conn)
    create_schema(conn)
    truncate_all(conn)
    assert conn.execute('SELECT COUNT(*) FROM news_flags').fetchone()[0] == 1
    assert conn.execute('SELECT COUNT(*) FROM inbox_messages').fetchone()[0] == 2
    conn.close()
