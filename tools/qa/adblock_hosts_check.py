#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Thoron adblock, lines that only name a host: the host is stopped, checked end to end and offline (ROADMAP S.14).

Lists of harmful sites are often written as plain host names ("bad.example"), or as a hosts file
("0.0.0.0 bad.example"). uBlock Origin reads such a line as the rule for that whole host; a parser of filter
rules alone takes it for a piece of text, which never stops a page. Here three such lines are typed into "My
filters"; a local server answers for every name used (host-resolver rules; every other name fails, so nothing
leaves the PC) and writes down which hosts were asked. Steps:

    before    without the lines every page opens
    stopped   the page of a host named plainly and the page of a host named as in a hosts file are not opened
              (the blocked page names the site, the server is not asked), also under another name of the host
    others    a page that only mentions such a host in its address opens, and so does the page of another host

    py -3 -I tools/qa/adblock_hosts_check.py --browser <out>\\thoron.exe --work <scratch dir>
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

PLAIN, HOSTS_FILE, OTHER = "plain-line.test", "hosts-line.test", "other-site.test"
LINES = f"{PLAIN}\n0.0.0.0 {HOSTS_FILE}\n127.0.0.1 localhost.localdomain\n"
BLOCKED_TITLE = "Thoron blocked this page"
SETTLE_S = 2.5
# name -> (address, whether the lines stop it)
PAGES = {"plain": (f"http://{PLAIN}/page", True), "plain-www": (f"http://www.{PLAIN}/", True),
         "hosts-file": (f"http://{HOSTS_FILE}/", True), "mention": (f"http://{OTHER}/?next={PLAIN}", False),
         "other": (f"http://{OTHER}/page", False)}
READ = "JSON.stringify({title: document.title, text: document.body ? document.body.innerText : ''})"


def before_problems(seen: dict) -> list[str]:
    return [f"before: {name} did not open without the lines ({seen[name].get('title')!r})"
            for name in PAGES if seen[name].get("title") != "a page"]


def stopped_problems(seen: dict, asked: list[str]) -> list[str]:
    out = []
    for name, (address, stopped) in PAGES.items():
        if not stopped:
            continue
        host = address.split("/")[2]
        if seen[name].get("title") != BLOCKED_TITLE:
            out.append(f"stopped: {address} was opened ({seen[name].get('title')!r})")
        elif host.removeprefix("www.") not in seen[name].get("text", ""):
            out.append(f"stopped: the blocked page for {address} does not name the site")
        if host in asked:
            out.append(f"stopped: {host} was asked although its page is blocked")
    return out


def others_problems(seen: dict) -> list[str]:
    return [f"others: {PAGES[name][0]} was not opened ({seen[name].get('title')!r})"
            for name, (_, stopped) in PAGES.items() if not stopped and seen[name].get("title") != "a page"]


class Server:
    """Answers for every name with a small page and writes down the hosts that were asked."""

    def __enter__(self):
        asked = self.asked = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                asked.append((self.headers.get("Host") or "").split(":")[0])
                body = b"<!doctype html><title>a page</title><p>a page"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
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


def _visit_all(port: int) -> dict:
    seen = {}
    for name, (address, _) in PAGES.items():
        ws = WebSocket(_open(port, "about:blank")["webSocketDebuggerUrl"])
        try:
            ws.call("Page.navigate", url=address)
            time.sleep(SETTLE_S)
            reply = ws.call("Runtime.evaluate", expression=READ, returnByValue=True)
            seen[name] = json.loads(reply.get("result", {}).get("value") or "{}")
        finally:
            ws.close()
    return seen


def _type_lines(port: int) -> None:
    ws = WebSocket(_open(port, "chrome://adblock/#mine")["webSocketDebuggerUrl"])
    try:
        time.sleep(4)
        ws.call("Runtime.evaluate", expression=f"const b = document.getElementById('my-filters'); b.value = "
                f"{json.dumps(LINES)}; b.dispatchEvent(new Event('input')); "
                "document.getElementById('save-filters').click(); 1")
        time.sleep(5)  # the engine is built again with them
    finally:
        ws.close()


def run(browser: Path, work: Path) -> list[str]:
    profile = Path(tempfile.mkdtemp(prefix="hosts-lines-", dir=work))
    problems: list[str] = []

    def step(name: str, found: list[str], seen: dict) -> None:
        print(f"{'PASS' if not found else 'FAIL'}  {name}: {({n: s.get('title') for n, s in seen.items()})}")
        problems.extend(found)

    with Server() as server:
        names = sorted({address.split("/")[2] for address, _ in PAGES.values()})
        rules = ", ".join(f"MAP {name} 127.0.0.1:{server.port}" for name in names)
        proc = subprocess.Popen(
            [str(browser), "--headless=new", f"--user-data-dir={profile}", "--no-first-run",
             "--no-default-browser-check", "--disable-background-networking", "--disable-component-update",
             "--enable-features=ThoronNativeAdblock",
             f"--host-resolver-rules={rules}, MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
             "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        port = None
        try:
            port = _devtools_port(profile)
            time.sleep(4)
            seen = _visit_all(port)
            step("before", before_problems(seen), seen)
            _type_lines(port)
            server.asked.clear()
            seen = _visit_all(port)
            step("stopped", stopped_problems(seen, list(server.asked)), seen)
            step("others", others_problems(seen), seen)
        except (OSError, RuntimeError, ValueError, KeyError, TypeError) as e:
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
    a.work.mkdir(parents=True, exist_ok=True)
    problems = run(a.browser.resolve(), a.work)
    for problem in problems:
        print(problem)
    print("HOSTS CHECK: PASSED" if not problems else f"HOSTS CHECK: FAILED ({len(problems)} problem(s))")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
