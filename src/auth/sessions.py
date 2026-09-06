"""Sign-in flow helpers over the WorkOS User Management SDK.

The OAuth handshake: authorization_url() -> WorkOS/Google -> complete_login(code).
Sessions are *sealed* (encrypted with the cookie password) before being stored in
an http-only cookie; authenticate() verifies/refreshes a sealed cookie on each
request. Role comes back from the session authentication, not the code exchange.
"""
from __future__ import annotations

from typing import Optional, Tuple

from workos.user_management import PasswordPlaintext

from src.auth import workos_client as wc


def authorization_url(state: str) -> str:
    """WorkOS authorization URL for Google OAuth, with a CSRF `state`."""
    return wc.client().user_management.get_authorization_url(
        provider="GoogleOAuth", redirect_uri=wc.redirect_uri(), state=state,
    )


def complete_login(code: str, invitation_token: Optional[str] = None):
    """Exchange the OAuth `code` for an AuthenticateResponse (user + tokens).

    When `invitation_token` is set (the invitee arrived via an invitation email
    and signed in with Google), WorkOS accepts the invitation as part of the
    exchange — adding the user to the org so the invite-only gate passes."""
    return wc.client().user_management.authenticate_with_code(
        code=code, invitation_token=invitation_token or None,
    )


def create_user_with_password(email: str, password: str,
                              first_name: Optional[str] = None,
                              last_name: Optional[str] = None,
                              email_verified: bool = True):
    """Create a WorkOS user with an initial password (invitee 'set a password'
    path). Raises if a user with that email already exists.

    `email_verified` defaults to True: this account is only reachable via an
    invitation link emailed to `email`, so receiving it already proves control
    of the inbox. Marking the email verified up front skips the one-time-code
    challenge WorkOS would otherwise require on the first password sign-in."""
    return wc.client().user_management.create_user(
        email=email, password=PasswordPlaintext(password=password),
        email_verified=email_verified,
        first_name=first_name or None, last_name=last_name or None,
    )


# ---- email + password (and the reset / verification flows) ----
def password_login(email: str, password: str, invitation_token: Optional[str] = None):
    """Authenticate with email + password -> AuthenticateResponse. Pass
    `invitation_token` to also accept a pending invitation (join the org) on the
    invitee's first password sign-in.
    Raises workos._errors types (AuthenticationError, EmailVerificationRequiredError, …)."""
    return wc.client().user_management.authenticate_with_password(
        email=email, password=password, invitation_token=invitation_token or None,
    )


def request_password_reset(email: str):
    """Create a password-reset token; WorkOS emails the reset link to the user."""
    return wc.client().user_management.reset_password(email=email)


def confirm_reset(token: str, new_password: str):
    """Complete a reset (also how invited users set their first password)."""
    return wc.client().user_management.confirm_password_reset(token=token, new_password=new_password)


def verify_email(code: str, pending_token: str):
    """Finish an email-verification challenge -> AuthenticateResponse."""
    return wc.client().user_management.authenticate_with_email_verification(
        code=code, pending_authentication_token=pending_token,
    )


def seal(auth) -> str:
    """Encode an AuthenticateResponse into a sealed session string for the cookie."""
    from workos.session import seal_session_from_auth_response
    return seal_session_from_auth_response(
        access_token=auth.access_token,
        refresh_token=auth.refresh_token,
        user=auth.user.to_dict(),
        impersonator=auth.impersonator.to_dict() if auth.impersonator else None,
        cookie_password=wc.cookie_password(),
    )


def authenticate(sealed: str) -> Tuple[Optional[object], Optional[str]]:
    """Validate a sealed cookie. Returns (session_result, new_sealed).

    `new_sealed` is non-None only when the access token was expired and a refresh
    minted a fresh sealed session that the caller should re-set on the cookie.
    Returns (None, None) when the cookie is invalid / cannot be refreshed.
    """
    try:
        session = wc.client().user_management.load_sealed_session(
            session_data=sealed, cookie_password=wc.cookie_password(),
        )
    except Exception:  # noqa: BLE001 — malformed/forged cookie
        return None, None

    try:
        res = session.authenticate()
    except Exception:  # noqa: BLE001
        res = None
    if res is not None and getattr(res, "authenticated", False):
        return res, None

    # Access token expired — try a refresh (also rotates the sealed session).
    try:
        refreshed = session.refresh(cookie_password=wc.cookie_password())
    except Exception:  # noqa: BLE001
        return None, None
    if getattr(refreshed, "authenticated", False):
        return refreshed, getattr(refreshed, "sealed_session", None)
    return None, None


def _user_email(res) -> Optional[str]:
    u = getattr(res, "user", None)
    if isinstance(u, dict):
        return u.get("email")
    return getattr(u, "email", None)


def is_member(res) -> bool:
    """Invite-only gate: the user must belong to the configured WorkOS org.

    A plain Google/password sign-in often returns no `organization_id` even for a
    real member (WorkOS only includes it for org-scoped sign-ins), so we can't
    rely on that field alone. Fast-path on it when present, otherwise verify the
    user's actual membership via the API (list_users filtered by org + email).
    When WORKOS_ORG_ID is unset we accept any authenticated user (not advised).
    """
    want = wc.org_id()
    if not want:
        return True
    org = getattr(res, "organization_id", None)
    if org and org == want:
        return True
    email = _user_email(res)
    if not email:
        return False
    try:
        page = wc.client().user_management.list_users(organization_id=want, email=email)
        return bool(getattr(page, "data", None))
    except Exception:  # noqa: BLE001 — fail closed on API error
        return False


def user_payload(res) -> Tuple[dict, Optional[str]]:
    """Frontend-facing {user, role} from a session/auth result."""
    u = getattr(res, "user", None) or {}
    if not isinstance(u, dict):
        u = u.to_dict()
    first, last = u.get("first_name"), u.get("last_name")
    name = u.get("name") or " ".join(p for p in (first, last) if p) or u.get("email")
    payload = {
        "id": u.get("id"),
        "email": u.get("email"),
        "firstName": first,
        "lastName": last,
        "name": name,
        "profilePictureUrl": u.get("profile_picture_url"),
    }
    return payload, getattr(res, "role", None)
