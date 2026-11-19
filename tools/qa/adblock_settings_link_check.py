#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Thoron adblock in the side menu of chrome://settings, checked end to end and offline (ROADMAP P5.30).

The browser's own Settings lead to Thoron adblock's page as they lead to the extensions: an entry below
"Extensions" that opens chrome://adblock in a new tab. Steps:

    shown     with the built-in blocker on, the side menu has "Thoron adblock" with its icon, leading to
              chrome://adblock
    opens     a click on it opens chrome://adblock in a new tab
    hidden    with the built-in blocker off, the entry is not shown

    py -3 -I tools/qa/adblock_settings_link_check.py --browser <out>\\thoron.exe --work <scratch dir>
Exit status 0 only when every step passes.
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
from tools.qa.adblock_site_switch_check import _close_browser, _devtools_port, _open  # noqa: E402
from tools.qa.cdp import WebSocket  # noqa: E402

SETTINGS_URL = "chrome://settings/"
NAME = "Thoron adblock"
# The entry, found through every shadow root of the page: is it shown, its text, where it leads.
FIND = """(() => {
  const find = (root) => {
    const hit = root.querySelector('#thoronAdblockLink');
    if (hit) return hit;
    for (const el of root.querySelectorAll('*')) {
      if (el.shadowRoot) { const deep = find(el.shadowRoot); if (deep) return deep; }
    }
    return null;
  };
  const link = find(document);
  if (!link) return JSON.stringify(null);
  const box = link.getBoundingClientRect();
  return JSON.stringify({shown: !link.hidden && link.getClientRects().length > 0,
                         text: link.textContent.trim(), href: link.getAttribute('href'),
                         target: link.getAttribute('target'),
                         icon: !!link.querySelector('cr-icon')?.shadowRoot?.querySelector('svg path, svg g'),
                         x: Math.round(box.left + box.width / 2), y: Math.round(box.top + box.height / 2)});
})()"""


def shown_problems(found: dict | None) -> list[str]:
    if not found:
        return ["shown: the side menu has no Thoron adblock entry"]
    out = []
    if not found.get("shown"):
        out.append("shown: the entry is hidden while the blocker is on")
    if not found.get("icon"):
        out.append("shown: the entry's icon is not drawn")
    if found.get("text") != NAME:
        out.append(f"shown: the entry reads {found.get('text')!r}, not {NAME!r}")
    if found.get("href") != "chrome://adblock" or found.get("target") != "_blank":
        out.append(f"shown: the entry leads to {found.get('href')!r} ({found.get('target')!r}), "
                   "not chrome://adblock in a new tab")
    return out


def opens_problems(urls: list[str]) -> list[str]:
    if not any(u.startswith("chrome://adblock") for u in urls):
        return [f"opens: no chrome://adblock tab after the click ({urls})"]
    return []


def hidden_problems(found: dict | None) -> list[str]:
    if found and found.get("shown"):
        return ["hidden: the entry is shown while the blocker is off"]
    return []


def _launch(browser: Path, profile: Path, native: bool) -> subprocess.Popen:
    args = [str(browser), "--headless=new", f"--user-data-dir={profile}", "--no-first-run",
            "--no-default-browser-check", "--disable-default-apps", "--disable-background-networking",
            "--disable-component-update", "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
            # wide enough for Settings to show its side menu (a narrow window folds it away)
            "--window-size=1400,900",
            "--enable-features=ThoronNativeAdblock" if native else "--disable-features=ThoronNativeAdblock",
            "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0", "about:blank"]
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _eval(ws: WebSocket, expression: str):
    reply = ws.call("Runtime.evaluate", expression=expression, returnByValue=True)
    return json.loads(reply.get("result", {}).get("value") or "null")


def _tabs(port: int) -> list[str]:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=10) as answer:
        return [t.get("url", "") for t in json.load(answer) if t.get("type") == "page"]


def _session(browser: Path, work: Path, native: bool, steps) -> list[str]:
    profile = Path(tempfile.mkdtemp(prefix="settings-link-", dir=work))
    proc = _launch(browser, profile, native)
    port = None
    try:
        port = _devtools_port(profile)
        ws = WebSocket(_open(port, SETTINGS_URL)["webSocketDebuggerUrl"])
        time.sleep(3)
        try:
            return steps(ws, port)
        finally:
            ws.close()
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as e:
        return [f"the run failed: {e}"]
    finally:
        if port is not None:
            _close_browser(port, proc)
        else:
            bench._stop(proc, profile)
        shutil.rmtree(profile, ignore_errors=True)


def run(browser: Path, work: Path) -> list[str]:
    def on(ws, port):
        found = _eval(ws, FIND)
        problems = shown_problems(found)
        print(f"{'PASS' if not problems else 'FAIL'}  shown: {found}")
        if found:
            # a click of the mouse: a page's own click() opens no tab (no user gesture)
            for kind in ("mousePressed", "mouseReleased"):
                ws.call("Input.dispatchMouseEvent", type=kind, x=found["x"], y=found["y"], button="left",
                        clickCount=1)
        time.sleep(2)
        urls = _tabs(port)
        more = opens_problems(urls)
        print(f"{'PASS' if not more else 'FAIL'}  opens: {urls}")
        return problems + more

    def off(ws, port):
        found = _eval(ws, FIND)
        problems = hidden_problems(found)
        print(f"{'PASS' if not problems else 'FAIL'}  hidden: {found}")
        return problems

    return _session(browser, work, True, on) + _session(browser, work, False, off)


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--browser", required=True, type=Path)
    p.add_argument("--work", required=True, type=Path, help="scratch folder for the throwaway profile")
    a = p.parse_args(argv)
    a.work.mkdir(parents=True, exist_ok=True)
    problems = run(a.browser.resolve(), a.work)
    for problem in problems:
        print(problem)
    print("SETTINGS LINK CHECK: PASSED" if not problems else f"SETTINGS LINK CHECK: FAILED ({len(problems)} problem(s))")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
