#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Pictures of the hand-ported Thorium UI options in a running build, beside the same in an older one
(ROADMAP P2.23): the tab strip's combo button on the right (default) and on the left, the Thorium 2024 UI,
the classic omnibox, rectangular tabs, a custom tab width, and the link menu's "Open link in this tab".

Each configuration starts the browser in a real window on the screen (a minute in all), with a throwaway
profile of its own, offline, with three local tabs; the window is captured and closed. For the link menu a
right click is sent to a link and the open menu is captured. Only the browser's own windows are captured, each
by itself (Windows' PrintWindow), never the screen: nothing else that is open on the PC can be in a picture. The pictures are written to --out as
<label>-<configuration>.png, for a person to compare; nothing is judged here.
    py -3 -I tools/qa/ui_look_check.py --browser <Thoron>\\thoron.exe --label thoron158
        [--browser <Thorium>\\thorium.exe --label thorium156] --out <folder> --work <scratch dir>
Windows only.
"""
import argparse
import ctypes
import ctypes.wintypes as wt
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
from tools.qa.adblock_site_switch_check import _close_browser, _devtools_port  # noqa: E402
from tools.qa.cdp import WebSocket  # noqa: E402

CONFIGS = (
    ("default", []),
    ("combo-left", ["--enable-features=ThoriumLeftAlignedTabStripComboButton"]),
    ("thorium-2024", ["--enable-features=Thorium2024"]),
    ("classic-omnibox", ["--classic-omnibox"]),
    ("rectangular-tabs", ["--rectangular-tabs"]),
    ("tab-width-120", ["--custom-tab-width=120"]),
    ("link-menu", []),
)
PAGE = b"""<!doctype html><meta charset="utf-8"><title>Tab %d</title>
<body style="font: 20px sans-serif; margin: 40px"><a id="link" href="/2" style="font-size: 28px">A link</a></body>"""
WIDTH, HEIGHT, LEFT, TOP = 1000, 640, 40, 40


class _Pages(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        n = int(self.path.strip("/") or "1") if self.path.strip("/").isdigit() else 1
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(PAGE % n)

    def log_message(self, *a):
        pass


def windows_of(pid: int) -> list[tuple[int, tuple[int, int, int, int]]]:
    """The visible top-level windows of the process (the browser's window, an open menu), with their rectangles
    on the screen, the largest first."""
    user32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def each(hwnd, _):
        owner = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            r = wt.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            found.append(((r.right - r.left) * (r.bottom - r.top), hwnd, (r.left, r.top, r.right, r.bottom)))
        return True

    user32.EnumWindows(each, 0)
    return [(hwnd, rect) for _, hwnd, rect in sorted(found, reverse=True)]


def print_window(hwnd: int, width: int, height: int):
    """The window's own picture (PrintWindow with its full content), as a PIL image; None when it fails."""
    from PIL import Image
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    window_dc = user32.GetWindowDC(hwnd)
    memory_dc = gdi32.CreateCompatibleDC(window_dc)
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
    old = gdi32.SelectObject(memory_dc, bitmap)
    try:
        if not user32.PrintWindow(hwnd, memory_dc, 2):      # PW_RENDERFULLCONTENT
            return None

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG), ("biPlanes", wt.WORD),
                        ("biBitCount", wt.WORD), ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                        ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
                        ("biClrImportant", wt.DWORD)]
        info = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
        data = ctypes.create_string_buffer(width * height * 4)
        gdi32.GetDIBits(memory_dc, bitmap, 0, height, data, ctypes.byref(info), 0)
        return Image.frombuffer("RGBA", (width, height), data, "raw", "BGRA", 0, 1).convert("RGB")
    finally:
        gdi32.SelectObject(memory_dc, old)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(hwnd, window_dc)


def capture(pid: int, target: Path) -> bool:
    """The browser's windows, each printed by itself, laid out where they are: nothing else of the screen."""
    from PIL import Image
    found = windows_of(pid)
    if not found:
        return False
    left = min(r[0] for _, r in found)
    top = min(r[1] for _, r in found)
    right = max(r[2] for _, r in found)
    bottom = max(r[3] for _, r in found)
    canvas = Image.new("RGB", (right - left, bottom - top), "white")
    for hwnd, (l, t, r, b) in found:              # the largest (the browser's window) first, a menu over it
        picture = print_window(hwnd, r - l, b - t)
        if picture is None:
            return False
        canvas.paste(picture, (l - left, t - top))
    canvas.save(target)
    return True


def right_click_link(port: int) -> None:
    listing = json.loads(__import__("urllib.request").request.urlopen(f"http://127.0.0.1:{port}/json/list",
                                                                     timeout=5).read())
    page = next(t for t in listing if t.get("type") == "page")
    ws = WebSocket(page["webSocketDebuggerUrl"])
    try:
        box = ws.call("Runtime.evaluate", returnByValue=True, expression=(
            "JSON.stringify((r => ({x: r.left + r.width / 2, y: r.top + r.height / 2}))"
            "(document.getElementById('link').getBoundingClientRect()))"))["result"]["value"]
        at = json.loads(box)
        for kind in ("mousePressed", "mouseReleased"):
            ws.call("Input.dispatchMouseEvent", type=kind, x=at["x"], y=at["y"], button="right", clickCount=1)
    finally:
        ws.close()


def one(browser: Path, label: str, name: str, extra: list[str], url: str, out: Path, work: Path,
        host_rules: str) -> Path | None:
    profile = Path(tempfile.mkdtemp(prefix="ui-", dir=work))
    proc = subprocess.Popen(
        [str(browser), f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
         "--disable-background-networking", "--disable-component-update", f"--host-resolver-rules={host_rules}",
         f"--window-position={LEFT},{TOP}", f"--window-size={WIDTH},{HEIGHT}", "--remote-debugging-port=0",
         *extra, url + "1", url + "2", url + "3"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    port = None
    target = out / f"{label}-{name}.png"
    try:
        port = _devtools_port(profile)
        time.sleep(4)
        if name == "link-menu":
            right_click_link(port)
            time.sleep(1.2)
        return target if capture(proc.pid, target) else None
    finally:
        if port is not None:
            if name == "link-menu":
                ctypes.windll.user32.keybd_event(0x1B, 0, 0, 0)      # Esc closes the menu
                ctypes.windll.user32.keybd_event(0x1B, 0, 2, 0)
                time.sleep(0.3)
            _close_browser(port, proc)
        else:
            bench._stop(proc, profile)
        shutil.rmtree(profile, ignore_errors=True)


def run(browsers: list[tuple[Path, str]], out: Path, work: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Pages)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    rules = "MAP * ~NOTFOUND, EXCLUDE 127.0.0.1"
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    made = []
    try:
        for browser, label in browsers:
            for name, extra in CONFIGS:
                picture = one(browser, label, name, extra, url, out, work, rules)
                print(f"{'made' if picture else 'FAILED'}  {label} {name}: {picture or 'no window found'}")
                if picture:
                    made.append(picture)
    finally:
        server.shutdown()
    return made


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--browser", type=Path, action="append", required=True)
    p.add_argument("--label", action="append", required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--work", type=Path, required=True)
    a = p.parse_args(argv)
    if len(a.browser) != len(a.label):
        p.error("one --label for each --browser")
    made = run(list(zip(a.browser, a.label)), a.out, a.work / "ui-look")
    want = len(a.browser) * len(CONFIGS)
    print(f"UI LOOK: {len(made)} of {want} pictures")
    return 0 if len(made) == want else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
