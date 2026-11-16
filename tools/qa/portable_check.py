#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""The Windows portable package, started for real and offline (ROADMAP P2.8). Windows only.

The package is built from a build's Chrome-bin folder (tools/release/portable.py) and its .zip is unpacked into
folders whose names are hard on a launcher. The browser is started there through the launcher only, as a double
click starts it: headless, with DevTools on 127.0.0.1, with no network (every host name resolves to nothing), and
with its temporary folder pointed into the scratch folder, so that what it leaves there can be seen. Steps:

    package   the package is built, passes its audits, and nothing is started from one that does not
  in a folder with spaces, one named in several scripts (accented Latin, Cyrillic, CJK) and one with & % ! ^ ( ):
    first     the .zip unpacks to the package's files; the launcher ends at once and the browser runs; its
              program and its profile are in the folder (the browser says so, Windows says so, and the DevTools
              port file, Local State and Preferences are there); the profile is new, and a setting is changed
    again     a second start reads the setting back
    moved     the folder moved and renamed: the same profile, the setting still there
    folder    nothing appeared beside the package, in the working directory or in the browser's own folder
  then:
    root      with --drive-root: the package as the root of a drive letter that `subst` puts on its own folder
              (no real drive is touched; a real USB drive cannot be tested by a program)
    host      nothing new in the PC's own Thoron folders (names are compared, nothing is opened; a name that
              the PC's own browser makes meanwhile shows here too); the registry key the browser engine uses
              and the temporary folder are reported

Only a process whose program file is inside the scratch folder is ever closed, and everything made is removed.
    py -3 -I tools/qa/portable_check.py --chrome-bin <out>\\Chrome-bin --work <scratch dir> [--drive-root]
Exit status 0 only when every step passes (or the check does not apply, on another system).
"""
import argparse
import base64
import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.qa import bench  # noqa: E402
from tools.qa.adblock_site_switch_check import _close_browser, _devtools_port, _open  # noqa: E402
from tools.qa.cdp import WebSocket  # noqa: E402
from tools.release import package_audit, portable as po  # noqa: E402

SETTING = "webkit.webprefs.default_font_size"      # a plain setting of the profile, 16 until someone changes it
DEFAULT = 16
OFFLINE = "MAP * ~NOTFOUND, EXCLUDE 127.0.0.1"
ARGUMENTS = ("--headless=new", "--no-first-run", "--disable-background-networking", "--disable-component-update",
             f'"--host-resolver-rules={OFFLINE}"', "--remote-debugging-address=127.0.0.1",
             "--remote-debugging-port=0", "about:blank")
REAL_KEY = "Software\\Thoron"       # under the current user: where the browser engine keeps a few values
LAUNCHER_S = 30
NEEDED = ("executable_path", "profile_path")      # what chrome://version must have filled in before it is read
VERSION_JS = ("JSON.stringify(Object.fromEntries(['executable_path', 'profile_path', 'command_line'].map((id) => "
              "[id, ((document.getElementById(id) || {}).textContent || '').trim()])))")
READY_JS = "typeof chrome !== 'undefined' && !!chrome.settingsPrivate"
GET_JS = (f"new Promise((done) => chrome.settingsPrivate.getPref('{SETTING}', "
          "(pref) => done(pref ? pref.value : null)))")
SET_JS = f"new Promise((done) => chrome.settingsPrivate.setPref('{SETTING}', %d, '', (ok) => done(ok === true)))"


def supported() -> bool:
    return os.name == "nt"


def cases() -> list[dict]:
    """The folders a package is tried in, and moved to. Built from code points, so this file stays ASCII."""
    latin = "Caf\u00e9 \u00dcbung"
    cyrillic = "\u041f\u0440\u0438\u043c\u0435\u0440"
    cjk = "\u4f8b\u3048 \u30c6\u30b9\u30c8 \ud55c\uae00"
    return [
        {"name": "spaces", "first": "a folder  with spaces", "second": "another place", "value": 17},
        {"name": "scripts", "first": f"{latin} {cyrillic} {cjk}", "second": f"{cjk} {cyrillic}", "value": 19},
        {"name": "signs", "first": "R&D 100% (new)! a^b", "second": "50% & more! it's (2)", "value": 21},
    ]


def start_line(package: Path) -> str:
    """What a double click on the launcher runs, with the arguments this check needs passed through it."""
    return f'"{package / po.LAUNCHER}" ' + " ".join(ARGUMENTS)


def same(found: str | None, want: Path) -> bool:
    return bool(found) and os.path.normcase(os.path.normpath(found.strip())) == os.path.normcase(str(want))


def start_problems(package: Path, found: dict, real: Path | None = None) -> list[str]:
    """What one start got wrong. `real`: the folder a drive letter stands for, when `package` is its root."""
    out = [f"the run failed: {found['error']}"] if "error" in found else []
    if found.get("launcher") is None:
        out.append(f"the launcher had not ended after {LAUNCHER_S} s: it waits for the browser")
    elif found["launcher"] != 0:
        out.append(f"the launcher ended with {found['launcher']}")
    homes = [package] + ([real] if real else [])
    for key, who in (("executable_path", "the browser"), ("process", "Windows")):
        if not any(same(found.get(key), home / po.BROWSER_DIR / po.PROGRAM) for home in homes):
            out.append(f"{who} names a program that is not the one in the folder")
    if not same(found.get("profile_path"), package / po.PROFILE_DIR / "Default"):
        out.append("the browser says its profile is not the one in the folder")
    if OFFLINE not in (found.get("command_line") or ""):
        out.append("an argument with spaces did not reach the browser whole")
    for key, what in (("port_file", "the DevTools port file"), ("local_state", "Local State"),
                      ("preferences", "Default\\Preferences")):
        if not found.get(key):
            out.append(f"{what} is not in the folder's profile")
    if found.get("left"):
        out.append(f"{found['left']} browser process(es) did not end and had to be stopped")
    return out


def setting_problems(found: dict, before: int, change: int | None) -> list[str]:
    """`before`: what the setting must be at the start; `change`: what this start sets it to, if anything."""
    out = []
    if found.get("before") != before:
        out.append(f"the setting is {found.get('before')} at the start, not {before}")
    if change is not None and found.get("after") != change:
        out.append(f"the setting is {found.get('after')} after the change, not {change}")
    want = before if change is None else change
    if found.get("saved") != want:
        out.append(f"the profile on the disk holds {found.get('saved')} after the exit, not {want}")
    return out


def folder_problems(package: list[str], beside: list[str], working: list[str], browser_before: list[str],
                    browser_after: list[str]) -> list[str]:
    """Names only: the package's top, its parent folder, the working directory, the browser's own folder."""
    out = []
    extra = sorted(set(package) - {po.LAUNCHER, po.README, po.BROWSER_DIR, po.PROFILE_DIR})
    if extra or po.PROFILE_DIR not in package:
        out.append(f"the package's folder holds {sorted(package)}")
    if len(beside) != 1:
        out.append(f"beside the package: {sorted(beside)}")
    if working:
        out.append(f"in the working directory: {sorted(working)}")
    if browser_before != browser_after:
        changed = sorted(set(browser_before) ^ set(browser_after))
        out.append(f"the browser's own folder changed: {changed[:5]}")
    return out


def host_problems(before: dict, after: dict) -> list[str]:
    """New names in the PC's own folders (folder -> names, or None when the folder is not there)."""
    out = []
    for folder, names in after.items():
        new = sorted(set(names or []) - set(before.get(folder) or []))
        if names is not None and before.get(folder) is None:
            out.append(f"{folder} was made")
        elif new:
            out.append(f"new in {folder}: {new}")
    return out


def registry_report(before: dict | None, after: dict | None) -> str:
    """Keys (name -> time of the last write) made or written between two looks; names and times only."""
    if after is None:
        return "no key"
    if before is None:
        return f"the key was made, with {sorted(k for k in after if k)}"
    new = sorted(k for k in after if k not in before)
    written = sorted(k or "(the key itself)" for k in after if k in before and after[k] != before[k])
    return f"new keys: {new or 'none'}; written during the runs: {written or 'none'}"


def masked(names: list[str]) -> dict:
    """Names with their numbers replaced, counted: what kinds of entries a folder holds."""
    out: dict = {}
    for name in names:
        kind = re.sub(r"\d+", "#", name)
        out[kind] = out.get(kind, 0) + 1
    return dict(sorted(out.items()))


def key_kind(local_state: dict) -> str:
    """How a profile keeps its key for passwords and cookies: the kind only, never the key."""
    raw = (local_state.get("os_crypt") or {}).get("encrypted_key")
    if not raw:
        return "no key"
    try:
        head = base64.b64decode(raw)[:5]
    except ValueError:
        return "unreadable"
    return "the Windows account (DPAPI)" if head == b"DPAPI" else "another kind"


def where_named(node, needle: str, at: str = "") -> list[str]:
    """The settings in parsed settings whose text, or whose own name, holds `needle`: a folder the package was
    moved away from. A setting is told by its dotted name, never by what it holds."""
    if isinstance(node, dict):
        out = []
        for key, value in node.items():
            if needle.casefold() in str(key).casefold():
                out.append(f"{at} (a name in it)" if at else "(a name)")
            out += where_named(value, needle, f"{at}.{key}" if at else str(key))
        return out
    if isinstance(node, list):
        return [where for value in node for where in where_named(value, needle, at)]
    return [at] if isinstance(node, str) and needle.casefold() in node.casefold() else []


def mentions(profile: Path, needle: str) -> list[str]:
    out = []
    for name in ("Local State", "Default/Preferences", "Default/Secure Preferences"):
        try:
            settings = json.loads((profile / name).read_text(encoding="utf-8"))
            out += [f"{name}: {where}" for where in where_named(settings, needle)]
        except (OSError, ValueError):
            pass
    return sorted(set(out))


def disk_facts(profile: Path) -> dict:
    """What a start left in the profile folder: which files, the saved setting, how the key is kept."""
    out = {"local_state": (profile / "Local State").is_file(),
           "preferences": (profile / "Default" / "Preferences").is_file(), "saved": None, "key": "no key"}
    try:
        prefs = json.loads((profile / "Default" / "Preferences").read_text(encoding="utf-8"))
        out["saved"] = ((prefs.get("webkit") or {}).get("webprefs") or {}).get("default_font_size", DEFAULT)
        out["key"] = key_kind(json.loads((profile / "Local State").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return out


def names_in(folders: dict) -> dict:
    """The names in each folder (label -> folder), None when it is not there. Nothing is opened."""
    out = {}
    for label, folder in folders.items():
        try:
            out[label] = sorted(os.listdir(folder))
        except OSError:
            out[label] = None
    return out


def real_places() -> dict:
    """Where an installed Thoron lives on this PC: its folder and its profile folder, under a label to print."""
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return {}
    return {"%LOCALAPPDATA%\\Thoron": Path(local) / "Thoron",
            f"%LOCALAPPDATA%\\Thoron\\{po.PROFILE_DIR}": Path(local) / "Thoron" / po.PROFILE_DIR}


def registry_keys(path: str = REAL_KEY) -> dict | None:
    """Every key below `path` of the current user with the time of its last write. Read only, no values."""
    import winreg
    out = {}

    def walk(sub: str) -> None:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, f"{path}\\{sub}" if sub else path, 0, winreg.KEY_READ) as key:
            count, _, written = winreg.QueryInfoKey(key)
            out[sub] = written
            children = [winreg.EnumKey(key, i) for i in range(count)]
        for child in children:
            try:
                walk(f"{sub}\\{child}" if sub else child)
            except OSError:
                pass

    try:
        walk("")
    except OSError:
        return None
    return out


def _kernel32():
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.restype = wintypes.HANDLE
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.WaitForSingleObject.restype = wintypes.DWORD
    k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                             ctypes.POINTER(wintypes.DWORD)]
    k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k.GetLogicalDrives.restype = wintypes.DWORD
    for walk in (k.Process32FirstW, k.Process32NextW):
        walk.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    return k


def _program(k, handle) -> str:
    from ctypes import wintypes
    size = wintypes.DWORD(32768)
    text = ctypes.create_unicode_buffer(size.value)
    if not k.QueryFullProcessImageNameW(handle, 0, text, ctypes.byref(size)):
        raise OSError("the program of a process cannot be read")
    return text.value


def program_of(pid: int) -> str | None:
    """The program file of a process, asked with the right to read that name and nothing more."""
    k = _kernel32()
    handle = k.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        return _program(k, handle)
    except OSError:
        return None
    finally:
        k.CloseHandle(handle)


class Started:
    """A running process held as subprocess.Popen holds one (pid, wait), so that the repo's helpers can close it.

    The launcher's own process ends at once, so the browser it started is found afterwards. The open handle
    keeps the process number from being given to another process while it is held.
    """

    def __init__(self, pid: int):
        self._k = _kernel32()
        self.pid = pid
        self._handle = self._k.OpenProcess(0x00100000 | 0x1000, False, pid)   # wait for it, ask for its program
        if not self._handle:
            raise OSError(f"process {pid} is not there any more")

    def program(self) -> str:
        """The program file of the process, as Windows names it."""
        return _program(self._k, self._handle)

    def wait(self, timeout: float | None = None) -> int:
        limit = 0xFFFFFFFF if timeout is None else int(timeout * 1000)
        if self._k.WaitForSingleObject(self._handle, limit) != 0:
            raise subprocess.TimeoutExpired(f"process {self.pid}", timeout)
        return 0

    def close(self) -> None:
        if self._handle:
            self._k.CloseHandle(self._handle)
            self._handle = None


def own_processes(belongs, name: str = po.PROGRAM) -> list[tuple[int, int]]:
    """(process, parent) of every running `name` whose program file `belongs` (a test of the file's full name).

    This is how the check tells its own browser copies from any other browser on the PC: by the program file,
    which for its copies is inside the scratch folder. Other processes are only asked for that name.
    """
    from ctypes import wintypes

    class Entry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", wintypes.LONG), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", wintypes.WCHAR * 260)]

    k = _kernel32()
    snapshot = k.CreateToolhelp32Snapshot(2, 0)        # every process
    if not snapshot or snapshot == wintypes.HANDLE(-1).value:
        raise OSError("the processes cannot be listed")
    out, entry = [], Entry()
    entry.dwSize = ctypes.sizeof(Entry)
    try:
        more = k.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            if entry.szExeFile.lower() == name.lower():
                program = program_of(entry.th32ProcessID)       # None: it ended meanwhile, or is not ours to ask
                if program and belongs(program):
                    out.append((entry.th32ProcessID, entry.th32ParentProcessID))
            more = k.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        k.CloseHandle(snapshot)
    return out


def stop_own(belongs, scratch: Path, patience_s: float = 15) -> int:
    """Wait for this check's own browser processes to end and stop those that do not. How many were stopped."""
    deadline = time.monotonic() + patience_s
    while time.monotonic() < deadline:
        if not own_processes(belongs):
            return 0
        time.sleep(0.5)
    left = own_processes(belongs)
    stopped = 0
    for pid, parent in left:
        if parent in {p for p, _ in left}:
            continue                                    # it ends with its parent
        try:
            process = Started(pid)
        except OSError:
            continue
        try:
            if belongs(process.program()):              # still ours, and the handle keeps the number ours
                bench._stop(process, Path(tempfile.mkdtemp(prefix="stopped-", dir=scratch)))
                stopped += 1
        finally:
            process.close()
    return stopped


def free_letter() -> str | None:
    """A drive letter nothing uses, from the end of the alphabet."""
    used = _kernel32().GetLogicalDrives()
    for letter in "ZYXWVUTSRQPONMLKJIHGFED":
        if not used & (1 << (ord(letter) - ord("A"))):
            return letter
    return None


def devtools_port(profile: Path, tries: int = 3) -> int:
    """The port file in the profile, as the other checks read it, with patience for a program just unpacked."""
    for n in range(tries):
        try:
            return _devtools_port(profile)
        except RuntimeError:
            if n == tries - 1:
                raise
    raise RuntimeError("DevTools did not start")


def evaluate(ws: WebSocket, expression: str):
    reply = ws.call("Runtime.evaluate", expression=expression, awaitPromise=True, returnByValue=True)
    return reply.get("result", {}).get("value")


def wait_for(ws: WebSocket, expression: str, good, limit_s: float = 40):
    deadline = time.monotonic() + limit_s
    while True:
        value = evaluate(ws, expression)
        if good(value):
            return value
        if time.monotonic() > deadline:
            raise RuntimeError("a page of the browser did not answer")
        time.sleep(0.3)


def one_start(package: Path, working: Path, temp: Path, change: int | None, belongs) -> dict:
    """One start through the launcher and a normal exit. What was seen, for the *_problems functions."""
    found: dict = {}
    profile = package / po.PROFILE_DIR
    (profile / "DevToolsActivePort").unlink(missing_ok=True)    # one left by the last start names a closed port
    began = time.monotonic()
    launcher = subprocess.Popen(start_line(package), cwd=working, env=dict(os.environ, TEMP=str(temp), TMP=str(temp)),
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                creationflags=subprocess.CREATE_NO_WINDOW)
    port = browser = None
    sockets = []
    try:
        try:
            found["launcher"] = launcher.wait(timeout=LAUNCHER_S)
        except subprocess.TimeoutExpired:
            launcher.kill()                                     # the launcher's own cmd.exe, started just above
            found["launcher"] = None
        found["launcher_s"] = round(time.monotonic() - began, 1)
        port = devtools_port(profile)
        found["port_file"] = True
        running = own_processes(belongs)
        tops = [pid for pid, parent in running if parent not in {p for p, _ in running}]
        if len(tops) != 1:
            raise RuntimeError(f"{len(tops)} browsers run from the folder, not 1")
        browser = Started(tops[0])
        found["process"] = browser.program()
        sockets.append(WebSocket(_open(port, "chrome://version")["webSocketDebuggerUrl"]))
        told = wait_for(sockets[-1], VERSION_JS, lambda v: v and all(json.loads(v)[k] for k in NEEDED))
        found.update(json.loads(told))
        sockets.append(WebSocket(_open(port, "chrome://settings/")["webSocketDebuggerUrl"]))
        wait_for(sockets[-1], READY_JS, bool)
        found["before"] = evaluate(sockets[-1], GET_JS)
        if change is not None:
            evaluate(sockets[-1], SET_JS % change)
            found["after"] = evaluate(sockets[-1], GET_JS)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as e:
        found["error"] = str(e)
    finally:
        for ws in sockets:
            try:
                ws.close()
            except OSError:
                pass
        if browser is not None and port is not None:
            try:
                _close_browser(port, browser)                   # a normal exit, as when a person closes it
            except subprocess.TimeoutExpired:
                pass
        found["left"] = stop_own(belongs, temp)
        if browser is not None:
            browser.close()
    found.update(disk_facts(profile))
    return found


def unpack(archive: Path, place: Path, package: Path) -> list[str]:
    """The .zip unpacked into `place`; why what came out is not the package (empty when it is)."""
    with zipfile.ZipFile(archive) as z:
        z.extractall(place)
    got = place / po.FOLDER
    out = [p.name for p in place.iterdir() if p.name != po.FOLDER]
    out = [f"the .zip holds more than one folder: {out}"] if out else []
    if not got.is_dir() or po.files(got) != po.files(package):
        return out + ["the .zip does not unpack to the package's files"]
    return out + [f"unpacked: {p}" for p in po.audit(got)]


def only(program: Path):
    """A test for own_processes: is a process's program file this one?"""
    wanted = os.path.normcase(str(program))
    return lambda image: os.path.normcase(image) == wanted


def run_case(case: dict, made: dict, root: Path, working: Path, temp: Path, step) -> None:
    name, value = case["name"], case["value"]
    place = root / case["first"]
    problems = unpack(made["zip"], place, made["package"])
    package = place / po.FOLDER
    if problems:
        step(f"{name}/first", problems, "nothing was started")
        return
    browser_before = po.files(package / po.BROWSER_DIR)
    found = one_start(package, working, temp, value, only(package / po.BROWSER_DIR / po.PROGRAM))
    step(f"{name}/first", start_problems(package, found) + setting_problems(found, DEFAULT, value),
         f"the launcher ended after {found.get('launcher_s')} s; program and profile in the folder; a new profile, "
         f"setting {found.get('before')} -> {found.get('after')}; its key is kept by {found.get('key')}")
    found = one_start(package, working, temp, None, only(package / po.BROWSER_DIR / po.PROGRAM))
    step(f"{name}/again", start_problems(package, found) + setting_problems(found, value, None),
         f"the setting read back: {found.get('before')}")
    moved = root / case["second"] / f"Thoron {name}"
    moved.parent.mkdir()
    for attempt in range(40):       # a scanner may still hold a file for a moment
        try:
            package.rename(moved)
            break
        except OSError as e:
            if attempt == 39:
                step(f"{name}/moved", [f"the folder could not be moved: {e.strerror}"], "")
                return
            time.sleep(0.5)
    found = one_start(moved, working, temp, None, only(moved / po.BROWSER_DIR / po.PROGRAM))
    old = mentions(moved / po.PROFILE_DIR, case["first"])
    step(f"{name}/moved", start_problems(moved, found) + setting_problems(found, value, None),
         f"the same profile in the new place, setting {found.get('before')}; settings that still name the old "
         f"place: {old or 'none'}")
    step(f"{name}/folder",
         folder_problems([p.name for p in moved.iterdir()], [p.name for p in moved.parent.iterdir()],
                         [p.name for p in working.iterdir()], browser_before, po.files(moved / po.BROWSER_DIR))
         + ([f"left where the package was: {[p.name for p in place.iterdir()]}"] if any(place.iterdir()) else []),
         f"the package holds {sorted(p.name for p in moved.iterdir())}, nothing beside it or in the working directory")
    shutil.rmtree(place, ignore_errors=True)
    shutil.rmtree(moved.parent, ignore_errors=True)


def run_root(made: dict, root: Path, working: Path, temp: Path, step) -> None:
    place = root / "for a drive letter"
    problems = unpack(made["zip"], place, made["package"])
    package = place / po.FOLDER
    letter = free_letter()
    if problems or not letter:
        step("root", problems or ["no drive letter is free"], "nothing was started")
        return
    if subprocess.run(["subst", f"{letter}:", str(package)], capture_output=True).returncode != 0:
        step("root", ["subst could not put a drive letter on the folder"], "nothing was started")
        return
    try:
        drive = Path(f"{letter}:\\")
        mine = (only(drive / po.BROWSER_DIR / po.PROGRAM), only(package / po.BROWSER_DIR / po.PROGRAM))
        found = one_start(drive, working, temp, 23, lambda image: any(test(image) for test in mine))
        problems = start_problems(drive, found, real=package) + setting_problems(found, DEFAULT, 23)
    finally:
        subprocess.run(["subst", f"{letter}:", "/d"], capture_output=True)
    if os.path.exists(f"{letter}:\\"):
        problems.append("the drive letter is still there: remove it with `subst <letter>: /d`")
    if not (package / po.PROFILE_DIR / "Default" / "Preferences").is_file():
        problems.append("the profile is not in the folder the drive letter stood for")
    step("root", problems, f"started as <letter>:\\{po.LAUNCHER}, the launcher ended after {found.get('launcher_s')} s; "
                           f"profile at <letter>:\\{po.PROFILE_DIR}, setting {found.get('before')} -> {found.get('after')}; "
                           "the letter is removed again")
    shutil.rmtree(place, ignore_errors=True)


def run(chrome_bin: Path, work: Path, variant: str, drive_root: bool, case: str | None) -> list[str]:
    problems: list[str] = []

    def step(name: str, found: list[str], detail: str) -> None:
        print(f"{'PASS' if not found else 'FAIL'}  {name}: {detail}", flush=True)
        problems.extend(f"{name}: {p}" for p in found)

    root = Path(tempfile.mkdtemp(prefix="portable-", dir=work))
    inside = os.path.normcase(str(root)) + os.sep
    try:
        working, temp = root / "working directory", root / "temp"
        working.mkdir()
        temp.mkdir()
        try:
            made = po.build(chrome_bin, root / "dist", variant)
        except (po.PortableError, OSError) as e:
            step("package", [str(e)], "not built")
            return problems
        browser = made["package"] / po.BROWSER_DIR      # audited as `package_audit.py --dir` lists it
        audits = po.audit(made["package"]) + package_audit.audit(
            [str(p.relative_to(browser)) for p in browser.rglob("*")], "win")
        step("package", audits, f"{made['files']} files, Thoron {made['version']}, a .zip of "
                                f"{made['zip'].stat().st_size / 1e6:.0f} MB; the portable audit and package_audit.py pass")
        if audits:
            return problems         # nothing is started from a package that fails its audit
        before = {"names": names_in(real_places()), "keys": registry_keys()}
        for one in cases():
            if case in (None, one["name"]):
                run_case(one, made, root, working, temp, step)
        if drive_root:
            run_root(made, root, working, temp, step)
        after = {"names": names_in(real_places()), "keys": registry_keys()}
        left = masked([p.name for p in temp.iterdir() if not p.name.startswith("stopped-")])
        count = sum(len(v or []) for v in after["names"].values())
        new = host_problems(before["names"], after["names"])
        step("host", new,
             f"{len(after['names'])} folders of the PC's own Thoron hold {count} names, {'some' if new else 'none'} "
             f"new; registry key {REAL_KEY}: {registry_report(before['keys'], after['keys'])}; left in the "
             f"temporary folder: {left or 'nothing'}")
    finally:
        stop_own(lambda image: os.path.normcase(image).startswith(inside), root, patience_s=0)
        shutil.rmtree(root, ignore_errors=True)
        if root.exists():
            problems.append("the scratch folder could not be removed")
    return problems


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--chrome-bin", required=True, type=Path, help="a build's Chrome-bin folder; it is only read")
    p.add_argument("--work", required=True, type=Path, help="scratch folder; what is made there is removed again")
    p.add_argument("--variant", default="win-x64-avx2")
    p.add_argument("--drive-root", action="store_true", help="also start from the root of a `subst` drive letter")
    p.add_argument("--case", choices=[c["name"] for c in cases()], help="only this folder")
    a = p.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    if not supported():
        print("PORTABLE CHECK: does not apply here (the package is for Windows)")
        return 0
    a.work.mkdir(parents=True, exist_ok=True)
    problems = run(a.chrome_bin.resolve(), a.work.resolve(), a.variant, a.drive_root, a.case)
    for problem in problems:
        print(problem)
    print("PORTABLE CHECK: PASSED" if not problems else f"PORTABLE CHECK: FAILED ({len(problems)} problem(s))")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
