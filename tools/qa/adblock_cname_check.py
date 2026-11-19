#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Thoron adblock's CNAME uncloaking, checked end to end and offline (ROADMAP P5.18).

A tracker can hide under a site's own name: in DNS, metrics.news.example is a name for the tracker's host, so
a rule for the tracker never sees it. The network tells the browser a host's canonical names with each answer;
Thoron adblock holds them against the lists, as uBlock Origin does on Firefox. Here a local server answers for
every name (host-resolver rules; nothing leaves the PC), and a switch the browser only accepts for answers from
127.0.0.1 gives the canonical names DNS would. "My filters" name the tracker. Steps:

    hidden    an image from a host whose canonical name is the tracker is blocked (its first request reaches
              the server: the name comes with the answer)
    learned   the next request to that host is blocked before it leaves: the server never sees it
    kept      a canonical name no list names, one of the site's own (uBlock Origin's cnameIgnore1stParty) and a
              host an exception rule allows (cnameIgnoreExceptions) all load
    off       with "Uncloak canonical names" off, the hidden tracker loads again (and on again afterwards)
    cost      what the look at a canonical name adds: images from a host with one (checked, let through)
              against images from a host without, taken in turns; the middle times may differ by 15 ms at most

    py -3 -I tools/qa/adblock_cname_check.py --browser <out>\\thoron.exe --work <scratch dir>
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
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.qa import bench  # noqa: E402
from tools.qa.adblock_site_switch_check import _close_browser, _devtools_port, _open  # noqa: E402
from tools.qa.adblock_syntax_check import NO_HTTPS_FIRST  # noqa: E402
from tools.qa.cdp import WebSocket  # noqa: E402

SITE = "example.com"
PAGE = f"news.{SITE}"
TRACKER = "tracker.example.net"
# each host the page loads an image from, and its canonical name (what DNS would say)
ALIASES = {
    f"metrics.{SITE}": TRACKER,               # a tracker under the site's own name
    f"static.{SITE}": f"{SITE}.edge.example.org",  # a content network no list names
    f"img.{SITE}": f"ads.{SITE}",             # one of the site's own names (listed, but first-party)
    f"spared.{SITE}": TRACKER,                # the tracker, but an exception allows the host
}
MY_FILTERS = f"||{TRACKER}^\n||ads.{SITE}^\n@@||spared.{SITE}^\n"
# a host with no canonical name, for the cost step, and how many images of each host it takes
PLAIN = f"plain.{SITE}"
COST_ROUNDS = 30
COST_MOST_MS = 15.0
SETTINGS_URL = "chrome://adblock/"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


class Server:
    """Answers every name: a page for the page's host, a small image for the rest; remembers what was asked."""

    def __init__(self):
        self.seen: list[str] = []
        seen = self.seen

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_GET(self):
                host = (self.headers.get("Host") or "").split(":")[0]
                seen.append(f"{host}{self.path}")
                if host == PAGE:
                    body, kind = b"<!doctype html><title>cname check</title><p>page</p>", "text/html"
                else:
                    body, kind = PNG, "image/png"
                self.send_response(200)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

        self._httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._httpd.daemon_threads = True
        self.port = self._httpd.server_address[1]

    def __enter__(self):
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self._httpd.shutdown()
        self._httpd.server_close()


def load_images(paths: dict[str, str]) -> str:
    """What the page runs: each image loaded one after the other; "loaded" or "blocked" for each."""
    return ("(async () => { const out = {}; for (const [id, url] of Object.entries(%s)) {"
            " out[id] = await new Promise((done) => { const i = new Image();"
            " i.onload = () => done('loaded'); i.onerror = () => done('blocked'); i.src = url; }); }"
            " return JSON.stringify(out); })()" % json.dumps(paths))


def timed_images(named: str, plain: str, rounds: int) -> str:
    """What the page runs for the cost step: an image of each host in turn, each a new address; the time each
    took, in ms."""
    return ("(async () => { const out = {named: [], plain: []};"
            " const one = (url) => new Promise((done) => { const t = performance.now(); const i = new Image();"
            " i.onload = i.onerror = () => done(performance.now() - t); i.src = url; });"
            f" for (let n = 0; n < {rounds}; n++) {{"
            f" out.named.push(await one('http://{named}/c' + n + '.png'));"
            f" out.plain.push(await one('http://{plain}/c' + n + '.png')); }}"
            " return JSON.stringify(out); })()")


def middle(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    return 0.0 if not n else (ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) / 2)


def cost_problems(times: dict) -> list[str]:
    if not times.get("named") or not times.get("plain"):
        return ["cost: no times"]
    named, plain = middle(times["named"]), middle(times["plain"])
    if named - plain > COST_MOST_MS:
        return [f"cost: an answer with a canonical name took {named:.1f} ms, one without {plain:.1f} ms"]
    return []


def hidden_problems(got: dict, seen: list[str]) -> list[str]:
    out = []
    if got.get("metrics") != "blocked":
        out.append(f"hidden: the tracker under the site's name {got.get('metrics')}, not blocked")
    if f"metrics.{SITE}/p1.png" not in seen:
        out.append("hidden: its first request did not reach the server (it should: the name comes with the answer)")
    return out


def learned_problems(got: dict, seen: list[str]) -> list[str]:
    out = []
    if got.get("again") != "blocked":
        out.append(f"learned: the next request to the host {got.get('again')}, not blocked")
    if f"metrics.{SITE}/p2.png" in seen:
        out.append("learned: the next request to the host left the browser")
    return out


def kept_problems(got: dict) -> list[str]:
    return [f"kept: {name} {got.get(name)}, not loaded" for name in ("static", "img", "spared")
            if got.get(name) != "loaded"]


def off_problems(off: dict, on: dict) -> list[str]:
    out = []
    if off.get("metrics") != "loaded":
        out.append(f"off: with uncloaking off the hidden tracker {off.get('metrics')}, not loaded")
    if on.get("metrics") != "blocked":
        out.append(f"off: on again, the hidden tracker {on.get('metrics')}, not blocked")
    return out


def _launch(browser: Path, profile: Path, port: int) -> subprocess.Popen:
    names = [PAGE, *ALIASES, PLAIN]
    mapping = ", ".join(f"MAP {name} 127.0.0.1:{port}" for name in names)
    cname = ",".join(f"{host}={alias}" for host, alias in ALIASES.items())
    args = [str(browser), "--headless=new", f"--user-data-dir={profile}", "--no-first-run",
            "--no-default-browser-check", "--disable-default-apps", "--disable-background-networking",
            "--disable-component-update", f"--disable-features={NO_HTTPS_FIRST}",
            "--enable-features=ThoronNativeAdblock",
            f"--host-resolver-rules={mapping}, MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
            f"--thoron-adblock-cname-for-testing={cname}",
            "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0", "about:blank"]
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _eval(ws: WebSocket, expression: str):
    reply = ws.call("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True)
    return reply.get("result", {}).get("value")


def run(browser: Path, work: Path) -> list[str]:
    profile = Path(tempfile.mkdtemp(prefix="cname-", dir=work))
    problems: list[str] = []
    with Server() as server:
        proc = _launch(browser, profile, server.port)
        port = None
        try:
            port = _devtools_port(profile)
            settings = WebSocket(_open(port, SETTINGS_URL)["webSocketDebuggerUrl"])
            time.sleep(3)

            def setting(call: str, *args) -> None:
                _eval(settings, "import('chrome://resources/js/cr.js').then((cr) => cr.sendWithPromise("
                      + ", ".join(json.dumps(a) for a in (call, *args)) + ")).then(() => 'done')")
                time.sleep(1)

            setting("setMyFilters", MY_FILTERS)
            page = WebSocket(_open(port, f"http://{PAGE}/")["webSocketDebuggerUrl"])
            time.sleep(2)

            def images(paths: dict[str, str]) -> dict:
                return json.loads(_eval(page, load_images(paths)) or "{}")

            def report(name: str, found: list[str], detail) -> None:
                print(f"{'PASS' if not found else 'FAIL'}  {name}: {detail}")
                problems.extend(found)

            first = images({"metrics": f"http://metrics.{SITE}/p1.png"})
            report("hidden", hidden_problems(first, list(server.seen)), first)
            again = images({"again": f"http://metrics.{SITE}/p2.png"})
            report("learned", learned_problems(again, list(server.seen)), again)
            kept = images({"static": f"http://static.{SITE}/s.png", "img": f"http://img.{SITE}/i.png",
                           "spared": f"http://spared.{SITE}/t.png"})
            report("kept", kept_problems(kept), kept)
            setting("setSetting", "cname-uncloak", False)
            off = images({"metrics": f"http://metrics.{SITE}/p3.png"})
            setting("setSetting", "cname-uncloak", True)
            on = images({"metrics": f"http://metrics.{SITE}/p4.png"})
            report("off", off_problems(off, on), {"off": off, "on": on})
            times = json.loads(_eval(page, timed_images(f"static.{SITE}", PLAIN, COST_ROUNDS)) or "{}")
            report("cost", cost_problems(times), f"middle {middle(times.get('named', [])):.1f} ms with a "
                   f"canonical name, {middle(times.get('plain', [])):.1f} ms without")
            page.close()
            settings.close()
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
    print("CNAME CHECK: PASSED" if not problems else f"CNAME CHECK: FAILED ({len(problems)} problem(s))")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
