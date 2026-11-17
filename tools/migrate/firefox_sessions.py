#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Open windows, tabs and tab groups of a Firefox profile, and the same in a Thoron profile (ROADMAP P4.8).

Firefox keeps its session in `sessionstore.jsonlz4` (written when it quits) and, while it runs, in
`sessionstore-backups/recovery.jsonlz4`. Both are Mozilla's "mozLz4" file: the magic `mozLz40\\0`, the size of
the contents (32 bits) and the contents as one LZ4 block; the contents are JSON: the windows in order, each with
its tabs (each tab's pages, `entries`, and the current one, `index`, counted from 1), the chosen tab (`selected`,
from 1), the tab groups (`groups`: id, name, colour, collapsed) and the recently closed tabs (`_closedTabs`).

This module trusts no byte of it: the file size, the unpacked size, the counts and the lengths are capped, the
LZ4 block is checked as it is unpacked, every value is checked for its type, and bad input raises
`FirefoxSessionError` (a `sessions.SessionError`), never another exception or a hang. What a reading gives is the
reading of `sessions.py` (the same keys), so the rest of Thoron's import treats both browsers alike:

  - only web pages come over (http, https, ftp and file addresses); Firefox's own pages (about:, moz-extension:,
    view-source:, ...) have no meaning in Thoron and are counted in `dropped`, and a tab left with no page is
    dropped as Chromium does;
  - a group gets a stable id made from Firefox's (SHA-256), its name and its colour (Firefox's "gray" is "grey");
  - a pinned tab is never in a group, and the pinned tabs of a window come first, as Thoron needs them.

    py -3 -I tools/migrate/firefox_sessions.py read --file <profile>\\sessionstore.jsonlz4
        prints the reading as JSON (titles and addresses are the person's own: keep them on the PC)
    py -3 -I tools/migrate/firefox_sessions.py import --from <Firefox profile folder> --to "<Thoron User Data>\\Default"
        [--set-aside] [--restore-on-next-start]
        writes the session Firefox would restore as a Thoron session file (`Sessions/Session_<time>`), checked by
        reading it back; Firefox's files are only read, and hashed before and after. Refused while either browser
        runs, for a Thoron profile that has never started, and when the Thoron profile has a session of its own
        (`--set-aside` keeps that one in a folder inside `Sessions/`); `--restore-on-next-start` as in sessions.py.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys
import time
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.migrate import sessions as snss  # noqa: E402
from tools.migrate import import_profile as _profile_import  # noqa: E402
from tools.migrate.import_profile import ImportRefused, VerificationFailed  # noqa: E402


class FirefoxSessionError(snss.SessionError):
    """The input is not a Firefox session this reader accepts; the only exception bad input raises."""


MAGIC = b"mozLz40\0"
MOST_FILE_BYTES = 64 * 1024 * 1024
MOST_UNPACKED_BYTES = 256 * 1024 * 1024
MOST_WINDOWS = snss.MOST_WINDOWS
MOST_TABS = snss.MOST_TABS
MOST_NAVIGATIONS = 50                 # per tab, the newest kept around the current one (Chromium keeps 50)
MOST_URL_BYTES = 16 * 1024            # a page address longer than this does not come over
MOST_TITLE_CHARS = 1024
WEB_SCHEMES = ("http:", "https:", "ftp:", "file:")
COLOURS = {"gray": "grey", "grey": "grey", "blue": "blue", "red": "red", "yellow": "yellow", "green": "green",
           "pink": "pink", "purple": "purple", "cyan": "cyan", "orange": "orange"}
SIZE_MODES = {"normal": "normal", "maximized": "maximized", "minimized": "minimized", "fullscreen": "fullscreen"}
SESSION_FILES = ("sessionstore.jsonlz4", "sessionstore-backups/recovery.jsonlz4",
                 "sessionstore-backups/recovery.baklz4")


# --- the file: mozLz4 ------------------------------------------------------------------------------------------

def decode_mozlz4(data: bytes) -> bytes:
    """The contents of a mozLz4 file: the LZ4 block unpacked and checked against the size the header names."""
    if len(data) > MOST_FILE_BYTES:
        raise FirefoxSessionError(f"larger than {MOST_FILE_BYTES // (1024 * 1024)} MB")
    if len(data) < 12 or data[:8] != MAGIC:
        raise FirefoxSessionError("not a Firefox session file (no mozLz4 header)")
    size = struct.unpack_from("<I", data, 8)[0]
    if size > MOST_UNPACKED_BYTES:
        raise FirefoxSessionError(f"it says it unpacks to more than {MOST_UNPACKED_BYTES // (1024 * 1024)} MB")
    return lz4_block(memoryview(data)[12:], size)


def lz4_block(src, size: int) -> bytes:
    """One LZ4 block (the format of lz4's LZ4_decompress_safe), unpacked to exactly `size` bytes."""
    out = bytearray()
    i, n = 0, len(src)

    def more(count: int) -> int:
        nonlocal i
        while True:
            if i >= n:
                raise FirefoxSessionError("the packed contents end inside a length")
            b = src[i]
            i += 1
            count += b
            if b != 255:
                return count

    while True:
        if i >= n:
            raise FirefoxSessionError("the packed contents end before their last literals")
        token = src[i]
        i += 1
        literals = token >> 4
        if literals == 15:
            literals = more(literals)
        if literals > n - i or len(out) + literals > size:
            raise FirefoxSessionError("a run of literals goes past the end")
        out += src[i:i + literals]
        i += literals
        if i == n:
            break                                   # the last sequence has literals only
        if n - i < 2:
            raise FirefoxSessionError("the packed contents end inside an offset")
        offset = src[i] | (src[i + 1] << 8)
        i += 2
        if offset == 0 or offset > len(out):
            raise FirefoxSessionError("a copy reaches before the start")
        length = token & 15
        if length == 15:
            length = more(length)
        length += 4
        if len(out) + length > size:
            raise FirefoxSessionError("a copy goes past the size the file names")
        start = len(out) - offset
        if offset >= length:
            out += out[start:start + length]
        else:                                        # an overlapping copy repeats the last `offset` bytes
            pattern = bytes(out[start:])
            out += (pattern * (length // offset + 1))[:length]
    if len(out) != size:
        raise FirefoxSessionError(f"unpacks to {len(out)} bytes, not the {size} it names")
    return bytes(out)


def encode_mozlz4(contents: bytes) -> bytes:
    """A mozLz4 file of `contents`, all literals (valid LZ4; for tests, the fuzzer and made-up sessions)."""
    literals = len(contents)
    head = bytes([min(literals, 15) << 4])
    if literals >= 15:
        rest = literals - 15
        head += b"\xff" * (rest // 255) + bytes([rest % 255])
    return MAGIC + struct.pack("<I", len(contents)) + head + contents


# --- the contents ----------------------------------------------------------------------------------------------

def _clean_text(value) -> str:
    """A string as Thoron can store it: lone surrogates (which JSON allows) become U+FFFD."""
    if not isinstance(value, str):
        return ""
    return value.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "replace")


def _web_url(value) -> str | None:
    if not isinstance(value, str):
        return None
    url = _clean_text(value)
    if not url.lower().startswith(WEB_SCHEMES) or len(url.encode("utf-8")) > MOST_URL_BYTES:
        return None
    return url


def _named(names: dict, value, default: str) -> str:
    """A name Firefox writes, mapped; anything else (another type included) is the default."""
    return names.get(value, default) if isinstance(value, str) else default


def _int(value, default: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _group_id(window_index: int, firefox_id) -> str:
    """A 128-bit group id (32 hex digits) made from Firefox's own, the same each time."""
    return hashlib.sha256(f"firefox-group:{window_index}:{firefox_id}".encode("utf-8", "replace")).hexdigest()[:32]


def _tab(state, dropped: dict) -> dict | None:
    """One Firefox tab as a tab of the reading (without its id and group), or None when no page of it can come."""
    if not isinstance(state, dict):
        dropped["malformed"] += 1
        return None
    entries = state.get("entries")
    if not isinstance(entries, list):
        dropped["malformed"] += 1
        return None
    current = _int(state.get("index"), len(entries)) - 1         # Firefox counts from 1; missing means the last
    current = min(max(current, 0), max(len(entries) - 1, 0))
    # around the current page, at most MOST_NAVIGATIONS pages, newest kept as Chromium keeps them
    first = max(0, min(current - MOST_NAVIGATIONS // 2, len(entries) - MOST_NAVIGATIONS))
    navigations, new_current = [], 0
    for index in range(first, min(len(entries), first + MOST_NAVIGATIONS)):
        entry = entries[index]
        url = _web_url(entry.get("url")) if isinstance(entry, dict) else None
        if url is None:
            dropped["navigations"] += 1
            continue
        if index <= current:
            new_current = len(navigations)
        navigations.append({"index": len(navigations), "url": url,
                            "title": _clean_text(entry.get("title"))[:MOST_TITLE_CHARS]})
    dropped["navigations"] += len(entries) - min(len(entries), MOST_NAVIGATIONS)
    if not navigations:
        dropped["tabs"] += 1
        return None
    return {"pinned": state.get("pinned") is True, "current": new_current, "navigations": navigations,
            "firefox_group": state.get("groupId") if isinstance(state.get("groupId"), (str, int)) else None}


def read_firefox_session(data: bytes) -> dict:
    """The reading of a Firefox session file (mozLz4), in the terms of `sessions.read_session`."""
    try:
        text = decode_mozlz4(data).decode("utf-8")
        state = json.loads(text)
    except FirefoxSessionError:
        raise
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise FirefoxSessionError(f"the contents are not the JSON Firefox writes ({type(exc).__name__})") from exc
    return read_state(state)


def read_state(state) -> dict:
    """The reading of Firefox's session state (the JSON, already parsed)."""
    if not isinstance(state, dict) or not isinstance(state.get("windows"), list):
        raise FirefoxSessionError("not a Firefox session (no list of windows)")
    if len(state["windows"]) > MOST_WINDOWS:
        raise FirefoxSessionError(f"more than {MOST_WINDOWS} windows")
    dropped = {"windows": 0, "tabs": 0, "navigations": 0, "malformed": 0}
    out_windows, closed_tabs, next_id, all_tabs = [], [], 1, 0
    selected_window = _int(state.get("selectedWindow"), 1) - 1
    active = None
    for wi, window in enumerate(state["windows"]):
        if not isinstance(window, dict) or not isinstance(window.get("tabs"), list):
            dropped["malformed"] += 1
            continue
        if all_tabs + len(window["tabs"]) > MOST_TABS:
            raise FirefoxSessionError(f"more than {MOST_TABS} tabs")
        all_tabs += len(window["tabs"])
        groups_in = {}
        for g in window.get("groups") if isinstance(window.get("groups"), list) else []:
            if isinstance(g, dict) and isinstance(g.get("id"), (str, int)):
                groups_in[g["id"]] = g
        chosen = _int(window.get("selected"), 1) - 1
        kept, chosen_kept = [], None
        for ti, tab_state in enumerate(window["tabs"]):
            tab = _tab(tab_state, dropped)
            if tab is None:
                continue
            if ti == chosen:
                chosen_kept = len(kept)
            kept.append(tab)
        if not kept:
            dropped["windows"] += 1
            continue
        # pinned tabs first, never in a group; a group's tabs side by side (Firefox keeps them so)
        order = [t for t in kept if t["pinned"]] + [t for t in kept if not t["pinned"]]
        selected_tab = order.index(kept[chosen_kept]) if chosen_kept is not None else 0
        tabs_out, groups_out, seen = [], [], {}
        previous = None
        for t in order:
            fid = None if t["pinned"] else t["firefox_group"]
            gid = None
            if fid is not None and fid in groups_in and (fid not in seen or fid == previous):
                # a group's tabs stay side by side: a tab that comes back to a group after others is left out of it
                gid = seen.get(fid)
                if gid is None:
                    gid = seen[fid] = _group_id(wi, fid)
                    g = groups_in[fid]
                    groups_out.append({"id": gid, "title": _clean_text(g.get("name"))[:MOST_TITLE_CHARS],
                                       "color": _named(COLOURS, g.get("color"), "grey"),
                                       "collapsed": g.get("collapsed") is True})
            tabs_out.append({"id": next_id, "pinned": t["pinned"], "group": gid, "current": t["current"],
                             "navigations": t["navigations"]})
            previous = fid if gid is not None else None
            next_id += 1
        if wi == selected_window:
            active = len(out_windows)
        bounds = [max(-2 ** 31, min(2 ** 31 - 1, _int(window.get(k), 0)))
                  for k in ("screenX", "screenY", "width", "height")]
        out_windows.append({"id": next_id, "type": "normal",
                            "show_state": _named(SIZE_MODES, window.get("sizemode"), "normal"), "bounds": bounds,
                            "selected_tab": selected_tab, "user_title": "", "app_name": "", "tabs": tabs_out,
                            "groups": groups_out})
        next_id += 1
        for closed in window.get("_closedTabs") if isinstance(window.get("_closedTabs"), list) else []:
            tab = _tab(closed.get("state") if isinstance(closed, dict) else None, dropped)
            if tab is not None:
                closed_tabs.append({"pinned": False, "current": tab["current"], "navigations": tab["navigations"]})
    return {"format": snss.FORMAT, "source": "firefox", "windows": out_windows,
            "active_window": active if active is not None else (0 if out_windows else None),
            "closed_tabs": closed_tabs, "dropped": dropped}


def private_problems(contents: bytes) -> list[str]:
    """What in a session's contents names a user folder (a golden file must not)."""
    text = contents.decode("utf-8", "replace")
    found = []
    for needle in ("\\Users\\", "\\\\Users\\\\", "/Users/", "/home/", "C:\\\\Users", "AppData"):  # privacy-check: allow
        if needle in text:
            found.append(needle)
    return found


# --- a Thoron session file --------------------------------------------------------------------------------------

def to_snss(reading: dict, timestamp: int = 0) -> bytes:
    """A Thoron session file (`Session_`, SNSS) holding the reading's windows, as Chromium writes one
    (session_service_commands.cc): each window's bounds and type, each tab's window, place, pinned state, group
    and pages, the chosen page of each tab, the groups' names, colours and collapsed state, the chosen tab of each
    window and the active window."""
    commands = []
    c = snss.command
    window_id, tab_id = 1, 1000
    window_ids = []
    for w in reading["windows"]:
        window_ids.append(window_id)
        x, y, width, height = w["bounds"] if w.get("bounds") else (0, 0, 0, 0)
        show = {"normal": 1, "minimized": 2, "maximized": 3, "fullscreen": 5}.get(w["show_state"], 1)
        commands.append(c(snss.S_WINDOW_BOUNDS3, struct.pack("<iiiiii", window_id, x, y, width, height, show)))
        commands.append(c(snss.S_WINDOW_TYPE, struct.pack("<ii", window_id, 0)))
        for index, t in enumerate(w["tabs"]):
            commands.append(c(snss.S_TAB_WINDOW, struct.pack("<ii", window_id, tab_id)))
            commands.append(c(snss.S_TAB_INDEX, struct.pack("<ii", tab_id, index)))
            if t["pinned"]:
                commands.append(c(snss.S_PINNED, struct.pack("<i?3x", tab_id, True)))
            if t["group"] is not None:
                commands.append(c(snss.S_TAB_GROUP, struct.pack("<i4xQQ?7x", tab_id, int(t["group"][:16], 16),
                                                                 int(t["group"][16:], 16), True)))
            for nav in t["navigations"]:
                commands.append(c(snss.S_NAVIGATION, snss.navigation_pickle(tab_id, nav["index"], nav["url"],
                                                                            nav["title"], timestamp)))
            commands.append(c(snss.S_SELECTED_NAVIGATION, struct.pack("<ii", tab_id, t["current"])))
            tab_id += 1
        for g in w["groups"]:
            pickle = snss.PickleWriter().token(g["id"]).string16(g["title"]).u32(snss.COLOURS.index(g["color"]))
            commands.append(c(snss.S_GROUP_METADATA2, pickle.bool(g["collapsed"]).bool(False).done()))
        commands.append(c(snss.S_SELECTED_TAB, struct.pack("<ii", window_id, w["selected_tab"])))
        window_id += 1
    if reading.get("active_window") is not None and window_ids:
        commands.append(c(snss.S_ACTIVE_WINDOW, struct.pack("<i", window_ids[reading["active_window"]])))
    return snss.snss(commands)


def same_session(reading: dict, snss_reading: dict) -> list[str]:
    """Where a Thoron session file's reading differs from the Firefox reading it was made from (ids aside)."""
    def plain(windows):
        out = []
        for w in windows:
            ids = [g["id"] for g in w["groups"]]
            out.append({"show_state": w["show_state"], "selected_tab": w["selected_tab"],
                        "groups": [[g["title"], g["color"], g["collapsed"]] for g in w["groups"]],
                        "tabs": [[t["pinned"], None if t["group"] is None else ids.index(t["group"]), t["current"],
                                  [[n["url"], n["title"]] for n in t["navigations"]]] for t in w["tabs"]]})
        return out
    problems = []
    want, got = plain(reading["windows"]), plain(snss_reading["windows"])
    if len(want) != len(got):
        return [f"{len(got)} windows, not {len(want)}"]
    for i, (a, b) in enumerate(zip(want, got)):
        for key in a:
            if a[key] != b[key]:
                problems.append(f"window {i}: {key} differs")
    if reading.get("active_window") != snss_reading.get("active_window"):
        problems.append("the active window differs")
    return problems


# --- a profile ---------------------------------------------------------------------------------------------------

def firefox_running(profile: Path) -> bool:
    """Firefox holds `parent.lock` open while it runs (on Windows a file it locks; elsewhere a link)."""
    lock = profile / "parent.lock"
    if not lock.exists() and not lock.is_symlink():
        return False
    if os.name != "nt":
        return lock.is_symlink()
    try:
        with open(lock, "r+b"):
            return False
    except PermissionError:
        return True
    except OSError:
        return False


def newest_session(profile: Path) -> tuple[Path | None, dict | None, list[str]]:
    """The session file Firefox would restore (the newest one that reads), its reading and notes on the others."""
    candidates = []
    for name in SESSION_FILES:
        path = profile / name
        try:
            if path.is_file() and not path.is_symlink():
                candidates.append((path.stat().st_mtime, path))
        except OSError:
            continue
    notes = []
    for _, path in sorted(candidates, reverse=True):
        try:
            return path, read_firefox_session(snss.read_bytes(path)), notes
        except snss.SessionError as exc:
            notes.append(f"{path.name}: {exc}")
    return None, None, notes


def import_session(source: Path, dest: Path, set_aside: bool = False, now: float | None = None) -> dict:
    """Write the session Firefox would restore into the Thoron profile `dest` as a session file of its own. The
    Firefox files are only read, and hashed before and after; the file written is read back and must hold the
    same windows, tabs, pages and groups."""
    source, dest = Path(source).resolve(), Path(dest).resolve()
    if not source.is_dir():
        raise ImportRefused(f"{source} is not a Firefox profile folder")
    if not (dest / "Preferences").is_file():
        raise ImportRefused(f"{dest} is not a Thoron profile that has started: start Thoron once and close it, "
                            "then import the tabs (a new profile does not restore a session)")
    if dest == source or source in dest.parents or dest in source.parents:
        raise ImportRefused("the source and destination folders overlap")
    if firefox_running(source):
        raise ImportRefused("Firefox is running; close it completely first")
    if snss._running(dest):
        raise ImportRefused("Thoron is running; close it completely first")
    if snss._is_link(dest / "Sessions"):
        raise ImportRefused(f"{dest / 'Sessions'} is a link or junction; refusing to follow it")
    path, reading, notes = newest_session(source)
    if path is None:
        raise ImportRefused("the Firefox profile has no session to import" + (f" ({'; '.join(notes)})" if notes else ""))
    fresh = _profile_import.recently_written([path])
    if fresh:
        raise ImportRefused(f"Firefox wrote its session a moment ago ({fresh}), so it may still be closing; wait half "
                            "a minute and import again")
    before = snss._sha256(path)
    if not reading["windows"]:
        raise ImportRefused("the Firefox session has no window with a web page to import")
    # Chromium's session time: microseconds since 1601-01-01 (the file name and the pages' timestamps)
    when = int(((now if now is not None else time.time()) + 11644473600) * 1_000_000)
    data = to_snss(reading, when)
    problems = same_session(reading, snss.read_session(data))
    if problems:
        raise VerificationFailed(f"the Thoron session would not hold Firefox's ({problems[0]}); nothing was changed")
    target = dest / "Sessions"
    own = snss.session_files(target, "Session") + snss.session_files(target, "Tabs")
    if own and not set_aside:
        raise ImportRefused(f"the Thoron profile has a session of its own ({len(own)} file(s)) that the import would "
                            "replace; nothing was changed (--set-aside keeps it in a folder inside Sessions)")
    name = f"Session_{when}"
    aside = None
    try:
        target.mkdir(parents=True, exist_ok=True)
        if own:
            aside = target / f"Thoron before import {time.strftime('%Y%m%d-%H%M%S', time.gmtime())}"
            aside.mkdir()
            for p in own:
                os.replace(p, aside / p.name)
        with open(target / name, "xb") as f:      # never over a file that is there
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    except FileExistsError as exc:
        raise ImportRefused(f"{exc.filename} already exists in the Thoron profile; nothing more was written") from exc
    except OSError as exc:
        raise ImportRefused(f"writing the session failed ({exc}); Firefox's files are unchanged") from exc
    if snss._sha256(target / name) != hashlib.sha256(data).hexdigest():
        (target / name).unlink(missing_ok=True)
        raise VerificationFailed(f"{name} differs after writing and was removed; Firefox's files are unchanged")
    if not path.is_file() or snss._sha256(path) != before:
        raise VerificationFailed(f"{path.name} of Firefox changed during the import; something else wrote to it")
    if firefox_running(source) or snss._running(dest):
        raise ImportRefused("a browser was started during the import; close both and import again")
    return {"file": path.name, "written": name, "verified": True, "source_unchanged": True,
            "set_aside": None if aside is None else aside.name, **snss.counts(reading),
            "closed": len(reading["closed_tabs"]), "dropped": reading["dropped"], "notes": notes}


# --- command line ------------------------------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    read = sub.add_parser("read", help="print what a Firefox session file holds, as JSON")
    read.add_argument("--file", type=Path, required=True)
    imp = sub.add_parser("import", help="write Firefox's session into a Thoron profile")
    imp.add_argument("--from", dest="source", type=Path, required=True)
    imp.add_argument("--to", dest="dest", type=Path, required=True)
    imp.add_argument("--set-aside", action="store_true")
    imp.add_argument("--restore-on-next-start", action="store_true")
    a = parser.parse_args(argv)
    try:
        if a.command == "read":
            print(json.dumps(read_firefox_session(snss.read_bytes(a.file)), ensure_ascii=False, indent=1))
            return 0
        result = import_session(a.source, a.dest, a.set_aside)
        if a.restore_on_next_start:
            snss.restore_on_next_start(Path(a.dest).resolve().parent)
            result["restore_on_next_start"] = True
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return 0
    except snss.SessionError as exc:
        print(f"firefox session: {exc}", file=sys.stderr)
        return 1
    except (ImportRefused, VerificationFailed) as exc:
        print(f"firefox session import: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
