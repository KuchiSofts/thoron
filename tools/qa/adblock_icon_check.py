#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Thoron adblock, its shield in the address bar and in the toolbar, checked end to end and offline (ROADMAP
P5.52, P5.71, P5.72). Windows only.

The address bar holds the blocker's own shield on every web page, with the count of what it blocked there; a
click on it opens the blocker's menu (chrome://adblock-menu.top-chrome) from the shield, as uBlock Origin's
icon does, and a click on it again closes it. The address bar is part of the window, which a headless browser
does not draw, so this check runs the browser with a window, placed off the screen: it finds the shield with
Windows UI Automation and clicks it with the mouse messages a click sends to the window (the real mouse is
not moved). A local server serves a test page with an image from an ad host EasyList blocks (host-resolver
rules; every other name fails, so nothing leaves the PC). Steps:

    icon    the shield is in the address bar as soon as the page is shown, before anything is blocked
    count   it says how much was blocked once the ad image is stopped
    menu    a click on it opens the blocker's menu
    again   six clicks in a row: a click on the shield while the menu is closed opens it, every time, and the
            browser answers all along. The menu is seen by its own window: the page of a menu once kept saying
            it was shown while its window stayed hidden, and the menu did not open again for 30 seconds after
            it had closed (the page kept for a new opening). A menu closes when it loses the focus, which a
            window off the screen may make it do by itself; a click that closes an open menu is no failure.
            How long each opening took is shown; one that takes more than a second fails.
    place   chrome://adblock says where the shield is: in the toolbar only (the address bar has none, and a
            click on the toolbar's opens the menu), in the address bar only, and in both again.
    size    each shield is drawn on the line of the icons next to it (1 px) and in the middle of its place
            sideways, and as tall as those icons (2 px): measured on a picture of the window (P5.73)
    position chrome://adblock sets where in the toolbar (right after the address bar, next to the menu, after the
            extensions) and where in the address bar (at the far end, before the other icons, with them); the
            order of the buttons shows it (P5.73)

    py -3 -I tools/qa/adblock_icon_check.py --browser <out>\\thoron.exe --work <scratch dir>
Exit status 0 when every step passes (or the check does not apply, on another system).
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.qa import bench  # noqa: E402
from tools.qa.adblock_earlyhints_check import ad_host  # noqa: E402
from tools.qa.adblock_site_switch_check import _close_browser, _devtools_port, _open  # noqa: E402
from tools.qa.adblock_syntax_check import NO_HTTPS_FIRST  # noqa: E402
from tools.qa.adblock_trust_check import Server  # noqa: E402
from tools.qa.cdp import WebSocket  # noqa: E402

PAGE_HOST = "icon-check.test"
# what a shield says, and so its name ("Thoron adblock: 3 blocked on this page"), the address bar's and the
# toolbar's alike: they are told apart by where they are (the toolbar's is right of the address bar). Only
# buttons count: chrome://adblock's tab and page are named "Thoron adblock" too.
ICON = "Thoron adblock:"
# where the shield is, in the order the check sets it; the last is the default
PLACES = ("toolbar", "address", "both")
# a menu that opens later than this after a click fails
SLOW_MS = 1000
# chrome://adblock's choice of where the shield is, as a person changes it
SET_PLACE = ("(() => { const s = document.getElementById('shield-place'); s.value = '%s'; "
             "s.dispatchEvent(new Event('change')); return s.value; })()")
MENU_URL = "chrome://adblock-menu.top-chrome/"
SETTLE_S = 3.0
CLICKS = 6
# Finds the shields among the elements of the test browser (its process id in THORON_PID; no other program's
# windows are looked at), left to right: each one's name, where its middle is on the screen, and its width.
UIA = """
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$root = [System.Windows.Automation.AutomationElement]::RootElement
$mine = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ProcessIdProperty, [int]$env:THORON_PID)
$found = @()
for ($i = 0; $i -lt [int]$env:THORON_TRIES -and $found.Count -eq 0; $i++) {
  $found = @($root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $mine) |
      Where-Object { $_.Current.ControlType.ProgrammaticName -eq 'ControlType.Button' -and
                     $_.Current.Name.StartsWith('%s') } |
      Sort-Object { $_.Current.BoundingRectangle.X })
  if ($found.Count -eq 0) { Start-Sleep -Milliseconds 250 }
}
ConvertTo-Json -Compress -InputObject @($found | ForEach-Object { $r = $_.Current.BoundingRectangle
  @{ name = $_.Current.Name; x = [int]($r.X + $r.Width / 2); y = [int]($r.Y + $r.Height / 2); w = [int]$r.Width } })
""" % ICON


def is_toolbar(shield: dict, toolbar: dict | None) -> bool:
    """`shield` is the toolbar's: where the toolbar's was seen (`toolbar`) while both were shown."""
    return toolbar is not None and abs(shield.get("x", 0) - toolbar["x"]) <= 4 and \
        abs(shield.get("w", 0) - toolbar.get("w", 0)) <= 4


def where(found: list[dict], toolbar: dict | None) -> tuple[bool, bool]:
    """Whether the address bar and the toolbar have a shield, among the shields `found`."""
    return any(not is_toolbar(s, toolbar) for s in found), any(is_toolbar(s, toolbar) for s in found)


def ad_image(host: str) -> str:
    """What the page runs: an image from the ad host, which the blocker stops."""
    return (f"(() => {{ const i = new Image(); i.src = 'http://{host}/ad.png?' + Date.now(); "
            "document.body.append(i); return 1; })()")


def icon_problems(before: dict, after: dict) -> list[str]:
    out = []
    if not before.get("name"):
        out.append("icon: the address bar has no shield before anything is blocked")
    if not str(after.get("name", "")).endswith("blocked on this page") or \
            str(after.get("name", "")).startswith(f"{ICON} 0 "):
        out.append(f"count: the shield says {after.get('name')!r} once the ad image was stopped")
    return out


def place_problems(place: str, address: bool, toolbar: bool) -> list[str]:
    """Where the shield is with chrome://adblock's choice `place`: `address`, `toolbar`, whether each has one."""
    want_address, want_toolbar = place != "toolbar", place != "address"
    out = []
    if address != want_address:
        out.append(f"place: with {place!r}, the address bar {'has no' if want_address else 'still has a'} shield")
    if toolbar != want_toolbar:
        out.append(f"place: with {place!r}, the toolbar {'has no' if want_toolbar else 'still has a'} shield")
    return out


def slow_problems(opened_ms: list[int]) -> list[str]:
    """`opened_ms`: how long each click that opened the menu took to show it."""
    slow = [ms for ms in opened_ms if ms > SLOW_MS]
    return [f"fast: the menu took {slow} ms to open (more than {SLOW_MS} ms)"] if slow else []


def menu_problems(clicks: list[tuple[bool, bool]], answered: list[bool]) -> list[str]:
    """`clicks`: for each click, whether the menu's window was open before it, and whether it showed after it.
    A click on a closed menu must open it; a click on an open one may close it."""
    out = []
    if not clicks or not clicks[0][1]:
        out.append("menu: a click on the shield did not open the blocker's menu")
    missed = [n + 1 for n, (before, shown) in enumerate(clicks) if not before and not shown]
    if clicks and missed and missed != [1]:
        out.append(f"again: the menu was closed and did not open on click(s) {missed} of {len(clicks)}")
    if not all(answered):
        out.append(f"again: the browser did not answer after some clicks ({answered})")
    return out


def _launch_window(browser: Path, profile: Path, port: int, host: str) -> subprocess.Popen:
    args = [str(browser), f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
            "--disable-default-apps", "--disable-background-networking", "--disable-component-update",
            f"--disable-features={NO_HTTPS_FIRST}", "--enable-features=ThoronNativeAdblock",
            f"--host-resolver-rules=MAP {PAGE_HOST} 127.0.0.1:{port}, MAP {host} 127.0.0.1:{port}, "
            "MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
            # off the screen: the check needs a real window, not the person's attention
            "--window-position=-4000,-4000", "--window-size=1000,700",
            "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0", "about:blank"]
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _windows(pid: int) -> list[int]:
    """The visible top-level windows of the browser: its window, and the menu while it shows."""
    import ctypes
    import ctypes.wintypes as wt
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def each(hwnd, _):
        owner = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            name = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(hwnd, name, 64)
            if name.value == "Chrome_WidgetWin_1":
                found.append(hwnd)
        return True

    user32.EnumWindows(each, 0)
    return found


def _menu_window(pid: int) -> bool:
    """The menu's own window is shown: one of the browser's top-level windows about 330 px wide and tall enough
    (a tooltip is a window too, a small one)."""
    import ctypes
    import ctypes.wintypes as wt
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    for hwnd in _windows(pid):
        r = wt.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        if 250 < r.right - r.left < 450 and r.bottom - r.top > 300:
            return True
    return False


def _click(hwnd: int, x: int, y: int) -> None:
    """What a click sends to the window, at a point on the screen; the real mouse is not moved."""
    import ctypes
    import ctypes.wintypes as wt
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    point = wt.POINT(x, y)
    user32.ScreenToClient(hwnd, ctypes.byref(point))
    where = (point.y << 16) | (point.x & 0xFFFF)
    for message, keys in ((0x0200, 0), (0x0201, 0x0001), (0x0202, 0)):  # move, left down, left up
        user32.PostMessageW(hwnd, message, keys, where)
        time.sleep(0.06)


# P5.73: where in the toolbar and the address bar the shield sits, in the order the check sets it; the last of
# each setting is its default.
POSITIONS = (("toolbar-position", "address"), ("toolbar-position", "menu"), ("toolbar-position", "extensions"),
             ("address-position", "end"), ("address-position", "start"), ("address-position", "icons"))
SET_CHOICE = ("(() => { const s = document.getElementById('%s'); s.value = '%s'; "
              "s.dispatchEvent(new Event('change')); return s.value; })()")
# Every button of the test browser's windows: name, left, top, width, height on the screen.
UIA_ALL = """
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$root = [System.Windows.Automation.AutomationElement]::RootElement
$mine = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ProcessIdProperty, [int]$env:THORON_PID)
ConvertTo-Json -Compress -InputObject @($root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $mine) |
  Where-Object { $_.Current.ControlType.ProgrammaticName -eq 'ControlType.Button' -and
                 $_.Current.BoundingRectangle.Height -lt 50 -and $_.Current.BoundingRectangle.Width -gt 0 } |
  ForEach-Object { $r = $_.Current.BoundingRectangle
    @{ name = $_.Current.Name; x = [int]$r.X; y = [int]$r.Y; w = [int]$r.Width; h = [int]$r.Height } })
"""


def toolbar_buttons(pid: int) -> list[dict]:
    # UI Automation now and then answers with nothing while the window lays itself out: asked again
    found: list = []
    for _ in range(3):
        out = subprocess.run(["powershell.exe", "-NoProfile", "-Command", UIA_ALL], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=60,
                             env=dict(os.environ, THORON_PID=str(pid))).stdout.strip()
        found = json.loads(out or "[]")
        found = found if isinstance(found, list) else [found]
        if any(b["name"].startswith(ICON) for b in found):
            break
        time.sleep(1.0)
    return sorted(found, key=lambda b: (b["y"], b["x"]))


def split_shields(buttons: list[dict]) -> tuple[dict | None, dict | None]:
    """The address bar's shield (as tall as the address bar's icons) and the toolbar's (as tall as its buttons)."""
    shields = [b for b in buttons if b["name"].startswith(ICON)]
    return (next((b for b in shields if b["h"] < 30), None), next((b for b in shields if b["h"] >= 30), None))


def _row(buttons: list[dict], ref: dict) -> list[dict]:
    """The buttons on the same line as `ref`, left to right."""
    middle = ref["y"] + ref["h"] / 2
    return sorted((b for b in buttons if abs(b["y"] + b["h"] / 2 - middle) <= 6), key=lambda b: b["x"])


def position_problems(setting: str, value: str, buttons: list[dict]) -> list[str]:
    address, toolbar = split_shields(buttons)
    if setting == "toolbar-position":
        if not toolbar:
            return [f"position: no shield in the toolbar with {setting} {value!r}"]
        # the toolbar's buttons right of the address bar (the window's own buttons are on another line)
        right = [b for b in _row(buttons, toolbar) if b["h"] >= 30 and (not address or b["x"] > address["x"])]
        names = [b["name"][:22] for b in right]
        at = right.index(toolbar)
        if value == "address" and at != 0:
            return [f"position: 'right after the address bar', but the shield is button {at + 1} there ({names})"]
        if value == "menu" and at != len(right) - 2:
            return [f"position: 'next to the menu', but the shield is not right before it ({names})"]
        if value == "extensions" and at == len(right) - 1:
            return [f"position: 'after the extensions', but the shield is last ({names})"]
        return []
    if not address:
        return [f"position: no shield in the address bar with {setting} {value!r}"]
    # the address bar's icons (its security chip, wider, is not one)
    icons = [b for b in _row(buttons, address) if b["h"] < 30 and b["w"] <= 40]
    names = [b["name"][:22] for b in icons]
    at = icons.index(address)
    if value == "end" and at != len(icons) - 1:
        return [f"position: 'at the far end', but the shield is icon {at + 1} of {len(icons)} ({names})"]
    if value == "start" and at != 0:
        return [f"position: 'before the other icons', but the shield is icon {at + 1} ({names})"]
    if value == "icons" and len(icons) > 1 and at == len(icons) - 1:
        return [f"position: 'with the other icons', but the shield is at the far end ({names})"]
    return []


def _park_pointer(hwnd: int) -> None:
    """The pointer over the page, so that no button is drawn as hovered (the real mouse is not moved)."""
    import ctypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.PostMessageW(hwnd, 0x0200, 0, (400 << 16) | 400)


def _capture(hwnd: int) -> dict:
    """The window as it is drawn (also off the screen): where it is, and its pixels (BGRA, top row first)."""
    import ctypes
    import ctypes.wintypes as wt
    user32, gdi32 = ctypes.WinDLL("user32"), ctypes.WinDLL("gdi32")
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    hdc = user32.GetWindowDC(hwnd)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mem, bmp)
    user32.PrintWindow(hwnd, mem, 2)  # PW_RENDERFULLCONTENT

    class Header(ctypes.Structure):
        _fields_ = [("size", wt.DWORD), ("width", wt.LONG), ("height", wt.LONG), ("planes", wt.WORD),
                    ("bits", wt.WORD), ("compression", wt.DWORD), ("image", wt.DWORD), ("xppm", wt.LONG),
                    ("yppm", wt.LONG), ("used", wt.DWORD), ("important", wt.DWORD)]
    header = Header(ctypes.sizeof(Header), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(header), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(hwnd, hdc)
    return {"left": r.left, "top": r.top, "w": w, "h": h, "data": buf.raw}


def ink(capture: dict, button: dict) -> tuple[float, float, int, int] | None:
    """The middle (x, y, on the screen) and the size (width, height) of what is drawn inside `button`: the pixels
    clearly unlike the button's own background."""
    data, width = capture["data"], capture["w"]
    x0, y0 = button["x"] - capture["left"], button["y"] - capture["top"]

    def pixel(x: int, y: int) -> tuple[int, int, int]:
        i = (y * width + x) * 4
        return data[i], data[i + 1], data[i + 2]
    if x0 < 0 or y0 < 0 or x0 + button["w"] > width or y0 + button["h"] > capture["h"]:
        return None
    background = pixel(x0 + 1, y0 + 1)
    xs, ys = [], []
    for y in range(y0 + 1, y0 + button["h"] - 1):
        for x in range(x0 + 1, x0 + button["w"] - 1):
            if sum(abs(a - b) for a, b in zip(pixel(x, y), background)) > 120:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return ((min(xs) + max(xs)) / 2 + capture["left"], (min(ys) + max(ys)) / 2 + capture["top"],
            max(xs) - min(xs) + 1, max(ys) - min(ys) + 1)


def _neighbours(buttons: list[dict], shield: dict) -> list[dict]:
    """The icons next to a shield: the same height, on its line, not a shield, not a wide chip."""
    return [b for b in _row(buttons, shield) if b is not shield and not b["name"].startswith(ICON)
            and abs(b["h"] - shield["h"]) <= 2 and b["w"] <= 40]


def size_problems(buttons: list[dict], capture: dict) -> list[str]:
    """Each shield's drawing in the middle of its place as the icons next to it are (1 px), and as tall (2 px)."""
    out = []
    address, toolbar = split_shields(buttons)
    for shield, where in ((address, "address bar"), (toolbar, "toolbar")):
        if not shield:
            out.append(f"size: no shield in the {where}")
            continue
        mine = ink(capture, shield)
        if not mine:
            out.append(f"size: the {where}'s shield draws nothing")
            continue
        drawn = [(b, ink(capture, b)) for b in _neighbours(buttons, shield)]
        drawn = [(b, d) for b, d in drawn if d]
        if not drawn:
            continue
        # how far each drawing is from the middle of its own place, down; the shield's against its neighbours'
        offsets = sorted(d[1] - (b["y"] + b["h"] / 2) for b, d in drawn)
        theirs = offsets[len(offsets) // 2]
        own = mine[1] - (shield["y"] + shield["h"] / 2)
        if abs(own - theirs) > 1.0:
            out.append(f"size: the {where}'s shield is drawn {own - theirs:+.1f} px off the line of the icons "
                       f"next to it")
        if abs(mine[0] - (shield["x"] + shield["w"] / 2)) > 1.0:
            out.append(f"size: the {where}'s shield is drawn {mine[0] - (shield['x'] + shield['w'] / 2):+.1f} px "
                       f"off the middle of its place, sideways")
        heights = [d[3] for _, d in drawn]
        if mine[3] < min(heights) - 2 or mine[3] > max(heights) + 2:
            out.append(f"size: the {where}'s shield is {mine[3]} px tall, the icons next to it {heights}")
    return out


def size_summary(buttons: list[dict], capture: dict) -> str:
    address, toolbar = split_shields(buttons)
    parts = []
    for shield, where in ((address, "address bar"), (toolbar, "toolbar")):
        if shield and (d := ink(capture, shield)):
            near = [ink(capture, b) for b in _neighbours(buttons, shield)]
            parts.append(f"{where} {d[2]}x{d[3]} px (next to it: {[f'{n[2]}x{n[3]}' for n in near if n]})")
    return "; ".join(parts) or "no shield drawn"


def run(browser: Path, work: Path, host: str) -> list[str]:
    profile = Path(tempfile.mkdtemp(prefix="icon-", dir=work))
    problems: list[str] = []
    with Server() as server:
        proc = _launch_window(browser, profile, server.port, host)
        port = None
        try:
            port = _devtools_port(profile)
            target = _open(port, f"http://{PAGE_HOST}/page.html")
            time.sleep(SETTLE_S)

            def shields(tries: int = 24) -> list[dict]:
                out = subprocess.run(["powershell.exe", "-NoProfile", "-Command", UIA], capture_output=True,
                                     text=True, encoding="utf-8", errors="replace", timeout=60,
                                     env=dict(os.environ, THORON_PID=str(proc.pid),
                                              THORON_TRIES=str(tries))).stdout.strip()
                found = json.loads(out or "[]")
                return found if isinstance(found, list) else [found]

            def shield() -> dict:
                """The address bar's shield: the left one."""
                found = shields()
                return found[0] if found else {}

            def wait_for_menu(start: float) -> int:
                """How long the menu took to show from the press at `start`, in ms; -1: not within 1.7 s."""
                while time.monotonic() < start + 1.7:
                    if _menu_window(proc.pid):
                        return int((time.monotonic() - start) * 1000)
                    time.sleep(0.02)
                return -1

            def click(hwnd: int, at: dict) -> tuple[bool, int]:
                """A click on a shield: whether the menu was open before it, and how long it took to open
                (-1: it did not; 0 for a click that closes it)."""
                open_before = _menu_window(proc.pid)
                start = time.monotonic()
                _click(hwnd, at["x"], at["y"])
                if open_before:
                    time.sleep(0.4)
                    return True, 0 if _menu_window(proc.pid) else -1
                return False, wait_for_menu(start)

            before = shield()
            # the ad image: the page asks for it, the blocker stops it, the shield counts it
            ws = WebSocket(target["webSocketDebuggerUrl"])
            try:
                ws.call("Runtime.evaluate", expression=ad_image(host))
                time.sleep(SETTLE_S)
                after = shield()
                found = icon_problems(before, after)
                print(f"{'PASS' if not found else 'FAIL'}  icon and count: {before.get('name')!r} then "
                      f"{after.get('name')!r}")
                problems += found

                main = _windows(proc.pid)
                clicks, answered, opened_ms = [], [], []
                for _ in range(CLICKS if main and after.get("name") else 0):
                    open_before, took = click(main[0], after)
                    shown = took >= 0
                    if shown and not open_before:
                        opened_ms.append(took)
                    clicks.append((open_before, shown))
                    time.sleep(1.5)
                    try:
                        answered.append(ws.call("Runtime.evaluate", expression="1+1",
                                                returnByValue=True)["result"]["value"] == 2)
                    except (OSError, RuntimeError, KeyError):
                        answered.append(False)
                found = menu_problems(clicks, answered) + slow_problems(opened_ms)
                targets = [t.get("url", "") for t in json.loads(
                    urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=10).read())]
                if clicks and clicks[0][1] and not any(url.startswith(MENU_URL) for url in targets):
                    found.append("menu: what opened is not the blocker's menu")
                print(f"{'PASS' if not found else 'FAIL'}  menu and again: (open before, shown after) {clicks}, "
                      f"answered {answered}, opened in {opened_ms} ms")
                problems += found

                # where the shield is, as chrome://adblock sets it; the page's tab is in front again
                settings = _open(port, "chrome://adblock")
                time.sleep(SETTLE_S)
                urllib.request.urlopen(f"http://127.0.0.1:{port}/json/activate/{target['id']}", timeout=10)
                sws = WebSocket(settings["webSocketDebuggerUrl"])
                try:
                    # both shown (the default): the right one is the toolbar's
                    time.sleep(1.0)
                    both = shields(tries=8)
                    toolbar_ref = both[-1] if len(both) >= 2 else None
                    if toolbar_ref is None:
                        problems.append(f"place: by default the address bar and the toolbar do not both have a "
                                        f"shield ({len(both)} found)")
                    for place in PLACES if toolbar_ref else ():
                        sws.call("Runtime.evaluate", expression=SET_PLACE % place, returnByValue=True)
                        time.sleep(2.0)
                        now = shields(tries=4)
                        address, toolbar = where(now, toolbar_ref)
                        found = place_problems(place, address, toolbar)
                        opened = None
                        tool = next((s for s in now if is_toolbar(s, toolbar_ref)), None)
                        if place == "toolbar" and tool and main:
                            if _menu_window(proc.pid):
                                time.sleep(2.5)
                            _, opened = click(main[0], tool)
                            if opened < 0:
                                found.append("place: a click on the toolbar's shield did not open the menu")
                            found += slow_problems([opened] if opened >= 0 else [])
                            time.sleep(1.0)
                            if _menu_window(proc.pid):
                                click(main[0], tool)
                                time.sleep(1.0)
                        print(f"{'PASS' if not found else 'FAIL'}  place {place}: shield in the address bar "
                              f"{address}, in the toolbar {toolbar}"
                              + (f", menu from the toolbar in {opened} ms" if opened is not None else ""))
                        problems += found

                    # P5.73: each shield drawn in the middle of its place, as tall as the icons next to it
                    if main:
                        # the shield alone: its count's badge is switched off while it is measured
                        badge = ("(() => { const b = document.querySelector('[data-setting=badge]'); "
                                 "if (b.checked === %s) b.click(); return b.checked; })()")
                        sws.call("Runtime.evaluate", expression=badge % "true", returnByValue=True)
                        _park_pointer(main[0])
                        time.sleep(1.5)
                        row = toolbar_buttons(proc.pid)
                        picture = _capture(main[0])
                        found = size_problems(row, picture)
                        print(f"{'PASS' if not found else 'FAIL'}  size: {size_summary(row, picture)}")
                        problems += found
                        sws.call("Runtime.evaluate", expression=badge % "false", returnByValue=True)
                        time.sleep(1.0)

                    # P5.73: where in the toolbar and in the address bar, as chrome://adblock sets it
                    for setting, value in POSITIONS:
                        sws.call("Runtime.evaluate", expression=SET_CHOICE % (setting, value), returnByValue=True)
                        time.sleep(2.0)
                        row = toolbar_buttons(proc.pid)
                        found = position_problems(setting, value, row)
                        print(f"{'PASS' if not found else 'FAIL'}  position {setting} {value}: "
                              f"{[b['name'][:22] for b in row if b['y'] > row[0]['y'] - 99]}")
                        problems += found
                finally:
                    sws.close()
            finally:
                ws.close()
        except (OSError, RuntimeError, ValueError, KeyError, subprocess.TimeoutExpired) as e:
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
    p.add_argument("--lists", type=Path, help="the bundled lists file (default: next to the browser)")
    a = p.parse_args(argv)
    if os.name != "nt":
        print("ICON CHECK: does not apply (Windows only)")
        return 0
    host = ad_host((a.lists or a.browser.parent / "thoron_adblock_lists.txt").read_text(encoding="utf-8"))
    if not host:
        print("ICON CHECK: FAILED (EasyList holds no plain host rule)")
        return 1
    a.work.mkdir(parents=True, exist_ok=True)
    problems = run(a.browser.resolve(), a.work, host)
    for problem in problems:
        print(problem)
    print("ICON CHECK: PASSED" if not problems else f"ICON CHECK: FAILED ({len(problems)} problem(s))")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
