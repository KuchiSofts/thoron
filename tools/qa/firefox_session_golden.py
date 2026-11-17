#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""A golden Firefox session file for the Firefox session reader (ROADMAP P4.8), made by real Firefox. Windows only.

Firefox starts headless (no window on the screen) with a throwaway profile. Every connection that is not to
127.0.0.1 goes to a proxy that is not there, so it asks nothing of the network. It is driven through its own
remote protocol (Marionette, from Firefox's chrome code), and it builds the same session as
`session_golden.py` builds in Chromium browsers:
two windows, the second one minimized; a pinned tab; a group "Work" (blue, two tabs), a collapsed group "Later"
(red) and, in the second window, a group whose title has accented letters; tabs with several pages of history,
one of them taken back a page; a chosen tab in each window; and a closed tab. Pages come from a local server on
127.0.0.1. Then Firefox quits the normal way, so it writes `sessionstore.jsonlz4`, which is copied out as it is
together with its reading (`expected.json`, made by `tools/migrate/firefox_sessions.py`).

The profile is deleted afterwards. The file holds only what this run made (the local pages, their titles and
Firefox's own bookkeeping); the check refuses one that names a user folder.
    py -3 -I tools/qa/firefox_session_golden.py --firefox "C:\\Program Files\\Mozilla Firefox\\firefox.exe"
        --work <scratch dir> --out tools/migrate/tests/data/sessions/firefox
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.migrate import firefox_sessions as fs  # noqa: E402
from tools.qa import session_golden as golden  # noqa: E402

DEFAULT_FIREFOX = Path(r"C:\Program Files\Mozilla Firefox\firefox.exe")
DEAD_PROXY_PORT = 9          # the discard port: nothing answers on it

PREFS = {
    # every connection except to 127.0.0.1 goes to a proxy that is not there
    "network.proxy.type": 1, "network.proxy.http": "127.0.0.1", "network.proxy.http_port": DEAD_PROXY_PORT,
    "network.proxy.ssl": "127.0.0.1", "network.proxy.ssl_port": DEAD_PROXY_PORT,
    "network.proxy.socks": "127.0.0.1", "network.proxy.socks_port": DEAD_PROXY_PORT,
    "network.proxy.no_proxies_on": "127.0.0.1", "network.proxy.allow_hijacking_localhost": False,
    "network.dns.disableIPv6": True, "network.trr.mode": 5,
    # nothing reported, checked or shown at a first start
    "datareporting.policy.dataSubmissionEnabled": False, "datareporting.healthreport.uploadEnabled": False,
    "toolkit.telemetry.enabled": False, "toolkit.telemetry.reportingpolicy.firstRun": False,
    "app.update.disabledForTesting": True, "app.normandy.enabled": False, "browser.safebrowsing.malware.enabled": False,
    "browser.safebrowsing.phishing.enabled": False, "browser.shell.checkDefaultBrowser": False,
    "browser.startup.page": 0, "browser.startup.homepage": "about:blank",
    "browser.startup.homepage_override.mstone": "ignore", "browser.newtabpage.enabled": False,
    "browser.aboutwelcome.enabled": False, "browser.tabs.warnOnClose": False,
    "browser.tabs.groups.enabled": True,
    # the session is written at the end, and nothing is left out of it
    "browser.sessionstore.resume_from_crash": True, "browser.sessionstore.privacy_level": 0,
}

BUILD_JS = r"""
const [base, notes] = arguments;
return (async () => {
const sys = Services.scriptSecurityManager.getSystemPrincipal();
const first = Services.wm.getMostRecentWindow("navigator:browser");
const pause = (win, ms) => new Promise(r => win.setTimeout(r, ms));

async function settled(win, tab, url) {
  for (let i = 0; i < 200; i++) {
    await pause(win, 50);
    const b = tab.linkedBrowser;
    if (b.currentURI.spec === url && !tab.hasAttribute("busy") && !b.webProgress?.isLoadingDocument) {
      await pause(win, 150);
      return;
    }
  }
  throw new Error("did not load " + url);
}
async function go(win, tab, name) {
  const url = base + name;
  tab.linkedBrowser.fixupAndLoadURIString(url, {triggeringPrincipal: sys});
  await settled(win, tab, url);
}
async function tabWith(win, names, reuse) {
  const g = win.gBrowser;
  const tab = reuse || g.addTab("about:blank", {triggeringPrincipal: sys});
  for (const name of names) await go(win, tab, name);
  return tab;
}
async function back(win, tab, name) {
  tab.linkedBrowser.goBack();
  await settled(win, tab, base + name);
}

// the first window: pinned, "Work" (blue), "Later" (red, collapsed), a plain tab that is chosen
const g1 = first.gBrowser;
const pinned = await tabWith(first, ["pinned-1", "pinned-2"], g1.tabs[0]);
g1.pinTab(pinned);
const workA = await tabWith(first, ["work-a1", "work-a2", "work-a3"]);
await back(first, workA, "work-a2");
const workB = await tabWith(first, ["work-b1"]);
const laterC = await tabWith(first, ["later-c1", "later-c2"]);
const plainD = await tabWith(first, ["plain-d1", "plain-d2", "plain-d3"]);
const closed = await tabWith(first, ["closed-x1", "closed-x2"]);
g1.removeTab(closed, {animate: false});
g1.addTabGroup([workA, workB], {color: "blue", label: "Work", insertBefore: workA});
const later = g1.addTabGroup([laterC], {color: "red", label: "Later", insertBefore: laterC});
g1.selectedTab = plainD;
later.collapsed = true;

// the second window: a group with accented letters in its title, a plain tab that is chosen, minimized
const second = first.OpenBrowserWindow();
await new Promise(resolve => {
  const seen = subject => {
    if (subject === second) {
      Services.obs.removeObserver(seen, "browser-delayed-startup-finished");
      resolve();
    }
  };
  Services.obs.addObserver(seen, "browser-delayed-startup-finished");
});
const g2 = second.gBrowser;
const notesE = await tabWith(second, ["notes-e1"], g2.tabs[0]);
const otherF = await tabWith(second, ["other-f1", "other-f2"]);
g2.addTabGroup([notesE], {color: "green", label: notes, insertBefore: notesE});
g2.selectedTab = otherF;
second.minimize();
first.focus();
await pause(first, 2000);
return {first: g1.tabs.length, second: g2.tabs.length};
})();
"""


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Marionette:
    """Firefox's remote protocol: `<length>:<json>` messages, commands `[0, id, name, parameters]`."""

    def __init__(self, port: int, limit: float = 60):
        end = time.monotonic() + limit
        while True:
            try:
                self.sock = socket.create_connection(("127.0.0.1", port), timeout=5)
                break
            except OSError:
                if time.monotonic() > end:
                    raise RuntimeError("Firefox's remote protocol did not answer")
                time.sleep(0.5)
        self.sock.settimeout(180)
        self.buffer = b""
        self.next_id = 0
        self.hello = self._read()

    def _read(self):
        while b":" not in self.buffer:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise RuntimeError("Firefox closed its remote protocol")
            self.buffer += chunk
        length, _, rest = self.buffer.partition(b":")
        size = int(length)
        while len(rest) < size:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise RuntimeError("Firefox closed its remote protocol")
            rest += chunk
        self.buffer = rest[size:]
        return json.loads(rest[:size])

    def call(self, name: str, params: dict | None = None):
        self.next_id += 1
        body = json.dumps([0, self.next_id, name, params or {}]).encode("utf-8")
        self.sock.sendall(str(len(body)).encode() + b":" + body)
        while True:
            reply = self._read()
            if isinstance(reply, list) and reply[:2] == [1, self.next_id]:
                if reply[2]:
                    raise RuntimeError(f"{name}: {reply[2].get('error')}: {reply[2].get('message')}")
                return reply[3]

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def build(firefox: Path, work: Path, out: Path) -> dict:
    profile = Path(tempfile.mkdtemp(prefix="firefox-golden-", dir=work))
    port = free_port()
    prefs = {**PREFS, "marionette.port": port}
    (profile / "user.js").write_text("".join(f"user_pref({json.dumps(k)}, {json.dumps(v)});\n"
                                             for k, v in prefs.items()), encoding="utf-8")
    proc = None
    try:
        with golden.PageServer() as server:
            # Firefox's chrome code (where tabs, groups and windows are made) needs system access
            env = {**os.environ, "MOZ_REMOTE_ALLOW_SYSTEM_ACCESS": "1"}
            proc = subprocess.Popen([str(firefox), "-headless", "-no-remote", "-profile", str(profile), "-marionette",
                                     "-remote-allow-system-access"],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
            m = Marionette(port)
            try:
                m.call("WebDriver:NewSession", {"capabilities": {}})
                m.call("WebDriver:SetTimeouts", {"script": 170000})
                m.call("Marionette:SetContext", {"value": "chrome"})
                built = m.call("WebDriver:ExecuteScript", {"script": BUILD_JS, "args": [server.base, golden.NOTES]})
                m.call("Marionette:Quit", {"flags": ["eAttemptQuit"]})
            finally:
                m.close()
            proc.wait(timeout=120)
        written = profile / "sessionstore.jsonlz4"
        if not written.is_file():
            raise RuntimeError("Firefox wrote no sessionstore.jsonlz4")
        data = written.read_bytes()
        problems = fs.private_problems(fs.decode_mozlz4(data))
        if problems:
            raise RuntimeError(f"the session names something of this PC: {problems}")
        out.mkdir(parents=True, exist_ok=True)
        (out / "sessionstore.jsonlz4").write_bytes(data)
        reading = fs.read_firefox_session(data)
        (out / "expected.json").write_text(json.dumps(reading, ensure_ascii=False, indent=1) + "\n", encoding="utf-8",
                                           newline="\n")
        return {"built": built, "reading": reading}
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--firefox", type=Path, default=DEFAULT_FIREFOX)
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args(argv)
    a.work.mkdir(parents=True, exist_ok=True)
    result = build(a.firefox, a.work.resolve(), a.out)
    reading = result["reading"]
    print(f"firefox golden: {result['built']} tabs; written to {a.out}")
    problems = plan_problems(reading)
    for problem in problems:
        print(f"  differs from the plan: {problem}")
    return 0


def base_of(reading: dict) -> str:
    """The pages' address (`http://127.0.0.1:<port>/p/`) as the session names it."""
    url = reading["windows"][0]["tabs"][0]["navigations"][0]["url"]
    return url[:url.index("/p/") + 3]


def plan_problems(reading: dict) -> list[str]:
    """Where Firefox's session differs from the session that was built."""
    plan = golden.expected_plan(base_of(reading), True)
    shaped = golden.shape(reading, {"entries": [{"kind": "tab", **t} for t in reading["closed_tabs"]]})
    return golden.plan_problems(plan, shaped)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
