#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Thoron adblock, a blocked request that the page's own scriptlet would answer, checked end to end and offline
(ROADMAP P5.72).

uBlock Origin's `prevent-xhr` (`no-xhr-if`) answers the requests it matches inside the page, with an empty
success, so the page never learns they were blocked. Google Docs needs that: its lists block Docs' `/logImpressions`
calls, and a page that meets the network's refusal instead keeps showing "Trying to connect". A page that started
without its scriptlets (Thoron adblock still loading at start, or off for a while) would meet that refusal; so the
network gives such a request the very answer the scriptlet would. A worker never gets scriptlets, so a worker's
request shows what the network does. A local server serves the test page under a name of its own (host-resolver
rules; every other name fails, so nothing leaves the PC); My filters block two of its addresses and hold one
`no-xhr-if` for the first. Steps:

    page     the page's own call to the first address: answered in the page (status 200, empty), never sent
    worker   a worker's call to it: answered by the network the same way (status 200, empty), never sent
    plain    a worker's call to the second address, which no scriptlet answers: refused (status 0), never sent

    py -3 -I tools/qa/adblock_fakes_check.py --browser <out>\\thoron.exe --work <scratch dir>
Exit status 0 only when every step passes.
"""
import argparse
import http.server
import json
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.qa import bench  # noqa: E402
from tools.qa.adblock_site_switch_check import _close_browser, _devtools_port, _open  # noqa: E402
from tools.qa.adblock_syntax_check import _launch  # noqa: E402
from tools.qa.cdp import WebSocket  # noqa: E402

PAGE_HOST = "fakes-check.test"
SETTINGS_URL = "chrome://adblock/"
BUILD_S = 5.0
SETTLE_S = 2.5
MY_FILTERS = (f"||{PAGE_HOST}/api/log^\n"
              f"||{PAGE_HOST}/api/plain^\n"
              f"{PAGE_HOST}##+js(no-xhr-if, method:POST url:/api/log)\n")
PAGE = "<!doctype html><title>Thoron fakes check</title><p>fakes</p>"
WORKER = ("onmessage = (e) => { const x = new XMLHttpRequest(); x.open('POST', e.data);"
          " x.onloadend = () => postMessage({status: x.status, text: x.responseText}); x.send('w=1'); };")
# the page's own call, then the worker's two
CALLS = """(async () => {
  const call = (url) => new Promise((done) => { const x = new XMLHttpRequest(); x.open('POST', url);
    x.onloadend = () => done({status: x.status, text: x.responseText}); x.send('p=1'); });
  const worker = new Worker('/worker.js');
  const inWorker = (url) => new Promise((done) => { worker.onmessage = (e) => done(e.data);
    worker.postMessage(url); });
  const out = {page: await call('/api/log?from=page'), worker: await inWorker('/api/log?from=worker'),
               plain: await inWorker('/api/plain?from=worker')};
  worker.terminate();
  return JSON.stringify(out);
})()"""
# what each step must get, and the address the server must never be asked for
WANT = {"page": (200, "/api/log?from=page"), "worker": (200, "/api/log?from=worker"),
        "plain": (0, "/api/plain?from=worker")}


def step_problems(seen: dict, asked: list[str]) -> list[str]:
    """`seen`: what each call got; `asked`: the addresses the server was asked for."""
    out = []
    for step, (status, path) in WANT.items():
        got = seen.get(step) or {}
        if got.get("status") != status or (status == 200 and got.get("text") != ""):
            out.append(f"{step}: got {got!r}, not status {status}" + (" with an empty answer" if status else ""))
        if path in asked:
            out.append(f"{step}: the request for {path} reached the server")
    return out


class Server:
    def __init__(self):
        self.asked: list[str] = []
        asked = self.asked

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def answer(self, body: str, kind: str) -> None:
                data = body.encode()
                self.send_response(200)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                asked.append(self.path)
                if self.path.startswith("/worker.js"):
                    self.answer(WORKER, "text/javascript")
                else:
                    self.answer(PAGE, "text/html; charset=utf-8")

            def do_POST(self):
                asked.append(self.path)
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                self.answer("real", "text/plain")

        self._httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._httpd.daemon_threads = True
        self.port = self._httpd.server_address[1]

    def __enter__(self):
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self._httpd.shutdown()
        self._httpd.server_close()


def _eval(ws: WebSocket, expression: str):
    reply = ws.call("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True)
    return reply.get("result", {}).get("value")


def run(browser: Path, work: Path) -> list[str]:
    profile = Path(tempfile.mkdtemp(prefix="fakes-", dir=work))
    problems: list[str] = []
    with Server() as server:
        proc = _launch(browser, profile, server.port, [PAGE_HOST], native=True)
        port = None
        settings = page = None
        try:
            port = _devtools_port(profile)
            settings = WebSocket(_open(port, SETTINGS_URL)["webSocketDebuggerUrl"])
            time.sleep(2)
            # typed, as a person would: the input event enables Save
            _eval(settings, f"(() => {{ const box = document.getElementById('my-filters');"
                            f" box.value = {json.dumps(MY_FILTERS)}; box.dispatchEvent(new Event('input'));"
                            " document.getElementById('save-filters').click(); return 1; })()")
            time.sleep(BUILD_S)
            page = WebSocket(_open(port, f"http://{PAGE_HOST}/page.html")["webSocketDebuggerUrl"])
            time.sleep(SETTLE_S)
            seen = json.loads(_eval(page, CALLS) or "{}")
            found = step_problems(seen, list(server.asked))
            for step in WANT:
                mine = [f for f in found if f.startswith(step + ":")]
                print(f"{'PASS' if not mine else 'FAIL'}  {step}: {seen.get(step)}")
            problems += found
        except (OSError, RuntimeError, ValueError, KeyError, TypeError) as e:
            problems.append(f"the run failed: {e}")
        finally:
            for ws in (settings, page):
                if ws:
                    try:
                        ws.close()
                    except OSError:
                        pass
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
    print("FAKES CHECK: PASSED" if not problems else f"FAKES CHECK: FAILED ({len(problems)} problem(s))")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
