#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Sign-ins survive restarts and updates: cookies and site storage, checked end to end and offline (ROADMAP P5.9).

Upstream reports random logouts and lost sessions. A sign-in is a cookie the site set to last, so this is what
is checked: a local site (a made-up name that the browser is told is 127.0.0.1; every other name fails, so
nothing leaves the PC) sets a cookie that lasts a year, a cookie for the session only, and an item of local
storage. The cookies are kept encrypted by the browser, so a key that is lost or changed shows here as a
logout. Steps, all on one throwaway profile:

    set       the older build opens the site, which sets the three
    restart   the older build starts again: the lasting cookie and the storage are there; the session cookie
              is gone, as a browser closed and opened again ends its session
    update    the newer build opens the same profile, as after an update: the lasting cookie and the storage
              are there, read back as they were written
    again     the newer build starts once more: still there

    py -3 -I tools/qa/cookie_persistence_check.py --older <older thoron.exe> --newer <newer thoron.exe>
        --work <scratch dir>
Exit status 0 only when every step passes.
"""
import argparse
import http.server
import json
import shutil
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

HOST = "signin.test"
LASTING = "keep=made-up-session-7f3a"
SESSION = "only=this-session"
STORED = ("account", "made-up-user")
PAGE = "<!doctype html><title>site</title><p>site"
READ = (f"JSON.stringify({{cookie: document.cookie, stored: localStorage.getItem({json.dumps(STORED[0])})}})")


class Site:
    """Sets the cookies at /set; at /read it answers with the cookies the browser sent."""

    def __enter__(self):
        sent = self.sent = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                sent.append(self.headers.get("Cookie") or "")
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                if self.path.startswith("/set"):
                    self.send_header("Set-Cookie", f"{LASTING}; Max-Age=31536000; Path=/; SameSite=Lax")
                    self.send_header("Set-Cookie", f"{SESSION}; Path=/; SameSite=Lax")
                body = PAGE.encode()
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


def kept_problems(step: str, seen: dict, sent: str, session_wanted: bool) -> list[str]:
    out = []
    if LASTING not in sent or LASTING not in (seen.get("cookie") or ""):
        out.append(f"{step}: the lasting cookie is gone (sent {sent!r}): a sign-in would be lost")
    if seen.get("stored") != STORED[1]:
        out.append(f"{step}: the site's storage holds {seen.get('stored')!r}, not {STORED[1]!r}")
    if not session_wanted and SESSION in sent:
        out.append(f"{step}: the session cookie outlived the session")
    if session_wanted and SESSION not in sent:
        out.append(f"{step}: the session cookie is missing while the session lasts")
    return out


def _visit(browser: Path, profile: Path, port: int, path: str, store: bool, site: Site) -> tuple[dict, str]:
    (profile / "DevToolsActivePort").unlink(missing_ok=True)
    proc = subprocess.Popen(
        [str(browser), "--headless=new", f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
         "--disable-background-networking", "--disable-component-update",
         f"--host-resolver-rules=MAP {HOST} 127.0.0.1:{port}, MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
         "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    devtools = None
    try:
        devtools = _devtools_port(profile)
        ws = WebSocket(_open(devtools, "about:blank")["webSocketDebuggerUrl"])
        try:
            site.sent.clear()
            ws.call("Page.navigate", url=f"http://{HOST}{path}")
            time.sleep(2.5)
            if store:
                ws.call("Runtime.evaluate",
                        expression=f"localStorage.setItem({json.dumps(STORED[0])}, {json.dumps(STORED[1])}); 1")
                # what the session cookie looks like while the session lasts
                ws.call("Page.navigate", url=f"http://{HOST}/read")
                time.sleep(2)
            seen = json.loads(ws.call("Runtime.evaluate", expression=READ, returnByValue=True)
                              ["result"].get("value") or "{}")
        finally:
            ws.close()
        sent = site.sent[-1] if site.sent else ""
        time.sleep(1.5)   # cookies are written to disk a moment after they change
        return seen, sent
    finally:
        if devtools is not None:
            _close_browser(devtools, proc)
        else:
            bench._stop(proc, profile)


def run(older: Path, newer: Path, work: Path) -> list[str]:
    profile = Path(tempfile.mkdtemp(prefix="cookies-", dir=work))
    problems: list[str] = []

    def step(name: str, found: list[str], seen: dict) -> None:
        print(f"{'PASS' if not found else 'FAIL'}  {name}: storage {seen.get('stored')!r}, "
              f"{len((seen.get('cookie') or '').split(';')) if seen.get('cookie') else 0} cookie(s) visible")
        problems.extend(found)

    try:
        with Site() as site:
            seen, sent = _visit(older, profile, site.port, "/set", True, site)
            step("set", kept_problems("set", seen, sent, session_wanted=True), seen)
            seen, sent = _visit(older, profile, site.port, "/read", False, site)
            step("restart", kept_problems("restart", seen, sent, session_wanted=False), seen)
            seen, sent = _visit(newer, profile, site.port, "/read", False, site)
            step("update", kept_problems("update", seen, sent, session_wanted=False), seen)
            seen, sent = _visit(newer, profile, site.port, "/read", False, site)
            step("again", kept_problems("again", seen, sent, session_wanted=False), seen)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as e:
        problems.append(f"the run failed: {e}")
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    return problems


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--older", required=True, type=Path, help="the build before the update")
    p.add_argument("--newer", required=True, type=Path, help="the build after it (the same one is allowed)")
    p.add_argument("--work", required=True, type=Path)
    a = p.parse_args(argv)
    a.work.mkdir(parents=True, exist_ok=True)
    problems = run(a.older.resolve(), a.newer.resolve(), a.work)
    for problem in problems:
        print(problem)
    print("COOKIE CHECK: PASSED" if not problems else f"COOKIE CHECK: FAILED ({len(problems)} problem(s))")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
