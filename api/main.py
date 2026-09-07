"""FastAPI backend for the UOIG Investment Terminal

Serves the React frontend's data from the existing analytics layer. Run:
    python -m uvicorn api.main:app --reload --port 8000
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
import uuid
import warnings
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

log = logging.getLogger("uoig.auth")

# pandas warns when read_sql gets a raw psycopg connection (vs SQLAlchemy); the
# queries work fine on both backends, so quiet the cosmetic noise.
warnings.filterwarnings("ignore", message="pandas only supports SQLAlchemy")

import secrets as _secrets  # noqa: E402

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse, RedirectResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from api.build import FUND_META, build_terminal_data  # noqa: E402
from src.auth import sessions as auth_sessions  # noqa: E402
from src.auth import invitations as auth_invites  # noqa: E402
from src.auth import workos_client as wc  # noqa: E402
from src.auth import organization as auth_organization  # noqa: E402
from workos._errors import (AuthenticationError, BadRequestError, ConflictError,  # noqa: E402
                            EmailPasswordAuthDisabledError,
                            EmailVerificationRequiredError,
                            UnprocessableEntityError, WorkOSError)
from src.analytics.pnl import load_positions  # noqa: E402
from src.ingest.research import stock_research  # noqa: E402
from src.ingest.lookup import (search_symbols, quote_overview,  # noqa: E402
                               live_series, institutional_holders)
from src.ingest.predictions import stock_predictions  # noqa: E402
from src.ingest.thesis import stock_thesis  # noqa: E402
from src.assistant import answer as llm_answer, api_key as llm_key  # noqa: E402
from src.analytics.risk import daily_returns_matrix  # noqa: E402
from src.analytics.optimize import (fund_diagnostics, solve_optimizer,  # noqa: E402
                                    whatif_payload)
from src.analytics.series import (price_frame, period_return, synthetic_index,  # noqa: E402
                                  ticker_series, trailing_return)
from src.config import db_path, load_config  # noqa: E402
from src.model.schema import get_connection  # noqa: E402

CFG = load_config()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Refresh held-ticker quotes on a background thread (market hours only), so
    /api/data serves live spot prices while everything else stays nightly."""
    from src.ingest.live_prices import start as _start_poller

    def _get_held_tickers() -> list[str]:
        """Current non-cash holdings — the universe the live-price poller refreshes."""
        conn = _conn()
        try:
            return [r[0] for r in conn.execute(
                "SELECT ticker FROM securities WHERE sec_type != 'cash'")]
        finally:
            conn.close()

    interval = float((CFG.get("market_data") or {}).get("live_interval_seconds", 45))
    try:
        _start_poller(_get_held_tickers, interval=interval)
        log.info("live-price poller started (interval=%ss)", interval)
    except Exception:  # noqa: BLE001 — never block startup on the poller
        log.exception("live-price poller failed to start")
    yield

app = FastAPI(title="UOIG Investment Terminal API", lifespan=lifespan)
# Same-origin dev: wildcard CORS, no credentials. Split deploy (Vercel frontend +
# separate backend): set CORS_ORIGINS to the exact frontend origin(s) so cookies
# can ride cross-site (credentials require a non-wildcard origin). The middleware
# itself is added at the bottom of this module so it ends up OUTERMOST — that way
# CORS headers are attached to every response, including the auth gate's 401s and
# any error, and OPTIONS preflights are answered before the gate runs.
_CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]


# ---------------------------------------------------------------------------
# Authentication (WorkOS, invite-only Google OAuth). The whole app is gated:
# every /api/* route except health and /api/auth/* requires a valid session.
# The SPA (static mount at /) stays public; the client redirects to sign-in.
# ---------------------------------------------------------------------------
_AUTH_PUBLIC = ("/api/health", "/api/auth/")

# Surface a closed invite gate at boot: with WorkOS configured but no org id,
# is_member() fails closed and denies every sign-in. Warn so operators notice
# before users hit a wall of "not invited".
if wc.configured() and not wc.org_id() and not wc.auth_disabled():
    log.warning("WorkOS is configured but WORKOS_ORG_ID is unset — the invite "
                "gate is closed and all sign-ins will be denied until it is set.")


def _set_session_cookie(resp, sealed: str) -> None:
    resp.set_cookie(wc.COOKIE_NAME, sealed, max_age=wc.SESSION_MAX_AGE,
                    httponly=True, samesite=wc.cookie_samesite(), secure=wc.is_secure(), path="/")


def _app_redirect(path: str = "/"):
    """Redirect to the frontend origin (Vercel in a split deploy; same-origin otherwise)."""
    return RedirectResponse(wc.frontend_url() + path, status_code=302)


def _current(request: Request):
    """(session_result, new_sealed) for the request's cookie, or (None, None)."""
    sealed = request.cookies.get(wc.COOKIE_NAME)
    if not sealed or not wc.configured():
        return None, None
    return auth_sessions.authenticate(sealed)


@app.middleware("http")
async def auth_gate(request: Request, call_next):
    path = request.url.path
    gated = path.startswith("/api/") and not path.startswith(_AUTH_PUBLIC)
    if gated and not wc.auth_disabled():
        res, new_sealed = _current(request)
        if res is None:
            return JSONResponse({"detail": "authentication required"}, status_code=401)
        request.state.user = res
        response = await call_next(request)
        if new_sealed:
            _set_session_cookie(response, new_sealed)
        return response
    return await call_next(request)


@app.get("/api/auth/login")
def auth_login(invitation_token: str = ""):
    """Begin Google OAuth: stash a CSRF state cookie, 302 to WorkOS. When an
    invitee starts from the accept page, `invitation_token` is stashed in a
    short-lived cookie so the callback can accept the invite after Google."""
    if not wc.configured():
        raise HTTPException(503, "WorkOS is not configured on the server")
    state = _secrets.token_urlsafe(24)
    resp = RedirectResponse(auth_sessions.authorization_url(state), status_code=302)
    resp.set_cookie(wc.STATE_COOKIE, state, max_age=600, httponly=True,
                    samesite=wc.cookie_samesite(), secure=wc.is_secure(), path="/")
    if invitation_token:
        resp.set_cookie(wc.INVITE_COOKIE, invitation_token, max_age=600, httponly=True,
                        samesite=wc.cookie_samesite(), secure=wc.is_secure(), path="/")
    return resp


@app.get("/api/auth/callback")
def auth_callback(request: Request, code: str = "", state: str = ""):
    """OAuth return: verify state, exchange code, enforce invite-only, set cookie.
    If an invite token rode along (invitee signing in with Google), pass it to the
    exchange so WorkOS accepts the invitation and joins them to the org."""
    if not code or not state or state != request.cookies.get(wc.STATE_COOKIE):
        return _app_redirect("/?auth_error=bad_state")
    invite = request.cookies.get(wc.INVITE_COOKIE) or None
    try:
        auth = auth_sessions.complete_login(code, invitation_token=invite)
    except Exception:  # noqa: BLE001
        return _app_redirect("/?auth_error=auth_failed")
    if not auth_sessions.is_member(auth):
        return _app_redirect("/?auth_error=not_invited")
    resp = _app_redirect("/")
    resp.delete_cookie(wc.STATE_COOKIE, path="/")
    resp.delete_cookie(wc.INVITE_COOKIE, path="/")
    _set_session_cookie(resp, auth_sessions.seal(auth))
    return resp


def _finish_auth(auth):
    """Shared finalize for the JSON auth routes: enforce invite-only, then set the
    sealed session cookie. Mirrors the Google callback's member check + seal."""
    if not auth_sessions.is_member(auth):
        raise HTTPException(403, "not_invited")
    resp = JSONResponse({"ok": True})
    _set_session_cookie(resp, auth_sessions.seal(auth))
    return resp


@app.post("/api/auth/password-login")
def auth_password_login(payload: dict):
    """Email + password sign-in. Invite-only gate still applies."""
    if not wc.configured():
        raise HTTPException(503, "WorkOS is not configured on the server")
    email = (payload.get("email") or "").strip()
    password = payload.get("password") or ""
    invite = (payload.get("invitationToken") or "").strip() or None
    if not email or not password:
        raise HTTPException(400, "email and password are required")
    try:
        auth = auth_sessions.password_login(email, password, invitation_token=invite)
    except EmailVerificationRequiredError as exc:
        return JSONResponse({"needsVerification": True,
                             "pendingToken": getattr(exc, "pending_authentication_token", None)})
    except EmailPasswordAuthDisabledError:
        raise HTTPException(503, "email/password sign-in isn't enabled")
    except (AuthenticationError, BadRequestError, UnprocessableEntityError):
        raise HTTPException(401, "invalid email or password")
    except WorkOSError:
        raise HTTPException(401, "invalid email or password")
    return _finish_auth(auth)


@app.post("/api/auth/verify-email")
def auth_verify_email(payload: dict):
    """Complete an email-verification challenge raised during password sign-in."""
    code = (payload.get("code") or "").strip()
    token = payload.get("pendingToken") or ""
    if not code or not token:
        raise HTTPException(400, "code and pendingToken are required")
    try:
        auth = auth_sessions.verify_email(code, token)
    except WorkOSError:
        raise HTTPException(401, "invalid or expired code")
    return _finish_auth(auth)


@app.post("/api/auth/password-reset")
def auth_password_reset(payload: dict):
    """Request a password-reset email (also how invited users set a first password).
    Always returns ok so we don't reveal whether an address has an account."""
    if not wc.configured():
        raise HTTPException(503, "WorkOS is not configured on the server")
    email = (payload.get("email") or "").strip()
    if not email:
        raise HTTPException(400, "email is required")
    try:
        auth_sessions.request_password_reset(email)
    except WorkOSError:
        pass
    return {"ok": True}


@app.post("/api/auth/password-reset/confirm")
def auth_password_reset_confirm(payload: dict):
    """Set a new password from a reset token emailed by WorkOS."""
    if not wc.configured():
        raise HTTPException(503, "WorkOS is not configured on the server")
    token = (payload.get("token") or "").strip()
    password = payload.get("password") or ""
    if not token or not password:
        raise HTTPException(400, "token and password are required")
    try:
        auth_sessions.confirm_reset(token, password)
    except (BadRequestError, UnprocessableEntityError) as exc:
        # WorkOS rejected the *password* against the org policy (too short, low
        # complexity, or found in a breach) — surface that so the user can fix it,
        # rather than blaming the (valid) reset link.
        msg = str(getattr(exc, "message", "") or exc)
        emsg = msg.lower()
        if any(k in emsg for k in ("token", "expired", "invalid")) and "password" not in emsg:
            raise HTTPException(400, "invalid or expired reset link")
        raise HTTPException(422, msg or "password does not meet the requirements")
    except WorkOSError:
        raise HTTPException(400, "invalid or expired reset link")
    return {"ok": True}


@app.get("/api/auth/invitation")
def auth_invitation(token: str = ""):
    """Public lookup for the branded accept page: resolve an invitation token to
    the invitee's email + state so the page can greet them and validate the link.
    Never echoes the token back."""
    if not wc.configured():
        raise HTTPException(503, "WorkOS is not configured on the server")
    if not token:
        raise HTTPException(400, "token is required")
    try:
        inv = auth_invites.find_by_token(token)
    except Exception:  # noqa: BLE001 — unknown/expired token, or any WorkOS error
        raise HTTPException(404, "invitation not found")
    state = getattr(inv.state, "value", inv.state)
    return {
        "email": inv.email,
        "state": state,
        "pending": state == "pending",
        "organizationId": inv.organization_id,
        "roleSlug": inv.role_slug,
    }


def _workos_error_signals(exc) -> tuple[set[str], str]:
    """Collect the machine-readable codes and a lowercased text blob from a WorkOS
    APIError. create_user reports a *generic* top-level message ('Could not create
    user.') and puts the real reason in `code` plus the `errors` list — so to tell
    'email already taken' (code email_not_available) from 'weak password' (code
    password_strength_error) we must inspect those, not just the message text."""
    codes: set[str] = set()
    parts: list[str] = []
    code = getattr(exc, "code", None)
    if code:
        codes.add(str(code))
    msg = getattr(exc, "message", None)
    if msg:
        parts.append(str(msg))
    errors = getattr(exc, "errors", None) or []
    if isinstance(errors, (list, tuple)):
        for item in errors:
            if isinstance(item, dict):
                if item.get("code"):
                    codes.add(str(item["code"]))
                if item.get("message"):
                    parts.append(str(item["message"]))
    return codes, " ".join(parts).lower()


def _password_policy_message(exc) -> str:
    """A human-readable reason (or reasons) a password was rejected, drawn from
    exc.errors — e.g. the specific 'found N times in data breaches' text — falling
    back to the top-level message."""
    reasons = [str(item["message"]) for item in (getattr(exc, "errors", None) or [])
               if isinstance(item, dict) and item.get("message")]
    if reasons:
        return " ".join(reasons)
    return str(getattr(exc, "message", "") or "That password doesn't meet the requirements.")


@app.post("/api/auth/accept-password")
def auth_accept_password(payload: dict):
    """Invitee 'set a password' path: validate the invite token, create the user
    with the chosen password, then authenticate WITH the token so WorkOS accepts
    the invitation (joins the org) and we set the session cookie."""
    if not wc.configured():
        raise HTTPException(503, "WorkOS is not configured on the server")
    token = (payload.get("invitationToken") or "").strip()
    password = payload.get("password") or ""
    if not token or not password:
        raise HTTPException(400, "invitation token and password are required")
    try:
        inv = auth_invites.find_by_token(token)
    except Exception:  # noqa: BLE001 — unknown/expired token, or any WorkOS error
        raise HTTPException(404, "invitation not found")
    if getattr(inv.state, "value", inv.state) != "pending":
        raise HTTPException(409, "this invitation is no longer valid")
    user_existed = False
    try:
        auth_sessions.create_user_with_password(
            inv.email, password,
            (payload.get("firstName") or "").strip(),
            (payload.get("lastName") or "").strip(),
        )
    except (BadRequestError, ConflictError, UnprocessableEntityError) as exc:
        codes, detail = _workos_error_signals(exc)
        if "email_not_available" in codes or any(
            k in detail for k in ("already", "taken", "exists", "in use", "not available")
        ):
            # Expected: the invitee already exists. WorkOS provisions a *passwordless*
            # user the moment an invitation is sent, so create_user always fails here
            # with a generic "Could not create user." (code email_not_available) — we
            # match the code, not just the message. A never-signed-in invitee has no
            # password yet, so set the one they just chose on that existing user;
            # otherwise the password sign-in below can't succeed. Don't touch the
            # password of someone who has signed in before (a returning user).
            user_existed = True
            existing = auth_sessions.find_user_by_email(inv.email)
            if existing is not None and getattr(existing, "last_sign_in_at", None) is None:
                try:
                    auth_sessions.set_user_password(
                        existing.id, password,
                        (payload.get("firstName") or "").strip(),
                        (payload.get("lastName") or "").strip(),
                    )
                except (BadRequestError, UnprocessableEntityError) as pexc:
                    pcodes, _ = _workos_error_signals(pexc)
                    if "password_strength_error" in pcodes or any(
                        c.startswith("password_") for c in pcodes
                    ):
                        raise HTTPException(422, _password_policy_message(pexc))
                    log.exception("accept-password: set_user_password failed for %s", inv.email)
                    raise HTTPException(400, f"could not create the account: {getattr(pexc, 'message', pexc)}")
            log.info("accept-password: %s already provisioned; authenticating", inv.email)
        elif "password_strength_error" in codes or any(c.startswith("password_") for c in codes):
            # The chosen password failed the org policy (too short, too common, or
            # found in a breach — the last of which the page can't check client-side).
            # Surface the specific reason(s) as a 422 so the page shows them.
            log.info("accept-password: weak password for %s: %s", inv.email, sorted(codes))
            raise HTTPException(422, _password_policy_message(exc))
        else:
            log.exception("accept-password: create_user failed for %s", inv.email)
            raise HTTPException(400, f"could not create the account: {getattr(exc, 'message', exc)}")
    try:
        auth = auth_sessions.password_login(inv.email, password, invitation_token=token)
    except EmailVerificationRequiredError as exc:
        # Safety net: if WorkOS still requires a one-time code (e.g. a pre-existing
        # unverified account), hand the pending token to the frontend so the
        # verify-email step finishes auth AND accepts the invitation.
        return JSONResponse({"needsVerification": True,
                             "pendingToken": getattr(exc, "pending_authentication_token", None)})
    except EmailPasswordAuthDisabledError:
        raise HTTPException(503, "email/password sign-in isn't enabled")
    except AuthenticationError as exc:
        # Bad credentials. If the account already existed, the most likely cause is
        # a different password from a prior attempt — tell the user plainly so they
        # sign in (or use Google) rather than seeing a generic failure.
        log.warning("accept-password: auth failed for %s (existed=%s): %s",
                    inv.email, user_existed, getattr(exc, "message", exc))
        if user_existed:
            raise HTTPException(
                409,
                "An account already exists for this email. If an earlier invite attempt "
                "created it without a password, use Forgot / set password, then reopen "
                "this invitation and enter that password.",
            )
        raise HTTPException(401, "could not complete sign-in")
    except WorkOSError as exc:
        log.exception("accept-password: unexpected WorkOS error for %s", inv.email)
        raise HTTPException(401, f"could not complete sign-in: {getattr(exc, 'message', exc)}")
    return _finish_auth(auth)


@app.get("/api/auth/me")
def auth_me(request: Request):
    """Current user + role (+ canInvite), or 401. The frontend gate calls this on load."""
    if wc.auth_disabled():
        return {"user": {"id": "dev", "email": "dev@local", "name": "Dev User",
                         "firstName": "Dev", "lastName": "User", "profilePictureUrl": None},
                "role": wc.admin_role(), "canInvite": True}
    res, new_sealed = _current(request)
    if res is None:
        raise HTTPException(401, "not authenticated")
    payload, role = auth_sessions.user_payload(res)
    resp = JSONResponse({"user": payload, "role": role, "canInvite": wc.is_admin(role)})
    if new_sealed:
        _set_session_cookie(resp, new_sealed)
    return resp


@app.post("/api/auth/logout")
def auth_logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(wc.COOKIE_NAME, path="/")
    return resp


@app.post("/api/auth/invite")
def auth_invite(request: Request, payload: dict):
    """Invite a teammate by email. Admin-only (the first role-gated action); enforced
    server-side as well as hidden in the UI. Invites can also be sent from the dashboard."""
    if not wc.auth_disabled():
        res, _ = _current(request)
        if res is None:
            raise HTTPException(401, "not authenticated")
        if not wc.is_admin(getattr(res, "role", None)):
            raise HTTPException(403, "only an admin can invite teammates")
    if not wc.configured():
        raise HTTPException(503, "WorkOS is not configured on the server")
    email = (payload.get("email") or "").strip()
    if not email:
        raise HTTPException(400, "email is required")
    inv = auth_invites.send_invite(email, payload.get("role_slug"))
    return {"ok": True, "id": getattr(inv, "id", None), "email": email}


def _dev_directory():
    """Build the same allowlisted directory shape without WorkOS for local UI work."""
    roster_path = Path(__file__).resolve().parents[1] / "data" / "mock_uoig_roster.json"
    raw = json.loads(roster_path.read_text(encoding="utf-8"))
    people = {}
    for sector, assignments in raw.items():
        for name, ticker in assignments:
            people.setdefault(name, []).append({"sector": sector, "ticker": ticker})
    members = [{
        "id": "mock-" + name.lower().replace(" ", "-"), "name": name,
        "email": "mock." + name.lower().replace(" ", ".") + "@uoig.example.invalid",
        "profilePictureUrl": None, "role": "member", "roleName": "Analyst", "isMock": True,
        "coverage": coverage,
        "sectors": list(dict.fromkeys(row["sector"] for row in coverage)),
    } for name, coverage in people.items()]
    members.insert(0, {"id": "dev", "name": "Dev User", "email": "dev@local",
                       "profilePictureUrl": None, "role": "admin", "roleName": "Admin",
                       "isMock": False, "coverage": [], "sectors": []})
    return {"organization": {"id": "dev-uoig", "name": "UOIG"}, "members": members}


@app.get("/api/organization/members")
def organization_members():
    try:
        return _dev_directory() if wc.auth_disabled() else auth_organization.list_members()
    except auth_organization.OrganizationError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.patch("/api/profile")
def update_profile(request: Request, payload: dict):
    first = str(payload.get("firstName") or "").strip()
    last = str(payload.get("lastName") or "").strip()
    if not first or len(first) > 60 or len(last) > 60:
        raise HTTPException(400, "Enter a first name and keep each name under 60 characters")
    if wc.auth_disabled():
        return {"user": {"id": "dev", "email": "dev@local", "firstName": first,
                         "lastName": last, "name": (first + " " + last).strip(),
                         "profilePictureUrl": None}}
    res = getattr(request.state, "user", None)
    user, _ = auth_sessions.user_payload(res)
    if not user.get("id"):
        raise HTTPException(401, "not authenticated")
    try:
        return {"user": auth_organization.update_user(user["id"], first, last)}
    except auth_organization.OrganizationError as exc:
        raise HTTPException(502, str(exc)) from exc


def _conn():
    return get_connection(db_path(CFG))




def _fund_name(key: str):
    for f in CFG["funds"]:
        if FUND_META.get(f["name"], {}).get("key") == key or f["name"] == key:
            return f["name"], f["benchmark"]
    return None, None


@app.get("/api/health")
def health():
    """Liveness + a no-secrets config diagnostic (handy for verifying a deploy).
    Reports only booleans + non-secret config — never the secret values."""
    from src.model import db as _dbmod
    return {
        "ok": True,
        "db": "postgres" if _dbmod.use_postgres() else "sqlite",
        "workos": {
            "configured": wc.configured(),
            "apiKey": bool(wc.api_key()),
            "clientId": bool(wc.client_id()),
            "cookiePassword": bool(wc.cookie_password()),
            "orgId": bool(wc.org_id()),
            "redirectUri": wc.redirect_uri(),
        },
        "cors": _CORS_ORIGINS or "*",
        "frontendUrl": wc.frontend_url() or None,
        "cookieSameSite": wc.cookie_samesite(),
    }


@app.get("/api/data")
def data():
    conn = _conn()
    try:
        return build_terminal_data(CFG, conn)
    finally:
        conn.close()


@app.get("/api/series/{ticker}")
def series(ticker: str, period: str = "YTD"):
    conn = _conn()
    try:
        pf = price_frame(conn)
        s = ticker_series(pf, ticker, period)
        if s["close"]:
            return {"ticker": ticker, "period": period,
                    "ret": period_return(pf, ticker, period), **s}
    finally:
        conn.close()
    # Not a portfolio holding — pull a live series straight from yfinance.
    try:
        live = live_series(ticker, period)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"series fetch failed: {exc}")
    if not live["close"]:
        raise HTTPException(404, f"no series for {ticker}")
    return JSONResponse({"ticker": ticker.upper(), "period": period, **live}, headers={
        "Cache-Control": "public, max-age=300, s-maxage=300",
    })


@app.get("/api/search")
def search(q: str = "", limit: int = 8):
    """Yahoo Finance symbol search (equities only) for the global search box."""
    try:
        results = search_symbols(q, limit)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"search failed: {exc}")
    return JSONResponse({"results": results}, headers={
        "Cache-Control": "public, max-age=300, s-maxage=300",
    })


@app.get("/api/quote/{ticker}")
def quote(ticker: str):
    """Live overview for any equity, so off-portfolio tickers can open a stock
    page. Returns 404 for non-equities / unknown symbols."""
    try:
        ov = quote_overview(ticker)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"quote fetch failed: {exc}")
    if ov is None:
        raise HTTPException(404, f"no equity quote for {ticker}")
    return JSONResponse(ov, headers={
        "Cache-Control": "public, max-age=300, s-maxage=300",
    })


@app.get("/api/holders/{ticker}")
def holders(ticker: str):
    """Top institutional shareholders (13F) for any equity, for the stock page
    overview. Returns an empty list when Yahoo has no holder data."""
    try:
        return {"ticker": ticker.upper(), "holders": institutional_holders(ticker)}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"holders fetch failed: {exc}")


@app.get("/api/optimize/diagnostics/{fund}")
def optimize_diagnostics(fund: str):
    """Per-fund optimization diagnostics (active risk vs the benchmark): tracking
    error, active share, beta, active risk contribution, sector tilts, concentration."""
    name, _ = _fund_name(fund)
    if not name:
        raise HTTPException(404, f"unknown fund {fund}")
    conn = _conn()
    try:
        return fund_diagnostics(CFG, conn, name)
    finally:
        conn.close()


@app.get("/api/optimize/whatif/{fund}")
def optimize_whatif(fund: str):
    """What-if sandbox inputs: current book split (stocks/overlay), benchmark
    weights, and the annualized covariance so the client can recompute tracking
    error / active share / beta / vol live as sliders move."""
    name, _ = _fund_name(fund)
    if not name:
        raise HTTPException(404, f"unknown fund {fund}")
    conn = _conn()
    try:
        return whatif_payload(CFG, conn, name)
    finally:
        conn.close()


@app.post("/api/optimize/solve/{fund}")
def optimize_solve(fund: str, payload: dict | None = None):
    """Black-Litterman constrained mean-variance solve. Body: {views:
    [{t, q(%), conf}], max_pos(%), erp(%)}. Returns proposed weights, trades,
    before/after stats and the constrained efficient frontier."""
    name, _ = _fund_name(fund)
    if not name:
        raise HTTPException(404, f"unknown fund {fund}")
    p = payload or {}
    views = [{"t": str(v.get("t", "")).upper(), "q": float(v.get("q", 0)) / 100,
              "conf": v.get("conf", "med")}
             for v in (p.get("views") or []) if v.get("t")]
    max_pos = min(max(float(p.get("max_pos", 10)) / 100, 0.02), 0.5)
    erp = min(max(float(p.get("erp", 5)) / 100, 0.005), 0.15)
    conn = _conn()
    try:
        return solve_optimizer(CFG, conn, name, views=views, max_pos=max_pos, erp=erp)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    finally:
        conn.close()


@app.get("/api/fund-series/{fund}")
def fund_series(fund: str, period: str = "YTD"):
    conn = _conn()
    try:
        name, bench = _fund_name(fund)
        if not name:
            raise HTTPException(404, f"unknown fund {fund}")
        pos = load_positions(CFG, conn)
        rets = daily_returns_matrix(conn, (CFG.get("risk") or {}).get("beta_window_years", 3))
        weights = {r.ticker: r.port_w for r in
                   pos[(pos.fund == name) & (pos.sec_type != "cash")].itertuples()
                   if r.port_w == r.port_w}
        syn = synthetic_index(rets, weights, period)
        bs = ticker_series(pf := price_frame(conn), bench, period)
        bvals = [round(v / bs["close"][0] * 100, 3) for v in bs["close"]] if bs["close"] else []
        return {"fund": syn, "bench": {"dates": bs["dates"], "values": bvals, "ticker": bench}}
    finally:
        conn.close()


def _sector_cfg(group: str):
    for s in (CFG.get("sectors") or []):
        if str(s.get("name", "")).lower() == group.lower():
            return s
    return None


@app.get("/api/sector-series/{group}")
def sector_series(group: str, period: str = "1M"):
    """Sector detail chart + weekly movers. Returns the value-weighted sector
    index (rebased), each mapped iShares benchmark ETF (rebased), and the top/
    bottom 3 holdings by trailing one-week return. All read from the price store."""
    sc = _sector_cfg(group)
    if not sc:
        raise HTTPException(404, f"unknown sector {group}")
    conn = _conn()
    try:
        pf = price_frame(conn)
        rets = daily_returns_matrix(conn, (CFG.get("risk") or {}).get("beta_window_years", 3))
        pos = load_positions(CFG, conn)
        gics = set(sc.get("gics") or [])
        funda = {r[0]: r[1] for r in conn.execute(
            "SELECT ticker, gics_sector FROM fundamentals").fetchall()}

        # value-weighted sector index across BOTH funds (aggregate by ticker)
        weights, names = {}, {}
        for r in pos[pos.sec_type != "cash"].itertuples():
            sec = funda.get(r.ticker) or r.sector
            if sec in gics:
                weights[r.ticker] = weights.get(r.ticker, 0.0) + float(r.market_value or 0)
                names[r.ticker] = r.name
        syn = synthetic_index(rets, weights, period)

        names_map = CFG.get("benchmark_names") or {}
        benchmarks = []
        for etf in (sc.get("benchmarks") or []):
            bs = ticker_series(pf, etf, period)
            if not bs["close"]:
                continue
            base = bs["close"][0]
            benchmarks.append({
                "ticker": etf, "name": names_map.get(etf, etf),
                "dates": bs["dates"],
                "values": [round(v / base * 100, 3) for v in bs["close"]],
                "ret": period_return(pf, etf, period),
            })

        movers = [{"t": t, "n": names.get(t, t), "ret": trailing_return(pf, t, 7)}
                  for t in weights]
        movers = [m for m in movers if m["ret"] is not None]
        movers.sort(key=lambda m: m["ret"], reverse=True)
        top = movers[:3]
        top_set = {m["t"] for m in top}
        bottom = [m for m in reversed(movers) if m["t"] not in top_set][:3]
        return {
            "group": sc["name"], "period": period,
            "sector": syn, "benchmarks": benchmarks,
            "movers": {"top": top, "bottom": bottom},
        }
    finally:
        conn.close()


@app.get("/api/stock/{ticker}")
def stock_detail(ticker: str):
    """Live yfinance research for the stock-detail tabs (financials, earnings,
    news, analysts). Cached in-process; see src/ingest/research.py."""
    try:
        return stock_research(ticker.upper())
    except Exception as exc:  # noqa: BLE001 — surface upstream failure as 502
        raise HTTPException(502, f"research fetch failed: {exc}")


@app.get("/api/predictions/{ticker}")
def predictions(ticker: str):
    """Kalshi prediction-market cards for the stock-detail Predictions tab,
    from the curated PREDICTION_MARKETS.md map. See src/ingest/predictions.py."""
    try:
        return stock_predictions(ticker.upper())
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"prediction fetch failed: {exc}")


@app.get("/api/thesis/{ticker}")
def thesis(ticker: str):
    """Most recent investment thesis (three points) from THESIS.md."""
    return stock_thesis(ticker.upper())


_RATE_LIMITS: Dict[str, Dict[str, List[float]]] = {}
_RATE_LIMIT_LOCK = threading.Lock()

def _enforce_rate_limit(request: Request, kind: str, limit: int, window: int = 3600):
    user_id = "anonymous"
    res = getattr(request.state, "user", None)
    if res:
        try:
            from src.auth import sessions as auth_sessions
            user, _ = auth_sessions.user_payload(res)
            user_id = user.get("id") or getattr(request.client, "host", "anonymous")
        except Exception:
            user_id = getattr(request.client, "host", "anonymous")
    else:
        user_id = getattr(request.client, "host", "anonymous")

    now = time.time()
    with _RATE_LIMIT_LOCK:
        user_limits = _RATE_LIMITS.setdefault(user_id, {})
        history = user_limits.setdefault(kind, [])
        history = [ts for ts in history if now - ts < window]
        if len(history) >= limit:
            user_limits[kind] = history
            raise HTTPException(429, "Rate limit exceeded")
        history.append(now)
        user_limits[kind] = history


def _chat_system(conn, context: str) -> str:
    """System prompt that grounds the co-pilot in the live portfolio."""
    data = build_terminal_data(CFG, conn)
    lines = [
        "You are the research co-pilot embedded in the University of Oregon Investment "
        "Group (UOIG) investment terminal. You help the portfolio manager reason about the "
        "Tall Firs and Alumni Fund portfolios.",
        "Be concise and specific; ground every claim in the data below. Use plain text "
        "with **bold** for key figures. If something isn't in the data, say so rather than "
        "guessing. This is for an internal student investment club — not personalized "
        "financial advice.",
        "You can read this project's source repository with the list_files, read_file, and "
        "search_repo tools — use them for how the terminal works, how a number is computed, or "
        "the analytics/data pipeline. Secrets, the database, and ignored files are not "
        "accessible; don't claim otherwise.",
        "For deeper per-holding analysis you have: get_stock_fundamentals (live yfinance "
        "financials, earnings, news, analyst research), get_predictions (Kalshi market-implied "
        "odds), and get_thesis (the team's written pitch). Pull these on demand for a ticker; "
        "read only what the question needs.",
        "You can also search the web (web_search) for current information the portfolio data "
        "doesn't cover — recent news, macro events, analyst commentary, or anything time-sensitive. "
        "Use it when a question needs up-to-date external context, and cite the sources you used.",
        "",
        f"PORTFOLIO SNAPSHOT (as of {data.get('asOf')}):",
    ]
    for f in data["funds"].values():
        ret = (f.get("ret") or {})
        ytd = ret.get("YTD")
        lines.append(
            f"- {f['name']}: AUM ${f.get('aum')}M · YTD {round(ytd * 100, 1) if ytd is not None else '—'}% "
            f"· beta {f.get('beta')} vs {f.get('benchShort')} · α {f.get('alpha')}%"
        )
    lines.append("")
    lines.append("HOLDINGS (ticker · sector · fund · weight% · MTD%):")
    for h in sorted(data["holdings"], key=lambda x: -(x.get("w") or 0)):
        lines.append(f"- {h['t']} · {h.get('s')} · {h['fund']} · {h.get('w')}% · {h.get('mtd')}%")
    if context:
        lines += ["", f"The user is currently viewing: {context}. "
                      "Resolve 'this'/'it'/'here' to that context when ambiguous."]
    return "\n".join(lines)



_USER_CHAT_RUNS: dict[str, list[float]] = {}
_USER_AGENT_RUNS: dict[str, list[float]] = {}
_CHAT_LOCK = threading.Lock()
_ACTIVE_CHATS = 0
_AGENT_LOCK = threading.Lock()

def _enforce_rate_limit(user_id: str, history: dict[str, list[float]], lock: threading.Lock, limit: int, window: float) -> bool:
    with lock:
        now = time.time()
        user_history = history.get(user_id, [])
        user_history = [t for t in user_history if now - t < window]
        history[user_id] = user_history
        if len(user_history) >= limit:
            return False
        user_history.append(now)
        return True

def _get_user_id(request: Request) -> str:
    if wc.auth_disabled():
        return "dev"
    res = getattr(request.state, "user", None)
    if res:
        u = getattr(res, "user", None) or {}
        if not isinstance(u, dict):
            u = u.to_dict()
        return u.get("id") or "dev"
    return "dev"

@app.post("/api/chat")
def chat(request: Request, payload: dict):
    _enforce_rate_limit(request, "chat", limit=50, window=3600)
    """Live Ask-Claude turn via the Anthropic API (claude-haiku-4-5)."""
    user_id = _get_user_id(request)
    if not _enforce_rate_limit(user_id, _USER_CHAT_RUNS, lock=_CHAT_LOCK, limit=15, window=60):
        raise HTTPException(429, "Too many chat requests. Please wait a minute.")

    global _ACTIVE_CHATS
    with _CHAT_LOCK:
        if _ACTIVE_CHATS >= 5:
            raise HTTPException(503, "Chat service is busy. Please try again in a moment.")
        _ACTIVE_CHATS += 1

    try:
        messages = payload.get("messages") or []
        context = str(payload.get("context") or "")
        if not llm_key():
            return {"reply": "⚠ Ask Claude isn't configured yet. Set the **ANTHROPIC_API_KEY** "
                             "environment variable (or drop the key in `anthropic.key.txt` at the "
                             "repo root) and restart the backend."}
        conn = _conn()
        try:
            system = _chat_system(conn, context)
        finally:
            conn.close()
        try:
            return {"reply": llm_answer(messages, system)}
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"chat failed: {exc}")
    finally:
        with _CHAT_LOCK:
            _ACTIVE_CHATS -= 1


def _agent_context(data: dict) -> str:
    """Concise live-portfolio snapshot handed to the market-analysis agent. The
    full holdings ride along as a mounted file (see _agent_portfolio_json)."""
    lines = [f"UOIG endowment snapshot (as of {data.get('asOf')}):"]
    for f in data["funds"].values():
        ret = (f.get("ret") or {})
        ytd = ret.get("YTD")
        lines.append(f"- {f['name']}: ${f.get('aum')}M AUM, YTD "
                     f"{round(ytd * 100, 1) if ytd is not None else '—'}%, "
                     f"beta {f.get('beta')} vs {f.get('benchShort')}")
    top = sorted(data["holdings"], key=lambda h: -(h.get("w") or 0))[:12]
    lines.append("Top holdings (ticker · weight% · sector · MTD%):")
    for h in top:
        lines.append(f"- {h['t']} · {round(h.get('w') or 0, 1)}% · {h.get('s')} "
                     f"· {round(h.get('mtd') or 0, 1)}%")
    lines.append("")
    lines.append("Our full live holdings (every position, weights, and per-name returns) are "
                 "attached to this session as the file portfolio.json — read it for exact positions.")
    return "\n".join(lines)


def _agent_portfolio_json(data: dict) -> str:
    """Full live portfolio as JSON, mounted at /workspace/portfolio.json so the
    agent can analyze the actual Tall Firs / Alumni positions."""
    payload = {
        "as_of": data.get("asOf"),
        "funds": [{"name": f["name"], "aum_musd": f.get("aum"), "benchmark": f.get("benchShort"),
                   "returns": f.get("ret"), "beta": f.get("beta"), "alpha_pct": f.get("alpha"),
                   "sharpe": f.get("sharpe"), "ann_vol_pct": f.get("vol")}
                  for f in data["funds"].values()],
        "holdings": [{"ticker": h["t"], "name": h.get("n"), "sector": h.get("s"), "fund": h.get("fund"),
                      "weight_pct": h.get("w"), "price": h.get("px"), "mtd_pct": h.get("mtd"),
                      "day_pct": h.get("chg"), "market_value_usd": h.get("mv"), "beta": h.get("beta"),
                      "pe": h.get("pe"), "div_yield_pct": h.get("dy")}
                     for h in sorted(data["holdings"], key=lambda x: -(x.get("w") or 0))],
    }
    return json.dumps(payload, indent=2)


# In-process store for async agent runs. A run takes ~30s, which is too long for
# one blocking HTTP request (proxies/gateways cut it off), so the button kicks off
# a background thread and the frontend polls the status endpoint below.
_AGENT_JOBS: dict[str, dict] = {}


def _run_agent_task(job_id: str, aid: str, task: str, context: str, attachments: list, agent):
    try:
        reply = agent.run_agent(aid, task, context, attachments=attachments)
        _AGENT_JOBS[job_id] = {"status": "done", "reply": reply, "error": None}
    except Exception as exc:  # noqa: BLE001
        log.exception("agent run failed")
        _AGENT_JOBS[job_id] = {"status": "error", "reply": None, "error": str(exc)}


@app.post("/api/agent/run")
def agent_run(request: Request, payload: dict, background_tasks: BackgroundTasks):
    _enforce_rate_limit(request, "agent", limit=5, window=3600)
    """Start a Managed Agent (market analysis) run in the background and return a
    job id immediately. Poll GET /api/agent/run/{job_id} for the result. Agent id is
    `agent_id` in config.yaml (an ANTHROPIC_AGENT_ID env var overrides it)."""
    user_id = _get_user_id(request)
    if not _enforce_rate_limit(user_id, _USER_AGENT_RUNS, lock=_AGENT_LOCK, limit=5, window=600):
        raise HTTPException(429, "Too many agent runs. Please try again later.")

    now = time.time()
    job_id = uuid.uuid4().hex

    with _AGENT_LOCK:
        # evict stale
        stale_keys = []
        for k, v in _AGENT_JOBS.items():
            age = now - v.get("started_at", now)
            if v["status"] in ("done", "error") and age > 300:
                stale_keys.append(k)
            elif v["status"] == "running" and age > 1800:
                stale_keys.append(k)
        for k in stale_keys:
            _AGENT_JOBS.pop(k, None)

        active_jobs = sum(1 for v in _AGENT_JOBS.values() if v["status"] == "running")
        if active_jobs >= 3:
            raise HTTPException(503, "Agent service is busy. Please wait a moment.")

        _AGENT_JOBS[job_id] = {"status": "running", "reply": None, "error": None, "started_at": now}

    from src import agent_run as agent
    aid = (os.environ.get("ANTHROPIC_AGENT_ID") or CFG.get("agent_id") or "").strip()
    if not aid:
        _AGENT_JOBS.pop(job_id, None)
        raise HTTPException(503, "agent_not_configured")
    conn = _conn()
    try:
        data = build_terminal_data(CFG, conn)
    finally:
        conn.close()
    context = _agent_context(data)
    attachments = [{"filename": "portfolio.json", "mount_path": "/workspace/portfolio.json",
                    "content": _agent_portfolio_json(data)}]
    task = (payload.get("task") or "").strip() or (
        "Read the attached portfolio.json file for our holdings, then give today's "
        "market analysis for our portfolio: the key macro and sector drivers, notable "
        "moves in our holdings, and any risks or names to watch. Be concise and "
        "specific; cite sources where you used them.")


    MAX_CONCURRENT_RUNS = 2
    JOB_TTL = 3600

    # TTL cleanup
    now = time.time()
    for jid, job in list(_AGENT_JOBS.items()):
        if now - job.get("created_at", now) > JOB_TTL:
            _AGENT_JOBS.pop(jid, None)

    # Max concurrent check
    running_jobs = sum(1 for job in _AGENT_JOBS.values() if job["status"] == "running")
    if running_jobs >= MAX_CONCURRENT_RUNS:
        raise HTTPException(429, "Too many concurrent agent runs across the system")

    job_id = uuid.uuid4().hex
    _AGENT_JOBS[job_id] = {"status": "running", "reply": None, "error": None, "created_at": time.time()}

    def _worker():
        try:
            reply = agent.run_agent(aid, task, context, attachments=attachments)
            with _AGENT_LOCK:
                if job_id in _AGENT_JOBS:
                    _AGENT_JOBS[job_id].update({"status": "done", "reply": reply, "error": None})
        except Exception as exc:  # noqa: BLE001
            log.exception("agent run failed")
            with _AGENT_LOCK:
                if job_id in _AGENT_JOBS:
                    _AGENT_JOBS[job_id].update({"status": "error", "reply": None, "error": str(exc)})

    threading.Thread(target=_worker, daemon=True).start()
    return {"job_id": job_id, "status": "running"}


@app.get("/api/agent/run/{job_id}")
def agent_run_status(job_id: str):
    """Poll an agent run. While running, returns {status: 'running'}; on completion
    returns {status: 'done', reply} or {status: 'error', error} and drops the job."""
    with _AGENT_LOCK:
        job = _AGENT_JOBS.get(job_id)
        if job is None:
            raise HTTPException(404, "unknown or expired job")
        if job["status"] != "running":
            _AGENT_JOBS.pop(job_id, None)  # one-shot: free the slot once delivered
        return dict(job)


# CORS is added LAST so it's the outermost middleware: it answers OPTIONS
# preflights before the auth gate and attaches CORS headers to every response
# (including the gate's 401s and any error), so cross-origin failures surface as
# real statuses instead of opaque "no Access-Control-Allow-Origin" errors.
if _CORS_ORIGINS:
    app.add_middleware(CORSMiddleware, allow_origins=_CORS_ORIGINS, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])
else:
    app.add_middleware(CORSMiddleware, allow_origins=[], allow_methods=["*"], allow_headers=["*"])

# Serve the built React terminal (single-container deploy). The /api routes above
# are matched first; this catch-all mount serves the SPA for everything else.
_DIST = Path(__file__).resolve().parents[1] / "web" / "dist"
if _DIST.exists():
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="web")
