#!/usr/bin/env python3
"""Google Play Developer API (androidpublisher v3) through a service account.

Reads tracks, store listings and one-time products, and uploads a bundle to a
track as one edit. The service account's key never leaves its file except as a
signature: openssl signs the token request through a pipe.

    play_api.py tracks com.example.app
    play_api.py listing com.example.app [--language en-US]
    play_api.py products com.example.app
    play_api.py product com.example.app remove_ads --price 2.49 --title "Remove ads" --description "..."
    play_api.py upload com.example.app build/app.aab --track internal --track alpha --notes "Fixes."
"""

from __future__ import annotations

import argparse
import base64
import decimal
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Self

SCOPE = "https://www.googleapis.com/auth/androidpublisher"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://androidpublisher.googleapis.com/androidpublisher/v3/applications"
UPLOAD_API = "https://androidpublisher.googleapis.com/upload/androidpublisher/v3/applications"
DEFAULT_KEY = Path("~/.config/play-console/service-account.json")


class PlayError(RuntimeError):
    """An API call failed; the message carries Google's own explanation."""


def key_path() -> Path:
    """The service account key: $PLAY_SERVICE_ACCOUNT, else the shared default."""
    return Path(os.environ.get("PLAY_SERVICE_ACCOUNT") or DEFAULT_KEY).expanduser()


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def unsigned_assertion(email: str, now: int) -> str:
    """The JWT header and claims a service account signs to get an access token."""
    header = {"alg": "RS256", "typ": "JWT"}
    claims = {"iss": email, "scope": SCOPE, "aud": TOKEN_URL, "iat": now, "exp": now + 3600}
    return b64url(json.dumps(header).encode()) + "." + b64url(json.dumps(claims).encode())


def sign(message: str, private_key: str) -> str:
    """RS256 over the message with openssl, the key passed through a pipe rather than a file."""
    read_end, write_end = os.pipe()
    with os.fdopen(write_end, "w") as pipe:
        pipe.write(private_key)
    try:
        result = subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", f"/dev/fd/{read_end}"],
            input=message.encode(),
            capture_output=True,
            pass_fds=(read_end,),
            check=True,
        )
    finally:
        os.close(read_end)
    return b64url(result.stdout)


def access_token(account: dict) -> str:
    assertion = unsigned_assertion(account["client_email"], int(time.time()))
    assertion += "." + sign(assertion, account["private_key"])
    body = urllib.parse.urlencode(
        {"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion}
    ).encode()
    return call(urllib.request.Request(TOKEN_URL, data=body))["access_token"]


def call(request: urllib.request.Request, timeout: float = 60) -> dict:
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        raise PlayError(f"{request.get_method()} {request.full_url}: {error.code} {error.read().decode(errors='replace')}") from error
    return json.loads(raw) if raw else {}


def release_body(track: str, version_code: int, notes: str, status: str, name: str | None) -> dict:
    """A track holding one release of one version code, with en-US notes."""
    release = {"versionCodes": [str(version_code)], "status": status}
    if name:
        release["name"] = name
    if notes:
        release["releaseNotes"] = [{"language": "en-US", "text": notes}]
    return {"track": track, "releases": [release]}


def money(amount: str, currency: str = "USD") -> dict:
    """A decimal amount as Play's Money: whole units as a string, the fraction in nanos."""
    value = decimal.Decimal(amount)
    units = int(value)
    return {"currencyCode": currency, "units": str(units), "nanos": int((value - units) * 10**9)}


def product_body(package: str, product: str, title: str, description: str, converted: dict) -> dict:
    """A non-consumable one-time product: one buy option at Play's converted price in every region."""
    regions = [
        {"regionCode": code, "price": region["price"], "availability": "AVAILABLE"}
        for code, region in sorted(converted["convertedRegionPrices"].items())
    ]
    other = converted["convertedOtherRegionsPrice"]
    option = {
        "purchaseOptionId": "buy",
        "buyOption": {"legacyCompatible": True, "multiQuantityEnabled": False},
        "regionalPricingAndAvailabilityConfigs": regions,
        "newRegionsConfig": {"usdPrice": other["usdPrice"], "eurPrice": other["eurPrice"], "availability": "AVAILABLE"},
    }
    return {
        "packageName": package,
        "productId": product,
        "listings": [{"languageCode": "en-US", "title": title, "description": description}],
        "purchaseOptions": [option],
    }


class Client:
    def __init__(self, account: dict):
        self._token = access_token(account)

    def request(self, method: str, url: str, body: dict | None = None, data: bytes | None = None, timeout: float = 60) -> dict:
        headers = {"Authorization": f"Bearer {self._token}"}
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        elif data is not None:
            headers["Content-Type"] = "application/octet-stream"
        return call(urllib.request.Request(url, data=data, headers=headers, method=method), timeout)


class Edit:
    """One Play edit: everything inside it is committed together, or discarded on error."""

    def __init__(self, client: Client, package: str, commit: bool, not_for_review: bool = False):
        self._client = client
        self._package = package
        self._commit = commit
        self._not_for_review = not_for_review
        self.id = ""

    def url(self, path: str, upload: bool = False) -> str:
        return f"{UPLOAD_API if upload else API}/{self._package}/edits/{self.id}/{path}"

    def __enter__(self) -> Self:
        self.id = self._client.request("POST", f"{API}/{self._package}/edits", body={})["id"]
        return self

    def __exit__(self, kind, value, traceback) -> None:
        base = f"{API}/{self._package}/edits/{self.id}"
        if kind is None and self._commit:
            query = "?changesNotSentForReview=true" if self._not_for_review else ""
            self._client.request("POST", f"{base}:commit{query}")
        else:
            self._client.request("DELETE", base)


def show(data: dict) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("tracks", "listing", "products"):
        command = commands.add_parser(name)
        command.add_argument("package")
        if name == "listing":
            command.add_argument("--language", default="en-US")
    product = commands.add_parser("product", help="create or update a non-consumable one-time product and activate it")
    product.add_argument("package")
    product.add_argument("product")
    product.add_argument("--price", required=True, help="in USD; Play converts it for every other region")
    product.add_argument("--title", required=True)
    product.add_argument("--description", required=True)
    upload = commands.add_parser("upload")
    upload.add_argument("package")
    upload.add_argument("bundle", type=Path)
    upload.add_argument("--track", action="append", help="a track to release it on; repeat for several (default: internal)")
    upload.add_argument("--notes", default="")
    upload.add_argument("--name")
    upload.add_argument("--status", default="completed", choices=("completed", "draft"))
    upload.add_argument("--not-for-review", action="store_true", help="commit without sending changes for review")
    args = parser.parse_args(argv)

    path = key_path()
    if not path.is_file():
        print(f"no service account key at {path}; see the play-console skill", file=sys.stderr)
        return 2
    client = Client(json.loads(path.read_text()))
    try:
        if args.command == "tracks":
            with Edit(client, args.package, commit=False) as edit:
                show(client.request("GET", edit.url("tracks")))
        elif args.command == "listing":
            with Edit(client, args.package, commit=False) as edit:
                show(client.request("GET", edit.url(f"listings/{args.language}")))
        elif args.command == "products":
            show(client.request("GET", f"{API}/{args.package}/oneTimeProducts"))
        elif args.command == "product":
            app = f"{API}/{args.package}"
            converted = client.request("POST", f"{app}/pricing:convertRegionPrices", body={"price": money(args.price)})
            body = product_body(args.package, args.product, args.title, args.description, converted)
            query = urllib.parse.urlencode({
                "allowMissing": "true",
                "updateMask": "listings,purchaseOptions",
                "regionsVersion.version": converted["regionVersion"]["version"],
            })
            # patch alone is routed at lowercase onetimeproducts (discovery document)
            client.request("PATCH", f"{app}/onetimeproducts/{args.product}?{query}", body=body)
            activate = {"activatePurchaseOptionRequest": {"packageName": args.package, "productId": args.product, "purchaseOptionId": "buy"}}
            client.request("POST", f"{app}/oneTimeProducts/{args.product}/purchaseOptions:batchUpdateStates", body={"requests": [activate]})
            print(f"{args.package}: {args.product} active at {args.price} USD in {len(body['purchaseOptions'][0]['regionalPricingAndAvailabilityConfigs'])} regions")
        else:
            tracks = args.track or ["internal"]
            with Edit(client, args.package, commit=True, not_for_review=args.not_for_review) as edit:
                bundle = client.request("POST", edit.url("bundles?uploadType=media", upload=True), data=args.bundle.read_bytes(), timeout=900)
                for track in tracks:
                    body = release_body(track, bundle["versionCode"], args.notes, args.status, args.name)
                    client.request("PUT", edit.url(f"tracks/{track}"), body=body)
            print(f"{args.package}: version code {bundle['versionCode']} on {', '.join(tracks)} ({args.status})")
    except PlayError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
