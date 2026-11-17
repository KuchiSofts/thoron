#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Guided import of Chrome's saved passwords into Thoron (ROADMAP P3.17).

Chrome locks its saved passwords to itself (app-bound encryption): another program cannot read them, and Thoron
does not try. Chrome itself can write them to a CSV file, and Thoron's password manager can read such a file. This
tool guides those two steps and makes sure the file, which holds every password in plain text, does not stay:

    1. it opens Chrome's password settings, where "Export passwords" writes the CSV;
    2. it checks the file: Chrome's columns, at least one entry, not in a folder that a cloud service copies
       (OneDrive, Google Drive, Dropbox, iCloud, Box), and private to this Windows user's own folders;
    3. it opens Thoron's password settings, where "Import passwords" reads it;
    4. when the person says the import is done (or gives up), it overwrites the file with random bytes, flushes
       it to the disk, and deletes it; it does the same with a copy Chrome leaves beside it ("passwords (1).csv").

It reads the file's first line (the column names) and counts the lines; it never prints, logs or keeps a value.
Overwriting does not reach copies that a disk keeps by itself (flash wear levelling, a snapshot, a backup); the
guide says so, and that is why step 2 refuses a synced folder before anything is imported.

    py -3 -I tools/migrate/chrome_passwords.py --chrome <chrome.exe> --thoron <thoron.exe>
    py -3 -I tools/migrate/chrome_passwords.py --wipe <file.csv>       only step 4
"""
import argparse
import os
import secrets
import subprocess
import sys
from pathlib import Path

CHROME_COLUMNS = ("name", "url", "username", "password")
SYNCED = ("onedrive", "google drive", "googledrive", "my drive", "dropbox", "icloud", "icloud drive", "box",
          "box sync", "mega", "pcloud")
EXPORT_PAGE = "chrome://password-manager/settings"


class PasswordFileError(Exception):
    pass


def synced_folder(path: Path) -> str | None:
    """The name of the cloud service whose folder holds `path`, or None."""
    for part in path.resolve().parts[:-1]:
        name = part.casefold().strip()
        for service in SYNCED:
            if name == service or name.startswith(service + " - ") or name.startswith(service + "-"):
                return part
    return None


def own_folders() -> Path:
    """The person's own folders: the profile folder on Windows (C:\\Users\\<name>), the home folder on Linux.
    Other accounts of the PC cannot read what is inside them; a second drive's root or the Public folder they
    often can."""
    return Path.home()


def outside_own_folders(path: Path) -> bool:
    return own_folders().resolve() not in path.resolve().parents


def check_file(path: Path) -> int:
    """How many entries Chrome's CSV at `path` holds. PasswordFileError when it is not one, or is somewhere it
    should not be. Only the first line and the number of lines are read."""
    if not path.is_file():
        raise PasswordFileError("there is no such file")
    where = synced_folder(path)
    if where:
        raise PasswordFileError(f"the file is in {where}, a folder a cloud service copies: move it to a folder "
                                "of this PC that is not synced (such as Downloads) first, and delete it there")
    if outside_own_folders(path):
        raise PasswordFileError("the file is not in your own folders, so other accounts of this PC may be able to "
                                "read it: move it to your Downloads folder first, and delete it there")
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        header = f.readline().strip().lower()
        entries = sum(1 for line in f if line.strip())
    columns = tuple(c.strip() for c in header.split(","))
    if columns[:len(CHROME_COLUMNS)] != CHROME_COLUMNS:
        raise PasswordFileError("this is not Chrome's password file (its first line names other columns)")
    if entries == 0:
        raise PasswordFileError("the file holds no password")
    return entries


def wipe(path: Path, passes: int = 1) -> bool:
    """Overwrites the file at `path` with random bytes, flushes it to the disk, and deletes it. True when it is
    gone. A file that is not there is gone already."""
    if not path.exists():
        return True
    size = path.stat().st_size
    with path.open("r+b", buffering=0) as f:
        for _ in range(passes):
            f.seek(0)
            left = size
            while left > 0:
                block = secrets.token_bytes(min(left, 1 << 20))
                f.write(block)
                left -= len(block)
            f.flush()
            os.fsync(f.fileno())
        f.truncate(0)
        f.flush()
        os.fsync(f.fileno())
    path.unlink()
    return not path.exists()


def leftovers(path: Path) -> list[Path]:
    """Copies Chrome or the person may have left beside the file: "passwords (1).csv" and the like."""
    stem = path.stem.split(" (")[0]
    return sorted(p for p in path.parent.glob(f"{stem} (*).csv") if p != path)


def _open_page(program: Path, page: str) -> None:
    subprocess.Popen([str(program), page], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def guide(chrome: Path, thoron: Path, ask=input, say=print) -> int:
    say("1. Chrome opens its password settings. Choose \"Export passwords\" and save the file in Downloads.")
    _open_page(chrome, EXPORT_PAGE)
    answer = ask("   The file it saved (drag it here, or type its path; empty to stop): ").strip().strip('"')
    if not answer:
        say("Nothing was imported.")
        return 1
    path = Path(answer)
    try:
        entries = check_file(path)
    except PasswordFileError as exc:
        say(f"   {exc}.")
        return 1
    say(f"2. The file holds {entries} saved password(s).")
    say("3. Thoron opens its password settings. Choose \"Import passwords\" and pick that file.")
    _open_page(thoron, EXPORT_PAGE)
    ask("   Press Enter when Thoron has imported them (or when you want to stop): ")
    gone = [p for p in [path] + leftovers(path) if wipe(p)]
    say(f"4. The file was overwritten and deleted ({len(gone)} file(s)). A copy a backup or a synced folder made "
        "on its own is not reached by this; check those if the file was ever there.")
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--chrome", type=Path, help="Chrome's program, chrome.exe")
    p.add_argument("--thoron", type=Path, help="Thoron's program, thoron.exe")
    p.add_argument("--wipe", type=Path, help="only overwrite and delete this password file")
    a = p.parse_args(argv)
    if a.wipe:
        ok = wipe(a.wipe)
        print("the file was overwritten and deleted" if ok else "the file could not be deleted")
        return 0 if ok else 1
    if not a.chrome or not a.thoron:
        p.error("--chrome and --thoron, or --wipe")
    return guide(a.chrome, a.thoron)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
