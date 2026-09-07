"""Seed only explicitly marked mock users; default is a read-only preview.

Run as python -m scripts.seed_workos_mock_users [--apply]. Uses existing WorkOS
config, stdlib HTTPS, and no invitation/email/password endpoints. Rerunnable:
finds users by exact mock email and refuses to adopt unmarked accounts.
"""
import argparse
import json
import re
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from src.auth import workos_client as wc

ROOT = Path(__file__).resolve().parents[1]
SEED = "uoig-coverage-mock-v1"
ANALYST_ROLE = "member"  # Verified UOIG role: display name Analyst, slug member.


def roster():
    people = {}
    raw = json.loads((ROOT / "data/mock_uoig_roster.json").read_text())
    for sector, assignments in raw.items():
        for name, ticker in assignments:
            people.setdefault(name, []).append({"sector": sector, "ticker": ticker})
    return people


def api(method, path, body=None):
    key = wc.api_key()
    if not key:
        raise RuntimeError("Missing configured WorkOS API key")
    request = Request("https://api.workos.com" + path,
                      data=None if body is None else json.dumps(body).encode(),
                      headers={"Authorization": "Bearer " + key,
                               "Content-Type": "application/json"}, method=method)
    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except HTTPError as exc:
        # Do not print headers, credentials, or raw provider response bodies.
        raise RuntimeError(f"WorkOS {method} {path.split('?')[0]} returned HTTP {exc.code}") from None
    except URLError:
        raise RuntimeError("Could not connect to WorkOS") from None


def listing(path, **params):
    rows = []
    params["limit"] = 100
    while True:
        page = api("GET", path + "?" + urlencode(params))
        rows.extend(page["data"])
        after = page.get("list_metadata", {}).get("after")
        if not after:
            return rows
        params["after"] = after


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    people = roster()
    org_id = wc.org_id()
    if not org_id:
        raise RuntimeError("Missing configured WorkOS organization")
    org = api("GET", "/organizations/" + org_id)
    if org["name"] != "UOIG":
        raise RuntimeError("Configured organization is not UOIG; no changes made")
    roles = api("GET", f"/authorization/organizations/{org_id}/roles")["data"]
    if not any(r["slug"] == ANALYST_ROLE and r["name"] == "Analyst" for r in roles):
        raise RuntimeError("UOIG has no analyst role; no users created")
    print(json.dumps({"organization": org["name"], "organization_id": org_id,
                      "users": len(people), "assignments": sum(map(len, people.values())),
                      "apply": args.apply}), flush=True)
    report = {"seed": SEED, "organization_id": org_id, "users": []}
    report_path = ROOT / ".tmp/workos-mock-users-result.json"
    if args.apply:
        report_path.parent.mkdir(exist_ok=True)
    for name, coverage in people.items():
        slug = re.sub(r"[^a-z0-9]+", ".", name.lower()).strip(".")
        email = f"mock.{slug}@uoig.example.invalid"
        metadata = {"mock": "true", "seed": SEED, "display_name": name,
                    "organization_id": org_id,
                    "coverage": json.dumps(coverage, separators=(",", ":"))}
        found = listing("/user_management/users", email=email)
        if len(found) > 1:
            raise RuntimeError("Multiple users match " + email)
        user = found[0] if found else None
        if user and (user.get("metadata", {}).get("seed") != SEED or
                     user.get("metadata", {}).get("organization_id") != org_id):
            raise RuntimeError("Refusing to modify an unmarked account: " + email)
        if not args.apply:
            print(json.dumps({"name": name, "email": email, "action": "reuse" if user else "create",
                              "coverage": coverage}), flush=True)
            continue
        action = "reused"
        if user is None:
            first, _, last = name.partition(" ")
            user = api("POST", "/user_management/users", {
                "email": email, "first_name": first,
                "last_name": (last + " (Mock)").strip(), "email_verified": False,
                "metadata": metadata})
            action = "created"
        if any(user.get("metadata", {}).get(k) != v for k, v in metadata.items()):
            raise RuntimeError("Existing mock data differs; inspect before updating: " + email)
        entry = {"name": name, "email": email, "user_id": user["id"],
                 "action": action, "coverage": coverage}
        report["users"].append(entry)
        report_path.write_text(json.dumps(report, indent=2) + "\n")
        memberships = listing("/user_management/organization_memberships",
                              organization_id=org_id, user_id=user["id"],
                              statuses="active,inactive,pending")
        if memberships:
            if len(memberships) != 1 or memberships[0]["status"] != "active" or memberships[0]["role"]["slug"] != ANALYST_ROLE:
                raise RuntimeError("Existing membership needs review: " + email)
            membership = memberships[0]
        else:
            membership = api("POST", "/user_management/organization_memberships", {
                "user_id": user["id"], "organization_id": org_id, "role_slug": ANALYST_ROLE})
        verified = api("GET", "/user_management/organization_memberships/" + membership["id"])
        if (verified["organization_id"] != org_id or verified["user_id"] != user["id"] or
                verified["status"] != "active" or verified["role"]["slug"] != ANALYST_ROLE):
            raise RuntimeError("Membership verification failed: " + email)
        entry.update(membership_id=membership["id"], status="verified", role=ANALYST_ROLE)
        report_path.write_text(json.dumps(report, indent=2) + "\n")
        print(f"Verified {name}: {action}, analyst, {len(coverage)} assignments", flush=True)
    if args.apply:
        print(f"Verified {len(report['users'])} mock members. Report: {report_path}")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        raise SystemExit(str(exc))
