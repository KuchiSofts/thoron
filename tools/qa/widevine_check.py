#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Widevine is not shipped and still works when a site needs it (ROADMAP P2.6). ONLINE, unlike the other
checks: run it on purpose.

Thoron does not ship Google's Widevine module (it may not be redistributed; `tools/release/package_audit.py`
checks the package). The browser downloads it from Google's component updater when it is needed, as Chromium
does. This check uses a throwaway profile and asks for it the way chrome://components does. It contacts
Google's update server and, for the last step, a public demo of the Shaka Player project with a Widevine test
stream. Steps:

    absent    on a fresh profile the browser has no Widevine module (version 0.0.0.0)
    fetched   asked for, the component updater downloads and installs it
    keys      a page gets Widevine through Encrypted Media Extensions: key system access, media keys, and
              a licence request from the module for a test key id (after a restart of the browser if the
              running one cannot load the new module)
    plays     the demo's Widevine test stream plays (its time moves on)

    py -3 -I tools/qa/widevine_check.py --browser <out>\\thoron.exe --work <scratch dir> [--no-playback]
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

COMPONENTS_URL = "chrome://components/"
# the component updater's id of the Widevine module
WIDEVINE_ID = "oimompecagnajdejgnnjijobebaeigek"
FETCH_S = 240
DEMO = ("https://shaka-player-demo.appspot.com/demo/#audiolang=en;textlang=en;"
        "asset=https://storage.googleapis.com/shaka-demo-assets/angel-one-widevine/dash.mpd;play")
VERSION = ("import('chrome://resources/js/cr.js').then((cr) => cr.sendWithPromise('requestComponentsData'))"
           ".then((d) => JSON.stringify((d.components || []).filter((c) => c.id === '%s')"
           ".map((c) => ({version: c.version, status: c.status}))[0] || null))" % WIDEVINE_ID)
ASK = "chrome.send('checkUpdate', ['%s']); JSON.stringify('asked')" % WIDEVINE_ID
# Encrypted Media Extensions with a 'cenc' box that names Widevine and one test key id: the module answers
# with a message (a licence request) when it is there and works.
KEYS = """(async () => {
  const kid = new Uint8Array(16).fill(7);
  const data = new Uint8Array([0x08, 0x01, 0x12, 0x10, ...kid]);
  const system = [0xed, 0xef, 0x8b, 0xa9, 0x79, 0xd6, 0x4a, 0xce, 0xa3, 0xc8, 0x27, 0xdc, 0xd5, 0x1d, 0x21, 0xed];
  const size = 32 + data.length;
  const box = new Uint8Array([0, 0, 0, size, 0x70, 0x73, 0x73, 0x68, 0, 0, 0, 0, ...system,
                              0, 0, 0, data.length, ...data]);
  try {
    const access = await navigator.requestMediaKeySystemAccess('com.widevine.alpha', [{
      initDataTypes: ['cenc'],
      videoCapabilities: [{contentType: 'video/mp4; codecs="avc1.42E01E"', robustness: 'SW_SECURE_CRYPTO'}],
    }]);
    const keys = await access.createMediaKeys();
    const session = keys.createSession();
    const bytes = await new Promise((done, fail) => {
      session.addEventListener('message', (e) => done(e.message.byteLength));
      session.generateRequest('cenc', box.buffer).catch((e) => fail(e));
      setTimeout(() => fail(new Error('no message from the module in 20 s')), 20000);
    });
    return JSON.stringify({access: true, message: bytes});
  } catch (e) {
    return JSON.stringify({access: false, error: String(e && e.name ? e.name + ': ' + e.message : e)});
  }
})()"""
PLAYING = """(() => { const v = document.querySelector('video');
  return JSON.stringify(v ? {time: v.currentTime, error: v.error ? v.error.message : '', ready: v.readyState}
                          : null); })()"""


def absent_problems(found: dict | None) -> list[str]:
    if found is None:
        return ["absent: the browser does not list a Widevine component at all (support is off)"]
    if found.get("version") not in ("0.0.0.0", ""):
        return [f"absent: a fresh profile already has Widevine {found.get('version')}"]
    return []


def fetched_problems(found: dict | None) -> list[str]:
    if not found or found.get("version") in ("0.0.0.0", "", None):
        return [f"fetched: the module was not installed ({found})"]
    return []


def keys_problems(found: dict) -> list[str]:
    if not found.get("access"):
        return [f"keys: no Widevine for the page: {found.get('error')}"]
    if not found.get("message"):
        return ["keys: the module made no licence request"]
    return []


def plays_problems(samples: list[dict | None]) -> list[str]:
    times = [s["time"] for s in samples if s]
    if not times:
        return ["plays: the demo page shows no video"]
    errors = [s["error"] for s in samples if s and s.get("error")]
    if errors:
        return [f"plays: the video failed: {errors[-1]}"]
    if max(times) - min(times) < 2.0:
        return [f"plays: the stream's time did not move on ({min(times):.1f} s to {max(times):.1f} s)"]
    return []


class Local:
    """A local page (a secure context) for the page's own requests."""

    def __init__(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                body = b"<!doctype html><title>widevine check</title><p>page"
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
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


def _launch(browser: Path, profile: Path) -> subprocess.Popen:
    # no --disable-component-update and no --disable-background-networking: the module comes that way
    args = [str(browser), "--headless=new", f"--user-data-dir={profile}", "--no-first-run",
            "--no-default-browser-check", "--disable-default-apps", "--mute-audio",
            "--autoplay-policy=no-user-gesture-required", "--window-size=1280,800",
            "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0", "about:blank"]
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _eval(ws: WebSocket, expression: str):
    reply = ws.call("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True)
    return json.loads(reply.get("result", {}).get("value") or "null")


def _keys(port: int, local_port: int) -> dict:
    page = WebSocket(_open(port, f"http://127.0.0.1:{local_port}/")["webSocketDebuggerUrl"])
    try:
        time.sleep(1.5)
        return _eval(page, KEYS) or {}
    finally:
        page.close()


def run(browser: Path, work: Path, playback: bool) -> list[str]:
    profile = Path(tempfile.mkdtemp(prefix="widevine-", dir=work))
    problems: list[str] = []

    def report(step: str, found: list[str], detail) -> None:
        print(f"{'PASS' if not found else 'FAIL'}  {step}: {detail}")
        problems.extend(found)

    with Local() as local:
        proc = _launch(browser, profile)
        port = None
        try:
            port = _devtools_port(profile)
            components = WebSocket(_open(port, COMPONENTS_URL)["webSocketDebuggerUrl"])
            time.sleep(3)
            first = _eval(components, VERSION)
            report("absent", absent_problems(first), first)
            if first is None:
                return problems

            _eval(components, ASK)
            found = first
            for _ in range(FETCH_S // 3):
                time.sleep(3)
                found = _eval(components, VERSION)
                if found and found.get("version") not in ("0.0.0.0", ""):
                    break
            report("fetched", fetched_problems(found), found)
            components.close()
            if fetched_problems(found):
                return problems

            keys = _keys(port, local.port)
            restarted = False
            if keys_problems(keys):
                # the running browser may only load a new module after a restart
                _close_browser(port, proc)
                port = None
                (profile / "DevToolsActivePort").unlink(missing_ok=True)
                proc = _launch(browser, profile)
                port = _devtools_port(profile)
                time.sleep(3)
                keys = _keys(port, local.port)
                restarted = True
            report("keys", keys_problems(keys), f"{keys}{' (after a restart)' if restarted else ''}")

            if playback:
                demo = WebSocket(_open(port, DEMO)["webSocketDebuggerUrl"])
                samples = []
                for _ in range(15):
                    time.sleep(3)
                    samples.append(_eval(demo, PLAYING))
                    times = [s["time"] for s in samples if s]
                    if times and max(times) - min(times) >= 2.0:
                        break
                demo.close()
                last = next((s for s in reversed(samples) if s), None)
                report("plays", plays_problems(samples), last)
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
    p.add_argument("--no-playback", action="store_true", help="leave out the demo stream (the last step)")
    a = p.parse_args(argv)
    sys.stdout.reconfigure(errors="backslashreplace")
    a.work.mkdir(parents=True, exist_ok=True)
    problems = run(a.browser.resolve(), a.work, not a.no_playback)
    for problem in problems:
        print(problem)
    print("WIDEVINE CHECK: PASSED" if not problems else f"WIDEVINE CHECK: FAILED ({len(problems)} problem(s))")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
