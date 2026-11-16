#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Chromium's Gemini plumbing is not loaded or shown, checked offline (ROADMAP S.16).

Chromium 158 puts its internal "Gemini in Chrome" component extension into every profile it opens and shows a
Google AI page in Settings. Thoron does not offer that feature, so its main switch is off: nothing of it is
loaded or shown, and that one switch brings it back for whoever wants it. No outside name can be resolved here,
so nothing leaves the PC. Steps:

    component  a new profile's extensions (the browser's own included) hold no Gemini component
    settings   the side menu of Settings has no AI entry, and Thoron's own entries are still there
    switch     with the feature's main switch on (`--enable-features=Glic`) the component is back: the switch
               is what was checked

    py -3 -I tools/qa/glic_check.py --browser <out>\\thoron.exe --work <scratch dir>
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

WORDS = ("gemini", "glic")
READ_MENU = """(() => {
  const find = (root, sel) => { const hit = root.querySelector(sel); if (hit) return hit;
    for (const el of root.querySelectorAll('*')) {
      if (el.shadowRoot) { const deep = find(el.shadowRoot, sel); if (deep) return deep; } }
    return null; };
  const menu = find(document, 'settings-menu');
  if (!menu || !menu.shadowRoot) return '[]';
  return JSON.stringify(Array.from(menu.shadowRoot.querySelectorAll('a'), (a) => ({id: a.id,
    href: a.getAttribute('href') || '', shown: !a.hidden && getComputedStyle(a).display !== 'none'}))); })()"""


def named(extensions: list[dict]) -> list[str]:
    """The names of the extensions that are part of the Gemini plumbing."""
    return [e.get("name", "") for e in extensions if any(w in e.get("name", "").lower() for w in WORDS)]


def component_problems(extensions: list[dict]) -> list[str]:
    if not extensions:
        return ["component: the browser's list of extensions could not be read"]
    found = named(extensions)
    return [f"component: a new profile holds {found}"] if found else []


def settings_problems(menu: list[dict]) -> list[str]:
    shown = [m for m in menu if m.get("shown")]
    out = []
    if len(shown) < 5:
        out.append(f"settings: the side menu could not be read ({len(shown)} entries)")
    ai = [m["id"] for m in shown if m.get("id") == "ai" or m.get("href") == "/ai"]
    if ai:
        out.append("settings: the side menu offers a Google AI page")
    if shown and not any(m.get("id") == "thoronAdblockLink" for m in shown):
        out.append("settings: Thoron adblock's entry is gone from the side menu")
    return out


def switch_problems(extensions: list[dict]) -> list[str]:
    return [] if named(extensions) else ["switch: with the main switch on the component is not there, so the "
                                         "first step proves nothing"]


def _look(browser: Path, work: Path, switches: list[str], menu: bool) -> tuple[list[dict], list[dict]]:
    profile = Path(tempfile.mkdtemp(prefix="glic-", dir=work))
    proc = subprocess.Popen(
        [str(browser), "--headless=new", f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
         "--disable-background-networking", "--disable-component-update",
         "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1", *switches,
         "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    port = None
    try:
        port = _devtools_port(profile)
        ws = WebSocket(_open(port, "chrome://extensions-internals/")["webSocketDebuggerUrl"])
        try:
            time.sleep(4)
            text = ws.call("Runtime.evaluate", expression="document.body.innerText",
                           returnByValue=True)["result"].get("value", "")
        finally:
            ws.close()
        extensions = json.loads(text[text.index("["):]) if "[" in text else []
        entries: list[dict] = []
        if menu:
            ws = WebSocket(_open(port, "chrome://settings/")["webSocketDebuggerUrl"])
            try:
                time.sleep(5)
                entries = json.loads(ws.call("Runtime.evaluate", expression=READ_MENU,
                                             returnByValue=True)["result"].get("value") or "[]")
            finally:
                ws.close()
        return extensions, entries
    finally:
        if port is not None:
            _close_browser(port, proc)
        else:
            bench._stop(proc, profile)
        shutil.rmtree(profile, ignore_errors=True)


def run(browser: Path, work: Path) -> list[str]:
    problems: list[str] = []

    def step(name: str, found: list[str], detail) -> None:
        print(f"{'PASS' if not found else 'FAIL'}  {name}: {detail}")
        problems.extend(found)

    try:
        extensions, menu = _look(browser, work, [], menu=True)
        step("component", component_problems(extensions), [e.get("name") for e in extensions])
        step("settings", settings_problems(menu), [m["id"] for m in menu if m.get("shown")])
        extensions, _ = _look(browser, work, ["--enable-features=Glic"], menu=False)
        step("switch", switch_problems(extensions), [e.get("name") for e in extensions])
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as e:
        problems.append(f"the run failed: {e}")
    return problems


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--browser", required=True, type=Path)
    p.add_argument("--work", required=True, type=Path, help="scratch folder for the throwaway profiles")
    a = p.parse_args(argv)
    a.work.mkdir(parents=True, exist_ok=True)
    problems = run(a.browser.resolve(), a.work)
    for problem in problems:
        print(problem)
    print("GEMINI CHECK: PASSED" if not problems else f"GEMINI CHECK: FAILED ({len(problems)} problem(s))")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
