#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""A page's language is found without a download from Google, checked offline (ROADMAP S.15).

Chromium finds a page's language (for "Translate this page?") with a model it downloads from Google's
optimization guide at every start. Thoron does not ask that service, so it uses the detector that is built in
(CLD3). Here local pages (127.0.0.1) in three languages are opened while `chrome://translate-internals` is
open, which lists what was detected for each page; no outside name can be resolved, so nothing leaves the PC
and no model can arrive. Steps:

    plain     pages that do not say their language (French, English): the detector names it
    declared  a page that says its language (Spanish, `<html lang="es">`): the same language is adopted
    built-in  every detection was made by the built-in detector (CLD3)

    py -3 -I tools/qa/language_detect_check.py --browser <out>\\thoron.exe --work <scratch dir>
Exit status 0 only when every step passes.
"""
import argparse
import http.server
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.qa import bench  # noqa: E402
from tools.qa.adblock_site_switch_check import _close_browser, _devtools_port, _open  # noqa: E402
from tools.qa.cdp import WebSocket  # noqa: E402

INTERNALS_URL = "chrome://translate-internals/"
BUILT_IN = "CLD3"
WAIT_S = 6.0
FRENCH = ("Le petit village se trouve au bord de la rivière, entre deux collines couvertes de forêts. Chaque "
          "matin, le boulanger ouvre sa boutique avant le lever du soleil et les habitants viennent chercher "
          "leur pain encore chaud. Les enfants traversent le vieux pont de pierre pour aller à l'école, pendant "
          "que les pêcheurs préparent leurs filets. Le dimanche, tout le monde se retrouve sur la place du "
          "marché pour acheter des légumes, du fromage et des fleurs.")
ENGLISH = ("The small village lies beside the river, between two hills covered with forest. Every morning the "
           "baker opens his shop before sunrise and the neighbours come to fetch their bread while it is still "
           "warm. The children cross the old stone bridge on their way to school, while the fishermen get their "
           "nets ready. On Sunday everybody meets in the market square to buy vegetables, cheese and flowers.")
SPANISH = ("El pequeño pueblo está a la orilla del río, entre dos colinas cubiertas de bosques. Cada mañana el "
           "panadero abre su tienda antes de que salga el sol y los vecinos vienen a buscar su pan todavía "
           "caliente. Los niños cruzan el viejo puente de piedra para ir a la escuela, mientras los pescadores "
           "preparan sus redes. El domingo todo el mundo se encuentra en la plaza del mercado para comprar "
           "verduras, queso y flores.")
# path -> (the language the page says it is in, its text, the language it is in)
PAGES = {"/plain-fr": ("", FRENCH, "fr"), "/plain-en": ("", ENGLISH, "en"), "/declared-es": ("es", SPANISH, "es")}
READ_LOG = """(() => JSON.stringify(Array.from(document.querySelectorAll('#tabpanel-detection-logs tbody tr'),
  (tr) => { const cell = (name) => (tr.querySelector('.detection-logs-' + name) || {}).textContent || '';
    return {url: cell('url'), declared: cell('html-root-language'), detected: cell('cld-language'),
            by: cell('detection-model-version'), adopted: cell('adopted-language')}; })))()"""


def page(declared: str, text: str) -> bytes:
    lang = f' lang="{declared}"' if declared else ""
    paragraphs = "".join(f"<p>{text}</p>" for _ in range(3))
    return (f'<!doctype html><html{lang}><head><meta charset="utf-8"><title>page</title></head>'
            f"<body><h1>page</h1>{paragraphs}</body></html>").encode("utf-8")


def code(shown: str) -> str:
    """The language code of what the internals page shows ("fr - French", "fr", "")."""
    return shown.strip().split(" ")[0].split("-")[0].lower()


def row_for(rows: list[dict], path: str) -> dict | None:
    hits = [r for r in rows if r.get("url", "").split("?")[0].endswith(path)]
    return hits[-1] if hits else None


def plain_problems(rows: list[dict]) -> list[str]:
    out = []
    for path, (declared, _, language) in PAGES.items():
        if declared:
            continue
        row = row_for(rows, path)
        if not row:
            out.append(f"plain: no detection was listed for {path}")
        elif code(row["detected"]) != language or code(row["adopted"]) != language:
            out.append(f"plain: {path} is in {language!r}; detected {row['detected']!r}, adopted {row['adopted']!r}")
    return out


def declared_problems(rows: list[dict]) -> list[str]:
    out = []
    for path, (declared, _, language) in PAGES.items():
        if not declared:
            continue
        row = row_for(rows, path)
        if not row:
            out.append(f"declared: no detection was listed for {path}")
        elif code(row["adopted"]) != language:
            out.append(f"declared: {path} says {declared!r} and is in {language!r}; adopted {row['adopted']!r}")
    return out


def built_in_problems(rows: list[dict]) -> list[str]:
    seen = [r for r in rows if any(r.get("url", "").split("?")[0].endswith(p) for p in PAGES)]
    if not seen:
        return ["built-in: no detection was listed"]
    other = sorted({r["by"].strip() for r in seen if r["by"].strip() != BUILT_IN})
    return [f"built-in: detections were made by {other}, not only by {BUILT_IN}"] if other else []


class Pages:
    """The local pages."""

    def __enter__(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                found = PAGES.get(self.path.split("?")[0])
                body = page(found[0], found[1]) if found else b"none"
                self.send_response(200 if found else 404)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


def run(browser: Path, work: Path) -> list[str]:
    profile = Path(tempfile.mkdtemp(prefix="language-", dir=work))
    problems: list[str] = []
    with Pages() as pages:
        args = [str(browser), "--headless=new", f"--user-data-dir={profile}", "--no-first-run",
                "--no-default-browser-check", "--disable-background-networking", "--disable-component-update",
                "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
                "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0", "about:blank"]
        proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        port = None
        ws = None
        try:
            port = _devtools_port(profile)
            ws = WebSocket(_open(port, INTERNALS_URL)["webSocketDebuggerUrl"])
            time.sleep(3)
            for path in PAGES:
                _open(port, f"http://127.0.0.1:{pages.port}{path}")
                time.sleep(WAIT_S)
            reply = ws.call("Runtime.evaluate", expression=READ_LOG, returnByValue=True)
            rows = json.loads(reply.get("result", {}).get("value") or "[]")
            for name, found in (("plain", plain_problems(rows)), ("declared", declared_problems(rows)),
                                ("built-in", built_in_problems(rows))):
                shown = [(r["url"].rsplit("/", 1)[-1], r["detected"], r["adopted"], r["by"]) for r in rows]
                print(f"{'PASS' if not found else 'FAIL'}  {name}: {shown}")
                problems.extend(found)
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
    a.work.mkdir(parents=True, exist_ok=True)
    problems = run(a.browser.resolve(), a.work)
    for problem in problems:
        print(problem)
    print("LANGUAGE CHECK: PASSED" if not problems else f"LANGUAGE CHECK: FAILED ({len(problems)} problem(s))")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
