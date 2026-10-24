#!/usr/bin/env python3
"""Read-only Binance Spot testnet authentication check for HMAC keys.

Only GET /api/v3/time and signed GET /api/v3/account are requested. Credentials
come from BINANCE_TESTNET_API_KEY and BINANCE_TESTNET_API_SECRET; an explicit
--env-file supplies values missing from the process environment. No orders run.

Official protocol references (checked 2026-10-24):
https://github.com/binance/binance-spot-api-docs/blob/master/testnet/general-info.md
https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md#timing-security
https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md#account-information-user_data
"""

import argparse
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import shlex
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener


BASE_URL = "https://testnet.binance.vision"
API_KEY_ENV = "BINANCE_TESTNET_API_KEY"
API_SECRET_ENV = "BINANCE_TESTNET_API_SECRET"
RECV_WINDOW_MS = 5000
MAX_RESPONSE_BYTES = 1024 * 1024


class CheckError(Exception):
    """An error safe to show without exposing request or response contents."""


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read_env_file(path):
    """Parse simple KEY=value lines; quoted values and # comments are supported.

    This does not execute shell syntax, expand variables, or support multiline
    values. Existing environment variables take precedence when used by main.
    """
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        raise CheckError("Cannot read the requested environment file.") from None
    values = {}
    for number, line in enumerate(lines, 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        name, separator, raw_value = line.partition("=")
        name = name.strip()
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise CheckError(f"Invalid environment assignment on line {number}.")
        try:
            parts = shlex.split(raw_value, comments=True, posix=True)
        except ValueError:
            raise CheckError(f"Invalid environment value on line {number}.") from None
        if len(parts) > 1:
            raise CheckError(f"Quote environment values with spaces on line {number}.")
        values[name] = parts[0] if parts else ""
    return values


def signed_query(secret, timestamp_ms):
    """Return the exact encoded parameters followed by their HMAC signature."""
    payload = urlencode({"timestamp": timestamp_ms, "recvWindow": RECV_WINDOW_MS})
    signature = hmac.new(
        secret.encode("utf-8"), payload.encode("ascii"), hashlib.sha256
    ).hexdigest()
    return f"{payload}&signature={signature}"


def request_json(path, *, query="", api_key=None, timeout=10.0):
    """GET one of the two fixed testnet paths, refusing all redirects."""
    if path not in ("/api/v3/time", "/api/v3/account"):
        raise CheckError("Unsupported testnet endpoint.")
    url = BASE_URL + path + ("?" + query if query else "")
    headers = {"Accept": "application/json"}
    if api_key is not None:
        headers["X-MBX-APIKEY"] = api_key
    try:
        request = Request(url, headers=headers, method="GET")
        with build_opener(NoRedirects()).open(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as error:
        # HTTPError text includes the signed URL; never display it or its body.
        raise CheckError(f"Testnet HTTP request failed (status {error.code}).") from None
    except (URLError, OSError, ValueError):
        raise CheckError("Testnet request failed; check connectivity and configuration.") from None
    if len(raw) > MAX_RESPONSE_BYTES:
        raise CheckError("Testnet response exceeded the size limit.")
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeError):
        raise CheckError("Testnet returned invalid JSON.") from None
    if not isinstance(result, dict):
        raise CheckError("Testnet returned an unexpected response.")
    if type(result.get("code")) is int and result["code"] < 0:
        raise CheckError(f"Testnet API rejected the request (code {result['code']}).")
    return result


def check_account(api_key, api_secret, *, timeout=10.0):
    """Check authentication and return only non-sensitive account metadata."""
    if not api_key or not api_secret:
        raise CheckError(f"Set {API_KEY_ENV} and {API_SECRET_ENV} for an HMAC key.")
    if not api_key.isascii() or any(character.isspace() for character in api_key):
        raise CheckError("Invalid API key format.")
    if "-----BEGIN" in api_secret:
        raise CheckError("This checker supports HMAC secrets; RSA/Ed25519 keys are unsupported.")
    if not math.isfinite(timeout) or timeout <= 0:
        raise CheckError("Timeout must be a positive finite number.")

    started_ms = int(time.time() * 1000)
    server = request_json("/api/v3/time", timeout=timeout)
    finished_ms = int(time.time() * 1000)
    server_ms = server.get("serverTime")
    if type(server_ms) is not int or server_ms <= 0:
        raise CheckError("Testnet response is missing a valid server time.")
    offset_ms = server_ms - (started_ms + finished_ms) // 2
    timestamp_ms = int(time.time() * 1000) + offset_ms
    account = request_json(
        "/api/v3/account", query=signed_query(api_secret, timestamp_ms),
        api_key=api_key, timeout=timeout,
    )
    flags = ("canTrade", "canWithdraw", "canDeposit")
    if (account.get("accountType") != "SPOT"
            or any(type(account.get(flag)) is not bool for flag in flags)
            or not isinstance(account.get("balances"), list)):
        raise CheckError("Testnet returned an unexpected account response.")
    # Do not print identifiers, permissions, asset names, or balances.
    return {
        "authenticated": True,
        "testnet": True,
        "accountType": "SPOT",
        **{flag: account[flag] for flag in flags},
        "balance_asset_count": len(account["balances"]),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--env-file", metavar="PATH", help="Explicit environment file path.")
    parser.add_argument("--timeout", type=float, default=10.0, help="Request timeout in seconds (default: 10).")
    args = parser.parse_args(argv)
    try:
        file_values = read_env_file(args.env_file) if args.env_file else {}
        key = os.environ.get(API_KEY_ENV, file_values.get(API_KEY_ENV, ""))
        secret = os.environ.get(API_SECRET_ENV, file_values.get(API_SECRET_ENV, ""))
        summary = check_account(key, secret, timeout=args.timeout)
    except CheckError as error:
        print(f"Check failed: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Check interrupted.", file=sys.stderr)
        return 130
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
