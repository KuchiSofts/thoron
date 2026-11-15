#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Windows Security prompts brought to the front, checked offline (ROADMAP P5.74). Windows only.

Windows asks "is it you?" (Windows Hello, the PIN: for showing and filling saved passwords, for passkeys and for a
password manager's own check) in a window of its own process, and it may open it behind the browser. Thoron brings
such a window to the front when it opens while the browser is in front or behind one of the browser's windows. No
real prompt is opened here: this check opens a stand-in window of the same kind (the window class Windows uses,
"Credential Dialog Xaml Host") behind a test browser's window, off the screen, without taking the focus, and an
ordinary window the same way. Steps:

    front   the stand-in is brought above the browser's window
    others  the ordinary window is left where it was, behind the browser's window

    py -3 -I tools/qa/windows_security_check.py --browser <out>\\thoron.exe --work <scratch dir>
Exit status 0 when both steps pass (or the check does not apply, on another system).
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

PROMPT_CLASS = "Credential Dialog Xaml Host"
OTHER_CLASS = "Thoron Check Ordinary Window"
SETTLE_S = 4.0
WAIT_S = 1.5


def zorder_problems(order: dict) -> list[str]:
    """`order`: the place of each window from the top (0 is in front): 'browser', 'prompt' and 'other'."""
    out = []
    if order.get("prompt") is None or order.get("browser") is None:
        return ["front: the windows were not found"]
    if order["prompt"] > order["browser"]:
        out.append("front: the stand-in Windows Security window stayed behind the browser's window")
    if order.get("other") is not None and order["other"] < order["browser"]:
        out.append("others: an ordinary window was brought in front of the browser's window too")
    return out


class Windows:
    """The two windows, made and served by a thread of their own (a window's thread must answer its messages)."""

    def __init__(self, below: int, rect: tuple[int, int, int, int]):
        self.below, self.rect = below, rect
        self.made = threading.Event()
        self.handles: dict[str, int] = {}
        self.thread_id = 0
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        import ctypes
        import ctypes.wintypes as wt
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32")
        WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
        user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
        user32.DefWindowProcW.restype = ctypes.c_ssize_t
        proc = WNDPROC(lambda h, m, w, l: user32.DefWindowProcW(h, m, w, l))

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [("style", wt.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                        ("cbWndExtra", ctypes.c_int), ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
                        ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH), ("lpszMenuName", wt.LPCWSTR),
                        ("lpszClassName", wt.LPCWSTR)]
        instance = kernel32.GetModuleHandleW(None)
        user32.CreateWindowExW.restype = wt.HWND
        user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
                                           ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
        user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                        wt.UINT]
        x, y, w, h = self.rect
        for key, name in (("prompt", PROMPT_CLASS), ("other", OTHER_CLASS)):
            cls = WNDCLASSW(0, proc, 0, 0, instance, None, None, None, None, name)
            user32.RegisterClassW(ctypes.byref(cls))
            # WS_POPUP, hidden; WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE: no taskbar button, never the focus
            hwnd = user32.CreateWindowExW(0x00000080 | 0x08000000, name, "Thoron check", 0x80000000,
                                          x + 40, y + 40, w // 2, h // 2, None, None, instance, None)
            # right behind the browser's window, then shown there without the focus
            user32.SetWindowPos(hwnd, self.below, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
            user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
            self.handles[key] = hwnd
        self.thread_id = kernel32.GetCurrentThreadId()
        self.made.set()
        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        for hwnd in self.handles.values():
            user32.DestroyWindow(hwnd)

    def start(self) -> None:
        self.thread.start()
        self.made.wait(10)

    def stop(self) -> None:
        import ctypes
        ctypes.WinDLL("user32").PostThreadMessageW(self.thread_id, 0x0012, 0, 0)  # WM_QUIT
        self.thread.join(5)


def zorder(handles: dict[str, int]) -> dict:
    """Each window's place among all the top-level windows, from the top."""
    import ctypes
    user32 = ctypes.WinDLL("user32")
    user32.GetTopWindow.restype = ctypes.c_void_p
    user32.GetWindow.restype = ctypes.c_void_p
    user32.GetWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    found, at, hwnd = {}, 0, user32.GetTopWindow(None)
    wanted = {v: k for k, v in handles.items()}
    while hwnd and len(found) < len(wanted):
        if hwnd in wanted:
            found[wanted[hwnd]] = at
        hwnd = user32.GetWindow(hwnd, 2)  # GW_HWNDNEXT
        at += 1
    return found


def run(browser: Path, work: Path) -> list[str]:
    import ctypes
    import ctypes.wintypes as wt
    from tools.qa.adblock_icon_check import _windows
    profile = Path(tempfile.mkdtemp(prefix="winsec-", dir=work))
    args = [str(browser), f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
            "--disable-background-networking", "--disable-component-update", "--host-resolver-rules=MAP * ~NOTFOUND",
            # off the screen: the check needs a real window, not the person's attention
            "--window-position=-4000,-4000", "--window-size=900,600", "about:blank"]
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    problems: list[str] = []
    try:
        time.sleep(SETTLE_S)
        main = _windows(proc.pid)
        if not main:
            return ["front: the test browser opened no window"]
        rect = wt.RECT()
        ctypes.WinDLL("user32").GetWindowRect(main[0], ctypes.byref(rect))
        windows = Windows(main[0], (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top))
        windows.start()
        try:
            time.sleep(WAIT_S)
            order = zorder(dict(windows.handles, browser=main[0]))
            found = zorder_problems(order)
            for step in ("front", "others"):
                mine = [f for f in found if f.startswith(step + ":")]
                print(f"{'PASS' if not mine else 'FAIL'}  {step}: places from the top {order}")
            problems += found
        finally:
            windows.stop()
    finally:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
        time.sleep(2)
        shutil.rmtree(profile, ignore_errors=True)
    return problems


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--browser", required=True, type=Path)
    p.add_argument("--work", required=True, type=Path, help="scratch folder for the throwaway profile")
    a = p.parse_args(argv)
    if os.name != "nt":
        print("WINDOWS SECURITY CHECK: does not apply (Windows only)")
        return 0
    a.work.mkdir(parents=True, exist_ok=True)
    problems = run(a.browser.resolve(), a.work)
    for problem in problems:
        print(problem)
    print("WINDOWS SECURITY CHECK: PASSED" if not problems
          else f"WINDOWS SECURITY CHECK: FAILED ({len(problems)} problem(s))")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
