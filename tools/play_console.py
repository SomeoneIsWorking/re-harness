#!/usr/bin/env python3
"""Google Play Console through one headless WebLua session signed in to the developer account.

For what the Play Developer API cannot do (play_api.py does releases and reads):
app content declarations, store settings, form factors, users and permissions,
the dashboard's setup steps, sending changes for review. Pages are addressed by
package name; account facts live in ~/.config/play-console/account.json:
{"developer": "<account id>", "apps": {"<package>": "<app id>"}}.

    play_console.py start [--headed]          # --headed once, for the user to sign in
    play_console.py open <package|-> <page>   # e.g. tracks/internal-testing, publishing, users-and-permissions
    play_console.py text
    play_console.py click "Save and publish" [--dialog]
    play_console.py check "Manage store presence"
    play_console.py join-link <package>
    play_console.py review <package>
    play_console.py ctl <weblua-ctl args...>   # type, upload, screenshot, eval, ...
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

CONSOLE = "https://play.google.com/console/u/0/developers"
DEFAULT_STATE = Path("~/.local/state/play-console")
DEFAULT_ACCOUNT = Path("~/.config/play-console/account.json")
DEFAULT_PORT = 7981

# Visible clickable elements whose trimmed text is exactly the target, inside the open dialog if asked.
FIND_CLICKABLE = """(() => {
  const text = %s, inDialog = %s;
  const dialogs = [...document.querySelectorAll('[role=dialog]')].filter(e => e.offsetParent);
  const scope = inDialog ? dialogs[dialogs.length - 1] : document;
  if (!scope) return 'no dialog';
  const hits = [...scope.querySelectorAll('button,a,[role=tab],[role=menuitem],[role=radio],[role=option]')]
    .filter(e => e.offsetParent && e.textContent.trim() === text);
  if (!hits.length) return 'not found';
  document.querySelectorAll('[data-play-console]').forEach(e => e.removeAttribute('data-play-console'));
  const hit = hits[hits.length - 1];
  hit.scrollIntoView({block: 'center'});
  if (hit.disabled || hit.getAttribute('aria-disabled') === 'true') return 'disabled';
  hit.setAttribute('data-play-console', 'target');
  return 'ok';
})()"""

# Material checkboxes keep their input hidden; the visible box takes the click.
FIND_CHECKBOX = """(() => {
  const label = %s;
  const box = [...document.querySelectorAll('material-checkbox,mat-checkbox')]
    .find(e => e.getBoundingClientRect().width > 0 && e.innerText.split('\\n')[0].trim() === label);
  if (!box) return 'not found';
  const input = box.querySelector('input');
  if (input && input.checked) return 'checked';
  if (box.classList.contains('disabled') || (input && input.disabled)) return 'disabled';
  document.querySelectorAll('[data-play-console]').forEach(e => e.removeAttribute('data-play-console'));
  const target = box.querySelector('.mdc-checkbox') || box;
  target.scrollIntoView({block: 'center'});
  target.setAttribute('data-play-console', 'target');
  return 'ok';
})()"""

IS_CHECKED = """(() => {
  const label = %s;
  const box = [...document.querySelectorAll('material-checkbox,mat-checkbox')]
    .find(e => e.getBoundingClientRect().width > 0 && e.innerText.split('\\n')[0].trim() === label);
  return String(!!(box && box.querySelector('input') && box.querySelector('input').checked));
})()"""

# The console keeps a hidden "Loading" banner in the body; its footer renders after the page's panels.
PAGE_READY = "(() => document.readyState === 'complete' && document.body.innerText.includes('Product updates') ? 'ready' : 'wait')()"
PAGE_TEXT = "document.querySelector('main') ? document.querySelector('main').innerText : document.body.innerText"
JOIN_LINK = "(document.documentElement.outerHTML.match(/https:\\/\\/play\\.google\\.com\\/apps\\/internaltest\\/\\d+/) || ['none'])[0]"


class ConsoleError(RuntimeError):
    pass


class Session:
    """The WebLua server and Chrome profile signed in to Play Console, shared by every project."""

    def __init__(self, state: Path, port: int, account: dict):
        self.state = state
        self.port = port
        self.account = account

    @classmethod
    def from_environment(cls) -> Session:
        state = Path(os.environ.get("PLAY_CONSOLE_STATE") or DEFAULT_STATE).expanduser()
        port = int(os.environ.get("PLAY_CONSOLE_PORT") or DEFAULT_PORT)
        account_file = Path(os.environ.get("PLAY_CONSOLE_ACCOUNT") or DEFAULT_ACCOUNT).expanduser()
        account = json.loads(account_file.read_text()) if account_file.is_file() else {}
        return cls(state, port, account)

    def ctl(self, *args: str, check: bool = True) -> str:
        binary = shutil.which("weblua-ctl") or str(Path("~/repo/weblua/build/bin/weblua-ctl").expanduser())
        env = dict(os.environ, WEBLUA_DIR=str(self.state))
        result = subprocess.run([binary, "--port", str(self.port), *args], env=env, capture_output=True, text=True, check=False)
        out = (result.stdout + result.stderr).strip()
        if check and (result.returncode != 0 or out.startswith("error")):
            raise ConsoleError(out or f"weblua-ctl {args[0]} failed")
        return out

    def eval(self, expression: str) -> str:
        out = self.ctl("eval", expression)
        return out.splitlines()[-1] if out else ""

    def page_url(self, package: str, page: str) -> str:
        developer = self.account.get("developer")
        if not developer:
            raise ConsoleError("no developer id; write it to ~/.config/play-console/account.json")
        if package == "-":
            return f"{CONSOLE}/{developer}/{page}"
        app = self.account.get("apps", {}).get(package)
        if not app:
            raise ConsoleError(f"no app id for {package}; add it under \"apps\" in account.json (it is in the app's console URL)")
        return f"{CONSOLE}/{developer}/app/{app}/{page}"

    def open(self, package: str, page: str) -> None:
        self.ctl("navigate", self.page_url(package, page))
        self.settle()

    def settle(self, timeout: float = 30) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.eval(PAGE_READY) == "ready":
                time.sleep(2)  # the console renders its panels after the document completes
                return
            time.sleep(1)
        raise ConsoleError("page did not finish loading")

    def click(self, text: str, dialog: bool = False) -> None:
        found = self.eval(FIND_CLICKABLE % (json.dumps(text), json.dumps(dialog)))
        if found != "ok":
            raise ConsoleError(f"click {text!r}: {found}")
        self.ctl("click", "[data-play-console=target]")
        time.sleep(2)

    def check(self, label: str) -> str:
        found = self.eval(FIND_CHECKBOX % json.dumps(label))
        if found != "ok":
            return found
        self.ctl("click", "[data-play-console=target]")
        if self.eval(IS_CHECKED % json.dumps(label)) != "true":
            raise ConsoleError(f"check {label!r}: still unchecked")
        return "checked now"

    def text(self) -> str:
        return " ".join(self.ctl("eval", PAGE_TEXT).split())

    def review(self, package: str, timeout: float = 20) -> str:
        self.open(package, "publishing")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            text = self.text()
            if "complete the required steps in the app dashboard" in text:
                return "locked: the dashboard still has required steps"
            if re.search(r"Send (\d+ )?changes? for review", text):
                return "ready: changes can be sent for review"
            if "Changes in review" in text:
                return "in review"
            if "Last published" in text and "Changes not yet submitted" not in text:
                return "published, nothing waiting"
            time.sleep(1)
        return "unknown: " + text[:300]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("start")
    start.add_argument("--headed", action="store_true", help="a visible window, for the user to sign in once")
    commands.add_parser("stop")
    commands.add_parser("status")
    page = commands.add_parser("open")
    page.add_argument("package", help="the app's package name, or - for an account page")
    page.add_argument("page")
    commands.add_parser("text")
    click = commands.add_parser("click")
    click.add_argument("text")
    click.add_argument("--dialog", action="store_true", help="only inside the open dialog")
    tick = commands.add_parser("check")
    tick.add_argument("label")
    for name in ("join-link", "review"):
        commands.add_parser(name).add_argument("package")
    passthrough = commands.add_parser("ctl")
    passthrough.add_argument("args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)

    session = Session.from_environment()
    try:
        if args.command == "start":
            session.state.mkdir(parents=True, exist_ok=True)
            flags = ["--headed"] if args.headed else []
            print(session.ctl("start", "--url", f"{CONSOLE}/", *flags))
        elif args.command in ("stop", "status"):
            print(session.ctl(args.command))
        elif args.command == "open":
            session.open(args.package, args.page)
            print(session.ctl("url"))
        elif args.command == "text":
            print(session.text())
        elif args.command == "click":
            session.click(args.text, args.dialog)
            print(f"clicked {args.text!r}")
        elif args.command == "check":
            print(f"{args.label}: {session.check(args.label)}")
        elif args.command == "join-link":
            session.open(args.package, "tracks/internal-testing")
            session.click("Testers")
            print(session.eval(JOIN_LINK))
        elif args.command == "review":
            print(session.review(args.package))
        else:
            print(session.ctl(*args.args))
    except ConsoleError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
