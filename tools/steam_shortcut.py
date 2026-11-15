#!/usr/bin/env python3
"""Non-Steam shortcuts in a running Steam, added through Steam's own client API.

Steam keeps shortcuts.vdf in memory and writes it back, so the file is never edited under a running
client. Instead this reaches the client's SharedJSContext over its CEF debugging port (127.0.0.1:8080,
which Decky Loader turns on) and calls SteamClient.Apps, the API Steam's own "Add a Non-Steam Game"
uses. A shortcut is matched by its name: adding one that exists updates it in place.

    steam_shortcut.py [--host ally] list
    steam_shortcut.py [--host ally] add --name N --exe E [--start-dir D] [--options O] [--icon PNG]
    steam_shortcut.py [--host ally] remove --name N

Without --host it talks to this machine's Steam.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import struct
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from contextlib import contextmanager
from typing import Iterator

CEF_PORT = 8080
CONTEXT_TITLE = "SharedJSContext"
# app_type of a non-Steam shortcut in the client's app store
SHORTCUT_APP_TYPE = 1073741824


class Refused(Exception):
    pass


@contextmanager
def _cef_port(host: str | None) -> Iterator[int]:
    """The local port that reaches the host's CEF debugging port."""
    if host is None:
        yield CEF_PORT
        return
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        local = probe.getsockname()[1]
    tunnel = subprocess.Popen(["ssh", "-N", "-o", "ConnectTimeout=5", "-o", "ExitOnForwardFailure=yes",
                               "-L", f"127.0.0.1:{local}:127.0.0.1:{CEF_PORT}", host])
    try:
        for _ in range(50):
            if tunnel.poll() is not None:
                raise Refused(f"ssh {host} tunnel exited with {tunnel.returncode}")
            try:
                socket.create_connection(("127.0.0.1", local), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        yield local
    finally:
        tunnel.terminate()
        tunnel.wait()


class Cdp:
    """One websocket to a CEF page, enough of RFC 6455 for CDP's text frames."""

    def __init__(self, port: int) -> None:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=5) as response:
                pages = json.load(response)
        except OSError as error:
            raise Refused(f"no Steam CEF debugging port ({error}); Steam runs with Decky Loader or "
                          "-cef-enable-debugging") from error
        page = next((p for p in pages if p.get("title") == CONTEXT_TITLE), None)
        if page is None:
            raise Refused(f"Steam has no {CONTEXT_TITLE} page yet")
        path = urllib.parse.urlsplit(page["webSocketDebuggerUrl"]).path
        self._socket = socket.create_connection(("127.0.0.1", port), timeout=30)
        key = base64.b64encode(os.urandom(16)).decode()
        self._socket.sendall((f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nUpgrade: websocket\r\n"
                              f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                              "Sec-WebSocket-Version: 13\r\n\r\n").encode())
        reply = b""
        while b"\r\n\r\n" not in reply:
            reply += self._socket.recv(4096)
        if b" 101 " not in reply.split(b"\r\n", 1)[0]:
            raise Refused(f"CEF refused the websocket: {reply.split(b'\r\n', 1)[0].decode()}")
        self._next = 0

    def close(self) -> None:
        self._socket.close()

    def _send(self, text: str) -> None:
        payload = text.encode()
        mask = os.urandom(4)
        header = bytes([0x81])
        if len(payload) < 126:
            header += bytes([0x80 | len(payload)])
        elif len(payload) < 1 << 16:
            header += bytes([0x80 | 126]) + struct.pack(">H", len(payload))
        else:
            header += bytes([0x80 | 127]) + struct.pack(">Q", len(payload))
        self._socket.sendall(header + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def _exactly(self, count: int) -> bytes:
        data = b""
        while len(data) < count:
            chunk = self._socket.recv(count - len(data))
            if not chunk:
                raise Refused("CEF closed the websocket")
            data += chunk
        return data

    def _receive(self) -> str:
        message = b""
        while True:
            first, second = self._exactly(2)
            length = second & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._exactly(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._exactly(8))[0]
            message += self._exactly(length)
            if first & 0x80:
                return message.decode()

    def evaluate(self, expression: str) -> object:
        """The value of an async JavaScript expression in the client's context."""
        self._next += 1
        self._send(json.dumps({"id": self._next, "method": "Runtime.evaluate",
                               "params": {"expression": expression, "awaitPromise": True,
                                          "returnByValue": True}}))
        while True:
            reply = json.loads(self._receive())
            if reply.get("id") != self._next:
                continue
            result = reply.get("result", {})
            if "exceptionDetails" in result:
                raise Refused(f"Steam's client threw: {result['exceptionDetails'].get('exception', {}).get('description')}")
            return result.get("result", {}).get("value")


LIST = f"""(async () => appStore.allApps
    .filter(app => app.app_type == {SHORTCUT_APP_TYPE})
    .map(app => ({{appid: app.appid, name: app.display_name}})))()"""


def shortcuts(cdp: Cdp) -> list[dict[str, object]]:
    found = cdp.evaluate(LIST)
    if not isinstance(found, list):
        raise Refused("Steam's app store did not answer with a list")
    return found


def add(cdp: Cdp, name: str, exe: str, start_dir: str, options: str, icon: str | None) -> int:
    """The shortcut's app id, after adding it or updating the one with this name."""
    match = [entry for entry in shortcuts(cdp) if entry["name"] == name]
    if len(match) > 1:
        raise Refused(f"{len(match)} shortcuts are named {name!r}; remove the extras first")
    quoted_exe = json.dumps(f'"{exe}"')
    quoted_dir = json.dumps(f'"{start_dir}"')
    if match:
        appid = int(match[0]["appid"])
    else:
        appid = int(cdp.evaluate(f"SteamClient.Apps.AddShortcut({json.dumps(name)}, {quoted_exe}, "
                                 f"{json.dumps(options)}, {quoted_dir})"))
    cdp.evaluate(f"""(async () => {{
        SteamClient.Apps.SetShortcutName({appid}, {json.dumps(name)});
        SteamClient.Apps.SetShortcutExe({appid}, {quoted_exe});
        SteamClient.Apps.SetShortcutStartDir({appid}, {quoted_dir});
        SteamClient.Apps.SetShortcutLaunchOptions({appid}, {json.dumps(options)});
        {f"SteamClient.Apps.SetShortcutIcon({appid}, {json.dumps(icon)});" if icon else ""}
    }})()""")
    return appid


def remove(cdp: Cdp, name: str) -> int:
    match = [entry for entry in shortcuts(cdp) if entry["name"] == name]
    for entry in match:
        cdp.evaluate(f"SteamClient.Apps.RemoveShortcut({int(entry['appid'])})")
    return len(match)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--host", help="an ssh host whose Steam to change; this machine's without it")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    adding = commands.add_parser("add")
    adding.add_argument("--name", required=True)
    adding.add_argument("--exe", required=True, help="the program, a path on the host")
    adding.add_argument("--start-dir", help="default: the program's directory")
    adding.add_argument("--options", default="", help="Steam launch options")
    adding.add_argument("--icon", help="a PNG on the host")
    removing = commands.add_parser("remove")
    removing.add_argument("--name", required=True)
    args = parser.parse_args()
    try:
        with _cef_port(args.host) as port:
            cdp = Cdp(port)
            try:
                if args.command == "list":
                    for entry in shortcuts(cdp):
                        print(f"{entry['appid']}\t{entry['name']}")
                elif args.command == "add":
                    start_dir = args.start_dir or args.exe.rsplit("/", 1)[0]
                    print(add(cdp, args.name, args.exe, start_dir, args.options, args.icon))
                else:
                    print(f"removed {remove(cdp, args.name)}")
            finally:
                cdp.close()
    except Refused as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
