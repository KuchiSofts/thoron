#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Thoron adblock's words in the browser's own pages, in the languages Thoron is translated into, checked
offline (ROADMAP P5.16).

While the built-in blocker is on, the browser's setting for ads is its switch: Settings call it "Ads and
trackers" and say what it does. These strings are translated into es, fr, de, pt-BR, pt-PT and ru; a
translation whose id does not match its text is silently left out and the English shows. For each language
the browser is started in that language and Settings' page of the setting is read. Steps, one per language:

    <lang>    the page's heading and its description are the translations, not the English

    py -3 -I tools/qa/adblock_strings_check.py --browser <out>\\thoron.exe --work <scratch dir>
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

PAGE = "chrome://settings/content/ads"
ENGLISH = ("Ads and trackers", "Ads and many trackers are blocked before they load")
# per language: the start of the heading and of the description, as translated
WANT = {
    "es": ("Anuncios y rastreadores", "Los anuncios y muchos rastreadores se bloquean"),
    "fr": ("Annonces et traqueurs", "Les annonces et de nombreux traqueurs sont bloqués"),
    "de": ("Werbung und Tracker", "Werbung und viele Tracker werden blockiert"),
    "pt-BR": ("Anúncios e rastreadores", "Anúncios e muitos rastreadores são bloqueados"),
    "pt-PT": ("Anúncios e rastreadores", "Os anúncios e muitos rastreadores são bloqueados"),
    "ru": ("Реклама и трекеры", "Реклама и многие трекеры блокируются"),
}
# Every text of the page, through its shadow roots.
TEXT = """(() => {
  const parts = [];
  const walk = (root) => {
    for (const el of root.querySelectorAll('*')) {
      if (el.shadowRoot) walk(el.shadowRoot);
      for (const node of el.childNodes) {
        if (node.nodeType === Node.TEXT_NODE && node.textContent.trim()) parts.push(node.textContent.trim());
      }
    }
  };
  walk(document);
  return parts.join('\\n');
})()"""


def language_problems(lang: str, text: str) -> list[str]:
    out = [f"{lang}: {want!r} is not on the page" for want in WANT[lang] if want not in text]
    out += [f"{lang}: the English {english!r} is shown" for english in ENGLISH if english in text]
    return out


def _launch(browser: Path, profile: Path, lang: str) -> subprocess.Popen:
    args = [str(browser), "--headless=new", f"--user-data-dir={profile}", "--no-first-run",
            "--no-default-browser-check", "--disable-default-apps", "--disable-background-networking",
            "--disable-component-update", "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
            "--enable-features=ThoronNativeAdblock", f"--lang={lang}", f"--accept-lang={lang}",
            "--window-size=1400,900", "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0",
            "about:blank"]
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run(browser: Path, work: Path) -> list[str]:
    problems: list[str] = []
    for lang in WANT:
        profile = Path(tempfile.mkdtemp(prefix=f"strings-{lang}-", dir=work))
        proc = _launch(browser, profile, lang)
        port = None
        try:
            port = _devtools_port(profile)
            ws = WebSocket(_open(port, PAGE)["webSocketDebuggerUrl"])
            time.sleep(3)
            reply = ws.call("Runtime.evaluate", expression=TEXT, returnByValue=True)
            ws.close()
            text = reply.get("result", {}).get("value") or ""
            found = language_problems(lang, text)
            print(f"{'PASS' if not found else 'FAIL'}  {lang}: {text.splitlines()[:1]}")
            problems += found
        except (OSError, RuntimeError, ValueError, KeyError, TypeError) as e:
            problems.append(f"{lang}: the run failed: {e}")
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
    p.add_argument("--work", required=True, type=Path, help="scratch folder for the throwaway profiles")
    a = p.parse_args(argv)
    # the pages' words in other scripts, on a console that may not have them
    sys.stdout.reconfigure(errors="backslashreplace")
    a.work.mkdir(parents=True, exist_ok=True)
    problems = run(a.browser.resolve(), a.work)
    for problem in problems:
        print(problem)
    print("STRINGS CHECK: PASSED" if not problems else f"STRINGS CHECK: FAILED ({len(problems)} problem(s))")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
