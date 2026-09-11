"""Standalone Capital IQ API smoke test; Python standard library only.

First obtain API credentials from your university's Capital IQ administrator
or support.api.mi@spglobal.com. Website/SSO access does not establish API access.

Run with --usage to test S&P's entitlement-neutral Usage Service.
Run with --dry-run to inspect the selected request without network calls.
Run without arguments to authenticate and request one annual revenue value.
No files are read/written, credentials are not saved, and requests are not retried.

Reference: S&P Capital IQ API Developer's Guide, May 7, 2026, sections 2 and 9.
https://www.support.marketplace.spglobal.com/content/dam/spglobal/mi/en/documents/marketplace/api/guides/spglobalapidevelopersguide.pdf
"""

import argparse
from decimal import Decimal, InvalidOperation
from getpass import getpass
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener


BASE = "https://api-ciq.marketintelligence.spglobal.com/gdsapi/rest/"
TOKEN_URL = BASE + "authenticate/api/v1/token"
DATA_URL = BASE + "v3/clientservice.json"
USAGE_URL = BASE + "v3/usageservice.json"
PAYLOAD = {"inputRequests": [{
    "function": "GDSP",
    "identifier": "IBM:NYSE",
    "mnemonic": "IQ_TOTAL_REV",
    "properties": {"PeriodType": "IQ_FY"},
}]}
USAGE_PAYLOAD = {"inputRequests": [{"mnemonic": "USAGE_METRICS"}]}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def post(url, body, content_type, token=None):
    headers = {"Accept": "application/json", "Content-Type": content_type}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = Request(url, data=body, headers=headers, method="POST")
    # HTTPS certificate verification remains enabled. Never forward credentials.
    with build_opener(NoRedirect()).open(request, timeout=30) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Show endpoints and sample request; do not connect.")
    parser.add_argument("--usage", action="store_true",
                        help="Test the Usage Service, available to all API users.")
    args = parser.parse_args()
    endpoint = USAGE_URL if args.usage else DATA_URL
    payload = USAGE_PAYLOAD if args.usage else PAYLOAD
    if args.dry_run:
        print("Token endpoint:", TOKEN_URL)
        print("Selected endpoint:", endpoint)
        print(json.dumps(payload, indent=2))
        print("Offline check only. API access has not been tested.")
        return 0

    print("Use your S&P API credentials, supplied for API access.")
    print("Credentials stay in memory. One login attempt; no automatic retries.")
    if not sys.stdin.isatty():
        print("Run this file in an interactive terminal to enter credentials privately.")
        return 1
    username = input("API username: ").strip()
    password = getpass("API password (hidden): ")
    if not username or not password:
        print("Both API username and password are required. No request sent.")
        return 1

    stage = "Authentication"
    try:
        auth = post(TOKEN_URL, urlencode({"username": username,
                    "password": password}).encode(),
                    "application/x-www-form-urlencoded")
        token = auth.get("access_token") if isinstance(auth, dict) else None
        if not isinstance(token, str) or not token.strip():
            print("Authentication did not return an access token. Raw response hidden.")
            return 1
        print("PASS: Authentication returned an access token (hidden).")
        stage = "Usage request" if args.usage else "Data request"
        result = post(endpoint, json.dumps(payload).encode(),
                      "application/json", token)
        entries = result.get("GDSSDKResponse") if isinstance(result, dict) else None
        if not isinstance(entries, list) or len(entries) != 1 or not isinstance(entries[0], dict):
            print("Data response format was unexpected; data access is unconfirmed.")
            return 1
        entry = entries[0]
        if entry.get("ErrMsg"):
            message = str(entry["ErrMsg"])
            for secret in (password, username, token):
                message = message.replace(secret, "[hidden]")
            print("Data request failed:", ascii(message[:500]))
            print("'Not Entitled' means the requested data needs additional permission.")
            return 1
        if args.usage:
            if entry.get("Mnemonic") != "USAGE_METRICS":
                print("Usage response format was unexpected; access is unconfirmed.")
                return 1
            print("PASS: Usage Service returned account metrics.")
            print("Rows:", entry.get("NumRows", 0))
            print("Hourly limit:", entry.get("HourlyLimit", "unreported"))
            print("Daily limit:", entry.get("DailyLimit", "unreported"))
            print("Monthly limit:", entry.get("MonthlyLimit", "unreported"))
            print("API authentication and entitlement-neutral service access work.")
            return 0
        rows = entry.get("Rows")
        values = [value for row in rows if isinstance(row, dict)
                  for value in (row.get("Row") or [])] if isinstance(rows, list) else []
        # HTTP 200 alone does not prove a usable financial value was returned.
        for value in values:
            try:
                number = Decimal(str(value))
            except InvalidOperation:
                continue
            if number.is_finite():
                print("PASS: IBM annual revenue returned a numeric value:", number)
                print("API authentication and this data entitlement both work.")
                print("This is a connectivity test; currency/scale were not validated.")
                return 0
        print("Authentication passed, but no numeric revenue was returned.")
        return 1
    except HTTPError as exc:
        hints = {
            401: "Credentials/token rejected. Confirm the API login with S&P.",
            403: "Access denied. Ask S&P to check account permissions or access restrictions.",
            423: "Account locked. Contact S&P API support; do not retry.",
            429: "Rate limit reached. Wait before trying again.",
        }
        print(f"{stage}: HTTP {exc.code}.", hints.get(exc.code,
              "Request failed. Share this status and the stage with S&P support."))
        return 1
    except (URLError, TimeoutError, OSError):
        print(f"{stage}: connection/TLS failure. Check internet, proxy, or firewall settings.")
        return 1
    except (ValueError, TypeError):
        print(f"{stage}: unexpected response. Raw response hidden to protect credentials.")
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        sys.exit(130)
