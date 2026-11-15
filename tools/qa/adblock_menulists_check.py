#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Native ad blocking, the filter lists in the blocker's menu, checked end to end and offline (ROADMAP P5.71).

The menu of the shield holds the filter lists, as chrome://adblock does: a list switched off or on, every list
downloaded again now, a list added by its address and removed again, each in use at once. The browser runs
headless with `--thoron-adblock-lists-url-for-testing`, which points the list updater at a local server (only
loopback addresses are taken there); the menu is opened as a tab, where it works on the tab before it. Steps:

    shown    the section lists the built-in lists, each with its switch and rule count, and how many are on
    off      EasyPrivacy switched off in the menu: it is off for the blocker too; on again: on again
    update   "Update now": every list in use is asked for from the server, and the menu says it looked
    add      a list added by its address: it is in use and shows with a way to remove it; removed: gone

    py -3 -I tools/qa/adblock_menulists_check.py --browser <out>\\thoron.exe --work <scratch dir>
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
from tools.qa.adblock_update_check import ListServer, split_lists  # noqa: E402
from tools.qa.cdp import WebSocket  # noqa: E402

MENU_URL = "chrome://adblock-menu.top-chrome/"
SETTLE_S = 2.5
EXTRA = "extra-menu"
EXTRA_TEXT = "! Title: Thoron menu lists check\n||extra-menu-list.test^\n"
READ = """JSON.stringify({count: document.getElementById('lists-count').textContent,
  state: document.getElementById('lists-state').textContent,
  rows: Array.from(document.querySelectorAll('#lists .list')).map((r) => ({
    name: r.querySelector('label span').textContent, box: !!r.querySelector('input'),
    on: r.querySelector('input') ? r.querySelector('input').checked : null,
    remove: !!r.querySelector('.remove'), n: r.querySelector('.n').textContent}))})"""
CALL = """(async () => { const {sendWithPromise} = await import('chrome://resources/js/cr.js');
  return JSON.stringify(await sendWithPromise('getLists')); })()"""


def shown_problems(seen: dict) -> list[str]:
    rows = seen.get("rows") or []
    out = []
    if len(rows) < 2:
        out.append(f"shown: the menu lists {len(rows)} lists")
    if any(not r.get("box") for r in rows):
        out.append("shown: a built-in list has no switch")
    if any(not r.get("n") for r in rows):
        out.append("shown: a list has no rule count")
    if not str(seen.get("count", "")).startswith("("):
        out.append(f"shown: the section says {seen.get('count')!r} about how many are on")
    return out


def row(seen: dict, name: str) -> dict:
    return next((r for r in seen.get("rows") or [] if r.get("name") == name), {})


def _eval(ws: WebSocket, expression: str):
    reply = ws.call("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True)
    if "exceptionDetails" in reply:
        details = reply["exceptionDetails"]
        raise RuntimeError(details.get("exception", {}).get("description") or details.get("text", "the page threw"))
    return reply.get("result", {}).get("value")


def _launch(browser: Path, profile: Path, port: int) -> subprocess.Popen:
    args = [str(browser), "--headless=new", f"--user-data-dir={profile}", "--no-first-run",
            "--no-default-browser-check", "--disable-default-apps", "--disable-background-networking",
            "--disable-component-update", "--enable-features=ThoronNativeAdblock",
            f"--thoron-adblock-lists-url-for-testing=http://127.0.0.1:{port}/lists/",
            "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
            "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0", "about:blank"]
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run(browser: Path, work: Path, lists_file: Path) -> list[str]:
    problems: list[str] = []
    profile = Path(tempfile.mkdtemp(prefix="menulists-", dir=work))

    def report(step: str, found: list[str], seen) -> None:
        print(f"{'PASS' if not found else 'FAIL'}  {step}: {seen}")
        problems.extend(found)

    lists = split_lists(lists_file.read_text(encoding="utf-8"))
    lists[EXTRA] = EXTRA_TEXT
    with ListServer(lists) as server:
        proc = _launch(browser, profile, server.port)
        port = None
        try:
            port = _devtools_port(profile)
            page = WebSocket(_open(port, f"http://127.0.0.1:{server.port}/test.html")["webSocketDebuggerUrl"])
            time.sleep(SETTLE_S)
            menu = WebSocket(_open(port, MENU_URL)["webSocketDebuggerUrl"])
            try:
                time.sleep(SETTLE_S)
                _eval(menu, "(() => { const box = document.getElementById('lists-box'); box.open = true; return 1; })()")
                time.sleep(SETTLE_S)
                seen = json.loads(_eval(menu, READ) or "{}")
                report("shown", shown_problems(seen), {"count": seen.get("count"), "rows": len(seen.get("rows") or [])})

                def lists_now() -> dict:
                    return {e.get("id"): e for e in (json.loads(_eval(menu, CALL) or "{}").get("lists") or [])}

                found = []
                if not row(seen, "EasyPrivacy"):
                    found.append("off: EasyPrivacy is not in the menu")
                else:
                    click = ("(() => { const r = Array.from(document.querySelectorAll('#lists .list')).find((r) =>"
                             " r.querySelector('label span').textContent === 'EasyPrivacy');"
                             " r.querySelector('input').click(); return 1; })()")
                    _eval(menu, click)
                    time.sleep(SETTLE_S + 2)
                    off = json.loads(_eval(menu, READ) or "{}")
                    off_state = lists_now().get("easyprivacy", {}).get("enabled")
                    if row(off, "EasyPrivacy").get("on") is not False or off_state is not False:
                        found.append(f"off: EasyPrivacy is {row(off, 'EasyPrivacy')} in the menu, {off_state} for the blocker")
                    if off.get("state") != "EasyPrivacy is switched off.":
                        found.append(f"off: the menu says {off.get('state')!r}")
                    _eval(menu, click)
                    time.sleep(SETTLE_S + 2)
                    on_state = lists_now().get("easyprivacy", {}).get("enabled")
                    if on_state is False:
                        found.append("off: EasyPrivacy did not come back on")
                report("off", found, [off.get("state") if row(seen, "EasyPrivacy") else None])

                before = server.list_requests
                _eval(menu, "document.getElementById('lists-update').click(); 1")
                state = ""
                for _ in range(40):
                    time.sleep(0.5)
                    state = _eval(menu, "document.getElementById('lists-state').textContent") or ""
                    if state and state != "Updating the lists...":
                        break
                asked = server.list_requests - before
                found = [] if asked > 0 and state == "Looked for newer lists." else \
                    [f"update: {asked} lists were asked for, and the menu says {state!r}"]
                report("update", found, {"asked": asked, "state": state})

                url = f"http://127.0.0.1:{server.port}/lists/{EXTRA}.txt"
                _eval(menu, f"(() => {{ document.getElementById('list-url').value = {json.dumps(url)};"
                            " document.querySelector('#list-add button').click(); return 1; })()")
                time.sleep(SETTLE_S + 3)
                added = json.loads(_eval(menu, READ) or "{}")
                mine = row(added, "Thoron menu lists check")
                found = []
                if not mine or not mine.get("remove"):
                    found.append(f"add: the added list shows as {mine} (the menu says {added.get('state')!r})")
                if added.get("state") != "The list was added and is in use.":
                    found.append(f"add: the menu says {added.get('state')!r}")
                if mine:
                    _eval(menu, "(() => { const r = Array.from(document.querySelectorAll('#lists .list')).find((r) =>"
                                " r.querySelector('label span').textContent === 'Thoron menu lists check');"
                                " r.querySelector('.remove').click(); return 1; })()")
                    time.sleep(SETTLE_S + 2)
                    gone = json.loads(_eval(menu, READ) or "{}")
                    if row(gone, "Thoron menu lists check"):
                        found.append("add: the list is still there after it was removed")
                report("add", found, {"added": bool(mine), "state": added.get("state")})
            finally:
                menu.close()
                page.close()
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
    p.add_argument("--lists", type=Path, help="the bundled lists file (default: next to the browser)")
    a = p.parse_args(argv)
    a.work.mkdir(parents=True, exist_ok=True)
    problems = run(a.browser.resolve(), a.work, a.lists or a.browser.parent / "thoron_adblock_lists.txt")
    for problem in problems:
        print(problem)
    print("MENU LISTS CHECK: PASSED" if not problems else f"MENU LISTS CHECK: FAILED ({len(problems)} problem(s))")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
