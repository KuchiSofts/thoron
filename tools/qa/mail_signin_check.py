#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Thoron M-Notifier asks Gmail only while somebody is signed in to Google, checked offline (ROADMAP S.15).

A profile nobody signed in to Google with must not tell Google that it is running, so the notifier looks at
Gmail's feed only while the browser's own list of the Google accounts in its cookies has an entry. Here no
outside name can be resolved, so nothing leaves the PC and no real account is used; that also tells the two
cases apart: a look that did not ask Gmail ends as "signed-out", one that asked ends as "offline". Steps:

    quiet     a new profile: the look ends as "signed-out" without asking Gmail
    asked     the same profile with a made-up account in the browser's list of signed-in Google accounts (and
              a made-up Google cookie, without which the browser empties that list): the look asks Gmail

    py -3 -I tools/qa/mail_signin_check.py --browser <out>\\thoron.exe --work <scratch dir>
Exit status 0 only when every step passes.
"""
import argparse
import base64
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.qa import bench  # noqa: E402
from tools.qa.adblock_site_switch_check import _close_browser, _devtools_port, _open  # noqa: E402
from tools.qa.cdp import WebSocket  # noqa: E402
from tools.qa.mail_check import GET_STATE, MENU_URL  # noqa: E402

LOOK_S = 6.0
ACCOUNT = "someone@example.com"
# the browser keeps the answer to "which Google accounts are signed in" here between starts
LIST_PREF = ("gaia_cookie", "last_list_accounts_binary_data")
SET_COOKIE = {"name": "LSID", "value": "stand-in", "url": "https://accounts.google.com/", "secure": True,
              "httpOnly": True}


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        out.append((n & 0x7F) | (0x80 if n > 0x7F else 0))
        n >>= 7
        if not n:
            return bytes(out)


def _field(number: int, payload: bytes) -> bytes:
    """A length-delimited protocol buffer field."""
    return _varint(number << 3 | 2) + _varint(len(payload)) + payload


def listed_accounts(emails: list[str]) -> str:
    """The browser's saved list of signed-in Google accounts (base64 of a ListAccountsResponse: field 1 an
    account, in it field 3 the address and field 10 an id)."""
    body = b"".join(_field(1, _field(3, email.encode()) + _field(10, f"{100000 + i}".encode()))
                    for i, email in enumerate(emails))
    return base64.b64encode(body).decode()


def with_list(preferences: dict, emails: list[str]) -> dict:
    """`preferences` (the profile's Preferences file) with the saved list of signed-in Google accounts."""
    out = dict(preferences)
    out[LIST_PREF[0]] = dict(out.get(LIST_PREF[0]) or {}, **{LIST_PREF[1]: listed_accounts(emails)})
    return out


def quiet_problems(state: dict) -> list[str]:
    if state.get("problem") == "signed-out" and not state.get("accounts"):
        return []
    return [f"quiet: without a Google sign-in the look ended as {state.get('problem')!r} with "
            f"{len(state.get('accounts') or [])} account(s): Gmail was asked"]


def asked_problems(state: dict) -> list[str]:
    if state.get("problem") == "offline":
        return []
    return [f"asked: with a Google account in the browser's list the look ended as {state.get('problem')!r}, "
            "not 'offline': Gmail was not asked"]


def _look(browser: Path, profile: Path, cookie: bool) -> dict:
    """Starts the browser, has the notifier look, and returns what its menu shows."""
    (profile / "DevToolsActivePort").unlink(missing_ok=True)
    args = [str(browser), "--headless=new", f"--user-data-dir={profile}", "--no-first-run",
            "--no-default-browser-check", "--disable-background-networking", "--disable-component-update",
            "--enable-features=ThoronMailNotifier", "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
            "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0", "about:blank"]
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    port = None
    ws = None
    try:
        port = _devtools_port(profile)
        ws = WebSocket(_open(port, MENU_URL)["webSocketDebuggerUrl"])
        time.sleep(3)
        ws.call("Runtime.evaluate", expression="chrome.send('checkNow'); 1")
        time.sleep(LOOK_S)
        reply = ws.call("Runtime.evaluate", expression=GET_STATE, awaitPromise=True, returnByValue=True)
        state = json.loads(reply.get("result", {}).get("value") or "{}")
        if cookie:
            ws.call("Network.setCookie", expires=int(time.time()) + 86400, **SET_COOKIE)
            time.sleep(1)
        return state
    finally:
        if ws:
            try:
                ws.close()
            except OSError:
                pass
        if port is not None:
            _close_browser(port, proc)
        else:
            bench._stop(proc, profile)


def run(browser: Path, work: Path) -> list[str]:
    profile = Path(tempfile.mkdtemp(prefix="mail-signin-", dir=work))
    problems: list[str] = []

    def step(name: str, found: list[str], state: dict) -> None:
        print(f"{'PASS' if not found else 'FAIL'}  {name}: problem {state.get('problem')!r}, "
              f"{len(state.get('accounts') or [])} account(s)")
        problems.extend(found)

    try:
        state = _look(browser, profile, cookie=True)
        step("quiet", quiet_problems(state), state)

        preferences = profile / "Default" / "Preferences"
        preferences.write_text(json.dumps(with_list(json.loads(preferences.read_text(encoding="utf-8")),
                                                    [ACCOUNT])), encoding="utf-8")
        state = _look(browser, profile, cookie=False)
        step("asked", asked_problems(state), state)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as e:
        problems.append(f"the run failed: {e}")
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    return problems


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--browser", required=True, type=Path)
    p.add_argument("--work", required=True, type=Path, help="scratch folder for the throwaway profile")
    a = p.parse_args(argv)
    a.work.mkdir(parents=True, exist_ok=True)
    problems = run(a.browser.resolve(), a.work)
    for problem in problems:
        print(problem)
    print("MAIL SIGN-IN CHECK: PASSED" if not problems else f"MAIL SIGN-IN CHECK: FAILED ({len(problems)} problem(s))")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
