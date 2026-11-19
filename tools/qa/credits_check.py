#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""chrome://credits lists what Thoron is built from, checked offline (ROADMAP P2.5).

Chromium's credits page lists its own third-party code. Thoron adds what it is built from besides that:
Thorium, uBlock Origin's scriptlets and resources, the filter lists it ships, the patch sources, and the
ad-blocking engine (adblock-rust). The page is made at build time from the third-party folders the browser
depends on, so an entry is missing when its folder is not one of them. Steps:

    listed    each entry is on the page, with a licence text of its own
    texts     Thorium's entry carries the BSD licence with its copyright line, the uBlock Origin entry the
              GNU General Public License version 3, the filter lists' entry names every shipped list

    py -3 -I tools/qa/credits_check.py --browser <out>\\thoron.exe --work <scratch dir>
Exit status 0 only when every step passes.
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.qa import bench  # noqa: E402
from tools.qa.adblock_site_switch_check import _close_browser, _devtools_port, _open  # noqa: E402
from tools.qa.cdp import WebSocket  # noqa: E402

PAGE = "chrome://credits/"
# the entries, by the name the page shows
ENTRIES = ("Thorium", "uBlock Origin scriptlets and redirect resources", "Filter lists shipped with Thoron adblock",
           "Patches from other browser projects", "adblock")
# what an entry's licence text must hold
TEXTS = {
    "Thorium": ("BSD 3-Clause License", "Alexander Frick"),
    "uBlock Origin scriptlets and redirect resources": ("GNU GENERAL PUBLIC LICENSE", "Version 3, 29 June 2007"),
    "Filter lists shipped with Thoron adblock": ("EasyList and EasyPrivacy", "uBlock filters",
                                                 "Online Malicious URL Blocklist",
                                                 "Creative Commons Attribution-ShareAlike 3.0 Unported"),
    "Patches from other browser projects": ("Bromite and Cromite", "ungoogled-chromium", "PATCH_LICENSES.md"),
}
# Each product of the page: its name and its licence text.
READ = """JSON.stringify(Array.from(document.querySelectorAll('.product')).map((p) => ({
  name: (p.querySelector('.title') || {}).textContent || '',
  text: (p.querySelector('.licence, .license') || {}).textContent || '',
})))"""


def listed_problems(products: list[dict]) -> list[str]:
    names = {p["name"].strip(): p for p in products}
    out = [f"listed: {name!r} is not on the page" for name in ENTRIES if name not in names]
    out += [f"listed: {name!r} has no licence text" for name in ENTRIES
            if name in names and len(names[name]["text"].strip()) < 100]
    return out


def texts_problems(products: list[dict]) -> list[str]:
    names = {p["name"].strip(): p["text"] for p in products}
    return [f"texts: {name!r} does not hold {want!r}" for name, wants in TEXTS.items() if name in names
            for want in wants if want not in names[name]]


def run(browser: Path, work: Path) -> list[str]:
    profile = Path(tempfile.mkdtemp(prefix="credits-", dir=work))
    args = [str(browser), "--headless=new", f"--user-data-dir={profile}", "--no-first-run",
            "--no-default-browser-check", "--disable-background-networking", "--disable-component-update",
            "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
            "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0", "about:blank"]
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    port = None
    problems: list[str] = []
    try:
        port = _devtools_port(profile)
        ws = WebSocket(_open(port, PAGE)["webSocketDebuggerUrl"])
        time.sleep(4)
        reply = ws.call("Runtime.evaluate", expression=READ, returnByValue=True)
        ws.close()
        products = json.loads(reply.get("result", {}).get("value") or "[]")
        for name, found in (("listed", listed_problems(products)), ("texts", texts_problems(products))):
            print(f"{'PASS' if not found else 'FAIL'}  {name}: {len(products)} entries on the page")
            problems += found
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
    print("CREDITS CHECK: PASSED" if not problems else f"CREDITS CHECK: FAILED ({len(problems)} problem(s))")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
