"""The welcome tour opens once per new user, and never for people who already had accounts."""
from tests.test_submissions import api  # noqa: F401  (fixture)


def start(api, user):  # noqa: F811
    response = api.call('POST', '/onboarding/start', user=user)
    assert response.status_code == 200, response.text
    return response.json()['show']


def test_existing_members_never_see_it(api):  # noqa: F811
    assert start(api, 'a') is False
    assert start(api, 'admin') is False


def test_new_member_sees_it_exactly_once(api):  # noqa: F811
    assert start(api, 'a') is False  # first use backfills everyone who is already a member
    api.members.append({'id': 'new', 'name': 'New Analyst', 'role': 'member', 'sectors': ['TMT'], 'coverage': []})
    assert start(api, 'new') is True
    assert start(api, 'new') is False
    assert start(api, 'new') is False


def test_requires_sign_in(api):  # noqa: F811
    assert api.call('POST', '/onboarding/start', user='nobody').status_code == 401


def test_directory_outage_never_opens_it(api, monkeypatch):  # noqa: F811
    from fastapi import HTTPException
    from api import submissions as subs

    def down():
        raise HTTPException(502, 'directory unavailable')
    monkeypatch.setattr(subs, 'directory', down)
    assert start(api, 'a') is False
    monkeypatch.setattr(subs, 'directory', lambda: api.members)
    api.members.append({'id': 'late', 'name': 'Late', 'role': 'member', 'sectors': [], 'coverage': []})
    assert start(api, 'late') is False   # backfill hadn't run, so this run backfills them as existing
