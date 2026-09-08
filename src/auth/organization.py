"""Small, allowlisted WorkOS adapter for the in-app UOIG member directory."""
from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from src.auth import workos_client as wc

ROLE_NAMES = {"admin": "Admin", "sector-leader": "Sector Leader", "member": "Analyst"}
SECTORS = ("TMT", "Consumer", "Financials", "Healthcare", "IME")


class OrganizationError(RuntimeError):
    pass


def _api(method: str, path: str, body: dict | None = None) -> dict:
    key = wc.api_key()
    if not key:
        raise OrganizationError("WorkOS is not configured")
    req = Request(
        "https://api.workos.com" + path,
        data=None if body is None else json.dumps(body).encode("utf-8"),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        method=method,
    )
    try:
        with urlopen(req, timeout=20) as response:
            return json.load(response)
    except HTTPError as exc:
        raise OrganizationError(f"WorkOS returned HTTP {exc.code}") from None
    except URLError:
        raise OrganizationError("Could not connect to WorkOS") from None


def _list(path: str, **params) -> list[dict]:
    rows: list[dict] = []
    params["limit"] = 100
    while True:
        page = _api("GET", path + "?" + urlencode(params))
        rows.extend(page.get("data") or [])
        after = (page.get("list_metadata") or {}).get("after")
        if not after:
            return rows
        params["after"] = after


def _coverage(metadata: dict) -> list[dict]:
    raw = metadata.get("coverage")
    if not raw:
        return []
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
        return [
            {"sector": str(row["sector"])[:40], "ticker": str(row["ticker"]).upper()[:12]}
            for row in value if isinstance(row, dict) and row.get("sector") and row.get("ticker")
        ]
    except (TypeError, ValueError):
        return []


def _lead_sectors(metadata: dict) -> list[str]:
    """Sectors this member leads for inbox routing — independent of both their
    base org role (an admin can also lead a sector) and their own ticker
    coverage (a leader doesn't need to personally cover a stock to lead)."""
    raw = metadata.get("lead_sectors")
    if not raw:
        return []
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
        return list(dict.fromkeys(
            str(sector)[:40] for sector in value if str(sector) in SECTORS
        ))
    except (TypeError, ValueError):
        return []


def list_members() -> dict:
    org_id = wc.org_id()
    if not org_id:
        raise OrganizationError("UOIG organization is not configured")
    org = _api("GET", "/organizations/" + org_id)
    memberships = _list(
        "/user_management/organization_memberships",
        organization_id=org_id,
        statuses="active",
    )
    # Membership payloads intentionally omit user metadata. Fetch the organization
    # users once and merge by ID so directory-only coverage metadata is available.
    users = {row.get("id"): row for row in _list(
        "/user_management/users", organization_id=org_id
    )}
    members = []
    for membership in memberships:
        embedded = membership.get("user") or {}
        user = users.get(membership.get("user_id") or embedded.get("id"), embedded)
        metadata = user.get("metadata") or {}
        role = (membership.get("role") or {}).get("slug") or "member"
        coverage = _coverage(metadata)
        members.append({
            "id": user.get("id") or membership.get("user_id"),
            "name": metadata.get("display_name") or user.get("name") or user.get("email") or "Member",
            "email": user.get("email") or "",
            "profilePictureUrl": user.get("profile_picture_url"),
            "role": role,
            "roleName": ROLE_NAMES.get(role, role.replace("-", " ").title()),
            "isMock": metadata.get("mock") in (True, "true", "1"),
            "coverage": coverage,
            "sectors": list(dict.fromkeys(row["sector"] for row in coverage)),
            "leadSectors": _lead_sectors(metadata),
        })
    members.sort(key=lambda row: (row["role"] != "admin", row["name"].lower()))
    return {"organization": {"id": org_id, "name": org.get("name") or "UOIG"}, "members": members}


def set_coverage(user_id: str, coverage: list[dict]) -> None:
    """Overwrite a member's company coverage. Merges into existing metadata
    (rather than replacing it outright) so mock-seed fields like `display_name`
    survive an admin editing a mock user's coverage."""
    user = _api("GET", "/user_management/users/" + user_id)
    metadata = dict(user.get("metadata") or {})
    metadata["coverage"] = json.dumps(coverage)
    _api("PUT", "/user_management/users/" + user_id, {"metadata": metadata})


def set_lead_sectors(user_id: str, sectors: list[str]) -> None:
    """Overwrite which sectors a member leads (receives weekly digests for).
    Independent of their org role and their own ticker coverage — an admin can
    lead a sector alongside a dedicated sector-leader, and a leader doesn't
    need a ticker assignment to be routed submissions."""
    user = _api("GET", "/user_management/users/" + user_id)
    metadata = dict(user.get("metadata") or {})
    metadata["lead_sectors"] = json.dumps(sectors)
    _api("PUT", "/user_management/users/" + user_id, {"metadata": metadata})


def set_role(user_id: str, role_slug: str) -> None:
    """Change a member's org role (admin / sector-leader / member)."""
    org_id = wc.org_id()
    if not org_id:
        raise OrganizationError("UOIG organization is not configured")
    memberships = _list(
        "/user_management/organization_memberships",
        organization_id=org_id, user_id=user_id, statuses="active",
    )
    if not memberships:
        raise OrganizationError("No active membership found for this user")
    _api("PUT", "/user_management/organization_memberships/" + memberships[0]["id"],
         {"role_slug": role_slug})


def update_user(user_id: str, first_name: str, last_name: str) -> dict:
    user = _api("PUT", "/user_management/users/" + user_id, {
        "first_name": first_name,
        "last_name": last_name,
    })
    return {
        "id": user.get("id"), "email": user.get("email"),
        "firstName": user.get("first_name"), "lastName": user.get("last_name"),
        "name": user.get("name") or " ".join(x for x in (first_name, last_name) if x),
        "profilePictureUrl": user.get("profile_picture_url"),
    }
