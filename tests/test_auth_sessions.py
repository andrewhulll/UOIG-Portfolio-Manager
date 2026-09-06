"""Regression tests for the WorkOS password account helpers."""
from __future__ import annotations

import sys
from pathlib import Path

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
