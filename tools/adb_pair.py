#!/usr/bin/env python3
"""Pair and connect an Android phone to adb over Wi-Fi without typing a code.

``adb_pair.py`` shows a QR code; on the phone open Developer options → Wireless debugging →
"Pair device with QR code" and scan it. The phone then advertises the pairing service under the
QR's name over mDNS, which this tool finds and pairs with. adb then connects to a paired phone by
itself over mDNS as ``<guid>._adb-tls-connect._tcp``, a serial that survives port changes.
"""

from __future__ import annotations

import argparse
import re
import secrets
import shutil
import string
import subprocess
import time
from pathlib import Path

PAIRING = "_adb-tls-pairing._tcp"
CONNECT = "_adb-tls-connect._tcp"
GUID = re.compile(r"guid=([^\]\s]+)")
POLL_SECONDS = 1.0


def adb(*args: str) -> str:
    result = subprocess.run(["adb", *args], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SystemExit(f"adb {' '.join(args)} failed: {(result.stderr or result.stdout).strip()}")
    return result.stdout


def services() -> list[tuple[str, str, str]]:
    """(instance, service, host:port) for each adb service on the network."""
    found = []
    for line in adb("mdns", "services").splitlines():
        fields = line.split()
        if len(fields) == 3 and fields[1].startswith("_adb-tls-"):
            found.append((fields[0], fields[1], fields[2]))
    return found


def wait_for(match, timeout: float, what: str) -> tuple[str, str, str]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for service in services():
            if match(service):
                return service
        time.sleep(POLL_SECONDS)
    raise SystemExit(f"timed out after {timeout:.0f}s waiting for {what}")


def show_qr(payload: str, png: Path | None) -> None:
    if shutil.which("qrencode") is None:
        raise SystemExit(
            "refused: qrencode is missing; install it with\n"
            "  Fedora: sudo dnf install qrencode\n"
            "  Debian/Ubuntu: sudo apt install qrencode\n"
            "  Arch: sudo pacman -S qrencode\n"
            "  macOS: brew install qrencode"
        )
    subprocess.run(["qrencode", "-t", "ANSIUTF8", "-m", "2", payload], check=True)
    if png is not None:
        subprocess.run(["qrencode", "-o", str(png), "-s", "10", payload], check=True)
        print(f"QR also saved to {png}")


def pair(timeout: float, png: Path | None) -> None:
    name = "adb-pair-" + secrets.token_hex(4)
    password = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))
    show_qr(f"WIFI:T:ADB;S:{name};P:{password};;", png)
    print("Phone: Developer options → Wireless debugging → Pair device with QR code, then scan.")
    _, _, address = wait_for(lambda s: s[0] == name and s[1] == PAIRING, timeout, "the phone to scan the code")
    paired = adb("pair", address, password).strip()
    print(paired)
    guid = GUID.search(paired)
    if guid is None:
        raise SystemExit("refused: adb pair reported no device guid")
    serial = f"{guid.group(1)}.{CONNECT}"
    deadline = time.monotonic() + timeout
    while f"{serial}\tdevice" not in adb("devices"):
        if time.monotonic() > deadline:
            raise SystemExit(f"timed out waiting for adb to connect {serial}")
        time.sleep(POLL_SECONDS)
    print(f"connected: adb -s {serial}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--timeout", type=float, default=120, help="seconds to wait for the phone")
    parser.add_argument("--png", type=Path, help="also write the QR code to this PNG")
    options = parser.parse_args()
    if shutil.which("adb") is None:
        raise SystemExit("refused: adb is not on PATH; install Android platform-tools")
    pair(options.timeout, options.png)


if __name__ == "__main__":
    main()
