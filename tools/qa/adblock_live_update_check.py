#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Native ad blocking, filter list updates from the real list servers (ROADMAP P5.70). ONLINE, unlike the
other checks: run it on purpose.

A throwaway profile asks for "Update now" on chrome://adblock, as a person does. The browser downloads every
list that is in use from its own address (no cookies, nothing that tells who asks: the same requests it makes
by itself every few days) and checks each one before it is used. Steps:

    update    "Update now" ends without an error, and every list in use was downloaded and taken in
              ("updated", or "unchanged" when the server had nothing new); none was kept back as failed
    rules     each list holds a plausible number of rules, and together they hold more than 100,000

    py -3 -I tools/qa/adblock_live_update_check.py --browser <out>\\thoron.exe --work <scratch dir>
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

SETTINGS_URL = "chrome://adblock/"
SETTLE_S = 3.0
TAKEN = ("updated", "unchanged")
MIN_RULES_EACH = 100
MIN_RULES_ALL = 100_000


def update_problems(answer, lists: list[dict]) -> list[str]:
    out = [] if answer == "" else [f"update: \"Update now\" answered {answer!r}"]
    used = [entry for entry in lists if entry.get("enabled")]
    if not used:
        out.append("update: no list is in use")
    for entry in used:
        if entry.get("note") not in TAKEN:
            out.append(f"update: {entry.get('id')} was not taken in: {entry.get('note')!r}")
    return out


def rules_problems(lists: list[dict]) -> list[str]:
    used = [entry for entry in lists if entry.get("enabled")]
    out = [f"rules: {e.get('id')} holds only {e.get('rules')} rules" for e in used
           if not isinstance(e.get("rules"), int) or e["rules"] < MIN_RULES_EACH]
    total = sum(e["rules"] for e in used if isinstance(e.get("rules"), int))
    if total < MIN_RULES_ALL:
        out.append(f"rules: the lists hold {total} rules together")
    return out


def run(browser: Path, work: Path) -> list[str]:
    problems: list[str] = []
    profile = Path(tempfile.mkdtemp(prefix="live-update-", dir=work))

    def report(step: str, found: list[str], seen) -> None:
        print(f"{'PASS' if not found else 'FAIL'}  {step}: {seen}")
        problems.extend(found)

    proc = subprocess.Popen([str(browser), "--headless=new", f"--user-data-dir={profile}", "--no-first-run",
                             "--no-default-browser-check", "--disable-default-apps", "--disable-sync",
                             "--enable-features=ThoronNativeAdblock", "--remote-debugging-address=127.0.0.1",
                             "--remote-debugging-port=0", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    port = None
    try:
        port = _devtools_port(profile)
        ws = WebSocket(_open(port, SETTINGS_URL)["webSocketDebuggerUrl"])
        try:
            time.sleep(SETTLE_S)

            def call(name: str):
                reply = ws.call("Runtime.evaluate", awaitPromise=True, returnByValue=True, expression=(
                    "(async () => { const {sendWithPromise} = await import('chrome://resources/js/cr.js');"
                    f" return JSON.stringify(await sendWithPromise({json.dumps(name)})); }})()"))
                return json.loads(reply.get("result", {}).get("value") or "null")

            start = time.time()
            answer = call("updateNow")
            took = round(time.time() - start)
            lists = (call("getState") or {}).get("lists", [])
            used = {e.get("id"): e.get("note") for e in lists if e.get("enabled")}
            report("update", update_problems(answer, lists), {"seconds": took, "lists": used})
            report("rules", rules_problems(lists),
                   {e.get("id"): e.get("rules") for e in lists if e.get("enabled")})
        finally:
            ws.close()
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as e:
        problems.append(f"the run failed: {e}")
    finally:
        if port is not None:
            _close_browser(port, proc)
        elif proc.poll() is None:
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
    print("LIVE UPDATE CHECK: PASSED" if not problems else f"LIVE UPDATE CHECK: FAILED ({len(problems)} problem(s))")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
