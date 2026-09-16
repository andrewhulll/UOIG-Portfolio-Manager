"""#133 regression: a sector leader cannot acknowledge their own submission."""
import copy
import sqlite3
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api import main
from api import submissions as routes
from src.model import submissions as store

MEMBERS = [
    {'id': 'a', 'name': 'Alex Analyst', 'role': 'member', 'sectors': ['TMT', 'Healthcare'],
     'coverage': [{'ticker': 'AAPL', 'sector': 'TMT'}, {'ticker': 'LLY', 'sector': 'Healthcare'}]},
    {'id': 'b', 'name': 'Blair Analyst', 'role': 'analyst', 'sectors': ['TMT'], 'coverage': []},
    {'id': 'lead', 'name': 'Taylor Lead', 'role': 'sector-leader', 'sectors': [], 'leadSectors': ['TMT']},
    {'id': 'colead', 'name': 'Casey Lead', 'role': 'sector-leader', 'sectors': [], 'leadSectors': ['TMT']},
    {'id': 'health', 'name': 'Harper Lead', 'role': 'sector-leader', 'sectors': [], 'leadSectors': ['Healthcare']},
    {'id': 'admin', 'name': 'Admin', 'role': 'admin', 'sectors': [], 'leadSectors': []},
]


@pytest.fixture
def api(monkeypatch, tmp_path):
    path = tmp_path / 'weekly.db'
    members = copy.deepcopy(MEMBERS)
    # Blair is both an analyst (can flag/submit in TMT) and a TMT sector lead.
    next(m for m in members if m['id'] == 'b')['leadSectors'] = ['TMT']

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
    client = TestClient(main.app)

    def call(method, url, user='a', body=None):
        return client.request(method, '/api' + url, headers={'x-test-user': user},
                              **({'json': body} if body is not None else {}))

    yield SimpleNamespace(call=call, connect=connect, members=members)
    client.close()


def test_sector_lead_cannot_ack_own_submission(api):
    # Blair (analyst + TMT sector lead) flags and submits her own TMT digest.
    flag = api.call('POST', '/flags', 'b', {'title': 'New product', 'ticker': 'AAPL',
                                            'sector': 'TMT', 'note': 'Watch margins.'})
    assert flag.status_code == 200, flag.text
    sent = api.call('POST', '/submissions', 'b', {'sector': 'TMT'})
    assert sent.status_code == 200, sent.text
    sub_id = sent.json()['id']
    assert sent.json()['status'] == 'submitted'

    # Self-ack is forbidden for leaders, even though Blair is a TMT lead.
    self_ack = api.call('POST', f'/submissions/{sub_id}/ack', 'b')
    assert self_ack.status_code == 403, self_ack.text
    assert api.call('GET', '/flags/mine', 'b').json()['submissions'][0]['status'] == 'submitted'

    # A different sector leader can still ack it.
    other = api.call('POST', f'/submissions/{sub_id}/ack', 'lead')
    assert other.status_code == 200, other.text
    assert other.json()['acked_by'] == 'lead'
    assert api.call('GET', '/flags/mine', 'b').json()['submissions'][0]['status'] == 'acked'
