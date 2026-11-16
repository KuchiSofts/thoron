#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Signed updates of Thoron adblock's scriptlets and stand-ins, checked end to end and offline (ROADMAP P5.23).

The scriptlets run inside every page, so a newer copy is only taken in when it is signed with Thoron's key and
newer than the copy in use (tools/release/adblock_resources.py makes such a file). Here a local server stands in
for the list servers and for the place updates come from (the browser accepts only loopback addresses for
that), and a key made for this run stands in for Thoron's (a switch the browser honours only then). The
update adds a scriptlet that marks the page; "My filters" ask for it on a test page. Steps:

    shipped     no update on offer: the scriptlet is unknown, the page is not marked
    forged      an update whose text was changed after signing: refused, nothing stored, page not marked
    updated     a signed, newer update: stored and in use at once, the page is marked "A"
    older       a signed update older than the one in use: refused, the page keeps "A"
    restart     the browser starts again: the stored copy is checked again and used, the page is marked "A"
    other-key   started with another key: the stored copy does not verify, the shipped copy is used
    no-key      started without a key (as every browser is until Thoron's key exists): the shipped copy is
                used, and the update is not even asked for

    py -3 -I tools/qa/adblock_resources_check.py --browser <out>\\thoron.exe --work <scratch dir>
Exit status 0 only when every step passes.
"""
import argparse
import base64
import http.server
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.qa import bench  # noqa: E402
from tools.qa.adblock_site_switch_check import _close_browser, _devtools_port, _open  # noqa: E402
from tools.qa.adblock_update_check import split_lists  # noqa: E402
from tools.qa.cdp import WebSocket  # noqa: E402
from tools.release import adblock_resources as ar  # noqa: E402

PAGE_HOST = "resources-check.test"
RESOURCES_PATH = "/lists/thoron_adblock_resources.signed"
SETTINGS_URL = "chrome://adblock/"
MY_FILTERS = f"{PAGE_HOST}##+js(thoron-resources-mark)\n"
MARK = "document.documentElement.getAttribute('data-thoron-resources')"
OLD, NEW = "2026120100", "2026120200"


def with_mark(shipped_json: str, mark: str) -> str:
    """The shipped resources and one more scriptlet, which marks the page with `mark`."""
    items = json.loads(shipped_json)
    code = f"function thoronResourcesMark() {{ document.documentElement.setAttribute('data-thoron-resources', '{mark}'); }}"
    items.append({"name": "thoron-resources-mark.js", "aliases": [], "kind": {"mime": "application/javascript"},
                  "content": base64.b64encode(code.encode()).decode("ascii")})
    return json.dumps(items)


def forge(signed: str) -> str:
    """The same file with its scriptlet changed after it was signed."""
    head, body = signed.split("\n\n", 1)
    items = json.loads(body)
    items[-1]["content"] = base64.b64encode(b"function thoronResourcesMark() { document.title = 'forged'; }").decode()
    return head + "\n\n" + json.dumps(items)


class Server:
    def __init__(self, lists: dict[str, str]):
        self.lists = lists
        self.resources: str | None = None
        self.resource_requests = 0
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def _send(self, code: int, kind: str, body: bytes):
                self.send_response(code)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                path = urllib.parse.urlsplit(self.path).path
                if path == RESOURCES_PATH:
                    server.resource_requests += 1
                    if server.resources is None:
                        self._send(404, "text/plain", b"not found")
                    else:
                        self._send(200, "text/plain; charset=utf-8", server.resources.encode("utf-8"))
                elif path.startswith("/lists/") and path.endswith(".txt") and path[7:-4] in server.lists:
                    self._send(200, "text/plain; charset=utf-8", server.lists[path[7:-4]].encode("utf-8"))
                elif path == "/page.html":
                    self._send(200, "text/html; charset=utf-8", b"<!doctype html><title>resources</title><p>page")
                else:
                    self._send(404, "text/plain", b"not found")

        self._httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._httpd.daemon_threads = True
        self.port = self._httpd.server_address[1]

    def __enter__(self):
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self._httpd.shutdown()
        self._httpd.server_close()


def stored_serial(profile: Path) -> str | None:
    """The serial of the update the profile keeps, if any."""
    found = profile / "Thoron Adblock" / "resources.signed"
    if not found.exists():
        return None
    lines = found.read_text(encoding="utf-8").split("\n", 2)
    return lines[1].removeprefix("serial: ") if len(lines) > 1 else None


def step_problems(step: str, mark: str | None, want_mark: str | None, stored: str | None,
                  want_stored: str | None) -> list[str]:
    out = []
    if mark != want_mark:
        out.append(f"{step}: the page is marked {mark!r}, not {want_mark!r}")
    if stored != want_stored:
        out.append(f"{step}: the stored update is {stored!r}, not {want_stored!r}")
    return out


def _launch(browser: Path, profile: Path, port: int, key: bytes | None) -> subprocess.Popen:
    args = [str(browser), "--headless=new", f"--user-data-dir={profile}", "--no-first-run",
            "--no-default-browser-check", "--disable-default-apps", "--disable-background-networking",
            "--disable-component-update", "--enable-features=ThoronNativeAdblock",
            f"--thoron-adblock-lists-url-for-testing=http://127.0.0.1:{port}/lists/",
            f"--host-resolver-rules=MAP {PAGE_HOST} 127.0.0.1:{port}, MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
            "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0", "about:blank"]
    if key is not None:
        args.insert(-1, f"--thoron-adblock-resources-key-for-testing={base64.b64encode(key).decode('ascii')}")
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _eval(ws: WebSocket, expression: str):
    reply = ws.call("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True)
    return reply.get("result", {}).get("value")


class Session:
    """One start of the browser on the profile, with chrome://adblock and the test page open."""

    def __init__(self, browser: Path, profile: Path, port: int, key: bytes | None):
        # the port file of the run before would point at a browser that is gone
        (profile / "DevToolsActivePort").unlink(missing_ok=True)
        self.proc = _launch(browser, profile, port, key)
        self.profile = profile
        self.port = _devtools_port(profile)
        self.settings = WebSocket(_open(self.port, SETTINGS_URL)["webSocketDebuggerUrl"])
        time.sleep(3)

    def call(self, name: str, *args) -> str:
        return _eval(self.settings, "import('chrome://resources/js/cr.js').then((cr) => cr.sendWithPromise("
                     + ", ".join(json.dumps(a) for a in (name, *args)) + "))")

    def mark(self) -> str | None:
        page = WebSocket(_open(self.port, f"http://{PAGE_HOST}/page.html")["webSocketDebuggerUrl"])
        try:
            time.sleep(1.5)
            return _eval(page, MARK)
        finally:
            page.close()

    def close(self) -> None:
        try:
            self.settings.close()
        except OSError:
            pass
        _close_browser(self.port, self.proc)


def run(browser: Path, work: Path) -> list[str]:
    bundled_dir = browser.parent
    lists = split_lists((bundled_dir / "thoron_adblock_lists.txt").read_text(encoding="utf-8"))
    shipped = (bundled_dir / "thoron_adblock_resources.json").read_text(encoding="utf-8")
    private, public = ar.keygen()
    _, other_public = ar.keygen()
    signed_new = ar.sign(with_mark(shipped, "A"), NEW, private)
    signed_old = ar.sign(with_mark(shipped, "B"), OLD, private)
    profile = Path(tempfile.mkdtemp(prefix="resources-", dir=work))
    problems: list[str] = []

    def report(step: str, found: list[str], detail: str) -> None:
        print(f"{'PASS' if not found else 'FAIL'}  {step}: {detail}")
        problems.extend(found)

    with Server(lists) as server:
        session = None
        try:
            session = Session(browser, profile, server.port, public)
            session.call("setMyFilters", MY_FILTERS)
            time.sleep(1)
            session.call("updateNow")
            mark = session.mark()
            report("shipped", step_problems("shipped", mark, None, stored_serial(profile), None), f"mark {mark!r}")

            server.resources = forge(signed_new)
            session.call("updateNow")
            mark = session.mark()
            report("forged", step_problems("forged", mark, None, stored_serial(profile), None)
                   + ([] if server.resource_requests else ["forged: the update was never asked for"]),
                   f"mark {mark!r}, asked {server.resource_requests} time(s)")

            server.resources = signed_new
            session.call("updateNow")
            mark = session.mark()
            report("updated", step_problems("updated", mark, "A", stored_serial(profile), NEW), f"mark {mark!r}")

            server.resources = signed_old
            session.call("updateNow")
            mark = session.mark()
            report("older", step_problems("older", mark, "A", stored_serial(profile), NEW), f"mark {mark!r}")
            session.close()

            server.resources = None
            session = Session(browser, profile, server.port, public)
            mark = session.mark()
            report("restart", step_problems("restart", mark, "A", stored_serial(profile), NEW), f"mark {mark!r}")
            session.close()

            session = Session(browser, profile, server.port, other_public)
            mark = session.mark()
            report("other-key", step_problems("other-key", mark, None, stored_serial(profile), NEW),
                   f"mark {mark!r}")
            session.close()

            server.resources = signed_new
            asked = server.resource_requests
            session = Session(browser, profile, server.port, None)
            session.call("updateNow")
            mark = session.mark()
            found = step_problems("no-key", mark, None, stored_serial(profile), NEW)
            if server.resource_requests != asked:
                found.append("no-key: the update was asked for without a key")
            report("no-key", found, f"mark {mark!r}, asked {server.resource_requests - asked} time(s)")
            session.close()
            session = None
        except (OSError, RuntimeError, ValueError, KeyError, TypeError) as e:
            problems.append(f"the run failed: {e}")
        finally:
            if session is not None:
                try:
                    session.close()
                except (OSError, RuntimeError):
                    bench._stop(session.proc, profile)
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
    print("RESOURCES CHECK: PASSED" if not problems else f"RESOURCES CHECK: FAILED ({len(problems)} problem(s))")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
