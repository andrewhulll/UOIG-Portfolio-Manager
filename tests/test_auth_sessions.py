"""Regression tests for the WorkOS password account helpers."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from workos.user_management import PasswordPlaintext  # noqa: E402

from src.auth import sessions  # noqa: E402


class _FakeUserManagement:
    def __init__(self):
        self.create_kwargs = None

    def create_user(self, **kwargs):
        self.create_kwargs = kwargs
        return object()


class _FakeClient:
    def __init__(self):
        self.user_management = _FakeUserManagement()


def test_create_user_wraps_plaintext_password_for_workos_v10(monkeypatch):
    client = _FakeClient()
    monkeypatch.setattr(sessions.wc, "client", lambda: client)

    sessions.create_user_with_password(
        "invitee@example.com", "correct horse battery staple", "Test", "User"
    )

    sent = client.user_management.create_kwargs
    assert sent["email"] == "invitee@example.com"
    assert isinstance(sent["password"], PasswordPlaintext)
    assert sent["password"].password == "correct horse battery staple"
    assert sent["email_verified"] is True
    assert sent["first_name"] == "Test"
    assert sent["last_name"] == "User"

# --- is_member tests ---

def _res(org=None, email=None, user_is_dict=True):
    """A minimal stand-in for a WorkOS authenticate/session result."""
    if email is not None:
        if user_is_dict:
            user = {"email": email}
        else:
            user = SimpleNamespace(email=email)
    else:
        user = None
    return SimpleNamespace(organization_id=org, user=user)


def _fake_api_client(data=None, raises=False):
    """A stand-in for wc.client() whose user_management.list_users is stubbed."""
    def list_users(organization_id=None, email=None):
        if raises:
            raise RuntimeError("workos api down")
        return SimpleNamespace(data=list(data or []))
    return SimpleNamespace(user_management=SimpleNamespace(list_users=list_users))


def test_is_member_dev_bypass_wins(monkeypatch):
    monkeypatch.setattr(sessions.wc, "auth_disabled", lambda: True)
    monkeypatch.setattr(sessions.wc, "org_id", lambda: None)
    assert sessions.is_member(_res()) is True


def test_is_member_org_unset_fails_closed(monkeypatch):
    monkeypatch.setattr(sessions.wc, "auth_disabled", lambda: False)
    monkeypatch.setattr(sessions.wc, "org_id", lambda: None)
    assert sessions.is_member(_res(email="a@b.com")) is False


def test_is_member_matching_org_id_fast_path(monkeypatch):
    monkeypatch.setattr(sessions.wc, "auth_disabled", lambda: False)
    monkeypatch.setattr(sessions.wc, "org_id", lambda: "org_123")

    def _no_api_call():
        raise AssertionError("wc.client() should not be called on the fast path")

    monkeypatch.setattr(sessions.wc, "client", _no_api_call)
    assert sessions.is_member(_res(org="org_123")) is True


def test_is_member_mismatch_without_email_denied(monkeypatch):
    monkeypatch.setattr(sessions.wc, "auth_disabled", lambda: False)
    monkeypatch.setattr(sessions.wc, "org_id", lambda: "org_123")
    assert sessions.is_member(_res(org=None, email=None)) is False


def test_is_member_api_membership_found(monkeypatch):
    monkeypatch.setattr(sessions.wc, "auth_disabled", lambda: False)
    monkeypatch.setattr(sessions.wc, "org_id", lambda: "org_123")
    monkeypatch.setattr(sessions.wc, "client", lambda: _fake_api_client(data=[{"id": "u1"}]))
    assert sessions.is_member(_res(org=None, email="a@b.com")) is True


def test_is_member_api_membership_not_found(monkeypatch):
    monkeypatch.setattr(sessions.wc, "auth_disabled", lambda: False)
    monkeypatch.setattr(sessions.wc, "org_id", lambda: "org_123")
    monkeypatch.setattr(sessions.wc, "client", lambda: _fake_api_client(data=[]))
    assert sessions.is_member(_res(org=None, email="a@b.com")) is False


def test_is_member_api_error_fails_closed(monkeypatch):
    monkeypatch.setattr(sessions.wc, "auth_disabled", lambda: False)
    monkeypatch.setattr(sessions.wc, "org_id", lambda: "org_123")
    monkeypatch.setattr(sessions.wc, "client", lambda: _fake_api_client(raises=True))
    assert sessions.is_member(_res(org=None, email="a@b.com")) is False


def test_is_member_user_is_object_found(monkeypatch):
    monkeypatch.setattr(sessions.wc, "auth_disabled", lambda: False)
    monkeypatch.setattr(sessions.wc, "org_id", lambda: "org_123")
    monkeypatch.setattr(sessions.wc, "client", lambda: _fake_api_client(data=[{"id": "u1"}]))
    # tests the branch in _user_email where user is an object, not a dict
    assert sessions.is_member(_res(org=None, email="a@b.com", user_is_dict=False)) is True
