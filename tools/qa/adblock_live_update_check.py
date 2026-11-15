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
    switch    (P5.71) in the menu of the shield, EasyPrivacy switched off and on again: so it is for the blocker
    add       in the menu, a real list of the settings page's catalog added by its address (uBlock Origin's
              "Block Outsider Intrusion into LAN", from its own site): downloaded, checked and in use; removed
              again: gone

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
MENU_URL = "chrome://adblock-menu.top-chrome/"
# a list of the settings page's catalog ("More lists"), small and from uBlock Origin's own site
ADDED_LIST = "https://ublockorigin.github.io/uAssets/filters/lan-block.txt"
MENU_ROWS = """JSON.stringify({state: document.getElementById('lists-state').textContent,
  rows: Array.from(document.querySelectorAll('#lists .list')).map((r) => ({
    name: r.querySelector('label span').textContent,
    on: r.querySelector('input') ? r.querySelector('input').checked : null, remove: !!r.querySelector('.remove')}))})"""
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


def switch_problems(menu: dict, off, on) -> list[str]:
    out = []
    if menu.get("state") != "EasyPrivacy is switched off.":
        out.append(f"switch: the menu says {menu.get('state')!r}")
    if off is not False:
        out.append(f"switch: switched off in the menu, EasyPrivacy is {off!r} for the blocker")
    if on is not True:
        out.append(f"switch: switched on again, EasyPrivacy is {on!r} for the blocker")
    return out


def add_problems(state, new: list[dict], gone) -> list[str]:
    out = []
    if state != "The list was added and is in use.":
        out.append(f"add: the menu says {state!r}")
    if len(new) != 1 or not new[0].get("remove"):
        out.append(f"add: the menu shows {new} as the new list")
    if gone is not True:
        out.append("add: the list is still there after it was removed")
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

            # the menu, opened as a tab (it works on the tab before it), with its lists shown
            menu = WebSocket(_open(port, MENU_URL)["webSocketDebuggerUrl"])
            try:
                time.sleep(SETTLE_S)

                def menu_eval(expression: str):
                    reply = menu.call("Runtime.evaluate", awaitPromise=True, returnByValue=True,
                                      expression=expression)
                    return reply.get("result", {}).get("value")

                def rows() -> dict:
                    return json.loads(menu_eval(MENU_ROWS) or "{}")

                def enabled(list_id: str):
                    return next((e.get("enabled") for e in (call("getState") or {}).get("lists", [])
                                 if e.get("id") == list_id), None)

                menu_eval("(() => { document.getElementById('lists-box').open = true; return 1; })()")
                time.sleep(SETTLE_S)
                toggle = ("(() => { const r = Array.from(document.querySelectorAll('#lists .list')).find((r) =>"
                          " r.querySelector('label span').textContent === 'EasyPrivacy');"
                          " r.querySelector('input').click(); return 1; })()")
                menu_eval(toggle)
                time.sleep(SETTLE_S + 3)
                off, off_state = rows(), enabled("easyprivacy")
                menu_eval(toggle)
                time.sleep(SETTLE_S + 3)
                on_state = enabled("easyprivacy")
                report("switch", switch_problems(off, off_state, on_state),
                       {"menu": off.get("state"), "off": off_state, "on again": on_state})

                before = {r.get("name") for r in rows().get("rows") or []}
                menu_eval("(() => { document.getElementById('list-url').value = " + json.dumps(ADDED_LIST) + ";"
                          " document.querySelector('#list-add button').click(); return 1; })()")
                added = {}
                for _ in range(60):
                    time.sleep(0.5)
                    added = rows()
                    if added.get("state") and added.get("state") != "Updating the lists...":
                        break
                time.sleep(1)
                added = rows()
                new = [r for r in added.get("rows") or [] if r.get("name") not in before]
                gone = None
                if new and new[0].get("remove"):
                    name = new[0]["name"]
                    menu_eval("(() => { const r = Array.from(document.querySelectorAll('#lists .list')).find((r) =>"
                              " r.querySelector('label span').textContent === " + json.dumps(name) + ");"
                              " r.querySelector('.remove').click(); return 1; })()")
                    time.sleep(SETTLE_S + 2)
                    gone = not any(r.get("name") == name for r in rows().get("rows") or [])
                report("add", add_problems(added.get("state"), new, gone),
                       {"state": added.get("state"), "added": [r.get("name") for r in new], "removed": gone})
            finally:
                menu.close()
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
