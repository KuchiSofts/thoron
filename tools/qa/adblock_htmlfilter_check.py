#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Native ad blocking, what uBlock Origin does to an answer before the page reads it (in Firefox; here in every
page), checked end to end and offline (ROADMAP P5.66).

HTML filtering (`site##^script:has-text(...)`) takes elements out of a page's HTML before it is parsed;
`site##^responseheader(refresh)` takes a header out of a page's answer; `||site^$replace=/a/b/` replaces a text in
an answer, a page's and a script's. My filters bring the rules (allowed to use what needs trust, which the last two
need). A local server serves the pages under names of their own (host-resolver rules; every other name fails, so
nothing leaves the PC). Steps:

    html      a script with the words a rule names does not run and is not in the page; the other one runs
    meta      a <meta http-equiv="refresh"> a rule names is taken out: the page stays
    header    a "Refresh" header a rule names is taken out: the page stays
    replace   a text in the page and in its script is replaced
    logger    the logger lists the HTML filter and the replacement that acted
    other     a page of another site keeps all of it
    except    #@#^ takes the HTML filter back on a site
    structure (P5.68) rules on the page's structure (`:upward()`, `:has()` in `:not()`, combinators): a script
              they name does not run where their conditions hold, and runs where they do not

    py -3 -I tools/qa/adblock_htmlfilter_check.py --browser <out>\\thoron.exe --work <scratch dir>
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

SITE = "filter-site.test"
OTHER = "other-site.test"
SPARED = "spared-site.test"
SETTINGS_URL = "chrome://adblock/"
SETTLE_S = 3.0
TITLE = "Thoron HTML filter check"
MY_FILTERS = (f"{SITE},{SPARED}##^script:has-text(thoron-detector)\n"
              f"{SITE}##^meta[http-equiv=\"refresh\"]\n"
              f"{SITE}##^responseheader(refresh)\n"
              f"||{SITE}^$replace=/thoronOldWord/thoronNewWord/g\n"
              f"{SPARED}#@#^script:has-text(thoron-detector)\n"
              f"{SITE}##^html > head > link[rel=\"canonical\"]:not([href*=\"/recipes/\"]):upward(1) > "
              "script:has-text(thoron-structure)\n"
              f"{SITE}##^body:not(:has(#player)) > script:has-text(thoron-gtm)\n")
PAGE = (f"<!doctype html><title>{TITLE}</title><link rel=\"canonical\" href=\"/news/1\">"
        "<script>window.structured = 'thoron-structure';</script>"
        "<script>window.detector = 'thoron-detector';</script>"
        "<script>window.kept = 'thoronOldWord';</script>"
        "<script src=\"/lib.js\"></script>"
        "<p id=\"word\">thoronOldWord</p><script>window.gtm = 'thoron-gtm';</script>")
# where the structure rules' conditions do not hold: a canonical address under /recipes/, a player
RECIPES = (f"<!doctype html><title>{TITLE} recipes</title><link rel=\"canonical\" href=\"/recipes/1\">"
           "<script>window.structured = 'thoron-structure';</script><div id=\"player\"></div>"
           "<script>window.gtm = 'thoron-gtm';</script>")
META_PAGE = f"<!doctype html><title>{TITLE} meta</title><meta http-equiv=\"refresh\" content=\"1;url=/gone.html\"><p>meta</p>"
LIB = "window.fromLib = 'thoronOldWord';"
READ = ("JSON.stringify({detector: window.detector || null, kept: window.kept || null, lib: window.fromLib || null,"
        " structured: window.structured || null, gtm: window.gtm || null,"
        " word: (document.getElementById('word') || {}).textContent || null,"
        " inPage: document.documentElement.outerHTML.includes('thoron-detector'), at: location.pathname})")


def html_problems(seen: dict) -> list[str]:
    out = []
    if seen.get("detector") is not None or seen.get("inPage"):
        out.append(f"html: the script the rule names ran or is in the page ({seen})")
    if seen.get("kept") is None:
        out.append(f"html: the other script did not run ({seen})")
    return out


def stay_problems(step: str, path: str, want: str) -> list[str]:
    return [] if path == want else [f"{step}: the page went to {path}, not stayed at {want}"]


def replace_problems(seen: dict) -> list[str]:
    want = "thoronNewWord"
    out = []
    for key in ("kept", "word", "lib"):
        if seen.get(key) != want:
            out.append(f"replace: {key} is {seen.get(key)!r}, not {want!r}")
    return out


def logger_problems(rows: list[str]) -> list[str]:
    out = []
    if "##^script:has-text(thoron-detector)" not in rows:
        out.append(f"logger: the HTML filter is not listed ({rows})")
    if not any(r.startswith("$replace=/thoronOldWord/") for r in rows):
        out.append(f"logger: the replacement is not listed ({rows})")
    return out


def structure_problems(here: dict, there: dict) -> list[str]:
    """`here`: the page the rules' conditions hold on; `there`: the one they do not."""
    out = []
    for key in ("structured", "gtm"):
        if here.get(key) is not None:
            out.append(f"structure: on the page the rules are for, {key} ran")
        if there.get(key) is None:
            out.append(f"structure: on the page whose structure is not theirs, {key} did not run")
    return out


def other_problems(step: str, seen: dict) -> list[str]:
    if seen.get("detector") != "thoron-detector" or seen.get("kept") != "thoronOldWord":
        return [f"{step}: the page was changed ({seen})"]
    return []


class Server:
    def __init__(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_GET(self):
                path = self.path.split("?")[0]
                headers = {}
                if path == "/lib.js":
                    body, ctype = LIB.encode(), "text/javascript"
                elif path == "/recipes.html":
                    body, ctype = RECIPES.encode(), "text/html; charset=utf-8"
                elif path == "/meta.html":
                    body, ctype = META_PAGE.encode(), "text/html; charset=utf-8"
                elif path == "/header.html":
                    body, ctype = f"<!doctype html><title>{TITLE} header</title><p>header</p>".encode(), "text/html"
                    headers["Refresh"] = "1;url=/gone.html"
                else:
                    body, ctype = PAGE.encode(), "text/html; charset=utf-8"
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                for name, value in headers.items():
                    self.send_header(name, value)
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


def _eval(ws: WebSocket, expression: str):
    reply = ws.call("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True)
    if "exceptionDetails" in reply:
        raise RuntimeError(reply["exceptionDetails"].get("text", "the page threw"))
    return reply.get("result", {}).get("value")


ASK = """(async () => {{ const {{sendWithPromise}} = await import('chrome://resources/js/cr.js');
  return JSON.stringify(await sendWithPromise({call})); }})()"""
LOG_ROWS = """(async () => { const {sendWithPromise} = await import('chrome://resources/js/cr.js');
  const tab = (await sendWithPromise('getLog')).find((t) => t.title === %s) || {entries: []};
  return JSON.stringify(tab.entries.filter((e) => e.type === 'cosmetic' || e.type === 'replace').map((e) => e.url));
})()""" % json.dumps(TITLE)


def run(browser: Path, work: Path) -> list[str]:
    problems: list[str] = []
    profile = Path(tempfile.mkdtemp(prefix="htmlfilter-", dir=work))

    def report(step: str, found: list[str], seen) -> None:
        print(f"{'PASS' if not found else 'FAIL'}  {step}: {seen}")
        problems.extend(found)

    with Server() as server:
        proc = _launch(browser, profile, server.port, [SITE, OTHER, SPARED], native=True)
        port = None
        try:
            port = _devtools_port(profile)
            settings = WebSocket(_open(port, SETTINGS_URL)["webSocketDebuggerUrl"])
            try:
                time.sleep(SETTLE_S)
                _eval(settings, ASK.format(call="'setTrustMyFilters', true"))
                time.sleep(2)
                _eval(settings, ASK.format(call=f"'setMyFilters', {json.dumps(MY_FILTERS)}"))
                time.sleep(SETTLE_S + 1)  # the rules are built in

                def visit(host: str, path: str = "/page.html", wait: float = SETTLE_S) -> dict:
                    page = WebSocket(_open(port, f"http://{host}{path}")["webSocketDebuggerUrl"])
                    try:
                        time.sleep(wait)
                        return json.loads(_eval(page, READ) or "{}")
                    finally:
                        page.close()

                seen = visit(SITE)
                report("html", html_problems(seen), seen)
                there = visit(SITE, "/recipes.html")
                report("structure", structure_problems(seen, there),
                       [{k: seen.get(k) for k in ("structured", "gtm")}, {k: there.get(k) for k in ("structured", "gtm")}])
                report("replace", replace_problems(seen), {k: seen.get(k) for k in ("kept", "word", "lib")})
                for step, path in (("meta", "/meta.html"), ("header", "/header.html")):
                    after = visit(SITE, path, wait=SETTLE_S + 1)
                    report(step, stay_problems(step, after.get("at", ""), path), after.get("at"))
                time.sleep(2)  # the logger asks every two seconds
                rows = json.loads(_eval(settings, LOG_ROWS) or "[]")
                report("logger", logger_problems(rows), rows)
                for step, host in (("other", OTHER), ("except", SPARED)):
                    seen = visit(host)
                    report(step, other_problems(step, seen), {k: seen.get(k) for k in ("detector", "kept")})
            finally:
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
    print("HTML FILTER CHECK: PASSED" if not problems else f"HTML FILTER CHECK: FAILED ({len(problems)} problem(s))")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
