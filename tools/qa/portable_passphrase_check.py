#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""A portable copy locked with a passphrase, checked end to end on a test copy (ROADMAP P4.9).

A portable layout is made around the given build (a folder junction, nothing copied) with a fresh User Data
folder, and a local page sets a cookie: the cookie is encrypted with the copy's profile key, so reading it after
each start shows the key opened. The unlock window is Thoron's own Windows dialog; it is driven with window
messages (no screen capture). Steps:

    lock       chrome://thoron-portable locks the copy: a recovery key shown and confirmed, the key file written,
               Local State's copy of the key gone, the copy marked as locked
    quit       a start shows the unlock window; a wrong passphrase is refused there; Quit ends the browser
    recovery   the recovery key as a person might type it (small letters, no dashes) opens the copy: the cookie is
               there
    remember   the passphrase with "Remember this PC": the copy opens, and the next start asks nothing
    forget     the page forgets this PC: the next start asks again
    change     the page changes the passphrase: the old one is refused, the new one opens the copy
    tampered   a changed byte in the key file: the start says so and quits; nothing else changed
    remove     the page removes the lock: no key file, Local State holds the key again, a start asks nothing and the
               cookie is there
    missing    locked again, then the key file deleted: the start warns, No quits (still marked), Yes starts without

    py -3 -I tools/qa/portable_passphrase_check.py --browser <out>\\thoron.exe --work <scratch dir>
Windows only. Exit status 0 only when every step passes.
"""
import argparse
import ctypes
import http.server
import json
import os
import secrets
import shutil
import socketserver
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from ctypes import wintypes
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.qa.adblock_site_switch_check import _close_browser, _devtools_port, _open  # noqa: E402
from tools.qa.cdp import WebSocket  # noqa: E402

PAGE_URL = "chrome://thoron-portable/"
PASSPHRASE = "violet harbour lantern seven"
NEW_PASSPHRASE = "quiet orchard copper ninety"
KEY_FILE = "Thoron Portable Key"

# the unlock window's controls (unlock_dialog_win.cc)
EDIT, REMEMBER, STATUS, SWITCH = 102, 103, 104, 105
IDOK, IDCANCEL, IDYES, IDNO = 1, 2, 6, 7
WM_SETTEXT, WM_GETTEXT, WM_GETTEXTLENGTH, WM_COMMAND = 0x000C, 0x000D, 0x000E, 0x0111
BM_SETCHECK, BST_CHECKED = 0x00F1, 1


class Win32:
    """The few window calls the check needs (user32 through ctypes)."""

    def __init__(self):
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        u = self.user32
        u.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM), wintypes.LPARAM]
        u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u.IsWindowVisible.argtypes = [wintypes.HWND]
        u.GetDlgItem.argtypes = [wintypes.HWND, ctypes.c_int]
        u.GetDlgItem.restype = wintypes.HWND
        u.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        u.SendMessageW.restype = ctypes.c_ssize_t
        u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

    def dialogs(self, pid: int) -> list[int]:
        """The visible dialog windows of process `pid`."""
        found: list[int] = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def each(hwnd, _):
            owner = wintypes.DWORD()
            self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value == pid and self.user32.IsWindowVisible(hwnd):
                name = ctypes.create_unicode_buffer(64)
                self.user32.GetClassNameW(hwnd, name, 64)
                if name.value == "#32770":
                    found.append(hwnd)
            return True

        self.user32.EnumWindows(each, 0)
        return found

    def wait_dialog(self, pid: int, item: int, timeout: float = 60) -> int:
        """The dialog of `pid` that has control `item`."""
        end = time.time() + timeout
        while time.time() < end:
            for hwnd in self.dialogs(pid):
                if self.user32.GetDlgItem(hwnd, item):
                    return hwnd
            time.sleep(0.2)
        raise RuntimeError(f"no window with control {item} appeared")

    def text(self, dialog: int, item: int) -> str:
        control = self.user32.GetDlgItem(dialog, item)
        length = self.user32.SendMessageW(control, WM_GETTEXTLENGTH, 0, 0)
        buf = ctypes.create_unicode_buffer(length + 1)
        self.user32.SendMessageW(control, WM_GETTEXT, length + 1, ctypes.cast(buf, ctypes.c_void_p).value)
        return buf.value

    def set_text(self, dialog: int, item: int, value: str) -> None:
        control = self.user32.GetDlgItem(dialog, item)
        buf = ctypes.create_unicode_buffer(value)
        self.user32.SendMessageW(control, WM_SETTEXT, 0, ctypes.cast(buf, ctypes.c_void_p).value)

    def check(self, dialog: int, item: int) -> None:
        self.user32.SendMessageW(self.user32.GetDlgItem(dialog, item), BM_SETCHECK, BST_CHECKED, 0)

    def press(self, dialog: int, item: int) -> None:
        # posted: the dialog checks a passphrase for a second or two before it answers
        self.user32.PostMessageW(dialog, WM_COMMAND, item, self.user32.GetDlgItem(dialog, item) or 0)


class CookieServer:
    """A local page that sets a cookie (/set) and shows the cookies it gets (/get)."""

    def __init__(self):
        self.value = secrets.token_hex(12)
        value = self.value

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = (self.headers.get("Cookie") or "").encode() if self.path == "/get" else b"set"
                self.send_response(200)
                if self.path == "/set":
                    self.send_header("Set-Cookie", f"thoronportable={value}; Max-Age=864000; Path=/")
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def make_layout(browser: Path, work: Path) -> tuple[Path, Path]:
    """A portable layout around the build: <root>\\Thoron.exe, <root>\\App\\current and the build's folder as
    <root>\\App\\v (a junction). Returns the browser to start and the User Data folder."""
    root = Path(tempfile.mkdtemp(prefix="portable-passphrase-", dir=work))
    (root / "Thoron.exe").write_bytes(b"launcher stand-in")
    (root / "App" / "current").mkdir(parents=True)
    subprocess.run(["cmd", "/c", "mklink", "/J", str(root / "App" / "v"), str(browser.parent)], check=True,
                   capture_output=True)
    return root / "App" / "v" / browser.name, root / "User Data"


def launch(browser: Path, user_data: Path) -> subprocess.Popen:
    (user_data / "DevToolsActivePort").unlink(missing_ok=True)
    args = [str(browser), "--headless=new", f"--user-data-dir={user_data}", "--no-first-run",
            "--no-default-browser-check", "--disable-background-networking", "--disable-component-update",
            "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0", "about:blank"]
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class Session:
    """One start of the browser, once it runs: DevTools on a tab."""

    def __init__(self, proc: subprocess.Popen, user_data: Path):
        self.proc = proc
        self.port = _devtools_port(user_data)
        self.ws = None

    def go(self, url: str, settle: float = 2.5) -> None:
        if self.ws:
            self.ws.close()
        self.ws = WebSocket(_open(self.port, url)["webSocketDebuggerUrl"])
        time.sleep(settle)

    def run(self, expression: str):
        reply = self.ws.call("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True)
        return reply.get("result", {}).get("value")

    def body(self, url: str) -> str:
        self.go(url, 1.5)
        return self.run("document.body.innerText") or ""

    def wait_text(self, element: str, want: str, timeout: float = 90) -> str:
        end = time.time() + timeout
        text = ""
        while time.time() < end:
            text = self.run(f"document.getElementById({json.dumps(element)}).textContent") or ""
            if want in text:
                return text
            time.sleep(0.5)
        return text

    def page(self, script: str) -> None:
        self.run("(() => {" + script + "})()")

    def close(self) -> None:
        if self.ws:
            self.ws.close()
        _close_browser(self.port, self.proc)


def local_state(user_data: Path) -> dict:
    return json.loads((user_data / "Local State").read_text(encoding="utf-8"))


def cookie_encrypted(user_data: Path, value: str) -> bool:
    """The cookie is in the profile's database, encrypted (v10), and its value is not there as it is."""
    db = user_data / "Default" / "Network" / "Cookies"
    copy = db.with_name("Cookies.check")
    shutil.copyfile(db, copy)
    try:
        con = sqlite3.connect(copy)
        rows = con.execute("SELECT value, encrypted_value FROM cookies WHERE name = 'thoronportable'").fetchall()
        con.close()
    finally:
        copy.unlink(missing_ok=True)
    return bool(rows) and all(not plain and bytes(enc).startswith(b"v10") and value.encode() not in bytes(enc)
                              for plain, enc in rows)


def run(browser: Path, work: Path) -> list[str]:
    if os.name != "nt":
        return ["this check runs on Windows only"]
    win = Win32()
    problems: list[str] = []
    cookies = CookieServer()
    exe, user_data = make_layout(browser, work)
    root = user_data.parent
    key_file = user_data / KEY_FILE
    session = None

    def report(name: str, found: list[str], detail) -> None:
        print(f"{'PASS' if not found else 'FAIL'}  {name}: {detail}")
        problems.extend(found)

    def start() -> subprocess.Popen:
        return launch(exe, user_data)

    def unlock(proc, secret: str, *, recovery=False, remember=False, wrong: str = "") -> str:
        """Types into the unlock window; returns the window's message after a wrong try ("" if none)."""
        dialog = win.wait_dialog(proc.pid, EDIT)
        said = ""
        if wrong:
            win.set_text(dialog, EDIT, wrong)
            win.press(dialog, IDOK)
            end = time.time() + 60
            while time.time() < end and "open" not in (said := win.text(dialog, STATUS)):
                time.sleep(0.3)
        if recovery:
            win.press(dialog, SWITCH)
            time.sleep(0.5)
        if remember:
            win.check(dialog, REMEMBER)
        win.set_text(dialog, EDIT, secret)
        win.press(dialog, IDOK)
        return said

    def asks(proc, timeout: float = 30) -> bool:
        """True when the start shows the unlock window, False when the browser starts without it."""
        end = time.time() + timeout
        while time.time() < end:
            if any(win.user32.GetDlgItem(h, EDIT) for h in win.dialogs(proc.pid)):
                return True
            if (user_data / "DevToolsActivePort").exists():
                return False
            time.sleep(0.2)
        raise RuntimeError("the browser neither asked nor started")

    def cookie_seen(s: Session) -> bool:
        return f"thoronportable={cookies.value}" in s.body(cookies.url("/get"))

    def lock_on_page(s: Session) -> str:
        s.go(PAGE_URL, 3)
        s.page(f"""document.getElementById('pass').value = {json.dumps(PASSPHRASE)};
                   document.getElementById('repeat').value = {json.dumps(PASSPHRASE)};
                   document.getElementById('with-recovery').checked = true;
                   document.getElementById('next').click();""")
        time.sleep(1.5)
        recovery = s.run("document.getElementById('recovery-key').textContent") or ""
        s.page(f"""document.getElementById('last-group').value = {json.dumps(recovery[-4:])};
                   document.getElementById('lock').click();""")
        s.wait_text("message", "locked with your passphrase")
        return recovery

    try:
        # lock
        session = Session(start(), user_data)
        session.body(cookies.url("/set"))
        before_lock = cookie_seen(session)
        recovery = lock_on_page(session)
        session.close()
        session = None
        state = local_state(user_data)
        found = [] if before_lock else ["lock: the cookie was not set before locking"]
        if len(recovery.replace("-", "")) != 32:
            found.append(f"lock: no recovery key shown ({recovery!r})")
        if not key_file.is_file():
            found.append("lock: no key file")
        if state.get("os_crypt", {}).get("encrypted_key"):
            found.append("lock: Local State still holds the key")
        if state.get("thoron_portable", {}).get("locked") is not True:
            found.append("lock: the copy is not marked as locked")
        if not cookie_encrypted(user_data, cookies.value):
            found.append("lock: the cookie is not in the database encrypted")
        report("lock", found, f"key file {key_file.stat().st_size if key_file.is_file() else 0} bytes")

        # quit
        before = key_file.read_bytes()
        proc = start()
        dialog = win.wait_dialog(proc.pid, EDIT)
        win.set_text(dialog, EDIT, "not the passphrase at all")
        win.press(dialog, IDOK)
        said = ""
        end = time.time() + 60
        while time.time() < end and "open" not in (said := win.text(dialog, STATUS)):
            time.sleep(0.3)
        win.press(dialog, IDCANCEL)
        try:
            code = proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            code = None
            proc.kill()
        found = [] if "does not open" in said else [f"quit: a wrong passphrase was answered {said!r}"]
        if code is None:
            found.append("quit: the browser did not end")
        if (user_data / "DevToolsActivePort").exists():
            found.append("quit: the browser started anyway")
        if key_file.read_bytes() != before:
            found.append("quit: the key file changed")
        report("quit", found, f"said {said!r}, exit {code}")

        # recovery
        proc = start()
        unlock(proc, recovery.replace("-", "").lower(), recovery=True)
        session = Session(proc, user_data)
        found = [] if cookie_seen(session) else ["recovery: the cookie is not readable"]
        session.close()
        session = None
        report("recovery", found, "opened with the recovery key")

        # remember
        proc = start()
        unlock(proc, PASSPHRASE, remember=True)
        session = Session(proc, user_data)
        session.close()
        proc = start()
        asked = asks(proc)
        if asked:
            unlock(proc, PASSPHRASE)
        session = Session(proc, user_data)
        found = [] if not asked else ["remember: the copy asked again on this PC"]
        if not cookie_seen(session):
            found.append("remember: the cookie is not readable")
        report("remember", found, "opened without the passphrase" if not asked else "asked")

        # forget
        session.go(PAGE_URL, 3)
        session.page("document.getElementById('forget-pc').click();")
        forgotten = session.wait_text("message", "forgotten")
        session.close()
        session = None
        proc = start()
        asked = asks(proc)
        if asked:
            unlock(proc, PASSPHRASE)
        session = Session(proc, user_data)
        found = [] if asked else ["forget: the next start did not ask for the passphrase"]
        if "forgotten" not in forgotten:
            found.append(f"forget: the page said {forgotten!r}")
        report("forget", found, forgotten)

        # change
        session.go(PAGE_URL, 3)
        session.page(f"""document.getElementById('current').value = {json.dumps(PASSPHRASE)};
                         document.getElementById('fresh').value = {json.dumps(NEW_PASSPHRASE)};
                         document.getElementById('fresh-repeat').value = {json.dumps(NEW_PASSPHRASE)};
                         document.getElementById('change').click();""")
        changed = session.wait_text("message", "changed")
        session.close()
        session = None
        proc = start()
        said = unlock(proc, NEW_PASSPHRASE, wrong=PASSPHRASE)
        session = Session(proc, user_data)
        found = [] if "changed" in changed else [f"change: the page said {changed!r}"]
        if "does not open" not in said:
            found.append(f"change: the old passphrase was answered {said!r}")
        if not cookie_seen(session):
            found.append("change: the cookie is not readable")
        session.close()
        session = None
        report("change", found, f"old passphrase: {said!r}")

        # tampered
        good = key_file.read_bytes()
        bad = bytearray(good)
        bad[30] ^= 0x01  # inside the passphrase lock's salt
        key_file.write_bytes(bytes(bad))
        proc = start()
        said = ""
        dialog = win.wait_dialog(proc.pid, EDIT)
        win.set_text(dialog, EDIT, NEW_PASSPHRASE)
        win.press(dialog, IDOK)
        end = time.time() + 60
        while time.time() < end and "open" not in (said := win.text(dialog, STATUS)):
            time.sleep(0.3)
        win.press(dialog, IDCANCEL)
        proc.wait(timeout=60)
        key_file.write_bytes(good)
        found = [] if "does not open" in said else [f"tampered: answered {said!r}"]
        report("tampered", found, f"said {said!r}")

        # remove
        proc = start()
        unlock(proc, NEW_PASSPHRASE)
        session = Session(proc, user_data)
        session.go(PAGE_URL, 3)
        session.page(f"""document.getElementById('check-pass').value = {json.dumps(NEW_PASSPHRASE)};
                         document.getElementById('remove').click();""")
        removed = session.wait_text("message", "removed")
        session.close()
        session = None
        state = local_state(user_data)
        found = [] if "removed" in removed else [f"remove: the page said {removed!r}"]
        if key_file.exists():
            found.append("remove: the key file is still there")
        if not state.get("os_crypt", {}).get("encrypted_key"):
            found.append("remove: Local State has no key")
        if state.get("thoron_portable", {}).get("locked") is not False:
            found.append("remove: the copy is still marked as locked")
        proc = start()
        if asks(proc):
            found.append("remove: the copy still asks for a passphrase")
            proc.kill()
        else:
            session = Session(proc, user_data)
            if not cookie_seen(session):
                found.append("remove: the cookie is not readable")
            session.close()
            session = None
        report("remove", found, removed)

        # missing
        session = Session(start(), user_data)
        lock_on_page(session)
        session.close()
        session = None
        key_file.unlink()
        proc = start()
        box = win.wait_dialog(proc.pid, IDNO)
        win.press(box, IDNO)
        proc.wait(timeout=60)
        still = local_state(user_data).get("thoron_portable", {}).get("locked") is True
        proc = start()
        box = win.wait_dialog(proc.pid, IDYES)
        win.press(box, IDYES)
        session = Session(proc, user_data)
        session.close()
        session = None
        found = [] if still else ["missing: No did not keep the copy marked as locked"]
        if local_state(user_data).get("thoron_portable", {}).get("locked") is not False:
            found.append("missing: Yes left the copy marked as locked")
        report("missing", found, "No quit, Yes started without")
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired,
            sqlite3.Error) as e:
        problems.append(f"the run failed: {e}")
    finally:
        if session is not None:
            try:
                session.close()
            except (OSError, RuntimeError):
                session.proc.kill()
        cookies.close()
        subprocess.run(["cmd", "/c", "rmdir", str(root / "App" / "v")], capture_output=True)
        shutil.rmtree(root, ignore_errors=True)
    return problems


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--browser", required=True, type=Path)
    p.add_argument("--work", required=True, type=Path, help="scratch folder for the test copy")
    a = p.parse_args(argv)
    sys.stdout.reconfigure(errors="backslashreplace")
    a.work.mkdir(parents=True, exist_ok=True)
    problems = run(a.browser.resolve(), a.work.resolve())
    for problem in problems:
        print(problem)
    print("PORTABLE PASSPHRASE CHECK: PASSED" if not problems
          else f"PORTABLE PASSPHRASE CHECK: FAILED ({len(problems)} problem(s))")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
