#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""The release's own updater applies the release (ROADMAP P4.6), checked with the real updater program.

In a program folder of its own (a folder per version and the file `current`, as components/thoron_update/swap.h
describes) the updater under test applies three versions:

    first     a version without an updater in it: the updater applies it itself
    hand-off  a version with its own thoron_update.exe: the apply is handed to that one (the output says so),
              which puts it in place; the copy made for the hand-off is gone afterwards
    tampered  a version whose thoron_update.exe is not the one its files name: it is never started, the apply
              ends with bad files (exit 12) and nothing is switched
    status    names the second version as current and the first as the one before it

The "versions" are small stand-in files; only the updater is real, and nothing runs but it.
    py -3 -I tools/qa/updater_handoff_check.py --updater <out>\\thoron_update.exe --work <scratch dir>
Exit status 0 only when every step passes.
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

OLDER, NEWER, THIRD = "158.0.8127.3000", "158.0.8127.3010", "158.0.8127.3020"
UPDATER = "thoron_update.exe"
HAND_OFF_COPY = "thoron_update.handoff.exe"
EXIT_BAD_FILES = 12


def listing(files: dict[str, bytes]) -> list[dict]:
    """The files of a version as --files takes them: path, size and SHA-256, sorted by path."""
    return [{"path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for name, data in sorted(files.items())]


def tampered(data: bytes) -> bytes:
    """`data` with its middle byte changed: the same length, another hash."""
    middle = len(data) // 2
    return data[:middle] + bytes([data[middle] ^ 0xFF]) + data[middle + 1:]


def stage(app: Path, work: Path, version: str, staged: dict[str, bytes], listed: dict[str, bytes]) -> list[str]:
    folder = app / f"{version}.staging"
    folder.mkdir()
    for name, data in staged.items():
        (folder / name).write_bytes(data)
    files = work / f"{version}.files.json"
    files.write_text(json.dumps(listing(listed)), encoding="utf-8")
    return [f"--root={app}", f"--apply={folder}", f"--version={version}", f"--files={files}"]


def run(updater: Path, work: Path) -> list[str]:
    if work.exists():
        shutil.rmtree(work)
    (work / "copy").mkdir(parents=True)
    tool = work / "copy" / UPDATER
    shutil.copy2(updater, tool)
    app = work / "Application"
    app.mkdir()
    real = updater.read_bytes()
    problems = []

    def call(step: str, args: list[str]) -> tuple[int, str]:
        done = subprocess.run([str(tool), *args], capture_output=True, text=True, timeout=300)
        print(f"{step:<9} exit {done.returncode}: {done.stdout.strip().replace(chr(10), ' | ')}")
        return done.returncode, done.stdout

    browser = {"thoron.exe": b"browser " + OLDER.encode()}
    code, out = call("first", stage(app, work, OLDER, browser, browser))
    if code != 0 or "handed off" in out:
        problems.append("first: the updater did not apply a version without an updater itself")

    with_updater = {"thoron.exe": b"browser " + NEWER.encode(), UPDATER: real}
    code, out = call("hand-off", stage(app, work, NEWER, with_updater, with_updater))
    if code != 0 or f"handed off to the updater of {NEWER}" not in out or "done" not in out:
        problems.append("hand-off: the apply was not handed to the version's own updater")
    if (app / HAND_OFF_COPY).exists():
        problems.append("hand-off: the copy made for it is still there")
    if not (app / NEWER / UPDATER).is_file():
        problems.append("hand-off: the new version has no updater")

    listed = {"thoron.exe": b"browser " + THIRD.encode(), UPDATER: real}
    code, out = call("tampered", stage(app, work, THIRD, dict(listed, **{UPDATER: tampered(real)}), listed))
    if code != EXIT_BAD_FILES or "handed off" in out:
        problems.append(f"tampered: gave {code}, not {EXIT_BAD_FILES}, or was started")
    if (app / HAND_OFF_COPY).exists() or (app / f"{THIRD}.staging").exists():
        problems.append("tampered: the copy or the staged folder is still there")

    code, out = call("status", [f"--root={app}", "--status"])
    if f"current: {NEWER}\nprevious: {OLDER}\n" not in out:
        problems.append("status: the tampered version was switched to, or the others are not named")
    shutil.rmtree(work, ignore_errors=True)
    return problems


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--updater", type=Path, required=True, help="the thoron_update.exe to check")
    p.add_argument("--work", type=Path, required=True, help="a scratch folder; a folder `handoff` is made in it")
    a = p.parse_args(argv)
    if not a.updater.is_file():
        print("updater hand-off: the updater is not there", file=sys.stderr)
        return 2
    problems = run(a.updater, a.work / "handoff")
    for problem in problems:
        print(f"FAIL  {problem}")
    print(f"UPDATER HAND-OFF CHECK: {'PASSED' if not problems else f'FAILED ({len(problems)} problem(s))'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
