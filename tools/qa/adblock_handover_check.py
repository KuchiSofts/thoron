#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Native ad blocking on by default, and the hand-over from uBlock Origin, checked end to end and offline
(ROADMAP P5.17, P5.24).

The browser is started as a person starts it, without switches for the blocker and with its preinstalled
extensions. A local server serves a page with an image from a host a rule of My filters blocks (host-resolver
rules; every other name fails, so nothing leaves the PC). Steps:

    default   a new profile: the built-in blocker is on with no switch (the image is never asked for), and no
              uBlock Origin is put into it
    off       "Built-in ad blocking" off: a new profile gets the built-in uBlock Origin, as before
    kept      that profile started again with the built-in blocker on: uBlock Origin is still there and on
    both      the menu says that both are on; "Keep both" hides it for good, also when the menu opens again

    py -3 -I tools/qa/adblock_handover_check.py --browser <out>\\thoron.exe --work <scratch dir>
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
from tools.qa.adblock_syntax_check import NO_HTTPS_FIRST  # noqa: E402
from tools.qa.cdp import WebSocket  # noqa: E402

UBO_ID = "fkgkibajhfbepljeaefdnfnegdcjomkh"
PAGE_HOST = "handover-page.test"
AD_HOST = "ads.handover-page.test"
SETTINGS_URL = "chrome://adblock/"
MENU_URL = "chrome://adblock-menu.top-chrome/"
SETTLE_S = 2.5
INSTALL_WAIT_S = 60
PAGE = f'<!doctype html><title>Thoron hand-over check</title><img id="ad" src="http://{AD_HOST}/ad.png">'
READ_BOTH = "JSON.stringify({shown: !document.getElementById('both-box').hidden})"


def installed(profile: Path) -> bool:
    """uBlock Origin unpacked into the profile's extensions."""
    folder = profile / "Default" / "Extensions" / UBO_ID
    return folder.is_dir() and any(folder.iterdir())


def default_problems(asked: int, has_ubo: bool, blocking) -> list[str]:
    out = []
    if blocking is not True:
        out.append(f"default: chrome://adblock has blocking {blocking!r}")
    if asked:
        out.append(f"default: the image of the blocked host was asked for {asked} time(s)")
    if has_ubo:
        out.append("default: a new profile got the built-in uBlock Origin next to the built-in blocker")
    return out


def both_problems(first: dict, after_keep: dict, again: dict) -> list[str]:
    out = []
    if not first.get("shown"):
        out.append("both: the menu does not say that uBlock Origin is on as well")
    if after_keep.get("shown"):
        out.append("both: \"Keep both\" did not hide it")
    if again.get("shown"):
        out.append("both: it shows again after \"Keep both\"")
    return out


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
                body = PAGE.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
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


def _start(browser: Path, profile: Path, port: int, native_off: bool = False) -> subprocess.Popen:
    """As a person starts it: no switch for the blocker, preinstalled extensions on (no
    --disable-default-apps); only what keeps the run offline and plain http."""
    mapping = f"MAP {PAGE_HOST} 127.0.0.1:{port}, MAP {AD_HOST} 127.0.0.1:{port}"
    disable = NO_HTTPS_FIRST + (",ThoronNativeAdblock" if native_off else "")
    args = [str(browser), "--headless=new", f"--user-data-dir={profile}", "--no-first-run",
            "--no-default-browser-check", "--disable-background-networking", "--disable-component-update",
            f"--disable-features={disable}", f"--host-resolver-rules={mapping}, MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
            "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0", "about:blank"]
    (profile / "DevToolsActivePort").unlink(missing_ok=True)
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _eval(ws: WebSocket, expression: str):
    reply = ws.call("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True)
    if "exceptionDetails" in reply:
        raise RuntimeError(reply["exceptionDetails"].get("text", "the page threw"))
    return reply.get("result", {}).get("value")


def _call(ws: WebSocket, name: str, *args):
    return json.loads(_eval(ws, "(async () => { const {sendWithPromise} = await import('chrome://resources/js/cr.js');"
                                f" return JSON.stringify(await sendWithPromise({json.dumps(name)},"
                                f" ...{json.dumps(list(args))})); }})()") or "null")


def _wait_installed(profile: Path, seconds: float) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if installed(profile):
            return True
        time.sleep(1)
    return installed(profile)


def run(browser: Path, work: Path) -> list[str]:
    problems: list[str] = []

    def report(step: str, found: list[str], seen) -> None:
        print(f"{'PASS' if not found else 'FAIL'}  {step}: {seen}")
        problems.extend(found)

    with Server() as server:
        # default: a new profile, nothing switched
        profile = Path(tempfile.mkdtemp(prefix="handover-new-", dir=work))
        proc, port = _start(browser, profile, server.port), None
        try:
            port = _devtools_port(profile)
            settings = WebSocket(_open(port, SETTINGS_URL)["webSocketDebuggerUrl"])
            time.sleep(SETTLE_S)
            answer = _call(settings, "setMyFilters", f"||{AD_HOST}^")
            if answer:
                raise RuntimeError(f"the filters were not taken: {answer!r}")
            blocking = (_call(settings, "getSettings") or {}).get("blocking")
            settings.close()
            before = server.asked
            page = WebSocket(_open(port, f"http://{PAGE_HOST}/page.html")["webSocketDebuggerUrl"])
            time.sleep(SETTLE_S)
            page.close()
            has_ubo = _wait_installed(profile, 20)   # it would be put in within seconds of the start
            report("default", default_problems(server.asked - before, has_ubo, blocking),
                   {"blocking": blocking, "asked": server.asked - before, "ubo": has_ubo})
        except (OSError, RuntimeError, ValueError, KeyError, TypeError) as e:
            problems.append(f"default: the run failed: {e}")
        finally:
            if port is not None:
                _close_browser(port, proc)
            elif proc.poll() is None:
                bench._stop(proc, profile)
            shutil.rmtree(profile, ignore_errors=True)

        # off: the built-in blocker switched off, a new profile; then kept and both
        profile = Path(tempfile.mkdtemp(prefix="handover-old-", dir=work))
        proc, port = _start(browser, profile, server.port, native_off=True), None
        try:
            port = _devtools_port(profile)
            got = _wait_installed(profile, INSTALL_WAIT_S)
            report("off", [] if got else ["off: with the built-in blocker off, a new profile got no uBlock Origin"],
                   {"ubo": got})
            _close_browser(port, proc)
            port = None
            if got:
                proc = _start(browser, profile, server.port)
                port = _devtools_port(profile)
                time.sleep(SETTLE_S + 2)
                extensions = WebSocket(_open(port, "chrome://extensions/")["webSocketDebuggerUrl"])
                time.sleep(SETTLE_S)
                info = json.loads(_eval(extensions, "new Promise((done) => chrome.developerPrivate.getExtensionInfo("
                                                    f"{json.dumps(UBO_ID)}, (i) => done(JSON.stringify(i ? "
                                                    "{state: i.state} : {}))))") or "{}")
                extensions.close()
                kept = installed(profile) and info.get("state") == "ENABLED"
                report("kept", [] if kept else [f"kept: uBlock Origin is {info or 'gone'}"], info)

                page = WebSocket(_open(port, f"http://{PAGE_HOST}/page.html")["webSocketDebuggerUrl"])
                time.sleep(SETTLE_S)
                menu = WebSocket(_open(port, MENU_URL)["webSocketDebuggerUrl"])
                time.sleep(SETTLE_S)
                first = json.loads(_eval(menu, READ_BOTH) or "{}")
                _eval(menu, "document.getElementById('both-keep').click(); 1")
                time.sleep(0.5)
                after_keep = json.loads(_eval(menu, READ_BOTH) or "{}")
                menu.close()
                menu = WebSocket(_open(port, MENU_URL)["webSocketDebuggerUrl"])
                time.sleep(SETTLE_S)
                again = json.loads(_eval(menu, READ_BOTH) or "{}")
                menu.close()
                page.close()
                report("both", both_problems(first, after_keep, again), [first, after_keep, again])
        except (OSError, RuntimeError, ValueError, KeyError, TypeError) as e:
            problems.append(f"off/kept/both: the run failed: {e}")
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
    p.add_argument("--work", required=True, type=Path, help="scratch folder for the throwaway profiles")
    a = p.parse_args(argv)
    a.work.mkdir(parents=True, exist_ok=True)
    problems = run(a.browser.resolve(), a.work)
    for problem in problems:
        print(problem)
    print("HANDOVER CHECK: PASSED" if not problems else f"HANDOVER CHECK: FAILED ({len(problems)} problem(s))")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
