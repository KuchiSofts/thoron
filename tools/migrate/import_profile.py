#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Import a Thorium profile into Thoron by copying it (design §7.7, ROADMAP P3 import, Windows).

The whole `User Data` folder is copied, never moved, and every file is verified by SHA-256. The
source is only read: Thorium keeps working exactly as before and stays a natural backup. Saved
passwords and cookies keep working because the DPAPI-wrapped key travels inside the copied
`Local State` (same Windows user).

Refused, with nothing changed, when: the source is not a `User Data` folder; either browser is
running (`lockfile`); the folders overlap; or the destination already holds a profile (a fresh
install's empty `Crashpad` folder is fine).

After the copy it writes a report (ROADMAP P3.18) beside the destination, `Thoron import report.json`, and prints
it: for every profile how many bookmarks, history entries, saved passwords, cookies, autofill entries and
extensions came over, counted in the copy, and what was not brought over and why. It holds counts and names of
profiles and files only: never a password, a user name, an address, a cookie or any other value.
    py -3 -I tools/migrate/import_profile.py --from "%LOCALAPPDATA%\\Thorium\\User Data" --to "%LOCALAPPDATA%\\Thoron\\User Data"
"""
import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
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


def _walk_entries(root: Path):
    """Yield (path, is_dir) for everything under root. Any error stops the walk (never a silent skip);
    junctions and links are refused, so nothing outside the profile can be pulled in."""
    stack = [root]
    while stack:
        folder = stack.pop()
        with os.scandir(folder) as it:
            for entry in it:
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


def _is_fresh(dest: Path) -> bool:
    """No profile yet: absent, or only what an installer creates (an empty Crashpad folder)."""
    if not dest.exists():
        return True
    return not any(p.is_file() and p.relative_to(dest).parts[0] != "Crashpad" for p in dest.rglob("*"))


def import_profile(source: Path, dest: Path) -> dict:
    source, dest = Path(source).resolve(), Path(dest).resolve()
    if not (source / "Local State").is_file():
        raise ImportRefused(f"{source} is not a browser 'User Data' folder (no 'Local State')")
    if (source / "lockfile").exists():
        raise ImportRefused("the source browser is running; close it completely first")
    if (dest / "lockfile").exists():
        raise ImportRefused("the destination browser is running; close it completely first")
    if dest == source or source in dest.parents or dest in source.parents:
        raise ImportRefused("the source and destination folders overlap")
    if not _is_fresh(dest):
        raise ImportRefused(f"{dest} already holds a profile; nothing was changed")
    files, dirs = _list(source)
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
    if (source / "lockfile").exists() or (dest / "lockfile").exists():
        raise ImportRefused("a browser was started during the import, so the copy may be inconsistent; "
                            "the source is unchanged, close both browsers and import again into a fresh folder")
    changed = [rel for rel, digest in before.items()
               if not (source / rel).is_file() or _sha256(source / rel) != digest]
    if changed:
        raise VerificationFailed(f"{len(changed)} file(s) of the source changed during the import (for example "
                                 f"{changed[:3]}); something else wrote to it")
    return {"files": len(files), "bytes": total, "verified": True, "source_unchanged": True}


# --- the report (ROADMAP P3.18) ---------------------------------------------------------------------------

REPORT_NAME = "Thoron import report.json"
# (what, the database or file in a profile, the table, how it is counted)
COUNTED = (("history entries", "History", "urls"), ("saved passwords", "Login Data", "logins"),
           ("cookies", "Network/Cookies", "cookies"), ("autofill entries", "Web Data", "autofill"))


def _count_rows(database: Path, table: str) -> int | None:
    """How many rows `table` of the SQLite database at `database` holds; None when it cannot be read. A copy of
    the copy is opened, read only, so neither the profile nor its journal is touched."""
    if not database.is_file():
        return None
    with tempfile.TemporaryDirectory() as tmp:
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


def _database_check(database: Path) -> str:
    """SQLite's own check of a copy of the database at `database`: "ok", or what is wrong (never its content)."""
    with tempfile.TemporaryDirectory() as tmp:
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


def _count_bookmarks(path: Path) -> int | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

    def walk(node) -> int:
        if not isinstance(node, dict):
            return 0
        own = 1 if node.get("type") == "url" else 0
        return own + sum(walk(child) for child in node.get("children", []) or [])

    return sum(walk(root) for root in (data.get("roots") or {}).values())


def _count_extensions(profile: Path) -> int | None:
    folder = profile / "Extensions"
    if not folder.is_dir():
        return 0
    return sum(1 for entry in folder.iterdir() if entry.is_dir() and entry.name != "Temp")


def profile_report(profile: Path) -> dict:
    """Counts for one copied profile, and what could not be counted."""
    counts, not_counted = {}, []
    bookmarks = _count_bookmarks(profile / "Bookmarks")
    if bookmarks is None and (profile / "Bookmarks").exists():
        not_counted.append("bookmarks: the file could not be read")
    counts["bookmarks"] = bookmarks or 0
    for what, name, table in COUNTED:
        found = _count_rows(profile / name, table)
        if found is None and (profile / name).exists():
            not_counted.append(f"{what}: the database could not be read")
        counts[what] = found or 0
    counts["extensions"] = _count_extensions(profile) or 0
    damaged = [f"{name}: {found}" for name in DATABASES
               if (profile / name).is_file() and (found := _database_check(profile / name)) != "ok"]
    return {"counts": counts, "not_counted": not_counted, "databases": damaged or ["all ok"]}


def import_report(dest: Path, copied: dict) -> dict:
    """The report of an import into `dest`: counts and names only."""
    profiles = {}
    for folder in sorted(p for p in dest.iterdir() if p.is_dir() and (p / "Preferences").is_file()):
        profiles[folder.name] = profile_report(folder)
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
