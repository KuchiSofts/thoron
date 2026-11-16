#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Golden session files for the session reader (ROADMAP P3.15), made by a real browser. Windows only.

The browser starts with a window (off the screen), a throwaway profile, offline (host-resolver rules; only
127.0.0.1 answers) and a small test extension that builds a known session through the tabs and tabGroups APIs:
two windows, the second one minimized; a pinned tab; a group "Work" (blue, two tabs), a collapsed group "Later"
(red) and, in the second window, a group whose title has accented letters; tabs with several pages of history,
one of them taken back a page; a chosen tab in each window; and a closed tab for the recently closed list. Pages
come from a local server on 127.0.0.1. Then the browser is closed the normal way (DevTools `Browser.close`) so it
writes its session, and the newest `Session_` and `Tabs_` files are copied out with what describes this PC
taken out (window bounds, which depend on the screen, and the virtual desktop's id); every other byte stays as
the browser wrote it. The reading of the copies must be the session that was built; it is written beside them
as `expected.json`.

What the browser writes, not what was asked, is the golden file: a page's title is saved when the page's state
is next synced, so a tab that was never shown can keep an empty title; and closing the windows at the exit adds
them to the recently closed list.

A browser that ignores `--load-extension` gets the same windows, tabs and history through DevTools alone,
without the pinned tab and the groups, which only an extension can make; it says so.
    py -3 -I tools/qa/session_golden.py --browser <path>\\chrome.exe --work <scratch dir>
        --out tools/migrate/tests/data/sessions/chrome [--port 47615]
"""
from __future__ import annotations

import argparse
import ctypes
import http.server
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.migrate import sessions  # noqa: E402
from tools.qa.cdp import WebSocket  # noqa: E402

PORT = 47615
TITLE = "Thoron session test "
NAME_RE = re.compile(r"^/p/([a-z0-9-]{1,40})$")
SAVE_WAIT_S = 4          # the browser writes its session a few seconds after a change
# where the copies put every window: off the screen, the same on every PC
BOUNDS = (-4000, -4000, 800, 600)
EXTENSION = {"manifest_version": 3, "name": "Thoron session test", "version": "1",
             "permissions": ["tabs", "tabGroups"], "background": {"service_worker": "bg.js"}}
NOTES = "Notes éü"


def page(name: str) -> bytes:
    return f"<!doctype html><meta charset='utf-8'><title>{TITLE}{name}</title><p>{name}</p>".encode()


class PageServer:
    """Serves /p/<name> on 127.0.0.1 with the title "Thoron session test <name>"."""

    def __init__(self, port: int = 0):
        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_GET(self):
                match = NAME_RE.match(self.path)
                body = page(match.group(1)) if match else b"not found"
                self.send_response(200 if match else 404)
                self.send_header("Content-Type", "text/html; charset=utf-8" if match else "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

        class Server(http.server.ThreadingHTTPServer):
            daemon_threads = True

            def handle_error(self, request, client_address):
                pass                    # a browser that closes drops its connections; nothing to report

        self._httpd = Server(("127.0.0.1", port), Handler)
        self.port = self._httpd.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}/p/"

    def __enter__(self):
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self._httpd.shutdown()
        self._httpd.server_close()


def browser_args(browser: Path, profile: Path, extension: Path | None, urls: list[str]) -> list[str]:
    args = [str(browser), f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
            "--disable-background-networking", "--disable-component-update", "--disable-default-apps",
            "--disable-sync", "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
            "--window-position=-4000,-4000", "--window-size=800,600",
            "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0"]
    if extension is not None:
        # Google Chrome 137 and later ignore --load-extension unless this feature is turned off
        args += [f"--load-extension={extension}", "--disable-features=DisableLoadExtensionCommandLineSwitch"]
    return args + urls


def launch(args: list[str]) -> subprocess.Popen:
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class PipeBrowser:
    """A browser started with `--remote-debugging-pipe` on Windows: DevTools messages go through two anonymous
    pipes that the browser's C runtime opens as its file descriptors 3 (it reads) and 4 (it writes), handed over
    the way the C runtime takes them from its parent (STARTUPINFO.lpReserved2). Google Chrome loads an unpacked
    extension only for such a client (`Extensions.loadUnpacked`)."""

    def __init__(self, args: list[str]):
        import msvcrt
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle, dword = wintypes.HANDLE, wintypes.DWORD
        k32.CreatePipe.argtypes = [ctypes.POINTER(handle), ctypes.POINTER(handle), ctypes.c_void_p, dword]
        k32.SetHandleInformation.argtypes = [handle, dword, dword]
        k32.CloseHandle.argtypes = [handle]
        k32.WaitForSingleObject.argtypes = [handle, dword]
        k32.WaitForSingleObject.restype = dword
        k32.GetExitCodeProcess.argtypes = [handle, ctypes.POINTER(dword)]
        k32.CreateProcessW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
                                       wintypes.BOOL, dword, ctypes.c_void_p, wintypes.LPCWSTR, ctypes.c_void_p,
                                       ctypes.c_void_p]

        class SecurityAttributes(ctypes.Structure):
            _fields_ = [("nLength", wintypes.DWORD), ("lpSecurityDescriptor", wintypes.LPVOID),
                        ("bInheritHandle", wintypes.BOOL)]

        class StartupInfo(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR), ("lpDesktop", wintypes.LPWSTR),
                        ("lpTitle", wintypes.LPWSTR), ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
                        ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
                        ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD),
                        ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                        ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
                        ("lpReserved2", ctypes.c_void_p), ("hStdInput", wintypes.HANDLE),
                        ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE)]

        class ProcessInformation(ctypes.Structure):
            _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                        ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]

        def pipe() -> tuple[int, int]:
            sa = SecurityAttributes(ctypes.sizeof(SecurityAttributes), None, True)
            read, write = wintypes.HANDLE(), wintypes.HANDLE()
            if not k32.CreatePipe(ctypes.byref(read), ctypes.byref(write), ctypes.byref(sa), 1 << 20):
                raise OSError(ctypes.get_last_error(), "CreatePipe failed")
            return read.value, write.value

        to_child_read, to_child_write = pipe()
        from_child_read, from_child_write = pipe()
        for mine in (to_child_write, from_child_read):        # only the browser's ends are inherited
            k32.SetHandleInformation(mine, 1, 0)
        count, fopen_pipe = 5, 0x01 | 0x08                      # FOPEN | FPIPE
        block = (struct.pack("<i", count) + bytes([0, 0, 0, fopen_pipe, fopen_pipe])
                 + struct.pack("<5q", -1, -1, -1, to_child_read, from_child_write))
        buffer = ctypes.create_string_buffer(block, len(block))
        self._null = open(os.devnull, "r+b")                    # the browser's console output goes nowhere
        null = msvcrt.get_osfhandle(self._null.fileno())
        os.set_handle_inheritable(null, True)
        si = StartupInfo()
        si.cb = ctypes.sizeof(StartupInfo)
        si.dwFlags = 0x100                                      # STARTF_USESTDHANDLES
        si.hStdInput = si.hStdOutput = si.hStdError = null
        si.cbReserved2 = len(block)
        si.lpReserved2 = ctypes.cast(buffer, ctypes.c_void_p)
        pi = ProcessInformation()
        line = ctypes.create_unicode_buffer(subprocess.list2cmdline(args))
        if not k32.CreateProcessW(None, line, None, None, True, 0, None, None, ctypes.byref(si), ctypes.byref(pi)):
            raise OSError(ctypes.get_last_error(), "CreateProcessW failed")
        for theirs in (to_child_read, from_child_write):
            k32.CloseHandle(theirs)
        k32.CloseHandle(pi.hThread)
        self._k32, self._process, self.pid = k32, pi.hProcess, pi.dwProcessId
        self._out = os.fdopen(msvcrt.open_osfhandle(to_child_write, os.O_WRONLY | os.O_BINARY), "wb", buffering=0)
        self._in = os.fdopen(msvcrt.open_osfhandle(from_child_read, os.O_RDONLY | os.O_BINARY), "rb", buffering=0)
        self._buf, self._next = b"", 0

    def call(self, method: str, **params) -> dict:
        self._next += 1
        self._out.write(json.dumps({"id": self._next, "method": method, "params": params}).encode() + b"\0")
        while True:
            while b"\0" not in self._buf:
                chunk = self._in.read(1 << 16)
                if not chunk:
                    raise ConnectionError("the browser closed its DevTools pipe")
                self._buf += chunk
            raw, self._buf = self._buf.split(b"\0", 1)
            message = json.loads(raw)
            if message.get("id") == self._next:
                if "error" in message:
                    raise RuntimeError(f"{method}: {message['error']}")
                return message.get("result", {})

    def wait(self, timeout: float | None = None) -> int:
        from ctypes import wintypes
        if self._k32.WaitForSingleObject(self._process, 0xFFFFFFFF if timeout is None else int(timeout * 1000)):
            raise subprocess.TimeoutExpired("browser", timeout or 0)
        code = wintypes.DWORD()
        self._k32.GetExitCodeProcess(self._process, ctypes.byref(code))
        return code.value

    def close_pipes(self) -> None:
        for f in (self._out, self._in, self._null):
            try:
                f.close()
            except OSError:
                pass
        self._k32.CloseHandle(self._process)


def devtools_port(profile: Path, limit: float = 60) -> int:
    port_file = profile / "DevToolsActivePort"
    end = time.monotonic() + limit
    while time.monotonic() < end:
        try:
            lines = port_file.read_text(encoding="utf-8").splitlines()
            if lines and lines[0].strip().isdigit():
                return int(lines[0])
        except OSError:
            pass
        time.sleep(0.2)
    raise RuntimeError("DevTools did not start")


def targets(port: int) -> list[dict]:
    return json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=10).read())


def browser_socket(port: int) -> WebSocket:
    version = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=10).read())
    return WebSocket(version["webSocketDebuggerUrl"], timeout=60)


def close_browser(port: int | None, proc: subprocess.Popen) -> bool:
    """A normal exit through DevTools, so the browser writes its session; True when it exited by itself."""
    if port is not None:
        try:
            ws = browser_socket(port)
            try:
                ws.call("Browser.close")
            except (ConnectionError, OSError):
                pass
            finally:
                ws.close()
            proc.wait(timeout=60)
            time.sleep(1)
            return True
        except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired):
            pass
    # only this run's own browser (started here, with its own profile) is ever stopped
    subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        pass
    time.sleep(1)
    return False


def evaluate(ws: WebSocket, expression: str, gesture: bool = False):
    reply = ws.call("Runtime.evaluate", expression=expression, awaitPromise=True, returnByValue=True,
                    userGesture=gesture)
    if "exceptionDetails" in reply:
        detail = reply["exceptionDetails"]
        text = (detail.get("exception") or {}).get("description") or detail.get("text")
        raise RuntimeError(f"the script failed: {text}")
    return reply.get("result", {}).get("value")


def page_socket(port: int, url: str) -> WebSocket:
    target = next((t for t in targets(port) if t.get("type") == "page" and t.get("url") == url), None)
    if target is None:
        raise RuntimeError(f"no tab shows {url}")
    return WebSocket(target["webSocketDebuggerUrl"], timeout=60)


def wait_url(ws: WebSocket, url: str, limit: float = 15) -> None:
    end = time.monotonic() + limit
    while time.monotonic() < end:
        if evaluate(ws, "document.readyState + ' ' + location.href") == f"complete {url}":
            time.sleep(0.25)
            return
        time.sleep(0.1)
    raise RuntimeError(f"not loaded: {url}")


def wait_target(port: int, url: str, limit: float = 15) -> None:
    end = time.monotonic() + limit
    while time.monotonic() < end:
        if any(t.get("type") == "page" and t.get("url") == url for t in targets(port)):
            ws = page_socket(port, url)
            try:
                wait_url(ws, url)
            finally:
                ws.close()
            return
        time.sleep(0.2)
    raise RuntimeError(f"no tab shows {url}")


def navigate(port: int, url: str, names: list[str], base: str) -> None:
    """In the tab showing `url`, open each of `names` in turn (each one a page of its history)."""
    ws = page_socket(port, url)
    try:
        for name in names:
            ws.call("Page.navigate", url=base + name)
            wait_url(ws, base + name)
    finally:
        ws.close()


def go_back(port: int, url: str) -> None:
    """Take the tab showing `url` back one page, as the Back button does (chrome.tabs.goBack skips pages that
    were opened without a person's gesture)."""
    ws = page_socket(port, url)
    try:
        history = ws.call("Page.getNavigationHistory")
        entry = history["entries"][history["currentIndex"] - 1]
        ws.call("Page.navigateToHistoryEntry", entryId=entry["id"])
        wait_url(ws, entry["url"])
    finally:
        ws.close()


# Scripts the test extension's service worker runs. `B` is the base address of the pages.
HELPERS_JS = r"""
  const B = __BASE__;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  async function settle(id, url) {
    for (let i = 0; i < 300; i++) {
      const t = await chrome.tabs.get(id);
      if (t.status === 'complete' && t.url === url) { await sleep(250); return; }
      await sleep(50);
    }
    throw new Error('not loaded: ' + url);
  }
  async function go(id, name) { await chrome.tabs.update(id, {url: B + name}); await settle(id, B + name); }
  async function open(windowId, names) {
    const t = await chrome.tabs.create({windowId, url: B + names[0], active: false});
    await settle(t.id, B + names[0]);
    for (const n of names.slice(1)) await go(t.id, n);
    return t.id;
  }
  async function find(name) {
    const t = (await chrome.tabs.query({})).find((t) => t.url === B + name);
    if (!t) throw new Error('no tab shows ' + name);
    return t;
  }
"""
PIN_JS = "(async () => {" + HELPERS_JS + r"""
  const t = await find('pinned-2');
  await chrome.tabs.update(t.id, {pinned: true});
  return 'pinned';
})()"""
GROUPS_JS = "(async () => {" + HELPERS_JS + r"""
  const a = await find('work-a2'), b = await find('work-b1'), c = await find('later-c2'), d = await find('plain-d3');
  const work = await chrome.tabs.group({tabIds: [a.id, b.id], createProperties: {windowId: a.windowId}});
  await chrome.tabGroups.update(work, {title: 'Work', color: 'blue'});
  const later = await chrome.tabs.group({tabIds: [c.id], createProperties: {windowId: c.windowId}});
  await chrome.tabGroups.update(later, {title: 'Later', color: 'red'});
  await chrome.tabs.update(d.id, {active: true});
  await sleep(300);
  await chrome.tabGroups.update(later, {collapsed: true});
  const e = await find('notes-e1');
  const notes = await chrome.tabs.group({tabIds: [e.id], createProperties: {windowId: e.windowId}});
  await chrome.tabGroups.update(notes, {title: __NOTES__, color: 'green'});
  return 'grouped';
})()"""


def find_worker(port: int, limit: float = 20) -> dict | None:
    """The test extension's service worker, or None when the browser did not load the extension."""
    end = time.monotonic() + limit
    while time.monotonic() < end:
        worker = next((t for t in targets(port) if t.get("type") == "service_worker"
                       and t.get("url", "").startswith("chrome-extension://") and t["url"].endswith("/bg.js")), None)
        if worker is not None:
            return worker
        time.sleep(0.5)
    return None


def build(port: int, base: str, worker: dict | None) -> None:
    """Build the session: windows, tabs and history through DevTools; pin and groups through the extension."""
    browser = browser_socket(port)
    extension = None if worker is None else WebSocket(worker["webSocketDebuggerUrl"], timeout=180)
    try:
        def run(script: str, done: str) -> None:
            script = script.replace("__BASE__", json.dumps(base)).replace("__NOTES__", json.dumps(NOTES))
            if extension is not None and evaluate(extension, script) != done:
                raise RuntimeError("the test extension did not do its part")

        def new_tab(names: list[str], **params) -> str:
            tid = browser.call("Target.createTarget", url=base + names[0], background=True, **params)["targetId"]
            wait_target(port, base + names[0])
            navigate(port, base + names[0], names[1:], base)
            return tid

        wait_target(port, base + "pinned-1")
        navigate(port, base + "pinned-1", ["pinned-2"], base)
        run(PIN_JS, "pinned")
        new_tab(["work-a1", "work-a2", "work-a3"])
        go_back(port, base + "work-a3")
        new_tab(["work-b1"])
        new_tab(["later-c1", "later-c2"])
        d = new_tab(["plain-d1", "plain-d2", "plain-d3"])
        browser.call("Target.activateTarget", targetId=d)
        x = new_tab(["closed-x1", "closed-x2"])
        time.sleep(0.5)
        browser.call("Target.closeTarget", targetId=x)
        time.sleep(1)
        # the second window: off the screen, then a tab opened from its page (with a gesture, as a click would)
        e = new_tab(["notes-e1"], newWindow=True, left=BOUNDS[0], top=BOUNDS[1], width=BOUNDS[2],
                    height=BOUNDS[3])
        ws = page_socket(port, base + "notes-e1")
        try:
            evaluate(ws, f"window.open({json.dumps(base + 'other-f1')}, '_blank'), 1", gesture=True)
        finally:
            ws.close()
        wait_target(port, base + "other-f1")
        navigate(port, base + "other-f1", ["other-f2"], base)
        run(GROUPS_JS, "grouped")
        # move the first window and minimize the second, so the browser writes where they are
        first = browser.call("Browser.getWindowForTarget", targetId=d)["windowId"]
        browser.call("Browser.setWindowBounds", windowId=first,
                     bounds={"left": BOUNDS[0] + 10, "top": BOUNDS[1] + 10, "width": BOUNDS[2], "height": BOUNDS[3]})
        second = browser.call("Browser.getWindowForTarget", targetId=e)["windowId"]
        browser.call("Browser.setWindowBounds", windowId=second, bounds={"windowState": "minimized"})
    finally:
        browser.close()
        if extension is not None:
            extension.close()


def expected_plan(base: str, with_extension: bool) -> dict:
    """The session the build makes, in the terms of `shape` (no ids, no bounds)."""
    def tab(names, current=None, pinned=False, group=None):
        return {"pinned": pinned and with_extension, "group": group if with_extension else None,
                "current": len(names) - 1 if current is None else current,
                "navigations": [{"url": base + n, "title": TITLE + n} for n in names]}
    first = [tab(["pinned-1", "pinned-2"], pinned=True), tab(["work-a1", "work-a2", "work-a3"], 1, group=0),
             tab(["work-b1"], group=0), tab(["later-c1", "later-c2"], group=1),
             tab(["plain-d1", "plain-d2", "plain-d3"])]
    second = [tab(["notes-e1"], group=0), tab(["other-f1", "other-f2"])]
    groups1 = [{"title": "Work", "color": "blue", "collapsed": False},
               {"title": "Later", "color": "red", "collapsed": True}] if with_extension else []
    groups2 = [{"title": NOTES, "color": "green", "collapsed": False}] if with_extension else []
    return {"windows": [{"type": "normal", "show_state": "normal", "selected_tab": 4, "tabs": first,
                         "groups": groups1},
                        {"type": "normal", "show_state": "minimized", "selected_tab": 1, "tabs": second,
                         "groups": groups2}],
            "active_window": 0,
            "closed_tabs": [tab(["closed-x1", "closed-x2"])]}


def _tab_shape(t: dict, ids: list[str]) -> dict:
    return {"pinned": t["pinned"], "group": None if t["group"] is None else ids.index(t["group"]),
            "current": t["current"], "navigations": [{"url": n["url"], "title": n["title"]} for n in t["navigations"]]}


def shape(session: dict, closed: dict | None) -> dict:
    """A reading in plain terms: group ids become their position in the window, ids and bounds are left out."""
    windows = []
    for w in session["windows"]:
        ids = [g["id"] for g in w["groups"]]
        windows.append({"type": w["type"], "show_state": w["show_state"], "selected_tab": w["selected_tab"],
                        "tabs": [_tab_shape(t, ids) for t in w["tabs"]],
                        "groups": [{k: g[k] for k in ("title", "color", "collapsed")} for g in w["groups"]]})
    entries = (closed or {}).get("entries", [])
    closed_tabs = [{"pinned": e["pinned"], "group": None, "current": e["current"],
                    "navigations": [{"url": n["url"], "title": n["title"]} for n in e["navigations"]]}
                   for e in entries if e["kind"] == "tab"]
    closed_windows = [[[n["url"] for n in t["navigations"]] for t in e["tabs"]]
                      for e in entries if e["kind"] == "window"]
    return {"windows": windows, "active_window": session["active_window"], "closed_tabs": closed_tabs,
            "closed_windows": closed_windows}


def titles_agree(want: str, got: str) -> bool:
    """A title the browser saved is the page's; an empty one is a page whose state was not synced yet."""
    return got in ("", want)


def plan_problems(want: dict, got: dict) -> list[str]:
    """Where the reading differs from the session that was built."""
    problems = []

    def same_tabs(where: str, wants: list, gots: list) -> None:
        if len(wants) != len(gots):
            problems.append(f"{where}: {len(gots)} tabs, not {len(wants)}")
            return
        for i, (w, g) in enumerate(zip(wants, gots)):
            for key in ("pinned", "group", "current"):
                if w[key] != g[key]:
                    problems.append(f"{where} tab {i}: {key} is {g[key]!r}, not {w[key]!r}")
            urls = [n["url"] for n in g["navigations"]]
            if urls != [n["url"] for n in w["navigations"]]:
                problems.append(f"{where} tab {i}: history {urls}")
            elif not all(titles_agree(a["title"], b["title"]) for a, b in zip(w["navigations"], g["navigations"])):
                problems.append(f"{where} tab {i}: titles {[n['title'] for n in g['navigations']]}")

    if len(want["windows"]) != len(got["windows"]):
        return [f"{len(got['windows'])} windows, not {len(want['windows'])}"]
    for i, (w, g) in enumerate(zip(want["windows"], got["windows"])):
        for key in ("type", "show_state", "selected_tab", "groups"):
            if w[key] != g[key]:
                problems.append(f"window {i}: {key} is {g[key]!r}, not {w[key]!r}")
        same_tabs(f"window {i}", w["tabs"], g["tabs"])
    if want["active_window"] != got["active_window"]:
        problems.append(f"the active window is {got['active_window']!r}, not {want['active_window']!r}")
    same_tabs("recently closed", want["closed_tabs"], got["closed_tabs"])
    open_windows = sorted([[n["url"] for n in t["navigations"]] for t in w["tabs"]] for w in got["windows"])
    for listed in got["closed_windows"]:     # the windows closed at the exit, if the browser lists them
        if listed not in open_windows:
            problems.append(f"a recently closed window that was not open: {listed}")
    return problems


def sanitize(data: bytes) -> bytes:
    """A Session_ file with what describes the PC taken out: window bounds become BOUNDS (the show state stays),
    the virtual desktop's id and the platform's session id become empty. Every other byte stays as written."""
    def change(cid: int, payload: bytes) -> bytes:
        if cid == sessions.S_WINDOW_BOUNDS3 and len(payload) == 24:
            wid, *_, show = struct.unpack("<iiiiii", payload)
            return struct.pack("<iiiiii", wid, *BOUNDS, show)
        if cid == sessions.S_WINDOW_BOUNDS2 and len(payload) == 24:
            wid, *_, maximized = struct.unpack("<iiiii?3x", payload)
            return struct.pack("<iiiii?3x", wid, *BOUNDS, maximized)
        if cid == sessions.S_WORKSPACE2:
            wid = sessions._Pickle(payload).int()
            return payload if wid is None else sessions.PickleWriter().int(wid).string("").done()
        if cid == sessions.S_PLATFORM_ID:
            return sessions.PickleWriter().string("").done()
        return payload
    return sessions.rewrite(data, change)


def sanitize_closed(data: bytes) -> bytes:
    """A Tabs_ file with closed windows' bounds and virtual desktop ids made the same on every PC."""
    def change(cid: int, payload: bytes) -> bytes:
        if cid != sessions.T_WINDOW:
            return payload
        p = sessions._Pickle(payload)
        values = [p.int(), p.int(), p.int(), p.i64(), p.int(), p.int(), p.int(), p.int(), p.int()]
        if None in values or p.string() is None:
            return payload
        window_type = p.int()
        w = sessions.PickleWriter().int(values[0]).int(values[1]).int(values[2]).i64(values[3])
        for v in BOUNDS:
            w.int(v)
        w.int(values[8]).string("")
        if window_type is not None:
            w.int(window_type).raw(p.rest())
        return w.done()
    return sessions.rewrite(data, change)


def make(browser: Path, work: Path, out: Path, port: int = PORT) -> list[str]:
    """Build the session in `browser`, copy its files to `out` and check them; the problems found."""
    work.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="golden-", dir=work))
    profile, extension = root / "profile", root / "extension"
    extension.mkdir()
    (extension / "manifest.json").write_text(json.dumps(EXTENSION), encoding="utf-8")
    (extension / "bg.js").write_text("// the golden-file script drives it through DevTools\n", encoding="utf-8")
    problems: list[str] = []
    with PageServer(port) as server:
        base = server.base
        # the pipe as well as the port: Google Chrome loads the test extension only for a client on the pipe
        proc = PipeBrowser(browser_args(browser, profile, extension, [base + "pinned-1"])
                           + ["--remote-debugging-pipe", "--enable-unsafe-extension-debugging"])
        dt_port, worker = None, None
        try:
            dt_port = devtools_port(profile)
            time.sleep(2)
            worker = find_worker(dt_port, limit=8)
            if worker is None:
                try:
                    proc.call("Extensions.loadUnpacked", path=str(extension))
                    worker = find_worker(dt_port)
                    print("note: the browser ignores --load-extension; the test extension was loaded through "
                          "DevTools (Extensions.loadUnpacked on the pipe)")
                except (RuntimeError, ConnectionError, OSError) as e:
                    print(f"note: the browser did not load the test extension ({e}); the session is built through "
                          "DevTools alone, without a pinned tab and groups")
            build(dt_port, base, worker)
            time.sleep(SAVE_WAIT_S)
        except (OSError, RuntimeError, ValueError, KeyError) as e:
            problems.append(f"building the session failed: {e!r}")
        finally:
            if not close_browser(dt_port, proc):
                problems.append("the browser did not close by itself, so its session may not be saved")
            proc.close_pipes()
    if problems:
        return problems
    found = profile / "Default"
    session_path, session, notes = sessions.newest(found, "Session")
    tabs_path, closed, more = sessions.newest(found, "Tabs")
    if session_path is None:
        return [f"the browser wrote no session ({notes + more})"]
    out.mkdir(parents=True, exist_ok=True)
    for old in list(out.glob("Session_*")) + list(out.glob("Tabs_*")):
        old.unlink()
    clean = sanitize(session_path.read_bytes())
    (out / session_path.name).write_bytes(clean)
    reading = {"session": sessions.read_session(clean), "closed": None}
    if tabs_path is not None:
        clean_tabs = sanitize_closed(tabs_path.read_bytes())
        (out / tabs_path.name).write_bytes(clean_tabs)
        reading["closed"] = sessions.read_closed(clean_tabs)
    reading["built_with"] = "extension" if worker is not None else "devtools"
    problems += plan_problems(expected_plan(base, worker is not None), shape(reading["session"], reading["closed"]))
    (out / "expected.json").write_text(json.dumps(reading, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    if not problems:
        shutil.rmtree(root, ignore_errors=True)
    return problems


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--browser", required=True, type=Path)
    p.add_argument("--work", required=True, type=Path, help="scratch folder for the throwaway profile")
    p.add_argument("--out", required=True, type=Path, help="folder for the golden files")
    p.add_argument("--port", type=int, default=PORT, help="port of the local page server")
    a = p.parse_args(argv)
    if sys.platform != "win32":
        print("SESSION GOLDEN: not on Windows, nothing made")
        return 0
    problems = make(a.browser.resolve(), a.work.resolve(), a.out.resolve(), a.port)
    for problem in problems:
        print(problem)
    print("SESSION GOLDEN: MADE" if not problems else f"SESSION GOLDEN: FAILED ({len(problems)} problem(s))")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main(sys.argv[1:]))
