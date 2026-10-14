"""Checks for play_api.py and play_console.py that need no Google account."""

import base64
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(os.path.dirname(HERE), "tools")
sys.path.insert(0, TOOLS)
import play_api
import play_console


def decode(part):
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))


def verifies(message, signature, public_key):
    """True when openssl accepts the RS256 signature over the message."""
    with tempfile.NamedTemporaryFile("wb", delete=False) as sig:
        sig.write(base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4)))
    try:
        result = subprocess.run(
            ["openssl", "dgst", "-sha256", "-verify", public_key, "-signature", sig.name],
            input=message.encode(),
            capture_output=True,
            check=False,
        )
    finally:
        os.unlink(sig.name)
    return result.returncode == 0


def run_checks(check, scratch):
    fails = 0
    header, claims = (decode(part) for part in play_api.unsigned_assertion("svc@example.iam", 1000).split("."))
    fails += check(
        "play_api: the token request names the account, scope and audience for an hour",
        header == {"alg": "RS256", "typ": "JWT"}
        and claims == {"iss": "svc@example.iam", "scope": play_api.SCOPE, "aud": play_api.TOKEN_URL, "iat": 1000, "exp": 4600},
        json.dumps(claims),
    )

    with tempfile.TemporaryDirectory(dir=scratch) as d:
        private = os.path.join(d, "key.pem")
        public = os.path.join(d, "pub.pem")
        subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-out", private], check=True, capture_output=True)
        subprocess.run(["openssl", "pkey", "-in", private, "-pubout", "-out", public], check=True, capture_output=True)
        with open(private, encoding="ascii") as f:
            key = f.read()
        signature = play_api.sign("header.claims", key)
        fails += check("play_api: its signature verifies with the account's public key", verifies("header.claims", signature, public))
        fails += check("play_api: and fails over any other message", not verifies("header.claimz", signature, public))

        env = dict(os.environ, PLAY_SERVICE_ACCOUNT=os.path.join(d, "missing.json"))
        result = subprocess.run([sys.executable, os.path.join(TOOLS, "play_api.py"), "tracks", "com.example"], env=env, capture_output=True, text=True, check=False)
        fails += check("play_api: refuses without a key, naming where it looked", result.returncode == 2 and "missing.json" in result.stderr, result.stderr)

    body = play_api.release_body("internal", 12, "Fixes.", "completed", "12 (1.2.0)")
    fails += check(
        "play_api: a release holds one version code with its notes",
        body == {"track": "internal", "releases": [{"versionCodes": ["12"], "status": "completed", "name": "12 (1.2.0)", "releaseNotes": [{"language": "en-US", "text": "Fixes."}]}]},
        json.dumps(body),
    )

    fails += check("play_api: a price splits into whole units and nanos", play_api.money("2.49") == {"currencyCode": "USD", "units": "2", "nanos": 490000000}, json.dumps(play_api.money("2.49")))
    converted = {
        "convertedRegionPrices": {"TR": {"regionCode": "TR", "price": {"currencyCode": "TRY", "units": "149", "nanos": 990000000}}, "DE": {"regionCode": "DE", "price": {"currencyCode": "EUR", "units": "2", "nanos": 690000000}}},
        "convertedOtherRegionsPrice": {"usdPrice": {"currencyCode": "USD", "units": "2"}, "eurPrice": {"currencyCode": "EUR", "units": "2"}},
    }
    option = play_api.product_body("com.example", "remove_ads", "Remove ads", "No ads.", converted)["purchaseOptions"][0]
    fails += check(
        "play_api: a product is one single-quantity buy option, available at Play's price in every converted region",
        option["buyOption"] == {"legacyCompatible": True, "multiQuantityEnabled": False}
        and [(r["regionCode"], r["price"]["currencyCode"], r["availability"]) for r in option["regionalPricingAndAvailabilityConfigs"]] == [("DE", "EUR", "AVAILABLE"), ("TR", "TRY", "AVAILABLE")]
        and option["newRegionsConfig"]["availability"] == "AVAILABLE",
        json.dumps(option),
    )

    with tempfile.TemporaryDirectory(dir=scratch) as profile:
        with sqlite3.connect(os.path.join(profile, "cookies.sqlite")) as db:
            db.execute("CREATE TABLE moz_cookies (name, value, host, path, expiry, isSecure, isHttpOnly, sameSite)")
            db.executemany("INSERT INTO moz_cookies VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
                ("SID", "a", ".google.com", "/", 1900000000000, 1, 1, 1),
                ("NID", "b", "google.com", "/", 1900000000, 0, 0, 0),
                ("other", "c", ".example.com", "/", 1900000000, 0, 0, 2),
            ])
        cookies = play_console.google_cookies(Path(profile))
    fails += check(
        "play_console: only Google's cookies come over, expiry in seconds and sameSite named",
        [(c["name"], c["expires"], c.get("sameSite"), c["secure"]) for c in cookies] == [("SID", 1900000000, "Lax", True), ("NID", 1900000000, "None", False)],
        json.dumps([{k: v for k, v in c.items() if k != "value"} for c in cookies]),
    )

    session = play_console.Session(scratch, 1, {"developer": "42", "apps": {"com.example": "7"}})
    fails += check(
        "play_console: pages resolve by package, and account pages by -",
        session.page_url("com.example", "publishing") == f"{play_console.CONSOLE}/42/app/7/publishing"
        and session.page_url("-", "users-and-permissions") == f"{play_console.CONSOLE}/42/users-and-permissions",
    )
    try:
        session.page_url("com.unknown", "publishing")
        unknown = "no error"
    except play_console.ConsoleError as error:
        unknown = str(error)
    fails += check("play_console: an unknown package says where its app id goes", "com.unknown" in unknown and "account.json" in unknown, unknown)
    return fails
