"""Invite-only gate (is_member): fail-closed behavior — hermetic (no network).

Guards the security-critical property that the app denies access when it has no
organization to check membership against, while preserving the local-dev bypass.
Monkeypatches the workos_client accessors so nothing hits the WorkOS API.
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.auth import sessions  # noqa: E402
from src.auth import workos_client as wc  # noqa: E402


@contextmanager
def _patch(**attrs):
    """Temporarily replace attributes on the workos_client module."""
    saved = {k: getattr(wc, k) for k in attrs}
    for k, v in attrs.items():
        setattr(wc, k, v)
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(wc, k, v)


def _res(org=None, email=None):
    """A minimal stand-in for a WorkOS authenticate/session result."""
    user = {"email": email} if email is not None else None
    return SimpleNamespace(organization_id=org, user=user)


def _fake_client(data=None, raises=False):
    """A stand-in for wc.client() whose user_management.list_users is stubbed."""
    def list_users(organization_id=None, email=None):
        if raises:
            raise RuntimeError("workos api down")
        return SimpleNamespace(data=list(data or []))
    return SimpleNamespace(user_management=SimpleNamespace(list_users=list_users))


def _no_api_call():
    raise AssertionError("wc.client() should not be called on the fast path")


def test_dev_bypass_wins():
    # UOIG_AUTH_DISABLED short-circuits even when no org is configured.
    with _patch(auth_disabled=lambda: True, org_id=lambda: None):
        assert sessions.is_member(_res()) is True


def test_org_unset_fails_closed():
    # No org id + not bypassed -> deny everyone (fail closed).
    with _patch(auth_disabled=lambda: False, org_id=lambda: None):
        assert sessions.is_member(_res(email="a@b.com")) is False


def test_matching_org_id_fast_path():
    # organization_id on the result matches the gate -> allowed, no API call.
    with _patch(auth_disabled=lambda: False, org_id=lambda: "org_123",
                client=_no_api_call):
        assert sessions.is_member(_res(org="org_123")) is True


def test_mismatch_without_email_denied():
    # No matching org and no email to verify membership with -> denied.
    with _patch(auth_disabled=lambda: False, org_id=lambda: "org_123"):
        assert sessions.is_member(_res(org=None, email=None)) is False


def test_api_membership_found():
    # Falls back to list_users(org, email); a non-empty page means member.
    with _patch(auth_disabled=lambda: False, org_id=lambda: "org_123",
                client=lambda: _fake_client(data=[{"id": "u1"}])):
        assert sessions.is_member(_res(org=None, email="a@b.com")) is True


def test_api_membership_not_found():
    with _patch(auth_disabled=lambda: False, org_id=lambda: "org_123",
                client=lambda: _fake_client(data=[])):
        assert sessions.is_member(_res(org=None, email="a@b.com")) is False


def test_api_error_fails_closed():
    # An API exception must deny, never admit.
    with _patch(auth_disabled=lambda: False, org_id=lambda: "org_123",
                client=lambda: _fake_client(raises=True)):
        assert sessions.is_member(_res(org=None, email="a@b.com")) is False


if __name__ == "__main__":
    test_dev_bypass_wins()
    test_org_unset_fails_closed()
    test_matching_org_id_fast_path()
    test_mismatch_without_email_denied()
    test_api_membership_found()
    test_api_membership_not_found()
    test_api_error_fails_closed()
    print("OK")
