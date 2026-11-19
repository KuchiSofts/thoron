#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Passwords are saved, kept and filled in again (ROADMAP P5.8: upstream #137, #684, #1199).

The upstream reports: the browser offers to save a password and then has not saved it (#137, #1199), and a
password added by hand on the passwords page is gone after a restart (#684). This check does both on a
throwaway profile in a real window (the save prompt is a bubble, which a browser without a window has not),
against a sign-in page served on 127.0.0.1 with made-up names and a password made up for each run, never
shown. Nothing leaves the machine. Steps:

    prompted   after signing in on the local page, the browser offers to save (the bubble's Save button,
               found and pressed through UI Automation among the test browser's own windows only)
    saved      the password list (chrome://password-manager) holds it
    manual     a password added on the passwords page is in the list too
    encrypted  the profile's Login Data holds both, encrypted, and neither password in plain text
    kept       after the browser is closed and started again, the list still holds both
    filled     after the restart the sign-in page is filled in by the browser

    py -3 -I tools/qa/password_check.py --browser <out>\\thoron.exe --work <scratch dir>
Exit status 0 only when every step passes.
"""
import argparse
import http.server
import json
import os
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.qa import bench  # noqa: E402
from tools.qa.adblock_site_switch_check import _close_browser, _devtools_port, _open  # noqa: E402
from tools.qa.cdp import WebSocket  # noqa: E402

USER = "thoron-test-user"
MANUAL_USER = "thoron-manual-user"
MANUAL_URL = "https://login.example.com/"
LOGIN_PAGE = b"""<!doctype html><meta charset="utf-8"><title>sign in</title>
<form method="post" action="/done">
  <input id="user" name="user" autocomplete="username">
  <input id="pass" name="pass" type="password" autocomplete="current-password">
  <button id="go" type="submit">Sign in</button>
</form>"""
DONE_PAGE = b"<!doctype html><meta charset='utf-8'><title>signed in</title><p>signed in"
SAVE_BUTTON = "Save"
# Presses the button named THORON_BUTTON among the elements of the test browser (its process id in THORON_PID;
# no other program's windows are looked at). Prints "pressed" or "absent".
UIA_PRESS = """
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$A = [System.Windows.Automation.AutomationElement]
$mine = New-Object System.Windows.Automation.PropertyCondition($A::ProcessIdProperty, [int]$env:THORON_PID)
$done = 'absent'
for ($i = 0; $i -lt [int]$env:THORON_TRIES -and $done -eq 'absent'; $i++) {
  $button = $A::RootElement.FindAll([System.Windows.Automation.TreeScope]::Descendants, $mine) |
      Where-Object { $_.Current.ControlType.ProgrammaticName -eq 'ControlType.Button' -and
                     $_.Current.Name -eq $env:THORON_BUTTON } | Select-Object -First 1
  if ($button) {
    $button.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
    $done = 'pressed'
  } else { Start-Sleep -Milliseconds 500 }
}
$done
"""
LIST = ("chrome.passwordsPrivate.getSavedPasswordList().then((l) => JSON.stringify(l.map((e) => ({"
        "user: e.username, where: JSON.stringify(e.affiliatedDomains || e.urls || '')}))))")
ADD = ("chrome.passwordsPrivate.addPassword({url: %s, username: %s, password: %s, note: '', "
       "useAccountStore: false}).then(() => JSON.stringify('added'), (e) => JSON.stringify(String(e)))")
FILLED = ("JSON.stringify((() => { const p = document.getElementById('pass'), u = document.getElementById('user');"
          " const m = (e) => e.matches(':autofill') || e.matches(':-webkit-autofill');"
          " return {user: m(u), pass: m(p)}; })())")


def listed_problems(step: str, entries: list[dict] | None, users: list[str]) -> list[str]:
    if entries is None:
        return [f"{step}: the password list could not be read"]
    found = {e.get("user") for e in entries}
    return [f"{step}: {user} is not in the password list" for user in users if user not in found]


def stored_problems(rows: list[tuple[str, str, bytes]], secrets_: dict[str, str]) -> list[str]:
    """Each user has a row, its password is encrypted (Chromium's `v10`/`v20` prefix), never in plain text."""
    out = []
    for user, password in secrets_.items():
        mine = [r for r in rows if r[1] == user]
        if not mine:
            out.append(f"encrypted: Login Data has no row for {user}")
            continue
        value = mine[0][2] or b""
        if not value[:3] in (b"v10", b"v20"):
            out.append(f"encrypted: the password of {user} is not stored the way Chromium encrypts it")
        if password.encode() in value or password.encode("utf-16-le") in value:
            out.append(f"encrypted: the password of {user} is stored in plain text")
    return out


def filled_problems(state: dict | None) -> list[str]:
    if not state:
        return ["filled: the sign-in page could not be read"]
    if not state.get("pass"):
        return ["filled: the browser did not fill in the password on the sign-in page"]
    return []


class Site:
    """The local sign-in page; it keeps its port for the whole run, so the saved password fits it again."""

    def __init__(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, body: bytes):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                self._send(LOGIN_PAGE if self.path.startswith("/login") else DONE_PAGE)

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length") or 0))   # the form, thrown away
                self._send(DONE_PAGE)

        self._httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._httpd.daemon_threads = True
        self.port = self._httpd.server_address[1]

    def __enter__(self):
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self._httpd.shutdown()
        self._httpd.server_close()


def _launch(browser: Path, profile: Path) -> subprocess.Popen:
    return subprocess.Popen([str(browser), f"--user-data-dir={profile}", "--no-first-run",
                             "--no-default-browser-check", "--disable-default-apps", "--window-position=40,40",
                             "--window-size=1100,800", "--remote-debugging-port=0", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _eval(ws: WebSocket, expression: str):
    reply = ws.call("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True)
    value = reply.get("result", {}).get("value")
    return json.loads(value) if isinstance(value, str) else None


def _wait(ws: WebSocket, expression: str, seconds: float = 15):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            if _eval(ws, f"JSON.stringify(!!({expression}))"):
                return True
        except RuntimeError:      # the page is being replaced
            pass
        time.sleep(0.3)
    return False


def _type(ws: WebSocket, element: str, text: str) -> None:
    _eval(ws, f"JSON.stringify(document.getElementById('{element}').focus())")
    ws.call("Input.insertText", text=text)


def _press(pid: int, name: str, tries: int = 30) -> bool:
    out = subprocess.run(["powershell.exe", "-NoProfile", "-Command", UIA_PRESS], capture_output=True, text=True,
                         timeout=120, env=dict(os.environ, THORON_PID=str(pid), THORON_BUTTON=name,
                                               THORON_TRIES=str(tries))).stdout.strip()
    return out.endswith("pressed")


def _list(port: int) -> list[dict] | None:
    ws = WebSocket(_open(port, "chrome://password-manager/passwords")["webSocketDebuggerUrl"])
    try:
        if not _wait(ws, "typeof chrome !== 'undefined' && chrome.passwordsPrivate", 10):
            return None
        return _eval(ws, LIST)
    except RuntimeError:
        return None
    finally:
        ws.close()


def _rows(profile: Path) -> list[tuple[str, str, bytes]]:
    copy = profile.parent / f"{profile.name}-login-data"
    shutil.copy2(profile / "Default" / "Login Data", copy)
    db = sqlite3.connect(copy)
    try:
        return list(db.execute("SELECT origin_url, username_value, password_value FROM logins"))
    finally:
        db.close()             # `with` only ends the transaction; the file stays open until this
        copy.unlink(missing_ok=True)


def run(browser: Path, work: Path) -> list[str]:
    profile = Path(tempfile.mkdtemp(prefix="passwords-", dir=work))
    password, manual_password = secrets.token_urlsafe(12) + "a1", secrets.token_urlsafe(12) + "b2"
    problems: list[str] = []

    def report(step: str, found: list[str], detail="") -> None:
        print(f"{'PASS' if not found else 'FAIL'}  {step}{': ' + str(detail) if detail else ''}")
        problems.extend(found)

    with Site() as site:
        proc = _launch(browser, profile)
        port = None
        try:
            port = _devtools_port(profile)
            page = WebSocket(_open(port, f"http://127.0.0.1:{site.port}/login")["webSocketDebuggerUrl"])
            if not _wait(page, "document.getElementById('pass')"):
                return [*problems, "the run failed: the sign-in page did not load"]
            time.sleep(1.0)            # the password manager looks at the form once it is there
            _type(page, "user", USER)
            _type(page, "pass", password)
            page.call("Input.dispatchKeyEvent", type="keyDown", key="Enter", code="Enter",
                      windowsVirtualKeyCode=13, nativeVirtualKeyCode=13, text="\r")
            page.call("Input.dispatchKeyEvent", type="keyUp", key="Enter", code="Enter",
                      windowsVirtualKeyCode=13, nativeVirtualKeyCode=13)
            signed_in = _wait(page, "document.title === 'signed in'")
            page.close()
            pressed = signed_in and _press(proc.pid, SAVE_BUTTON)
            report("prompted", [] if pressed else
                   ["prompted: no offer to save the password after signing in" if signed_in
                    else "prompted: the sign-in page was not sent"])
            time.sleep(1.5)
            report("saved", listed_problems("saved", _list(port), [USER]) if pressed else
                   ["saved: nothing to look for"])

            ws = WebSocket(_open(port, "chrome://password-manager/passwords")["webSocketDebuggerUrl"])
            time.sleep(2.0)
            answer = _eval(ws, ADD % (json.dumps(MANUAL_URL), json.dumps(MANUAL_USER), json.dumps(manual_password)))
            ws.close()
            time.sleep(1.0)
            report("manual", listed_problems("manual", _list(port), [MANUAL_USER]), answer)

            _close_browser(port, proc)
            port = None
            report("encrypted", stored_problems(_rows(profile), {USER: password, MANUAL_USER: manual_password}))

            (profile / "DevToolsActivePort").unlink(missing_ok=True)
            proc = _launch(browser, profile)
            port = _devtools_port(profile)
            time.sleep(2.0)
            report("kept", listed_problems("kept", _list(port), [USER, MANUAL_USER]))
            page = WebSocket(_open(port, f"http://127.0.0.1:{site.port}/login")["webSocketDebuggerUrl"])
            _wait(page, "document.getElementById('pass')")
            state = None
            for _ in range(10):
                time.sleep(1.0)
                state = _eval(page, FILLED)
                if state and state.get("pass"):
                    break
            page.close()
            report("filled", filled_problems(state), state)
        except (OSError, RuntimeError, ValueError, KeyError, TypeError, sqlite3.Error) as e:
            problems.append(f"the run failed: {e}")
        finally:
            if port is not None:
                _close_browser(port, proc)
            else:
                bench._stop(proc, profile)
            shutil.rmtree(profile, ignore_errors=True)
    return problems


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--browser", required=True, type=Path)
    p.add_argument("--work", required=True, type=Path, help="scratch folder for the throwaway profile")
    a = p.parse_args(argv)
    sys.stdout.reconfigure(errors="backslashreplace")
    a.work.mkdir(parents=True, exist_ok=True)
    problems = run(a.browser.resolve(), a.work)
    for problem in problems:
        print(problem)
    print("PASSWORD CHECK: PASSED" if not problems else f"PASSWORD CHECK: FAILED ({len(problems)} problem(s))")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
