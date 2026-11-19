#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Does a site crash the browser's page (ROADMAP P5.6: upstream #1288, "STATUS_ACCESS_VIOLATION" on Discord)?

Opens each address in a real window on the screen with a throwaway profile, signed in nowhere, and watches the
page for a while through DevTools: a crashed renderer ("Aw, Snap!", STATUS_ACCESS_VIOLATION and its kind) then
answers every DevTools command with "Target crashed", which is counted. Online: the sites are really visited,
nothing is typed or sent.
    py -3 -I tools/qa/site_crash_check.py --browser <out>\\thoron.exe --work <scratch dir>
        [--url https://discord.com/login --url https://discord.com/app] [--seconds 60]
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.qa import bench  # noqa: E402
from tools.qa.adblock_site_switch_check import _close_browser, _devtools_port  # noqa: E402
from tools.qa.cdp import WebSocket  # noqa: E402

DEFAULT_URLS = ("https://discord.com/", "https://discord.com/login", "https://discord.com/app")


def crashed_in_error(message: str) -> bool:
    """Whether DevTools' answer says the page crashed (a crashed renderer answers every command so)."""
    return "crash" in message.lower()


def one(browser: Path, url: str, seconds: float, work: Path) -> dict:
    profile = Path(tempfile.mkdtemp(prefix="site-", dir=work))
    proc = subprocess.Popen([str(browser), f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
                             "--window-position=40,40", "--window-size=1200,850", "--remote-debugging-port=0",
                             "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    port = None
    try:
        port = _devtools_port(profile)
        listing = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=10).read())
        ws = WebSocket(next(t for t in listing if t.get("type") == "page")["webSocketDebuggerUrl"])
        crashed = False
        title = ""
        try:
            ws.call("Page.enable")
            ws.call("Page.navigate", url=url)
            end = time.monotonic() + seconds
            while time.monotonic() < end and not crashed:
                time.sleep(3)
                try:
                    got = ws.call("Runtime.evaluate", expression="document.title + ' | ' + location.href",
                                  returnByValue=True)
                    title = got.get("result", {}).get("value") or title
                except RuntimeError as exc:          # "Target crashed"; anything else is a page being replaced
                    crashed = crashed_in_error(str(exc))
                except (ConnectionError, OSError):   # the page's connection went with it
                    crashed = True
        finally:
            ws.close()
        return {"url": url, "crashed": crashed, "title": title[:120]}
    finally:
        if port is not None:
            _close_browser(port, proc)
        else:
            bench._stop(proc, profile)
        shutil.rmtree(profile, ignore_errors=True)


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--browser", type=Path, required=True)
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--url", action="append")
    p.add_argument("--seconds", type=float, default=60)
    a = p.parse_args(argv)
    a.work.mkdir(parents=True, exist_ok=True)
    results = [one(a.browser, url, a.seconds, a.work) for url in (a.url or DEFAULT_URLS)]
    for r in results:
        print(f"{'CRASHED' if r['crashed'] else 'ok'}  {r['url']}: {r['title']}")
    bad = [r for r in results if r["crashed"]]
    print(f"SITE CRASH CHECK: {'PASSED' if not bad else f'FAILED ({len(bad)} crash(es))'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
