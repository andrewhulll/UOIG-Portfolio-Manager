"""WorkOS client singleton + secret/config loading.

Secrets follow the same convention as src/assistant.py: an environment variable
first, then a git-ignored text file at the repo root. The three real secrets are
WORKOS_API_KEY, WORKOS_CLIENT_ID and WORKOS_COOKIE_PASSWORD; org id, redirect URI
and the cookie-secure flag are plain config (env, with sane dev defaults).
"""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_ENVNAME = re.compile(r"^[A-Z][A-Z0-9_]*$")

# Session cookie (sealed WorkOS session) and the short-lived OAuth CSRF-state cookie.
COOKIE_NAME = "uoig_session"
STATE_COOKIE = "uoig_oauth_state"
# Carries an invitation token across the Google-OAuth round trip, so the callback
# can accept the invite when an invitee signs in with Google. Short-lived.
INVITE_COOKIE = "uoig_invite"
SESSION_MAX_AGE = 60 * 60 * 24 * 14  # 14 days


def _parse_file(text: str) -> str | None:
    """First meaningful line: bare value, or `NAME=value` (only split when the
    left side looks like an env-var name, so base64 cookie passwords survive)."""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            name, _, rest = line.partition("=")
            if _ENVNAME.match(name.strip()):
                line = rest.strip()
        return line.strip().strip('"').strip("'")
    return None


def _secret(env_name: str, filename: str) -> str | None:
    """`env_name` env var (verbatim), else repo-root `filename`, else None."""
    env = os.environ.get(env_name)
    if env and env.strip():
        return env.strip()
    try:
        return _parse_file((_ROOT / filename).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def api_key() -> str | None:
    return _secret("WORKOS_API_KEY", "workos.key.txt")


def client_id() -> str | None:
    return _secret("WORKOS_CLIENT_ID", "workos.client.txt")


def cookie_password() -> str | None:
    """The session-seal key. WorkOS's seal uses this directly as a Fernet key,
    which must be exactly 32 url-safe-base64 bytes (44 chars). To accept any
    secret the user sets (e.g. a 43-char token_urlsafe(32)), normalize it to a
    valid Fernet key deterministically — same input always yields the same key,
    so sealed sessions stay valid across restarts."""
    raw = _secret("WORKOS_COOKIE_PASSWORD", "workos.cookie.txt")
    if not raw:
        return None
    import base64
    import hashlib
    try:
        if len(base64.urlsafe_b64decode(raw)) == 32:
            return raw  # already a valid Fernet key
    except Exception:  # noqa: BLE001 — not valid base64 / wrong length
        pass
    return base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest()).decode()


def org_id() -> str | None:
    """The WorkOS organization whose membership gates access (invite-only)."""
    return _secret("WORKOS_ORG_ID", "workos.org.txt")


def redirect_uri() -> str:
    """OAuth callback URL registered in WorkOS. Defaults to the dev Vite origin
    (Vite proxies /api to the backend), so the whole flow stays on :5173 locally."""
    return os.environ.get("WORKOS_REDIRECT_URI") or "http://localhost:5173/api/auth/callback"


def cookie_samesite() -> str:
    """SameSite policy for the session cookie. Use 'none' for a cross-site split
    (Vercel frontend + separate backend host); 'lax' for same-origin (default)."""
    val = (os.environ.get("UOIG_COOKIE_SAMESITE") or "lax").strip().lower()
    return val if val in ("lax", "none", "strict") else "lax"


def is_secure() -> bool:
    """Secure cookies in production (HTTPS). Forced on when SameSite=None, which
    browsers require to be Secure. Set UOIG_COOKIE_SECURE=1 otherwise."""
    if cookie_samesite() == "none":
        return True
    return os.environ.get("UOIG_COOKIE_SECURE", "").lower() in ("1", "true", "yes")


def frontend_url() -> str:
    """Origin the backend redirects to after OAuth (the Vercel app in a split
    deploy). Empty = same-origin, so redirects stay relative ('/')."""
    return (os.environ.get("FRONTEND_URL") or "").rstrip("/")


def auth_disabled() -> bool:
    """Local-dev escape hatch — bypass the auth gate. NEVER set in production."""
    return os.environ.get("UOIG_AUTH_DISABLED", "").lower() in ("1", "true", "yes")


def admin_role() -> str:
    """The WorkOS role slug that may invite teammates (the Admin). Override per the
    dashboard's role slug via WORKOS_ADMIN_ROLE."""
    return (os.environ.get("WORKOS_ADMIN_ROLE") or "admin").strip()


def is_admin(role) -> bool:
    """True if `role` is the Admin role (case-insensitive)."""
    return bool(role) and str(role).strip().lower() == admin_role().lower()


def configured() -> bool:
    """True once the three secrets needed to run the sign-in flow are present."""
    return bool(api_key() and client_id() and cookie_password())


@lru_cache(maxsize=1)
def _build(key: str, cid: str):
    from workos import WorkOSClient  # lazy: app boots without the SDK/creds
    return WorkOSClient(api_key=key, client_id=cid)


def client():
    key, cid = api_key(), client_id()
    if not (key and cid):
        raise RuntimeError("workos_not_configured")
    return _build(key, cid)
