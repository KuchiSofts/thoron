#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Import a Thorium profile into Thoron by copying it (design §7.7, ROADMAP P3 import, P3.16; Windows and Linux).

The whole `User Data` folder is copied, never moved, and every file is verified by SHA-256. The
source is only read: Thorium keeps working exactly as before and stays a natural backup. Saved
passwords and cookies keep working: on Windows the DPAPI-wrapped key travels inside the copied
`Local State` (same Windows user); on Linux both browsers keep it in the desktop's keyring under the
same name, `Chromium Safe Storage` (same Linux user). On Linux the browser's own process-singleton
links at the top of the folder (`SingletonLock`, `SingletonCookie`, `SingletonSocket`) are left out.

Refused, with nothing changed, when: the source is not a `User Data` folder; either browser is
running (`lockfile` on Windows, `SingletonLock` on Linux); the folders overlap; or the destination
already holds a profile (a fresh install's empty `Crashpad` folder is fine).

After the copy it writes a report (ROADMAP P3.18) beside the destination, `Thoron import report.json`, and prints
it: for every profile how many bookmarks, history entries, saved passwords, cookies, autofill entries and
extensions came over, counted in the copy, and what was not brought over and why. It holds counts and names of
profiles and files only: never a password, a user name, an address, a cookie or any other value.
    py -3 -I tools/migrate/import_profile.py --from "%LOCALAPPDATA%\\Thorium\\User Data" --to "%LOCALAPPDATA%\\Thoron\\User Data"
"""
import argparse
import contextlib
import hashlib
import json
import os
import shutil
import socket
import sqlite3
import sys
import tempfile
import time
from pathlib import Path


class ImportRefused(RuntimeError):
    pass


class VerificationFailed(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


_REPARSE_POINT = 0x400   # FILE_ATTRIBUTE_REPARSE_POINT: junctions and symbolic links
# On Linux the browser marks a running profile folder with three links of its own (its process singleton): they
# name the computer and the process, hold no profile data, and are left out of the copy.
SINGLETONS = ("SingletonLock", "SingletonCookie", "SingletonSocket")


def _running(user_data: Path) -> bool:
    """Whether a browser has `user_data` open: on Windows its `lockfile`; on Linux its `SingletonLock` link, read
    the way Chromium reads it ("<host name>-<process id>", a live process of this computer)."""
    if (user_data / "lockfile").exists():
        return True
    lock = user_data / "SingletonLock"
    if not lock.is_symlink():
        return False
    host, _, pid = os.readlink(lock).rpartition("-")
    if host != socket.gethostname() or not pid.isdigit():
        return True                     # another computer's lock, or one Thoron cannot read: assume it is in use
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False                    # the browser ended without removing it
    except OSError:
        return True
    return True


def _walk_entries(root: Path):
    """Yield (path, is_dir) for everything under root. Any error stops the walk (never a silent skip);
    junctions and links are refused, so nothing outside the profile can be pulled in (the browser's own
    process-singleton links at the top are no profile data and are left out)."""
    stack = [root]
    while stack:
        folder = stack.pop()
        with os.scandir(folder) as it:
            for entry in it:
                if folder == root and entry.name in SINGLETONS and entry.is_symlink():
                    continue
                st = entry.stat(follow_symlinks=False)
                if entry.is_symlink() or getattr(st, "st_file_attributes", 0) & _REPARSE_POINT:
                    raise ImportRefused(f"{Path(entry.path)} is a link or junction; refusing to follow it")
                if entry.is_dir(follow_symlinks=False):
                    stack.append(Path(entry.path))
                    yield Path(entry.path), True
                else:
                    yield Path(entry.path), False


def _list(root: Path) -> tuple[list[Path], list[Path]]:
    try:
        entries = list(_walk_entries(root))
    except ImportRefused:
        raise
    except OSError as exc:
        raise ImportRefused(f"cannot read part of {root} ({exc}); nothing was imported") from exc
    return [p for p, d in entries if not d], [p for p, d in entries if d]


# THREAT_MODEL I2, as tools/qa/profile_rehearsal.py does: a profile written less than this ago may belong to a
# browser that is still closing, and a drive's clock may run a little ahead of this one.
QUIET_SECONDS = 15
CLOCK_SLACK = 5


def recently_written(files: list[Path], now: float | None = None) -> str | None:
    """The name of one of `files` written less than QUIET_SECONDS ago, or None. A date a little ahead of this
    clock counts as now; one further ahead is a wrong clock, not a write, and is passed over."""
    now = time.time() if now is None else now
    for path in files:
        try:
            written = path.stat().st_mtime
        except OSError:
            continue                    # the copy says which file cannot be read
        if written <= now + CLOCK_SLACK and now - min(written, now) < QUIET_SECONDS:
            return path.name
    return None


# THREAT_MODEL I6: Chrome locks its saved passwords and cookies to itself (app-bound encryption, a key in
# `Local State` that only Chrome's own service can unlock). Their copies are of no use to Thoron, which never
# tries to get around that; the report says so instead of counting them as brought over. Thorium and Thoron
# keep their key with Windows' DPAPI only, which the copy can use.
LOCKED = ("saved passwords", "cookies")
LOCKED_NOTE = ("saved passwords and cookies: the browser they come from locks them to itself (Chrome's app-bound "
               "encryption), so Thoron cannot read the copies. Bring the passwords over with Chrome's own export "
               "(docs/user/IMPORT.md, section 4) and sign in to your sites again")
MOST_LOCAL_STATE_BYTES = 16 * 1024 * 1024


def locked_to_its_browser(user_data: Path) -> bool:
    """Whether the browser of `user_data` locks its passwords and cookies to itself (`os_crypt` in its `Local
    State` names an app-bound key). A file that cannot be read says no."""
    path = user_data / "Local State"
    try:
        if path.stat().st_size > MOST_LOCAL_STATE_BYTES:
            return False
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return False
    crypt = state.get("os_crypt") if isinstance(state, dict) else None
    return isinstance(crypt, dict) and bool(crypt.get("app_bound_encrypted_key"))


def _is_fresh(dest: Path) -> bool:
    """No profile yet: absent, or only what an installer creates (an empty Crashpad folder)."""
    if not dest.exists():
        return True
    return not any(p.is_file() and p.relative_to(dest).parts[0] != "Crashpad" for p in dest.rglob("*"))


def import_profile(source: Path, dest: Path) -> dict:
    source, dest = Path(source).resolve(), Path(dest).resolve()
    if not (source / "Local State").is_file():
        raise ImportRefused(f"{source} is not a browser 'User Data' folder (no 'Local State')")
    if _running(source):
        raise ImportRefused("the source browser is running; close it completely first")
    if _running(dest):
        raise ImportRefused("the destination browser is running; close it completely first")
    if dest == source or source in dest.parents or dest in source.parents:
        raise ImportRefused("the source and destination folders overlap")
    if not _is_fresh(dest):
        raise ImportRefused(f"{dest} already holds a profile; nothing was changed")
    files, dirs = _list(source)
    fresh = recently_written(files)
    if fresh:
        raise ImportRefused(f"the source was written a moment ago ({fresh}), so its browser may still be closing; "
                            "wait half a minute and import again")
    # the source as it was: it must be the same after the import (ROADMAP P3.14)
    before = {p.relative_to(source).as_posix(): _sha256(p) for p in files}
    total = 0
    try:
        for d in [source] + dirs:
            (dest / d.relative_to(source)).mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ImportRefused(f"cannot create folders in {dest} ({exc}); the source is unchanged") from exc
    for p in files:
        try:
            shutil.copy2(p, dest / p.relative_to(source))
        except OSError as exc:
            raise ImportRefused(f"copying {p.relative_to(source)} failed ({exc}); the source is unchanged, and the "
                                f"partial copy in {dest} is only a copy and can be deleted before trying again") from exc
        total += p.stat().st_size
    mismatched = [p.relative_to(source).as_posix() for p in files
                  if before[p.relative_to(source).as_posix()] != _sha256(dest / p.relative_to(source))]
    if mismatched:
        raise VerificationFailed(f"{len(mismatched)} file(s) differ after copying (for example {mismatched[:3]}); "
                                 f"the source is unchanged and the copy is left in {dest} for inspection")
    src_set = {p.relative_to(source).as_posix() for p in files}
    dst_set = {p.relative_to(dest).as_posix() for p in _list(dest)[0]}
    if src_set - dst_set:
        raise VerificationFailed(f"{len(src_set - dst_set)} file(s) missing in the copy; the source is unchanged")
    if _running(source) or _running(dest):
        raise ImportRefused("a browser was started during the import, so the copy may be inconsistent; "
                            "the source is unchanged, close both browsers and import again into a fresh folder")
    changed = [rel for rel, digest in before.items()
               if not (source / rel).is_file() or _sha256(source / rel) != digest]
    if changed:
        raise VerificationFailed(f"{len(changed)} file(s) of the source changed during the import (for example "
                                 f"{changed[:3]}); something else wrote to it")
    locked = locked_to_its_browser(source)
    return {"files": len(files), "bytes": total, "verified": True, "source_unchanged": True, "locked": locked,
            "not_brought_over": [LOCKED_NOTE] if locked else []}


# --- the report (ROADMAP P3.18) ---------------------------------------------------------------------------

REPORT_NAME = "Thoron import report.json"
# (what, the database or file in a profile, the table, how it is counted)
COUNTED = (("history entries", "History", "urls"), ("saved passwords", "Login Data", "logins"),
           ("cookies", "Network/Cookies", "cookies"), ("autofill entries", "Web Data", "autofill"))


# THREAT_MODEL I8: the copies the report reads hold what the databases hold (passwords, cookies), so they are
# made inside the destination it reports on, never in the system's temporary folder, and go when it is done.
SCRATCH_NAME = ".thoron-report-scratch"


@contextlib.contextmanager
def _scratch(near: Path):
    """A folder for the report's copies beside the profile `near` is in; what a run that was stopped left there
    goes first, and the folder goes when the report is done, also when it fails."""
    folder = near / SCRATCH_NAME
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir()
    try:
        yield folder
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _count_rows(database: Path, table: str, scratch: Path) -> int | None:
    """How many rows `table` of the SQLite database at `database` holds; None when it cannot be read. A copy of
    the copy is opened, read only, so neither the profile nor its journal is touched."""
    if not database.is_file():
        return None
    with tempfile.TemporaryDirectory(dir=scratch) as tmp:
        copy = Path(tmp) / "db"
        shutil.copy2(database, copy)
        try:
            con = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
            try:
                return con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            finally:
                con.close()
        except sqlite3.Error:
            return None


DATABASES = ("History", "Login Data", "Login Data For Account", "Web Data", "Network/Cookies", "Favicons",
             "Shortcuts", "Top Sites")


def _database_check(database: Path, scratch: Path) -> str:
    """SQLite's own check of a copy of the database at `database`: "ok", or what is wrong (never its content)."""
    with tempfile.TemporaryDirectory(dir=scratch) as tmp:
        copy = Path(tmp) / "db"
        shutil.copy2(database, copy)
        journal = Path(str(database) + "-journal")
        if journal.is_file():
            shutil.copy2(journal, Path(str(copy) + "-journal"))
        try:
            con = sqlite3.connect(copy)
            try:
                result = con.execute("PRAGMA integrity_check").fetchone()[0]
            finally:
                con.close()
        except sqlite3.Error as exc:
            return f"cannot be opened ({type(exc).__name__})"
    return "ok" if result == "ok" else "damaged"


MOST_BOOKMARKS_BYTES = 64 * 1024 * 1024   # a heavy real Bookmarks file is a few MB


def _count_bookmarks(path: Path) -> int | None:
    """How many bookmarks the Bookmarks file at `path` holds; None when it cannot be read or is not what a browser
    writes. The file comes from another browser's profile, so its size is capped and its tree is walked without
    recursion: a crafted file gives None, never an error."""
    try:
        if path.stat().st_size > MOST_BOOKMARKS_BYTES:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return None
    roots = (data.get("roots") or {}) if isinstance(data, dict) else None
    if not isinstance(roots, dict):
        return None
    count, stack = 0, list(roots.values())
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        count += 1 if node.get("type") == "url" else 0
        if isinstance(node.get("children"), list):
            stack.extend(node["children"])
    return count


def _count_extensions(profile: Path) -> int | None:
    folder = profile / "Extensions"
    if not folder.is_dir():
        return 0
    return sum(1 for entry in folder.iterdir() if entry.is_dir() and entry.name != "Temp")


def profile_report(profile: Path) -> dict:
    """Counts for one copied profile, and what could not be counted."""
    with _scratch(profile.parent) as scratch:
        return _profile_report(profile, scratch)


def _profile_report(profile: Path, scratch: Path) -> dict:
    counts, not_counted = {}, []
    bookmarks = _count_bookmarks(profile / "Bookmarks")
    if bookmarks is None and (profile / "Bookmarks").exists():
        not_counted.append("bookmarks: the file could not be read")
    counts["bookmarks"] = bookmarks or 0
    for what, name, table in COUNTED:
        found = _count_rows(profile / name, table, scratch)
        if found is None and (profile / name).exists():
            not_counted.append(f"{what}: the database could not be read")
        counts[what] = found or 0
    counts["extensions"] = _count_extensions(profile) or 0
    damaged = [f"{name}: {found}" for name in DATABASES
               if (profile / name).is_file() and (found := _database_check(profile / name, scratch)) != "ok"]
    return {"counts": counts, "not_counted": not_counted, "databases": damaged or ["all ok"]}


def import_report(dest: Path, copied: dict) -> dict:
    """The report of an import into `dest`: counts and names only."""
    profiles = {}
    for folder in sorted(p for p in dest.iterdir() if p.is_dir() and (p / "Preferences").is_file()):
        profiles[folder.name] = profile_report(folder)
        if copied.get("locked"):
            profiles[folder.name]["locked"] = [what for what in LOCKED if profiles[folder.name]["counts"].get(what)]
    return {
        "format": "thoron-import-report", "version": 1,
        "files": copied["files"], "bytes": copied["bytes"], "verified": copied["verified"],
        "source_unchanged": copied.get("source_unchanged", False),
        "profiles": profiles,
        # the import copies the whole folder, so nothing is left out; a profile the browser keeps elsewhere,
        # or data a browser locks to itself, is named here when it is found
        "not_brought_over": copied.get("not_brought_over", []),
    }


def report_text(report: dict) -> str:
    lines = [f"import: copied {report['files']} files ({report['bytes'] / 1024 ** 3:.2f} GB), every file verified"]
    for name, found in report["profiles"].items():
        counts = ", ".join(f"{n} {what}" for what, n in found["counts"].items())
        lines.append(f"  {name}: {counts}")
        lines += [f"    not counted: {why}" for why in found["not_counted"]]
        lines += [f"    database: {d}" for d in found.get("databases", []) if d != "all ok"]
        lines += [f"    {what}: copied, but locked to the browser they come from (see below)"
                  for what in found.get("locked", [])]
    for item in report["not_brought_over"]:
        lines.append(f"  not brought over: {item}")
    if not report["not_brought_over"]:
        lines.append("  not brought over: nothing")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from", dest="source", required=True, type=Path, help="Thorium 'User Data' folder")
    parser.add_argument("--to", dest="dest", required=True, type=Path, help="Thoron 'User Data' folder")
    a = parser.parse_args(argv)
    try:
        copied = import_profile(a.source, a.dest)
    except (ImportRefused, VerificationFailed) as exc:
        print(f"import: {exc}")
        return 1
    report = import_report(a.dest.resolve(), copied)
    where = a.dest.resolve().parent / REPORT_NAME
    try:
        where.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"import: the report could not be written beside the destination ({exc})")
    print(report_text(report))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main(sys.argv[1:]))
