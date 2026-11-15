#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Thoron adblock, chrome://adblock's lists for regions and languages and finding things there, checked offline
(ROADMAP P5.73).

The catalog names the countries of its regional lists by flag emoji, which Windows has no pictures for; the page
draws each flag itself, names the countries in the page's language, suggests the lists for the browser's
languages, and finds a list, a country or a setting as it is typed. The browser runs without a window and in
German (`--lang=de`), so the lists for Germany are the ones to suggest. Steps:

    flags     every regional list shows a drawn flag for each of its countries, and no flag emoji is left
    suggest   "Suggested for your languages" holds the lists for Germany, and only lists for its countries
    find      typing a country's name keeps only its lists; typing nonsense says that no list matches
    setting   typing in "Find a setting" keeps only the settings that hold it, under their headings
    preview   the shield's preview follows where it is set: next to the menu, then back to the default

    py -3 -I tools/qa/adblock_catalog_check.py --browser <out>\\thoron.exe --work <scratch dir>
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
REGIONS = "Regions and languages"
SUGGESTED = "Suggested for your languages"
# what the page shows of the catalog: for each group, its lists' countries, flags drawn and the text shown
READ_CATALOG = """(() => JSON.stringify(Array.from(document.querySelectorAll('#catalog details'), (d) => ({
  group: d.dataset.group,
  lists: Array.from(d.querySelectorAll('.entry'), (e) => ({
    flags: Array.from(e.querySelectorAll('svg.flag'), (f) => ({name: f.getAttribute('aria-label'),
                                                               shapes: f.querySelectorAll('rect, circle, polygon, path').length,
                                                               letters: f.querySelector('text') ? f.querySelector('text').textContent : ''})),
    text: e.textContent})),
})).concat([{none: !document.getElementById('catalog-none').hidden}])))()"""
TYPE = ("(() => { const box = document.getElementById('%s'); box.value = %s; "
        "box.dispatchEvent(new Event('input')); return box.value; })()")
READ_SETTINGS = r"""(() => JSON.stringify({
  shown: Array.from(document.querySelectorAll('#settings .option')).filter((o) => !o.hidden).map((o) => o.textContent.replace(/\s+/g, ' ').trim()),
  headings: Array.from(document.querySelectorAll('#settings h3')).filter((h) => !h.hidden).map((h) => h.textContent),
  none: !document.getElementById('find-none').hidden}))()"""
SET_CHOICE = ("(() => { const s = document.getElementById('%s'); s.value = '%s'; "
              "s.dispatchEvent(new Event('change')); return s.value; })()")
READ_PREVIEW = """(() => { const bar = document.querySelector('#shield-preview .pv-bar');
  if (!bar) return '';
  return Array.from(bar.querySelectorAll(':scope > .pv-icon, :scope > .pv-field'), (e) =>
    e.classList.contains('pv-field') ? '[' + Array.from(e.querySelectorAll('.pv-icon'), (i) =>
      i.classList.contains('pv-shield') ? 'S' : 'i').join('') + ']' : (e.classList.contains('pv-shield') ? 'S'
      : e.classList.contains('pv-menu') ? 'M' : 'b')).join(''); })()"""


def groups_of(seen: list) -> tuple[dict, bool]:
    """The page's catalog as read: group -> its lists, and whether it says that no list matches."""
    groups = {g["group"]: g["lists"] for g in seen if "group" in g}
    none = next((g["none"] for g in seen if "none" in g), False)
    return groups, none


def flags_problems(seen: list) -> list[str]:
    groups, _ = groups_of(seen)
    regional = groups.get(REGIONS, [])
    out = []
    if len(regional) < 30:
        out.append(f"flags: {len(regional)} lists for regions and languages, not all of them")
    no_flag = [lst["text"][:40] for lst in regional if not lst["flags"]]
    if no_flag:
        out.append(f"flags: lists without a flag: {no_flag[:5]}")
    letters = sorted({f["letters"] for lst in regional for f in lst["flags"] if f["letters"] or f["shapes"] < 2})
    if letters:
        out.append(f"flags: countries shown by their letters, not drawn: {letters}")
    emoji = [lst["text"][:40] for lst in regional if any(0x1F1E6 <= ord(c) <= 0x1F1FF for c in lst["text"])]
    if emoji:
        out.append(f"flags: flag emoji still shown in {emoji[:5]}")
    return out


def suggest_problems(seen: list, country: str) -> list[str]:
    groups, _ = groups_of(seen)
    suggested = groups.get(SUGGESTED)
    if not suggested:
        return ["suggest: no lists are suggested for the browser's language"]
    out = []
    if not all(any(f["name"] == country for f in lst["flags"]) for lst in suggested):
        out.append(f"suggest: a suggested list is not one for {country}: "
                   f"{[lst['text'][:40] for lst in suggested]}")
    return out


def find_problems(found: list, nothing: list, country: str) -> list[str]:
    groups, none = groups_of(found)
    out = []
    lists = [lst for group in groups.values() for lst in group]
    if not lists or none:
        out.append(f"find: typing {country!r} found no list")
    elif not all(country.lower() in lst["text"].lower() for lst in lists):
        out.append(f"find: typing {country!r} kept lists that do not name it: "
                   f"{[lst['text'][:40] for lst in lists if country.lower() not in lst['text'].lower()]}")
    groups, none = groups_of(nothing)
    if groups or not none:
        out.append("find: typing nonsense kept lists, or did not say that no list matches")
    return out


def setting_problems(found: dict, everything: dict, nothing: dict, word: str) -> list[str]:
    out = []
    if not found["shown"] or not all(word.lower() in s.lower() for s in found["shown"]):
        out.append(f"setting: typing {word!r} kept settings without it: {found['shown'][:5]}")
    if len(found["headings"]) >= len(everything["headings"]):
        out.append("setting: the headings without a matching setting stayed")
    if len(everything["shown"]) <= len(found["shown"]):
        out.append("setting: an empty search did not show every setting again")
    if nothing["shown"] or not nothing["none"]:
        out.append("setting: typing nonsense kept settings, or did not say that none matches")
    return out


def preview_problems(by_place: dict) -> list[str]:
    """`by_place`: the preview for each toolbar position, as `b`, `M`, `S` and the address bar's `[...]`."""
    out = []
    menu = by_place.get("menu", "")
    if not menu.endswith("SM"):
        out.append(f"preview: 'next to the menu' shows {menu!r}, not the shield right before the menu")
    default = by_place.get("extensions", "")
    if default.count("S") != 2 or default.endswith("SM"):
        out.append(f"preview: the default shows {default!r}, not a shield in the address bar and after the "
                   "extensions")
    return out


def _eval(ws: WebSocket, expression: str):
    reply = ws.call("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True)
    return reply.get("result", {}).get("value")


def run(browser: Path, work: Path) -> list[str]:
    profile = Path(tempfile.mkdtemp(prefix="catalog-", dir=work))
    problems: list[str] = []
    args = [str(browser), "--headless=new", f"--user-data-dir={profile}", "--no-first-run",
            "--no-default-browser-check", "--disable-background-networking", "--disable-component-update",
            "--enable-features=ThoronNativeAdblock", "--lang=de", "--host-resolver-rules=MAP * ~NOTFOUND",
            "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0", "about:blank"]
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    port = None
    ws = None
    try:
        port = _devtools_port(profile)
        ws = WebSocket(_open(port, SETTINGS_URL)["webSocketDebuggerUrl"])
        time.sleep(SETTLE_S)
        seen = json.loads(_eval(ws, READ_CATALOG) or "[]")
        for step, found in (("flags", flags_problems(seen)), ("suggest", suggest_problems(seen, "Deutschland"))):
            groups, _ = groups_of(seen)
            detail = (f"{len(groups.get(REGIONS, []))} regional lists" if step == "flags"
                      else f"{[lst['text'][:30] for lst in groups.get(SUGGESTED, [])]}")
            print(f"{'PASS' if not found else 'FAIL'}  {step}: {detail}")
            problems += found

        _eval(ws, TYPE % ("catalog-find", json.dumps("Österreich")))
        found_lists = json.loads(_eval(ws, READ_CATALOG) or "[]")
        _eval(ws, TYPE % ("catalog-find", json.dumps("qqxqq")))
        nothing = json.loads(_eval(ws, READ_CATALOG) or "[]")
        _eval(ws, TYPE % ("catalog-find", json.dumps("")))
        found = find_problems(found_lists, nothing, "Österreich")
        print(f"{'PASS' if not found else 'FAIL'}  find: "
              f"{[lst['text'][:30] for g in groups_of(found_lists)[0].values() for lst in g]}")
        problems += found

        everything = json.loads(_eval(ws, READ_SETTINGS))
        _eval(ws, TYPE % ("find-setting", json.dumps("Menü")))
        found_settings = json.loads(_eval(ws, READ_SETTINGS))
        _eval(ws, TYPE % ("find-setting", json.dumps("qqxqq")))
        nothing_settings = json.loads(_eval(ws, READ_SETTINGS))
        _eval(ws, TYPE % ("find-setting", json.dumps("")))
        found = setting_problems(found_settings, everything, nothing_settings, "Menü")
        print(f"{'PASS' if not found else 'FAIL'}  setting: {len(found_settings['shown'])} of "
              f"{len(everything['shown'])} settings shown, under {found_settings['headings']}")
        problems += found

        by_place = {}
        for place in ("menu", "extensions"):
            _eval(ws, SET_CHOICE % ("toolbar-position", place))
            time.sleep(1.5)
            by_place[place] = _eval(ws, READ_PREVIEW) or ""
        found = preview_problems(by_place)
        print(f"{'PASS' if not found else 'FAIL'}  preview: {by_place}")
        problems += found
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as e:
        problems.append(f"the run failed: {e}")
    finally:
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
    # countries' names in German ("Österreich") on a console that may not have their letters
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    a.work.mkdir(parents=True, exist_ok=True)
    problems = run(a.browser.resolve(), a.work)
    for problem in problems:
        print(problem)
    print("CATALOG CHECK: PASSED" if not problems else f"CATALOG CHECK: FAILED ({len(problems)} problem(s))")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
