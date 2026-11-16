#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Open windows, tabs and tab groups of a Chromium-family profile, read from its session files (ROADMAP P3.15).

A profile keeps them in `Sessions/`: `Session_<time>` holds the windows that come back on the next start and
`Tabs_<time>` the recently closed tabs, windows and groups. Both are Chromium's SNSS format: a header (`SNSS`,
version 3), then commands, each a 16-bit size, an 8-bit id and its contents (a fixed structure or a
base::Pickle); the browser replays the commands to rebuild its windows. This module replays them the same way
(components/sessions/core: session_service_commands.cc, tab_restore_service_impl.cc) and trusts no byte of
them: every read is bounds-checked, the file size, the counts and the work are capped, a command it does not know
or cannot read is skipped and counted, and bad input raises `SessionError`, never another exception or a hang.

What a reading gives: the windows in order (type, show state, bounds, the selected tab), each window's tabs in
order (pinned, group, the current navigation, and every navigation with its URL, title and index), the groups
(title, colour, collapsed) and the recently closed entries. Encrypted session files (`Sessions_Encrypted/`,
version 5) are not read; the browser writes a clear copy in `Sessions/` beside them.

    py -3 -I tools/migrate/sessions.py read --profile "<User Data>\\Default"     (or --file <a Session_ or Tabs_ file>)
        prints the reading as JSON; it only reads (titles and addresses are the person's own: keep them on the PC)
    py -3 -I tools/migrate/sessions.py import --from "<User Data>\\Default" --to "<Thoron User Data>\\Default"
        [--set-aside] [--restore-on-next-start]
        copies the session the source browser would restore (its newest `Session_` and `Tabs_` files) into a
        Thoron profile, never moving anything; the source is hashed before and after, and each file written is
        checked by SHA-256 against what was meant to be written. The copy is the source byte for byte except in
        two ways, and it must read exactly as the source does: (1) commands this reader cannot use (another
        vendor's own, or damaged ones) are left out, because the browser stops reading a session at the first
        such command and loses the rest; (2) each tab group's link to the source profile's saved groups is taken
        out, because Thoron would take a group linked to a saved group it does not know for one deleted elsewhere
        and close it with its tabs; unlinked, Thoron restores it and saves it as its own. Refused while either
        browser runs, for a Thoron profile that has never started, and when the Thoron profile has a session of
        its own (`--set-aside` keeps that one in a folder inside `Sessions/`). `--restore-on-next-start` makes
        the next start of Thoron open the imported windows once, the way it does after an update (`was.restarted`
        in `Local State`), without changing the start-up setting.
"""
from __future__ import annotations   # the pickle classes have methods named int, bool and bytes

import argparse
import bisect
import hashlib
import json
import os
import re
import struct
import sys
import time
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.migrate.import_profile import ImportRefused, VerificationFailed  # noqa: E402


class SessionError(Exception):
    """The input is not a session file this reader accepts; the only exception bad input raises."""


# --- limits: no input makes the reader use more memory or time than these allow ------------------------------
MOST_FILE_BYTES = 64 * 1024 * 1024    # a heavy real session is a few MB
MOST_COMMANDS = 2_000_000
MOST_WINDOWS = 1_000
MOST_TABS = 20_000
MOST_GROUPS = 20_000
MOST_NAVIGATIONS = 1_000              # per tab; a browser keeps 50
MOST_ALL_NAVIGATIONS = 200_000        # in all tabs together
MOST_ENTRIES = 1_000                  # recently closed; a browser keeps 25
MOST_WORK = 30_000_000                # steps of replay (a prune walks a tab's navigations)
MOST_LOCAL_STATE_BYTES = 8 * 1024 * 1024

SIGNATURE = b"SNSS"
VERSION = 3                           # kFileVersionWithMarker; 5 is the encrypted one
ENCRYPTED_VERSIONS = (2, 4, 5)
MARKER = 255                          # kInitialStateMarkerCommandId: the file holds a complete state after it
FORMAT = "thoron-session-reading"

COLOURS = ("grey", "blue", "red", "yellow", "green", "pink", "purple", "cyan", "orange")
WINDOW_TYPES = ("normal", "popup", "app", "devtools", "app_popup")
# PersistedWindowShowState (Session_ files); 6 and 7 were docked and detached, read as normal
SHOW_STATES = {1: "normal", 2: "minimized", 3: "maximized", 5: "fullscreen", 6: "normal", 7: "normal"}
# SerializedWindowShowState (Tabs_ files)
CLOSED_SHOW_STATES = {0: "default", 1: "normal", 2: "minimized", 3: "maximized", 4: "inactive", 5: "fullscreen"}

# Session_ command ids (session_service_commands.cc)
S_TAB_WINDOW, S_TAB_INDEX, S_PRUNED_BACK, S_NAVIGATION, S_SELECTED_NAVIGATION = 0, 2, 5, 6, 7
S_SELECTED_TAB, S_WINDOW_TYPE, S_WINDOW_BOUNDS2, S_PRUNED_FRONT, S_PINNED = 8, 9, 10, 11, 12
S_APP_ID, S_WINDOW_BOUNDS3, S_WINDOW_APP_NAME, S_TAB_CLOSED, S_WINDOW_CLOSED = 13, 14, 15, 16, 17
S_USER_AGENT, S_SESSION_STORAGE, S_ACTIVE_WINDOW, S_LAST_ACTIVE, S_WORKSPACE2 = 18, 19, 20, 21, 23
S_PRUNED, S_TAB_GROUP, S_GROUP_METADATA2, S_TAB_GUID, S_USER_AGENT2, S_TAB_DATA = 24, 25, 27, 28, 29, 30
S_WINDOW_TITLE, S_ALL_WORKSPACES, S_TAB_EXTRA, S_WINDOW_EXTRA, S_PLATFORM_ID = 31, 32, 33, 34, 35
S_SPLIT_TAB, S_SPLIT_DATA = 36, 37
# Tabs_ command ids (tab_restore_service_impl.cc)
T_NAVIGATION, T_RESTORED, T_WINDOW_OLD, T_SELECTED_NAVIGATION, T_PINNED, T_APP_ID = 1, 2, 3, 4, 5, 6
T_WINDOW_APP_NAME, T_USER_AGENT, T_WINDOW, T_GROUP_DATA, T_USER_AGENT2, T_WINDOW_TITLE = 7, 8, 9, 10, 11, 12
T_CREATE_GROUP, T_TAB_EXTRA, T_CREATE_SPLIT, T_SPLIT_DATA = 13, 14, 15, 16

_FILE_NAME_RE = re.compile(r"^(Session|Tabs)_([0-9]{1,19})$")
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z")
_REPARSE_POINT = 0x400


# --- the file: header and commands ----------------------------------------------------------------------------

def split_commands(data: bytes) -> tuple[list[tuple[int, bytes]], dict]:
    """The commands of an SNSS file as (id, contents), the marker left out, and what was seen: whether the file
    has the marker (the browser only uses a file that has it) and whether it ends cleanly (a torn last command is
    dropped, as the browser does)."""
    info: dict = {}
    return list(_commands(data, info)), info


def _check_header(data: bytes) -> None:
    if not isinstance(data, (bytes, bytearray)):
        raise SessionError("not bytes")
    if len(data) > MOST_FILE_BYTES:
        raise SessionError(f"larger than {MOST_FILE_BYTES // (1024 * 1024)} MB; not a session this reader accepts")
    if not data:
        raise SessionError("the file is empty")
    if len(data) < 8 or data[:4] != SIGNATURE:
        raise SessionError("not a session file (no SNSS header)")
    version = int.from_bytes(data[4:8], "little", signed=True)
    if version in ENCRYPTED_VERSIONS:
        raise SessionError(f"an encrypted session file (version {version}); the browser keeps a clear copy")
    if version != VERSION:
        raise SessionError(f"session file version {version} is not supported (only {VERSION})")


def _commands(data: bytes, info: dict):
    """Yield (id, contents) of each command; `info` gets "marker", "complete" and "commands" at the end."""
    _check_header(data)
    pos, end, count = 8, len(data), 0
    info.update(marker=False, complete=True, commands=0)
    while pos < end:
        if end - pos < 2:
            info["complete"] = False
            break
        size = data[pos] | (data[pos + 1] << 8)
        if size < 1 or size > end - pos - 2:
            info["complete"] = False
            break
        cid = data[pos + 2]
        if cid == MARKER:
            info["marker"] = True
        else:
            count += 1
            if count > MOST_COMMANDS:
                raise SessionError(f"more than {MOST_COMMANDS} commands; not a session this reader accepts")
            info["commands"] = count
            yield cid, bytes(data[pos + 3:pos + 2 + size])
        pos += 2 + size


class _Pickle:
    """A reader of base::Pickle contents with base::PickleIterator's rules: 4-byte alignment, and after a failed
    read every later read fails too. Each read returns None when the data is short."""

    def __init__(self, payload: bytes):
        self.data, self.pos = b"", 0
        if len(payload) < 4:
            return
        size = int.from_bytes(payload[:4], "little")
        if size > len(payload) - 4:
            return
        header = len(payload) - size
        if header % 4:
            return
        self.data, self.pos = payload, header

    def _take(self, n: int) -> bytes | None:
        if n < 0 or n > len(self.data) - self.pos:
            self.pos = len(self.data)
            return None
        out = self.data[self.pos:self.pos + n]
        self.pos = min(self.pos + n + (-n % 4), len(self.data))
        return out

    def _num(self, fmt: str):
        raw = self._take(struct.calcsize(fmt))
        return None if raw is None else struct.unpack(fmt, raw)[0]

    def int(self) -> int | None:
        return self._num("<i")

    def u32(self) -> int | None:
        return self._num("<I")

    def i64(self) -> int | None:
        return self._num("<q")

    def u64(self) -> int | None:
        return self._num("<Q")

    def double(self) -> float | None:
        return self._num("<d")

    def bool(self) -> bool | None:
        raw = self._take(1)
        return None if raw is None else raw[0] != 0

    def bytes(self) -> bytes | None:
        n = self.int()
        if n is None or n < 0:
            self.pos = len(self.data)
            return None
        return self._take(n)

    def string(self) -> str | None:
        raw = self.bytes()
        return None if raw is None else raw.decode("utf-8", "replace")

    def string16_raw(self) -> bytes | None:
        n = self.int()
        if n is None or n < 0:
            self.pos = len(self.data)
            return None
        return self._take(2 * n)

    def string16(self) -> str | None:
        raw = self.string16_raw()
        return None if raw is None else raw.decode("utf-16-le", "replace")

    def rest(self) -> bytes:
        """What follows the fields read so far (fields a newer browser may add)."""
        return self.data[self.pos:]

    def token(self) -> str | None:
        high, low = self.u64(), self.u64()
        return None if high is None or low is None else f"{high:016x}{low:016x}"


def _unpack(fmt: str, payload: bytes):
    """A fixed structure of the browser (little endian, with its padding): None unless the size is exact."""
    if len(payload) != struct.calcsize(fmt):
        return None
    return struct.unpack(fmt, payload)


def _session_id(value: int) -> int:
    return value if value > 0 else -1     # SessionID::FromSerializedValue


def _navigation(p: _Pickle) -> list | None:
    """[index, url, title] of a SerializedNavigationEntry; None when its required fields are not all there."""
    index, url, title = p.int(), p.string(), p.string16()
    page_state, transition = p.bytes(), p.int()
    if index is None or url is None or title is None or page_state is None or transition is None:
        return None
    return [index, url, title]


def _colour(value: int) -> str:
    return COLOURS[value] if 0 <= value < len(COLOURS) else "grey"   # TabGroupVisualData falls back to grey


def _window_type(value: int):
    return WINDOW_TYPES[value] if 0 <= value < len(WINDOW_TYPES) else value


class _Budget:
    def __init__(self):
        self.work = 0
        self.navigations = 0           # held in all tabs together
        self.tabs = 0                  # closed tabs made (Tabs_ files)
        self.skipped = {"unknown": 0, "malformed": 0, "over_limit": 0}
        self.unknown_ids: set[int] = set()
        self.index = -1                # the command being replayed
        self.dropped: list[int] = []   # the commands skipped as unknown or malformed: they change nothing

    def spend(self, steps: int) -> None:
        self.work += steps
        if self.work > MOST_WORK:
            raise SessionError("the file takes too long to read; not a session this reader accepts")

    def skip(self, why: str, cid: int | None = None) -> None:
        self.skipped[why] += 1
        if why != "over_limit" and (not self.dropped or self.dropped[-1] != self.index):
            self.dropped.append(self.index)
        if cid is not None and len(self.unknown_ids) < 64:
            self.unknown_ids.add(cid)


def _first_at_or_after(navs: list, index: int) -> int:
    return bisect.bisect_left(navs, index, key=lambda n: n[0])


def _put_navigation(navs: list, nav: list, budget: _Budget) -> bool:
    budget.spend(1)
    i = _first_at_or_after(navs, nav[0])
    if i < len(navs) and navs[i][0] == nav[0]:
        navs[i] = nav
        return True
    if len(navs) >= MOST_NAVIGATIONS or budget.navigations >= MOST_ALL_NAVIGATIONS:
        return False
    budget.navigations += 1
    navs.insert(i, nav)
    return True


def _prune(tab: dict, index: int, count: int, budget: _Budget) -> None:
    """ProcessTabNavigationPathPrunedCommand: `count` navigations from `index` are gone."""
    navs = tab["navs"]
    budget.spend(1 + len(navs))
    end = index + count
    if index <= tab["current"] < end:
        tab["current"] = index - 1
    elif tab["current"] >= end:
        tab["current"] -= count
    lo, hi = _first_at_or_after(navs, index), _first_at_or_after(navs, end)
    budget.navigations -= max(0, hi - lo)
    del navs[lo:hi]
    for nav in navs:
        if nav[0] >= index:
            nav[0] -= count


def _resolved_current(navs: list, current: int) -> int:
    """The position of the current navigation: the first one at or after its index, else the last."""
    i = _first_at_or_after(navs, current)
    return len(navs) - 1 if i == len(navs) else i


def _navigations_out(navs: list) -> list[dict]:
    return [{"index": n[0], "url": n[1], "title": n[2]} for n in navs]


# --- Session_: the windows that come back ----------------------------------------------------------------------

def read_session(data: bytes) -> dict:
    """The reading of a `Session_` file: its windows, tabs and groups as the browser would restore them."""
    return _read_session(data, _Budget())


def _read_session(data: bytes, budget: _Budget) -> dict:
    info: dict = {}
    tabs: dict[int, dict] = {}
    windows: dict[int, dict] = {}
    groups: dict[str, dict] = {}
    active = None

    def tab(tid: int) -> dict | None:
        tid = _session_id(tid)
        if tid not in tabs:
            if len(tabs) >= MOST_TABS:
                return None
            tabs[tid] = {"id": tid, "window": None, "visual": -1, "current": -1, "pinned": False, "group": None,
                         "navs": []}
        return tabs[tid]

    def window(wid: int) -> dict | None:
        wid = _session_id(wid)
        if wid not in windows:
            if len(windows) >= MOST_WINDOWS:
                return None
            windows[wid] = {"id": wid, "type": None, "selected": -1, "bounds": None, "show": "default",
                            "user_title": "", "app_name": ""}
        return windows[wid]

    def group(token: str) -> dict | None:
        if token not in groups:
            if len(groups) >= MOST_GROUPS:
                return None
            groups[token] = {"title": "", "colour": "grey", "collapsed": False}
        return groups[token]

    for index, (cid, payload) in enumerate(_commands(data, info)):
        budget.index = index
        budget.spend(1)
        ok = _replay_session_command(cid, payload, tab, window, group, tabs, windows, budget)
        if ok is None:
            continue                    # skipped and counted
        if cid == S_ACTIVE_WINDOW:
            active = ok
    return _session_out(tabs, windows, groups, active, info, budget)


def _replay_session_command(cid, payload, tab, window, group, tabs, windows, budget):
    """Replay one command; the active window's id for S_ACTIVE_WINDOW, True for the others, None when skipped.
    A command skipped as unknown or malformed changes nothing (a copy may leave it out)."""
    def bad():
        budget.skip("malformed")
        return None

    def full():
        budget.skip("over_limit")
        return None

    if cid in (S_TAB_WINDOW, S_TAB_INDEX, S_SELECTED_NAVIGATION, S_PRUNED_BACK, S_PRUNED_FRONT, S_SELECTED_TAB,
               S_WINDOW_TYPE):
        fields = _unpack("<ii", payload)
        if fields is None:
            return bad()
        first, value = fields
        if cid == S_TAB_WINDOW:
            t = tab(value)
            if t is None:
                return full()
            t["window"] = _session_id(first)
        elif cid in (S_SELECTED_TAB, S_WINDOW_TYPE):
            w = window(first)
            if w is None:
                return full()
            if cid == S_SELECTED_TAB:
                w["selected"] = value
            else:
                w["type"] = value       # a window without a type is a constrained one, which is dropped
        else:
            t = tab(first)
            if t is None:
                return full()
            if cid == S_TAB_INDEX:
                t["visual"] = value
            elif cid == S_SELECTED_NAVIGATION:
                t["current"] = value
            elif cid == S_PRUNED_BACK:
                budget.spend(len(t["navs"]))
                cut = _first_at_or_after(t["navs"], value)
                budget.navigations -= len(t["navs"]) - cut
                del t["navs"][cut:]
            else:
                if value <= 0:
                    return bad()
                _prune(t, 0, value, budget)
        return True
    if cid == S_PRUNED:
        fields = _unpack("<iii", payload)
        if fields is None or fields[1] < 0 or fields[2] <= 0:
            return bad()
        t = tab(fields[0])
        if t is None:
            return full()
        _prune(t, fields[1], fields[2], budget)
        return True
    if cid == S_NAVIGATION:
        p = _Pickle(payload)
        tid = p.int()
        nav = _navigation(p) if tid is not None else None
        if nav is None:
            return bad()
        t = tab(tid)
        if t is None or not _put_navigation(t["navs"], nav, budget):
            return full()
        return True
    if cid in (S_WINDOW_BOUNDS3, S_WINDOW_BOUNDS2):
        fields = _unpack("<iiiiii" if cid == S_WINDOW_BOUNDS3 else "<iiiii?3x", payload)
        if fields is None:
            return bad()
        w = window(fields[0])
        if w is None:
            return full()
        w["bounds"] = list(fields[1:5])
        if cid == S_WINDOW_BOUNDS3:
            w["show"] = SHOW_STATES.get(fields[5], "normal")
        else:
            w["show"] = "maximized" if fields[5] else "normal"
        return True
    if cid in (S_TAB_CLOSED, S_WINDOW_CLOSED):
        fields = _unpack("<i4xq", payload)
        if fields is None:
            return bad()
        gone = (tabs if cid == S_TAB_CLOSED else windows).pop(_session_id(fields[0]), None)
        if gone is not None and cid == S_TAB_CLOSED:
            budget.navigations -= len(gone["navs"])
        return True
    if cid == S_PINNED:
        fields = _unpack("<i?3x", payload)
        if fields is None:
            return bad()
        t = tab(fields[0])
        if t is None:
            return full()
        t["pinned"] = fields[1]
        return True
    if cid in (S_TAB_GROUP, S_SPLIT_TAB):
        fields = _unpack("<i4xQQ?7x", payload)
        if fields is None:
            return bad()
        t = tab(fields[0])
        if t is None:
            return full()
        if cid == S_TAB_GROUP:
            t["group"] = f"{fields[1]:016x}{fields[2]:016x}" if fields[3] else None
        return True
    if cid == S_GROUP_METADATA2:
        p = _Pickle(payload)
        token = p.token()
        title = p.string16() if token is not None else None
        colour = p.u32() if title is not None else None
        if colour is None:
            return bad()
        collapsed = p.bool()
        if p.bool() and p.string() is None:     # a saved group must name its saved id
            return bad()
        g = group(token)
        if g is None:
            return full()
        g.update(title=title, colour=_colour(colour), collapsed=bool(collapsed))
        return True
    if cid == S_ACTIVE_WINDOW:
        fields = _unpack("<i", payload)
        return bad() if fields is None else _session_id(fields[0])
    if cid in (S_LAST_ACTIVE, S_ALL_WORKSPACES):
        return True if _unpack("<i4xq" if cid == S_LAST_ACTIVE else "<i?3x", payload) else bad()
    if cid in (S_APP_ID, S_WINDOW_APP_NAME, S_WINDOW_TITLE, S_USER_AGENT, S_SESSION_STORAGE, S_WORKSPACE2,
               S_TAB_GUID):
        p = _Pickle(payload)
        owner, text = p.int(), p.string()
        if owner is None or text is None or (cid == S_TAB_GUID and not _UUID_RE.match(text)):
            return bad()
        if cid in (S_WINDOW_APP_NAME, S_WINDOW_TITLE):
            w = window(owner)
            if w is None:
                return full()
            w["app_name" if cid == S_WINDOW_APP_NAME else "user_title"] = text
        return True
    if cid == S_USER_AGENT2:
        p = _Pickle(payload)
        if p.int() is None or p.string() is None:
            return bad()
        has_metadata = p.bool()
        if has_metadata is None or (has_metadata and p.string() is None):
            return bad()
        return True
    if cid in (S_TAB_EXTRA, S_WINDOW_EXTRA):
        p = _Pickle(payload)
        return True if p.int() is not None and p.string() is not None and p.string() is not None else bad()
    if cid == S_TAB_DATA:
        p = _Pickle(payload)
        if p.int() is None:
            return bad()
        count = p.int()
        if count is None:
            return bad()
        for _ in range(max(0, count)):
            budget.spend(1)
            if p.string() is None or p.string() is None:
                return bad()
        return True
    if cid == S_PLATFORM_ID:
        return True if _Pickle(payload).string() is not None else bad()
    if cid == S_SPLIT_DATA:
        p = _Pickle(payload)
        return True if p.token() is not None and p.double() is not None and p.string() is not None else bad()
    budget.skip("unknown", cid)
    return None


def _session_out(tabs, windows, groups, active, info, budget) -> dict:
    """AddTabsToWindows, SortTabsBasedOnVisualOrderAndClear and UpdateSelectedTabIndex, then the reading."""
    members: dict[int, list] = {}
    for tid in sorted(tabs):
        t = tabs[tid]
        w = windows.get(t["window"]) if t["window"] is not None else None
        if w is None or not t["navs"]:
            continue
        members.setdefault(w["id"], []).append(t)
    out_windows = []
    for wid in sorted(windows):
        w = windows[wid]
        if w["type"] is None or not members.get(wid):
            continue                    # constrained or empty: the browser drops it
        ordered = sorted(members[wid], key=lambda t: (t["visual"], t["id"]))
        selected = next((i for i, t in enumerate(ordered) if t["visual"] == w["selected"]), 0)
        window_groups, seen, out_tabs = [], set(), []
        for t in ordered:
            if t["group"] is not None and t["group"] not in seen:
                seen.add(t["group"])
                g = groups.get(t["group"], {"title": "", "colour": "grey", "collapsed": False})
                window_groups.append({"id": t["group"], "title": g["title"], "color": g["colour"],
                                      "collapsed": g["collapsed"]})
            out_tabs.append({"id": t["id"], "pinned": t["pinned"], "group": t["group"],
                             "current": _resolved_current(t["navs"], t["current"]),
                             "navigations": _navigations_out(t["navs"])})
        out_windows.append({"id": wid, "type": _window_type(w["type"]), "show_state": w["show"],
                            "bounds": w["bounds"], "selected_tab": selected, "user_title": w["user_title"],
                            "app_name": w["app_name"], "tabs": out_tabs, "groups": window_groups})
    active_index = next((i for i, w in enumerate(out_windows) if w["id"] == active), None)
    return {"windows": out_windows, "active_window": active_index, "commands": info["commands"],
            "marker": info["marker"], "complete": info["complete"], "skipped": dict(budget.skipped),
            "unknown_ids": sorted(budget.unknown_ids)}


# --- Tabs_: recently closed ------------------------------------------------------------------------------------

def read_closed(data: bytes) -> dict:
    """The reading of a `Tabs_` file: the recently closed tabs, windows, groups and splits, newest first."""
    return _read_closed(data, _Budget())


def _read_closed(data: bytes, budget: _Budget) -> dict:
    """The replay of CreateEntriesFromCommands. The browser drops the whole list at the first command it cannot
    use; here such a command is skipped (it changes nothing) and the rest is read."""
    info: dict = {}
    entries: list[dict] = []
    state = {"tab": None, "window": None, "group": None, "split": None}   # an open entry and its tabs to come

    def new_tab() -> dict:
        return {"kind": "tab", "original_id": -1, "current": 0, "pinned": False, "group": None, "navs": []}

    def remove(original_id: int) -> None:
        if original_id == -1:
            return
        for i, entry in enumerate(entries):
            budget.spend(1)
            if entry["original_id"] == original_id:
                del entries[i]
                return

    def reset() -> None:
        state.update(tab=None, window=None, group=None, split=None)

    for index, (cid, payload) in enumerate(_commands(data, info)):
        budget.index = index
        budget.spend(1)
        if cid == T_RESTORED:
            fields = _unpack("<i", payload)
            if fields is None or state["window"] or state["group"]:
                budget.skip("malformed")
                continue
            reset()
            remove(_session_id(fields[0]))
        elif cid in (T_WINDOW, T_WINDOW_OLD, T_CREATE_GROUP, T_CREATE_SPLIT):
            parsed = _closed_container(cid, payload)
            if parsed is None or state["window"] or state["group"] or state["split"]:
                budget.skip("malformed")
                continue
            entry, original_id, count = parsed
            if len(entries) >= MOST_ENTRIES:
                budget.skip("over_limit")
                reset()
                continue
            remove(original_id)
            entry["original_id"] = original_id
            entries.append(entry)
            key = {"window": "window", "group": "group", "split": "split"}[entry["kind"]]
            state[key] = [entry, count]
        elif cid == T_SELECTED_NAVIGATION:
            fields = _unpack("<iiq", payload) or _unpack("<ii", payload)
            if fields is None:
                budget.skip("malformed")
                continue
            if budget.tabs >= MOST_TABS:
                budget.skip("over_limit")
                state["tab"] = None
                continue
            budget.tabs += 1
            t = new_tab()
            holder = state["window"] or state["group"] or state["split"]
            if holder is not None:
                holder[0]["tabs"].append(t)
                holder[1] -= 1
                if holder[1] <= 0:
                    state.update(window=None, group=None, split=None)
                budget.spend(1)
            else:
                if len(entries) >= MOST_ENTRIES:
                    budget.skip("over_limit")
                    state["tab"] = None
                    continue
                remove(_session_id(fields[0]))
                entries.append(t)
            t["current"] = fields[1]
            t["original_id"] = _session_id(fields[0])
            state["tab"] = t
        elif cid in (T_NAVIGATION, T_PINNED, T_GROUP_DATA, T_APP_ID, T_USER_AGENT, T_USER_AGENT2, T_TAB_EXTRA,
                     T_SPLIT_DATA):
            t = state["tab"]
            if t is None:
                budget.skip("malformed")
                continue
            if not _closed_tab_command(cid, payload, t, budget):
                budget.skip("malformed")
        elif cid in (T_WINDOW_APP_NAME, T_WINDOW_TITLE):
            p = _Pickle(payload)
            owner, text = p.int(), p.string()
            if state["window"] is None or owner is None or text is None:
                budget.skip("malformed")
                continue
            state["window"][0]["app_name" if cid == T_WINDOW_APP_NAME else "user_title"] = text
        else:
            budget.skip("unknown", cid)
    valid = [e for e in reversed(entries) if _closed_valid(e)]
    return {"entries": [_closed_out(e) for e in valid], "commands": info["commands"], "marker": info["marker"],
            "complete": info["complete"], "skipped": dict(budget.skipped), "unknown_ids": sorted(budget.unknown_ids)}


def _closed_container(cid: int, payload: bytes):
    """(entry, original id, how many tabs follow) of a window, group or split command; None when unreadable."""
    if cid == T_WINDOW_OLD:
        fields = _unpack("<iii4xq", payload) or _unpack("<iii", payload)
        if fields is None or fields[2] <= 0:
            return None
        return ({"kind": "window", "type": "normal", "show_state": "default", "bounds": None,
                 "selected": fields[1], "user_title": "", "app_name": "", "tabs": []}, _session_id(fields[0]),
                fields[2])
    p = _Pickle(payload)
    if cid == T_WINDOW:
        values = [p.int(), p.int(), p.int(), p.i64(), p.int(), p.int(), p.int(), p.int(), p.int()]
        workspace = p.string()
        if None in values or workspace is None:
            return None
        window_type = p.int()
        window_type = 0 if window_type is None else window_type
        wid, selected, count, _, x, y, width, height, show = values
        if width < 0 or height < 0 or show not in CLOSED_SHOW_STATES or not 0 <= window_type < len(WINDOW_TYPES):
            return None
        if count <= 0:
            return None
        bounds = None if (x, y, width, height) == (0, 0, 0, 0) else [x, y, width, height]
        return ({"kind": "window", "type": WINDOW_TYPES[window_type], "show_state": CLOSED_SHOW_STATES[show],
                 "bounds": bounds, "selected": selected, "user_title": "", "app_name": "", "tabs": []},
                _session_id(wid), count)
    if cid == T_CREATE_GROUP:
        token = p.token()
        values = [p.int(), p.int(), p.int()] if token is not None else [None]
        title = p.string16() if None not in values else None
        colour = p.u32() if title is not None else None
        if colour is None:
            return None
        saved = p.bool()
        if saved and not p.string():
            return None
        if p.i64() is None:
            return None
        gid, count, _ = values
        if count <= 0:
            return None
        return ({"kind": "group", "title": title, "color": _colour(colour), "tabs": []}, _session_id(gid), count)
    token = p.token()                  # T_CREATE_SPLIT
    sid = p.int() if token is not None else None
    if sid is None or p.i64() is None:
        return None
    return {"kind": "split", "tabs": []}, _session_id(sid), 2


def _closed_tab_command(cid: int, payload: bytes, t: dict, budget: _Budget) -> bool:
    if cid == T_PINNED:
        t["pinned"] = True             # only written for a pinned tab; its contents do not matter
        return True
    p = _Pickle(payload)
    if cid == T_NAVIGATION:
        nav = _navigation(p) if p.int() is not None else None
        if nav is None:
            return False
        if len(t["navs"]) >= MOST_NAVIGATIONS or budget.navigations >= MOST_ALL_NAVIGATIONS:
            budget.skip("over_limit")
            return True
        nav[0] = len(t["navs"])        # the browser numbers them by their order
        t["navs"].append(nav)
        budget.navigations += 1
        budget.spend(1)
        return True
    if cid == T_GROUP_DATA:
        token = p.token()
        title = p.string16()
        colour = p.u32() if title is not None else None
        if token is None or colour is None:
            return False
        saved = p.bool()
        if saved and not p.string():
            return False
        collapsed = p.bool()
        t["group"] = {"id": token, "title": title, "color": _colour(colour), "collapsed": bool(collapsed)}
        return True
    if cid in (T_APP_ID, T_USER_AGENT):
        return p.int() is not None and p.string() is not None
    if cid == T_USER_AGENT2:
        if p.int() is None or p.string() is None:
            return False
        has_metadata = p.bool()
        return has_metadata is not None and (not has_metadata or p.string() is not None)
    if cid == T_TAB_EXTRA:
        return p.int() is not None and p.string() is not None and p.string() is not None
    return p.token() is not None       # T_SPLIT_DATA


def _closed_tab_valid(t: dict) -> bool:
    return bool(t["navs"]) and 0 <= t["current"] < len(t["navs"])


def _closed_valid(entry: dict) -> bool:
    if entry["kind"] == "tab":
        return _closed_tab_valid(entry)
    if entry["kind"] == "window" and not 0 <= entry["selected"] < len(entry["tabs"]):
        return False
    if entry["kind"] == "split" and len(entry["tabs"]) != 2:
        return False
    return all(_closed_tab_valid(t) for t in entry["tabs"])


def _closed_tab_out(t: dict) -> dict:
    group = None if t["group"] is None else {k: t["group"][k] for k in ("title", "color", "collapsed")}
    return {"pinned": t["pinned"], "group": group, "current": t["current"],
            "navigations": _navigations_out(t["navs"])}


def _closed_out(entry: dict) -> dict:
    if entry["kind"] == "tab":
        return {"kind": "tab", **_closed_tab_out(entry)}
    out = {"kind": entry["kind"]}
    if entry["kind"] == "window":
        out.update(type=entry["type"], show_state=entry["show_state"], bounds=entry["bounds"],
                   selected_tab=entry["selected"], user_title=entry["user_title"])
    elif entry["kind"] == "group":
        out.update(title=entry["title"], color=entry["color"])
    out["tabs"] = [_closed_tab_out(t) for t in entry["tabs"]]
    return out


# --- a profile's files -----------------------------------------------------------------------------------------

def session_files(sessions: Path, prefix: str) -> list[Path]:
    """The `<prefix>_<time>` files of a `Sessions` folder, newest first; links and junctions are left out."""
    found = []
    try:
        with os.scandir(sessions) as it:
            for entry in it:
                match = _FILE_NAME_RE.match(entry.name)
                if not match or match.group(1) != prefix:
                    continue
                st = entry.stat(follow_symlinks=False)
                if entry.is_symlink() or getattr(st, "st_file_attributes", 0) & _REPARSE_POINT:
                    continue
                if entry.is_file(follow_symlinks=False):
                    found.append((int(match.group(2)), Path(entry.path)))
    except OSError:
        return []
    return [path for _, path in sorted(found, reverse=True)]


def read_bytes(path: Path) -> bytes:
    """A file's bytes, refused before reading when it is larger than a session can be."""
    try:
        if path.stat().st_size > MOST_FILE_BYTES:
            raise SessionError(f"{path.name} is larger than {MOST_FILE_BYTES // (1024 * 1024)} MB")
        with open(path, "rb") as f:
            data = f.read(MOST_FILE_BYTES + 1)
    except OSError as exc:
        raise SessionError(f"{path.name} cannot be read ({exc.strerror or exc})") from exc
    if len(data) > MOST_FILE_BYTES:
        raise SessionError(f"{path.name} is larger than {MOST_FILE_BYTES // (1024 * 1024)} MB")
    return data


def newest(profile: Path, prefix: str) -> tuple[Path | None, dict | None, list[str]]:
    """The file of `prefix` the browser would open (the newest one with a complete state), its reading, and notes
    on the newer files it passed over."""
    reader = read_session if prefix == "Session" else read_closed
    notes = []
    for path in session_files(Path(profile) / "Sessions", prefix):
        try:
            reading = reader(read_bytes(path))
        except SessionError as exc:
            notes.append(f"{path.name}: {exc}")
            continue
        if not reading["marker"]:
            notes.append(f"{path.name}: no complete state in it (the browser passes over it too)")
            continue
        return path, reading, notes
    return None, None, notes


def read_profile(profile: Path) -> dict:
    """The reading of a profile folder: the session that comes back, the recently closed entries, and notes."""
    profile = Path(profile)
    session_path, session, notes = newest(profile, "Session")
    tabs_path, closed, more = newest(profile, "Tabs")
    notes += more
    if session_path is None and session_files(profile / "Sessions_Encrypted", "Session"):
        notes.append("only encrypted session files were found; this reader does not decrypt them")
    return {"format": FORMAT, "version": 1,
            "session": None if session is None else {"file": session_path.name, **session},
            "closed": None if closed is None else {"file": tabs_path.name, **closed},
            "notes": notes}


def counts(reading: dict | None) -> dict:
    """How many windows, tabs, groups and pinned tabs a session reading holds."""
    windows = (reading or {}).get("windows") or []
    return {"windows": len(windows), "tabs": sum(len(w["tabs"]) for w in windows),
            "groups": sum(len(w["groups"]) for w in windows),
            "pinned": sum(1 for w in windows for t in w["tabs"] if t["pinned"])}


# --- the import ------------------------------------------------------------------------------------------------

def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_link(path: Path) -> bool:
    try:
        st = path.stat(follow_symlinks=False)
    except OSError:
        return False
    return path.is_symlink() or bool(getattr(st, "st_file_attributes", 0) & _REPARSE_POINT)


def _running(profile: Path) -> bool:
    return (profile / "lockfile").exists() or (profile.parent / "lockfile").exists()


def import_sessions(source: Path, dest: Path, set_aside: bool = False) -> dict:
    """Copy the session the source browser would restore (its newest `Session_` file with a complete state, and
    the newest `Tabs_` one) into the Thoron profile `dest`. The source is only read and is hashed before and
    after; each copy is checked by SHA-256. Thoron's own session files, if any, are kept in a folder inside
    `Sessions/` when `set_aside` is true; otherwise their presence refuses the import."""
    source, dest = Path(source).resolve(), Path(dest).resolve()
    if not source.is_dir():
        raise ImportRefused(f"{source} is not a profile folder")
    if not (dest / "Preferences").is_file():
        raise ImportRefused(f"{dest} is not a Thoron profile that has started: start Thoron once and close it, "
                            "then import the tabs (a new profile does not restore a session)")
    if dest == source or source in dest.parents or dest in source.parents:
        raise ImportRefused("the source and destination folders overlap")
    if _running(source):
        raise ImportRefused("the source browser is running; close it completely first")
    if _running(dest):
        raise ImportRefused("Thoron is running; close it completely first")
    for folder in (source / "Sessions", dest / "Sessions"):
        if _is_link(folder):
            raise ImportRefused(f"{folder} is a link or junction; refusing to follow it")
    session_path, session, notes = newest(source, "Session")
    if session_path is None:
        raise ImportRefused("the source has no session to import" + (f" ({'; '.join(notes)})" if notes else ""))
    tabs_path, closed, more = newest(source, "Tabs")
    notes += more
    wanted = [(p, prefix) for p, prefix in ((session_path, "Session"), (tabs_path, "Tabs")) if p is not None]
    before = {p.name: _sha256(p) for p, _ in wanted}
    # what is written (prepare_copy): the source's bytes without what Thoron would stop at and without the links
    # to the source's saved groups; it must read as the source does, with nothing left that a reader skips
    planned, unlinked, left_out = {}, 0, 0
    for path, prefix in wanted:
        try:
            data = read_bytes(path)
            new, done = prepare_copy(data, prefix)
            reader = read_session if prefix == "Session" else read_closed
            source_reading, copy_reading = reader(data), reader(new)
        except SessionError as exc:
            raise ImportRefused(f"{exc}; nothing was changed") from exc
        if hashlib.sha256(data).hexdigest() != before[path.name]:
            raise VerificationFailed(f"{path.name} of the source changed while it was read; nothing was changed")
        if (essence(copy_reading) != essence(source_reading) or copy_reading["skipped"]["unknown"]
                or copy_reading["skipped"]["malformed"]):
            raise VerificationFailed(f"{path.name} would not read as the source does; nothing was changed")
        planned[path.name] = new
        unlinked += done["unlinked_groups"] if prefix == "Session" else 0
        left_out += done["left_out"]
    target = dest / "Sessions"
    own = session_files(target, "Session") + session_files(target, "Tabs")
    aside = None
    if own and not set_aside:
        raise ImportRefused(f"the Thoron profile has a session of its own ({len(own)} file(s)) that the import would "
                            "replace; nothing was changed (--set-aside keeps it in a folder inside Sessions)")
    copied = []
    try:
        target.mkdir(parents=True, exist_ok=True)
        if own:
            aside = target / f"Thoron before import {time.strftime('%Y%m%d-%H%M%S', time.gmtime())}"
            aside.mkdir()
            for path in own:
                os.replace(path, aside / path.name)
        for name, new in planned.items():
            with open(target / name, "xb") as f:      # never over a file that is there
                copied.append(target / name)
                f.write(new)
                f.flush()
                os.fsync(f.fileno())
    except FileExistsError as exc:
        raise ImportRefused(f"{exc.filename} already exists in the Thoron profile; nothing more was written") from exc
    except OSError as exc:
        raise ImportRefused(f"writing the session failed ({exc}); the source is unchanged") from exc
    bad = [p.name for p in copied if _sha256(p) != hashlib.sha256(planned[p.name]).hexdigest()]
    if bad:
        for p in copied:
            p.unlink(missing_ok=True)
        raise VerificationFailed(f"{bad} differ after writing and were removed; the source is unchanged")
    changed = [p.name for p, _ in wanted if not p.is_file() or _sha256(p) != before[p.name]]
    if changed:
        raise VerificationFailed(f"{changed} of the source changed during the import; something else wrote to it")
    if _running(source) or _running(dest):
        raise ImportRefused("a browser was started during the import; close both and import again")
    return {"files": [p.name for p, _ in wanted], "verified": True, "source_unchanged": True,
            "set_aside": None if aside is None else aside.name, "unlinked_groups": unlinked, "left_out": left_out,
            **counts(session),
            "closed": len((closed or {}).get("entries") or []), "notes": notes}


def restore_on_next_start(user_data: Path) -> None:
    """Make the next start of the browser restore its last session once, as after an update (`was.restarted`
    in `Local State`, which the browser clears when it reads it). The file is replaced in one step."""
    state_file = Path(user_data) / "Local State"
    try:
        if state_file.stat().st_size > MOST_LOCAL_STATE_BYTES:
            raise ImportRefused("Local State is larger than it can be; it was not changed")
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ImportRefused(f"Local State cannot be read ({exc}); it was not changed") from exc
    if not isinstance(state, dict):
        raise ImportRefused("Local State is not what a browser writes; it was not changed")
    if not isinstance(state.get("was"), dict):
        state["was"] = {}
    state["was"]["restarted"] = True
    text = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
    tmp = state_file.with_name("Local State.thoron-import")
    try:
        tmp.write_text(text, encoding="utf-8")
        if json.loads(tmp.read_text(encoding="utf-8")) != state:
            raise ImportRefused("Local State did not read back as written; it was not changed")
        os.replace(tmp, state_file)
    except OSError as exc:
        raise ImportRefused(f"Local State could not be written ({exc}); it was not changed") from exc
    finally:
        tmp.unlink(missing_ok=True)


# --- writing (for tests, the fuzzer and golden files) ----------------------------------------------------------

class PickleWriter:
    """Writes base::Pickle contents the way the browser does (each field padded to 4 bytes)."""

    def __init__(self):
        self.parts: list[bytes] = []

    def _add(self, raw: bytes) -> "PickleWriter":
        self.parts.append(raw + b"\0" * (-len(raw) % 4))
        return self

    def int(self, v: int) -> "PickleWriter":
        return self._add(struct.pack("<i", v))

    def u32(self, v: int) -> "PickleWriter":
        return self._add(struct.pack("<I", v))

    def i64(self, v: int) -> "PickleWriter":
        return self._add(struct.pack("<q", v))

    def u64(self, v: int) -> "PickleWriter":
        return self._add(struct.pack("<Q", v))

    def double(self, v: float) -> "PickleWriter":
        return self._add(struct.pack("<d", v))

    def bool(self, v: bool) -> "PickleWriter":
        return self.int(1 if v else 0)          # Pickle::WriteBool writes an int

    def bytes(self, v: bytes) -> "PickleWriter":
        return self._add(struct.pack("<i", len(v)) + v)

    def string(self, v: str) -> "PickleWriter":
        return self.bytes(v.encode("utf-8"))

    def string16(self, v: str) -> "PickleWriter":
        return self.string16_raw(v.encode("utf-16-le"))

    def string16_raw(self, raw: bytes) -> "PickleWriter":
        return self._add(struct.pack("<i", len(raw) // 2) + raw)

    def raw(self, v: bytes) -> "PickleWriter":
        """Bytes as they are (the rest of a pickle that was read, already padded)."""
        self.parts.append(v)
        return self

    def token(self, v: str) -> "PickleWriter":
        return self.u64(int(v[:16], 16)).u64(int(v[16:], 16))

    def done(self) -> bytes:
        body = b"".join(self.parts)
        return struct.pack("<I", len(body)) + body


def navigation_pickle(tab_id: int, index: int, url: str, title: str, timestamp: int = 0) -> bytes:
    """The contents of an UpdateTabNavigation command, every field as SerializedNavigationEntry writes it."""
    w = PickleWriter().int(tab_id).int(index).string(url).string16(title).string("").int(0).int(0).string("")
    w.int(0).string("").bool(False).i64(timestamp).string16("").int(200).int(0).int(0).i64(-1).i64(-1).i64(-1)
    return w.int(0).done()


def command(cid: int, contents: bytes) -> bytes:
    if len(contents) > 0xFFFE:
        raise ValueError("a command holds at most 65534 bytes")
    return struct.pack("<HB", len(contents) + 1, cid) + contents


def snss(commands: list[bytes], marker: bool = True, version: int = VERSION) -> bytes:
    """An SNSS file of the given commands (each already made by `command`), with the marker after them."""
    return SIGNATURE + struct.pack("<i", version) + b"".join(commands) + (command(MARKER, b"") if marker else b"")


# --- changing a file command by command ------------------------------------------------------------------------

def raw_commands(data: bytes) -> tuple[list[tuple[int, bytes]], bytes]:
    """Every command of a file, the marker included, in its place; and the bytes after the last whole one."""
    _check_header(data)
    out, pos = [], 8
    while len(data) - pos >= 2:
        size = data[pos] | (data[pos + 1] << 8)
        if size < 1 or size > len(data) - pos - 2:
            break
        if len(out) > MOST_COMMANDS:
            raise SessionError(f"more than {MOST_COMMANDS} commands; not a session this reader accepts")
        out.append((data[pos + 2], bytes(data[pos + 3:pos + 2 + size])))
        pos += 2 + size
    return out, bytes(data[pos:])


def rewrite(data: bytes, change) -> bytes:
    """The file with each command's contents replaced by `change(id, contents)`; every other byte as it was."""
    commands, tail = raw_commands(data)
    return bytes(data[:8]) + b"".join(command(cid, change(cid, payload)) for cid, payload in commands) + tail


def _token_of(p: _Pickle) -> tuple[int, int] | None:
    high, low = p.u64(), p.u64()
    return None if high is None or low is None else (high, low)


def _unsaved_metadata(payload: bytes):
    """S_GROUP_METADATA2 without its saved-group link: (contents, token), or None when it has no link."""
    p = _Pickle(payload)
    token = _token_of(p)
    title = p.string16_raw() if token else None
    colour = p.u32() if title is not None else None
    collapsed = p.bool() if colour is not None else None
    if collapsed is None or not p.bool() or p.string() is None:
        return None
    w = PickleWriter().u64(token[0]).u64(token[1]).string16_raw(title).u32(colour).bool(collapsed).bool(False)
    return w.raw(p.rest()).done(), token


def _unsaved_closed_group_data(payload: bytes):
    """T_GROUP_DATA (a closed tab's group) without its saved-group link."""
    p = _Pickle(payload)
    token = _token_of(p)
    title = p.string16_raw() if token else None
    colour = p.u32() if title is not None else None
    if colour is None or not p.bool() or not p.string():
        return None
    collapsed = p.bool()
    w = PickleWriter().u64(token[0]).u64(token[1]).string16_raw(title).u32(colour).bool(False)
    if collapsed is not None:
        w.bool(collapsed)
    return w.raw(p.rest()).done(), token


def _unsaved_closed_group(payload: bytes):
    """T_CREATE_GROUP (a closed group) without its saved-group link."""
    p = _Pickle(payload)
    token = _token_of(p)
    ids = [p.int(), p.int(), p.int()] if token else [None]
    title = p.string16_raw() if None not in ids else None
    colour = p.u32() if title is not None else None
    if colour is None or not p.bool() or not p.string():
        return None
    timestamp = p.i64()
    if timestamp is None:
        return None
    w = PickleWriter().u64(token[0]).u64(token[1]).int(ids[0]).int(ids[1]).int(ids[2]).string16_raw(title)
    return w.u32(colour).bool(False).i64(timestamp).raw(p.rest()).done(), token


def unlink_saved_groups(data: bytes, prefix: str) -> tuple[bytes, int]:
    """The file with every tab group's link to the source profile's saved groups taken out, and how many groups
    had one. Thoron, finding a restored group linked to a saved group its own profile does not know, takes it for
    a group deleted elsewhere and closes it with its tabs (TabGroupSyncService::ConnectLocalTabGroup); an
    unlinked group is restored and saved as Thoron's own. Nothing else changes."""
    change_of = ({S_GROUP_METADATA2: _unsaved_metadata} if prefix == "Session" else
                 {T_GROUP_DATA: _unsaved_closed_group_data, T_CREATE_GROUP: _unsaved_closed_group})
    tokens = set()

    def change(cid: int, payload: bytes) -> bytes:
        fn = change_of.get(cid)
        changed = fn(payload) if fn else None
        if changed is None:
            return payload
        tokens.add(changed[1])
        return changed[0]

    return rewrite(data, change), len(tokens)


def essence(reading: dict) -> dict:
    """A reading without the counts of how it was read: what a copy must keep."""
    return {k: v for k, v in reading.items() if k not in ("commands", "skipped", "unknown_ids")}


def prepare_copy(data: bytes, prefix: str) -> tuple[bytes, dict]:
    """What the import writes for a session file (`prefix` "Session" or "Tabs"): its bytes without the commands
    this reader skips as unknown or malformed, and with the groups' saved-group links taken out
    (`unlink_saved_groups`). Thoron's own replay stops at the first command it cannot use and loses everything
    after it, so another vendor's commands or a damaged one must not reach it. Every other command stays byte for
    byte and in order; the copy reads as the source does."""
    budget = _Budget()
    (_read_session if prefix == "Session" else _read_closed)(data, budget)
    left_out = set(budget.dropped)
    commands, tail = raw_commands(data)
    kept, index = [], 0
    for cid, payload in commands:
        if cid != MARKER:
            index += 1
            if index - 1 in left_out:
                continue
        kept.append(command(cid, payload))
    cleaned, groups = unlink_saved_groups(bytes(data[:8]) + b"".join(kept) + tail, prefix)
    return cleaned, {"unlinked_groups": groups, "left_out": len(left_out)}


# --- command line ----------------------------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    read = sub.add_parser("read", help="print what a profile's session files hold, as JSON")
    where = read.add_mutually_exclusive_group(required=True)
    where.add_argument("--profile", type=Path, help="a profile folder, such as <User Data>\\Default")
    where.add_argument("--file", type=Path, help="one Session_ or Tabs_ file")
    imp = sub.add_parser("import", help="copy a profile's session into a Thoron profile")
    imp.add_argument("--from", dest="source", type=Path, required=True, help="the source profile folder")
    imp.add_argument("--to", dest="dest", type=Path, required=True, help="the Thoron profile folder")
    imp.add_argument("--set-aside", action="store_true", help="keep Thoron's own session in a folder inside Sessions")
    imp.add_argument("--restore-on-next-start", action="store_true",
                     help="the next start of Thoron opens the imported windows once")
    a = parser.parse_args(argv)
    if a.command == "read":
        try:
            if a.profile:
                reading = read_profile(a.profile)
            else:
                data = read_bytes(a.file)
                reading = (read_closed if a.file.name.startswith("Tabs") else read_session)(data)
        except SessionError as exc:
            print(f"sessions: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(reading, indent=2, ensure_ascii=False))
        return 0
    try:
        done = import_sessions(a.source, a.dest, set_aside=a.set_aside)
        if a.restore_on_next_start:
            restore_on_next_start(a.dest.resolve().parent)
    except (ImportRefused, VerificationFailed) as exc:
        print(f"sessions: {exc}")
        return 1
    print(f"tabs: copied {' and '.join(done['files'])}, every file verified; {done['windows']} window(s), "
          f"{done['tabs']} tab(s), {done['groups']} group(s), {done['pinned']} pinned, {done['closed']} recently "
          f"closed")
    if done["unlinked_groups"]:
        print(f"  {done['unlinked_groups']} group(s) come over as Thoron's own: their link to the other browser's "
              "saved groups is left out, or Thoron would close them")
    if done["left_out"]:
        print(f"  {done['left_out']} command(s) Thoron cannot use (another browser's own, or damaged) are left out, "
              "or Thoron would stop reading the session there")
    if done["set_aside"]:
        print(f"  Thoron's own session is kept in Sessions\\{done['set_aside']}")
    for note in done["notes"]:
        print(f"  passed over: {note}")
    if a.restore_on_next_start:
        print("  the next start of Thoron opens them")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main(sys.argv[1:]))
