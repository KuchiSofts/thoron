#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Native ad blocking, its own switch for every site, checked end to end and offline (ROADMAP P5.70).

The blocker is switched off and on while the browser runs, as uBlock Origin is: from chrome://adblock, from
the menu of the shield and with a keyboard shortcut, off for good or for a while. A local server serves a page
with an element a rule hides and an image from a host a rule blocks (host-resolver rules; every other name
fails, so nothing leaves the PC). Steps:

    on        the rules work: the image is never asked for, the element is hidden
    off       switched off on chrome://adblock: on a reload the image is asked for and the element shows; the
              page says so, and so does the menu
    back      switched on again: blocked and hidden again, with no restart
    menu      the menu's switch asks for how long; "Until I turn it on" turns it off and reloads the tab; the
              big button turns it on again
    shortcut  the shortcut "Blocking off or on for every site" switches it off and on
    while     off for a minute: the page says until when, and blocking is back on by itself after it
    kept      off for good stays off when the browser starts again; off until the browser closes does not

    py -3 -I tools/qa/adblock_power_check.py --browser <out>\\thoron.exe --work <scratch dir>
Exit status 0 only when every step passes.
"""
import argparse
import http.server
import json
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.qa import bench  # noqa: E402
from tools.qa.adblock_site_switch_check import _close_browser, _devtools_port, _open  # noqa: E402
from tools.qa.adblock_syntax_check import _launch  # noqa: E402
from tools.qa.cdp import WebSocket  # noqa: E402

PAGE_HOST = "power-page.test"
AD_HOST = "ads.power-page.test"
PAGE_URL = f"http://{PAGE_HOST}/page.html"
SETTINGS_URL = "chrome://adblock/"
MENU_URL = "chrome://adblock-menu.top-chrome/"
SETTLE_S = 2.5
FILTERS = f"||{AD_HOST}^\n{PAGE_HOST}##.banner"
PAGE = (f'<!doctype html><title>Thoron power check</title><div class="banner" id="b">an ad</div>'
        f'<img id="ad" src="http://{AD_HOST}/ad.png" width="20" height="20"><p>after</p>')
# a 1x1 transparent PNG
PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d4944415478da63f8ffff3f0005fe02fea7d6a5ff0000000049454e44ae426082")
READ_PAGE = "JSON.stringify({banner: getComputedStyle(document.getElementById('b')).display})"
READ_MENU = """JSON.stringify({pill: document.getElementById('everywhere').textContent,
  pressed: document.getElementById('everywhere').getAttribute('aria-pressed'),
  pause: document.getElementById('pause').hidden, state: document.getElementById('state').textContent,
  power: document.getElementById('power').getAttribute('aria-pressed')})"""
# CDP modifiers: Alt 1, Ctrl 2
CTRL_ALT = 3


def page_problems(step: str, seen: dict, *, blocking: bool) -> list[str]:
    """`seen`: the element's display and how often the image was asked for on the last load."""
    out = []
    if blocking and seen.get("asked"):
        out.append(f"{step}: the image of the blocked host was asked for ({seen})")
    if not blocking and not seen.get("asked"):
        out.append(f"{step}: the image was not asked for, blocking is still on ({seen})")
    if blocking and seen.get("banner") != "none":
        out.append(f"{step}: the element the rule hides shows ({seen})")
    if not blocking and seen.get("banner") == "none":
        out.append(f"{step}: the element is still hidden ({seen})")
    return out


def settings_problems(step: str, settings: dict, *, on: bool, state: str = "") -> list[str]:
    out = []
    if settings.get("blocking") is not on:
        out.append(f"{step}: chrome://adblock has blocking {settings.get('blocking')!r}, not {on}")
    if state and not str(settings.get("state", "")).startswith(state):
        out.append(f"{step}: chrome://adblock says {settings.get('state')!r}")
    return out


def menu_problems(step: str, seen: dict, *, on: bool, pause: bool = False) -> list[str]:
    out = []
    if seen.get("pressed") != ("true" if on else "false") or seen.get("pill") != ("On" if on else "Off"):
        out.append(f"{step}: the menu's switch shows {seen.get('pill')!r} ({seen.get('pressed')})")
    if seen.get("pause") is not (not pause):
        out.append(f"{step}: the menu's choices of how long are {'hidden' if seen.get('pause') else 'shown'}")
    if not on and not str(seen.get("state", "")).startswith("Thoron adblock is off for every site"):
        out.append(f"{step}: the menu says {seen.get('state')!r}")
    return out


def while_problems(back_at, now_ms: float) -> list[str]:
    """Off for one minute: back on about a minute from `now_ms`."""
    if not isinstance(back_at, (int, float)) or not now_ms + 40_000 <= back_at <= now_ms + 80_000:
        return [f"while: it comes back on at {back_at!r}, not about a minute from now"]
    return []


class Server:
    def __init__(self):
        self.asked = 0
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_GET(self):
                if self.path.startswith("/ad.png"):
                    server.asked += 1
                    body, kind = PNG, "image/png"
                else:
                    body, kind = PAGE.encode(), "text/html; charset=utf-8"
                self.send_response(200)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

        self._httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._httpd.daemon_threads = True
        self.port = self._httpd.server_address[1]

    def __enter__(self):
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self._httpd.shutdown()
        self._httpd.server_close()


def _eval(ws: WebSocket, expression: str):
    reply = ws.call("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True)
    if "exceptionDetails" in reply:
        raise RuntimeError(reply["exceptionDetails"].get("text", "the page threw"))
    return reply.get("result", {}).get("value")


def _call(ws: WebSocket, name: str, *args):
    """A message of chrome://adblock, as its own script sends it; its answer."""
    return json.loads(_eval(ws, "(async () => { const {sendWithPromise} = await import('chrome://resources/js/cr.js');"
                                f" return JSON.stringify(await sendWithPromise({json.dumps(name)},"
                                f" ...{json.dumps(list(args))})); }})()") or "null")


def run(browser: Path, work: Path) -> list[str]:
    problems: list[str] = []
    profile = Path(tempfile.mkdtemp(prefix="power-", dir=work))

    def report(step: str, found: list[str], seen) -> None:
        print(f"{'PASS' if not found else 'FAIL'}  {step}: {seen}")
        problems.extend(found)

    with Server() as server:
        proc = None
        port = None

        def start():
            nonlocal proc, port
            (profile / "DevToolsActivePort").unlink(missing_ok=True)  # it names the port of the run before
            proc = _launch(browser, profile, server.port, [PAGE_HOST, AD_HOST], native=True)
            port = _devtools_port(profile)
            settings = WebSocket(_open(port, SETTINGS_URL)["webSocketDebuggerUrl"])
            time.sleep(SETTLE_S)
            return settings

        def stop():
            nonlocal port
            _close_browser(port, proc)
            port = None

        def settings_now(settings: WebSocket) -> dict:
            """What the browser says, and what the page shows once it is looked at (a tab in the
            background gets its timers late; looked at again, it shows the switch at once)."""
            settings.call("Page.bringToFront")
            got = {}
            for _ in range(20):
                got = _call(settings, "getSettings") or {}
                got["state"] = _eval(settings, "document.getElementById('blocking-state').textContent")
                got["box"] = _eval(settings, "document.getElementById('blocking').checked")
                if got["box"] is got.get("blocking") and                         str(got["state"]).startswith("Thoron adblock is on" if got.get("blocking") else "Thoron adblock is off"):
                    break
                time.sleep(0.5)
            return got

        try:
            settings = start()
            answer = _call(settings, "setMyFilters", FILTERS)
            if answer:
                raise RuntimeError(f"the filters were not taken: {answer!r}")
            page = WebSocket(_open(port, PAGE_URL)["webSocketDebuggerUrl"])
            time.sleep(SETTLE_S)

            def load() -> dict:
                before = server.asked
                page.call("Page.reload", ignoreCache=True)
                time.sleep(SETTLE_S)
                seen = json.loads(_eval(page, READ_PAGE) or "{}")
                seen["asked"] = server.asked - before
                return seen

            seen = load()
            report("on", page_problems("on", seen, blocking=True), seen)

            # the box on chrome://adblock, as a person clicks it
            _eval(settings, "document.getElementById('blocking').click(); 1")
            time.sleep(1.5)
            now = settings_now(settings)
            seen = load()
            found = page_problems("off", seen, blocking=False)
            found += settings_problems("off", now, on=False, state="Thoron adblock is off for every site.")
            report("off", found, [seen, now.get("blocking"), now.get("state")])

            _eval(settings, "document.getElementById('blocking').click(); 1")
            time.sleep(1.5)
            now = settings_now(settings)
            seen = load()
            found = page_problems("back", seen, blocking=True)
            found += settings_problems("back", now, on=True, state="Thoron adblock is on for every site.")
            report("back", found, [seen, now.get("blocking"), now.get("state")])

            # the menu, opened as a tab: it acts on the tab before it, the page
            page.call("Page.bringToFront")
            menu = WebSocket(_open(port, MENU_URL)["webSocketDebuggerUrl"])
            try:
                time.sleep(SETTLE_S)
                found = menu_problems("menu", json.loads(_eval(menu, READ_MENU) or "{}"), on=True)
                _eval(menu, "document.getElementById('everywhere').click(); 1")
                time.sleep(0.5)
                asking = json.loads(_eval(menu, READ_MENU) or "{}")
                found += menu_problems("menu", asking, on=True, pause=True)
                before = server.asked
                _eval(menu, "document.querySelector('#pause [data-minutes=\"0\"]').click(); 1")
                time.sleep(SETTLE_S + 1)
                off = json.loads(_eval(menu, READ_MENU) or "{}")
                found += menu_problems("menu", off, on=False)
                if server.asked == before:
                    found.append("menu: the tab was not loaded again, or the image is still blocked")
                _eval(menu, "document.getElementById('power').click(); 1")
                time.sleep(SETTLE_S)
                back = json.loads(_eval(menu, READ_MENU) or "{}")
                found += menu_problems("menu", back, on=True)
                report("menu", found, [asking.get("pause"), off.get("pill"), off.get("state"), back.get("pill")])
            finally:
                menu.close()

            # the shortcut, on the page
            _call(settings, "setShortcut", "blocking", "Ctrl+Alt+Q")
            page.call("Page.bringToFront")

            def press() -> None:
                for kind in ("rawKeyDown", "keyUp"):
                    page.call("Input.dispatchKeyEvent", type=kind, modifiers=CTRL_ALT, code="KeyQ", key="q",
                              windowsVirtualKeyCode=81, nativeVirtualKeyCode=81)
                    time.sleep(0.1)
                time.sleep(SETTLE_S)

            press()
            first = (_call(settings, "getSettings") or {}).get("blocking")
            press()
            second = (_call(settings, "getSettings") or {}).get("blocking")
            found = [] if (first, second) == (False, True) else [f"shortcut: blocking went {first!r}, {second!r}"]
            report("shortcut", found, [first, second])

            # off for a minute
            now_ms = time.time() * 1000
            answer = _call(settings, "setBlocking", False, 1)
            time.sleep(6)  # the page shows the switch again every five seconds
            now = settings_now(settings)
            if answer != "":
                problems.append(f"while: the page answered {answer!r}")
            found = settings_problems("while", now, on=False, state="Thoron adblock is off for every site until ")
            found += while_problems(now.get("blocking-back"), now_ms)
            back_at = now.get("blocking-back") if isinstance(now.get("blocking-back"), (int, float)) else now_ms
            time.sleep(max(0.0, (back_at - time.time() * 1000) / 1000) + 6)
            later = settings_now(settings)
            found += settings_problems("while", later, on=True, state="Thoron adblock is on for every site.")
            seen = load()
            found += page_problems("while", seen, blocking=True)
            report("while", found, [now.get("state"), later.get("blocking"), seen])
            page.close()

            # kept: off for good, then off until the browser closes
            if settings_now(settings).get("box") is not True:
                problems.append("kept: the page does not show blocking as on before it is switched off")
            _eval(settings, "document.getElementById('blocking').click(); 1")
            time.sleep(1.5)
            settings.close()
            stop()
            settings = start()
            first = settings_now(settings)
            # "Until the browser closes", as a person clicks it
            _eval(settings, "document.querySelector('#power-section [data-minutes=\"-1\"]').click(); 1")
            time.sleep(1.5)
            closing = settings_now(settings)
            settings.close()
            stop()
            settings = start()
            second = settings_now(settings)
            found = settings_problems("kept", first, on=False)
            found += settings_problems("kept", closing, on=False,
                                       state="Thoron adblock is off for every site until the browser closes.")
            found += settings_problems("kept", second, on=True)
            report("kept", found, [first.get("blocking"), closing.get("state"), second.get("blocking")])
            settings.close()
        except (OSError, RuntimeError, ValueError, KeyError, TypeError) as e:
            problems.append(f"the run failed: {e}")
        finally:
            if port is not None:
                _close_browser(port, proc)
            elif proc is not None and proc.poll() is None:
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
    print("POWER CHECK: PASSED" if not problems else f"POWER CHECK: FAILED ({len(problems)} problem(s))")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
