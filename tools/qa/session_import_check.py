#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Imported tabs and tab groups come back in Thoron as they were (ROADMAP P3.15). Windows only.

For each source (a folder of golden session files, `tools/migrate/tests/data/sessions/<browser>`; for Firefox,
its `sessionstore.jsonlz4`, ROADMAP P4.8), the check:
1. makes a Thoron profile: Thoron starts once on a throwaway profile (its window off the screen, offline:
   host-resolver rules, only 127.0.0.1 answers) and is closed the normal way;
2. imports the source's session into it with `tools/migrate/sessions.py import` (a verified copy; Thoron's own
   first session is set aside), or for Firefox `tools/migrate/firefox_sessions.py import` (a session file of
   Thoron's own, made from Firefox's), and asks for it to be restored once on the next start, as an update does;
3. starts Thoron on it with no address on the command line, so only the imported windows open (where they were
   saved: off the screen), serves their pages again from 127.0.0.1 on the source's port, waits, and closes Thoron
   the normal way so it writes its own session;
4. reads the session Thoron wrote (a new file) and compares it with the source's reading: the same windows in
   order (type, show state, chosen tab), the tabs in order, pinned tabs, the groups with title, colour and
   collapsed state, the active window, and each tab's history (the addresses in order, the current page, and the
   titles: a title the source saved must stay; an empty one, a page whose state the source browser had not synced
   yet, may become that page's own title once Thoron loads it). The recently closed list must still hold the
   source's entries, after the windows that closing Thoron adds. The source files must be unchanged.

Firefox's file puts its windows on the screen (the first one maximized); the check imports a copy with them
moved off the screen and not maximized, so no window shows, and compares with that copy's reading. Firefox's
recently closed tabs are not imported, so they are not compared.

One difference is Thoron's own and is allowed: a window the source had minimized opens as a normal window,
because Chromium on Windows reopens a minimized window that way when it restores its own session too (Thoron
does it with a session it wrote itself, without any import). The check names such windows.
    py -3 -I tools/qa/session_import_check.py --browser <out>\\thoron.exe --work <scratch dir>
        --source tools/migrate/tests/data/sessions/chrome [--source ...]
Exit status 0 when every source passes (or the check does not apply, on another system).
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.migrate import firefox_sessions  # noqa: E402
from tools.migrate import sessions  # noqa: E402
from tools.qa import session_golden as golden  # noqa: E402

RESTORE_WAIT_S = 60
SETTLE_S = 8             # restored background tabs load one after another


def _tab(t: dict, group_ids: list) -> dict:
    return {"pinned": t["pinned"], "group": None if t["group"] is None else group_ids.index(t["group"]),
            "current": t["current"], "urls": [n["url"] for n in t["navigations"]],
            "titles": [n["title"] for n in t["navigations"]]}


def plain(reading: dict) -> list[dict]:
    """The windows of a session reading without what a restore renews: ids, group ids (a group gets a new one
    when it is restored), bounds and the raw navigation indexes (a restored tab numbers its pages from 0)."""
    out = []
    for w in reading["windows"]:
        ids = [g["id"] for g in w["groups"]]
        out.append({"type": w["type"], "show_state": w["show_state"], "selected_tab": w["selected_tab"],
                    "groups": [{k: g[k] for k in ("title", "color", "collapsed")} for g in w["groups"]],
                    "tabs": [_tab(t, ids) for t in w["tabs"]]})
    return out


def _closed_key(entry: dict) -> tuple:
    tabs = entry["tabs"] if "tabs" in entry else [entry]
    return (entry["kind"], tuple((t["current"], tuple(n["url"] for n in t["navigations"])) for t in tabs))


def reopened_normal(before: str, after: str) -> bool:
    """A minimized window that opened as a normal one: Thoron's own restore does that (see the module notes).
    A minimized window that was the active one (Brave writes that) stays minimized; never shown, it has no
    place in Thoron's own file yet, which reads as "default"."""
    return before == "minimized" and after in ("normal", "default")


def compare(source: dict, result: dict, page_title=lambda url: None, source_closed: dict | None = None,
            result_closed: dict | None = None) -> list[str]:
    """Where Thoron's session `result` differs from the imported `source` (both readings of `read_session`).
    `page_title(url)` is the title the page at `url` has, for a title the source left empty."""
    problems = []
    want, got = plain(source), plain(result)
    if len(want) != len(got):
        return [f"{len(got)} window(s) came back, not {len(want)}"]
    for i, (w, g) in enumerate(zip(want, got)):
        for key in ("type", "selected_tab", "groups"):
            if w[key] != g[key]:
                problems.append(f"window {i}: {key} is {g[key]!r}, not {w[key]!r}")
        if w["show_state"] != g["show_state"] and not reopened_normal(w["show_state"], g["show_state"]):
            problems.append(f"window {i}: show_state is {g['show_state']!r}, not {w['show_state']!r}")
        if len(w["tabs"]) != len(g["tabs"]):
            problems.append(f"window {i}: {len(g['tabs'])} tab(s), not {len(w['tabs'])}")
            continue
        for j, (a, b) in enumerate(zip(w["tabs"], g["tabs"])):
            where = f"window {i} tab {j}"
            for key in ("pinned", "group", "current", "urls"):
                if a[key] != b[key]:
                    problems.append(f"{where}: {key} is {b[key]!r}, not {a[key]!r}")
            if a["urls"] != b["urls"]:
                continue
            for url, before, after in zip(a["urls"], a["titles"], b["titles"]):
                if before != after and not (before == "" and after == page_title(url)):
                    problems.append(f"{where}: the title of {url} is {after!r}, not {before!r}")
    if source["active_window"] != result["active_window"]:
        problems.append(f"the active window is {result['active_window']!r}, not {source['active_window']!r}")
    if source_closed is not None:
        before = [_closed_key(e) for e in source_closed["entries"]]
        after = [_closed_key(e) for e in (result_closed or {"entries": []})["entries"]]
        added = after[:max(0, len(after) - len(before))]
        if after[max(0, len(after) - len(before)):] != before or any(kind != "window" for kind, _ in added):
            problems.append(f"the recently closed list is {after}, not {before} after the windows closed at the exit")
    return problems


def _hashes(folder: Path) -> dict:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.iterdir()) if p.is_file()}


def port_of(reading: dict) -> int | None:
    """The port of the local test pages, when every page of the session is one of them."""
    ports = set()
    for w in reading["windows"]:
        for t in w["tabs"]:
            for n in t["navigations"]:
                u = urllib.parse.urlsplit(n["url"])
                try:
                    port = u.port
                except ValueError:
                    return None
                if u.scheme != "http" or u.hostname != "127.0.0.1" or not u.path.startswith("/p/"):
                    return None
                ports.add(port)
    return ports.pop() if len(ports) == 1 else None


def window_states(port: int) -> dict[str, str]:
    """For each page Thoron shows, the state of its window as Windows has it now (normal, minimized, ...)."""
    states = {}
    ws = golden.browser_socket(port)
    try:
        for target in golden.targets(port):
            if target.get("type") == "page":
                try:
                    found = ws.call("Browser.getWindowForTarget", targetId=target["id"])
                except RuntimeError:
                    continue
                states[target.get("url", "")] = found.get("bounds", {}).get("windowState", "")
    finally:
        ws.close()
    return states


def live_show_states(source: dict, states: dict[str, str]) -> list[str | None]:
    """The state of Thoron's window for each window of the source, found by the page of its chosen tab."""
    out = []
    for w in source["windows"]:
        tab = w["tabs"][w["selected_tab"]] if w["tabs"] else None
        url = tab["navigations"][tab["current"]]["url"] if tab and tab["navigations"] else None
        out.append(states.get(url))
    return out


def offscreen_firefox(data: bytes) -> bytes:
    """A Firefox session file with its windows moved off the screen and none maximized (so none shows)."""
    import json
    state = json.loads(firefox_sessions.decode_mozlz4(data))
    for w in state["windows"]:
        w.update(screenX=golden.BOUNDS[0], screenY=golden.BOUNDS[1], width=golden.BOUNDS[2], height=golden.BOUNDS[3])
        if w.get("sizemode") in ("maximized", "fullscreen"):
            w["sizemode"] = "normal"
    return firefox_sessions.encode_mozlz4(json.dumps(state, ensure_ascii=False).encode("utf-8"))


def check_source(browser: Path, work: Path, source: Path) -> list[str]:
    """Import one golden source into a fresh Thoron profile, restore it, and compare; the problems found."""
    firefox = (source / "sessionstore.jsonlz4").is_file()
    session_files = [] if firefox else sessions.session_files(source, "Session")
    if not firefox and not session_files:
        return [f"{source} holds no Session_ file"]
    firefox_data = offscreen_firefox(sessions.read_bytes(source / "sessionstore.jsonlz4")) if firefox else b""
    source_session = (firefox_sessions.read_firefox_session(firefox_data) if firefox
                      else sessions.read_session(sessions.read_bytes(session_files[0])))
    tabs_files = [] if firefox else sessions.session_files(source, "Tabs")
    source_closed = sessions.read_closed(sessions.read_bytes(tabs_files[0])) if tabs_files else None
    port = port_of(source_session)
    if port is None:
        return [f"{source}: the session has pages other than the local test pages, which this check serves"]
    before = _hashes(source)
    root = Path(tempfile.mkdtemp(prefix="session-import-", dir=work))
    src_profile, user_data = root / "source" / "Default", root / "thoron"
    (src_profile / "Sessions").mkdir(parents=True)
    # the copies are dated an hour back, as files of a browser closed a while ago (the import waits otherwise;
    # a fresh checkout or copy dates them now)
    an_hour_ago = time.time() - 3600
    for f in session_files[:1] + tabs_files[:1]:
        shutil.copy2(f, src_profile / "Sessions" / f.name)
        os.utime(src_profile / "Sessions" / f.name, (an_hour_ago, an_hour_ago))
    if firefox:
        written = src_profile / "sessionstore.jsonlz4"
        written.write_bytes(firefox_data)
        os.utime(written, (an_hour_ago, an_hour_ago))
    problems: list[str] = []
    # 1. a Thoron profile that has started once
    proc = golden.launch(golden.browser_args(browser, user_data, None, ["about:blank"]))
    dt_port = None
    try:
        dt_port = golden.devtools_port(user_data)
        time.sleep(3)
    except RuntimeError as e:
        problems.append(f"Thoron did not start: {e}")
    finally:
        if not golden.close_browser(dt_port, proc):
            problems.append("Thoron did not close by itself the first time")
    if problems:
        return problems
    # 2. the import, as a person would run it
    try:
        if firefox:
            done = firefox_sessions.import_session(src_profile, user_data / "Default", set_aside=True)
            done.update(files=[done["written"]], unlinked_groups=0)
        else:
            done = sessions.import_sessions(src_profile, user_data / "Default", set_aside=True)
        sessions.restore_on_next_start(user_data)
    except (sessions.ImportRefused, sessions.VerificationFailed) as e:
        return [f"the import was refused: {e}"]
    imported = set(done["files"])
    # 3. Thoron starts on it and restores the windows (the port file of the first start would mislead the wait)
    (user_data / "DevToolsActivePort").unlink(missing_ok=True)
    live: list = []
    with golden.PageServer(port):
        proc = golden.launch(golden.browser_args(browser, user_data, None, []))
        dt_port = None
        try:
            dt_port = golden.devtools_port(user_data)
            want = sum(len(w["tabs"]) for w in source_session["windows"])
            end = time.monotonic() + RESTORE_WAIT_S
            while time.monotonic() < end:
                pages = [t for t in golden.targets(dt_port) if t.get("type") == "page"
                         and t.get("url", "").startswith("http://127.0.0.1:")]
                if len(pages) >= want:
                    break
                time.sleep(0.5)
            time.sleep(SETTLE_S)
            live = live_show_states(source_session, window_states(dt_port))
            time.sleep(golden.SAVE_WAIT_S)
        except (OSError, RuntimeError, ValueError) as e:
            problems.append(f"the restored Thoron could not be watched: {e}")
        finally:
            if not golden.close_browser(dt_port, proc):
                problems.append("Thoron did not close by itself, so its session may not be saved")
    # 4. what Thoron wrote
    profile = user_data / "Default"
    path, result, notes = sessions.newest(profile, "Session")
    _, result_closed, _ = sessions.newest(profile, "Tabs")
    if path is None:
        return problems + [f"Thoron wrote no session ({notes})"]
    if path.name in imported:
        return problems + ["Thoron did not write a session of its own: the imported file is still the newest"]
    problems += compare(source_session, result, lambda url: golden.TITLE + url.rsplit("/", 1)[-1],
                        source_closed, result_closed)
    if _hashes(source) != before:
        problems.append("the source files changed")
    counts = sessions.counts(result)
    reopened = [i for i, (w, g) in enumerate(zip(source_session["windows"], result["windows"]))
                if reopened_normal(w["show_state"], g["show_state"])]
    print(f"{'PASS' if not problems else 'FAIL'}  {source.name}: {counts['windows']} windows, {counts['tabs']} tabs, "
          f"{counts['groups']} groups, {counts['pinned']} pinned, "
          f"{sum(len(t['navigations']) for w in result['windows'] for t in w['tabs'])} pages of history and "
          f"{len((result_closed or {}).get('entries', []))} recently closed in Thoron's own session after the restore"
          f"; {done['unlinked_groups']} group(s) unlinked from the source's saved groups")
    if reopened:
        print(f"      window(s) {reopened}: minimized in the source; opened as a normal window, or kept minimized "
              f"when it was the active one (Thoron's own restore does both; live states {live})")
    if not problems:
        shutil.rmtree(root, ignore_errors=True)
    return problems


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--browser", required=True, type=Path, help="thoron.exe")
    p.add_argument("--work", required=True, type=Path, help="scratch folder for the throwaway profiles")
    p.add_argument("--source", required=True, type=Path, action="append", help="a folder of golden session files")
    a = p.parse_args(argv)
    if sys.platform != "win32":
        print("SESSION IMPORT CHECK: not on Windows, nothing to check")
        return 0
    a.work.mkdir(parents=True, exist_ok=True)
    problems = []
    for source in a.source:
        found = check_source(a.browser.resolve(), a.work.resolve(), source.resolve())
        problems += [f"{source.name}: {p}" for p in found]
    for problem in problems:
        print(problem)
    print("SESSION IMPORT CHECK: PASSED" if not problems
          else f"SESSION IMPORT CHECK: FAILED ({len(problems)} problem(s))")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main(sys.argv[1:]))
