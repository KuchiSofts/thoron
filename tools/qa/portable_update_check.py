#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""A portable copy updated from its release's package, end to end and offline (ROADMAP P3.20, P3.12).

The release's package is made by tools/release/portable.py from a build, with the launcher and the updater given.
A portable copy one version older is made from the same package (its version folder renamed, so which version a
start runs is told by the folder chrome://version names), or, with --previous, the last release's own portable
package is the older copy, so that the updater which runs is the one people have (THREAT_MODEL U14). In a folder with spaces, accented, Cyrillic and Chinese
letters:

    start     Thoron.exe starts the older version; a setting is changed
    update    the older copy's own updater: thoron_update --apply-package <release .zip> --version <newer>; it
              unpacks only the newer version's folder, hands the apply to the updater in it, puts the version in
              place and refreshes the launcher (its output says each)
    again     Thoron.exe starts the newer version, the setting kept
    status    thoron_update --status names the newer version as current and the older as the one before
    refused   a version the package does not have, and a file that is not a package, switch nothing
    rollback  after a setting changed in the newer version: `--rollback` without `--confirm` only says what it
              would do; with `--confirm --restore-profile` it puts the profile back from the snapshot the
              update took (`--snapshot-profile`), byte for byte, and switches back; the older version's folder
              is byte for byte what it was before the update, and the next start runs it with the setting
              from before the update

Nothing leaves the PC: the browser runs headless with every outside name unresolvable.
    py -3 -I tools/qa/portable_update_check.py --chrome-bin <Chrome-bin> --launcher <thoron_launcher.exe>
        --updater <thoron_update.exe> --work <scratch dir> [--previous <last release's portable .zip>]
        [--report <file for release.py prepare --update-check>]
Exit status 0 only when every step passes.
"""
import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.qa import portable_check as pc  # noqa: E402
from tools.qa import portable_launcher_check as pl  # noqa: E402
from tools.release import portable  # noqa: E402

PLACE = "Ünïcødé update Пример 例 & more"
OLDER = "158.0.8127.3000"
VERSION = re.compile(r"^\d+\.\d+\.\d+\.\d+$")


def update_problems(code: int, text: str, newer: str) -> list[str]:
    """What the output of --apply-package must say for an update that worked."""
    out = []
    if code != 0:
        out.append(f"update: thoron_update --apply-package gave {code}: {text.strip()[:200]}")
    for words in (f"handed off to the updater of {newer}", "done", "launcher: current"):
        if words not in text:
            out.append(f"update: the output does not say {words!r}")
    return out


def tree_hashes(folder: Path) -> dict[str, str]:
    """Every file below `folder` with its SHA-256, by its path inside it."""
    return {f.relative_to(folder).as_posix(): hashlib.sha256(f.read_bytes()).hexdigest()
            for f in sorted(folder.rglob("*")) if f.is_file()}


def restored_problems(snapshot: dict[str, str], profile: Path) -> list[str]:
    """The snapshot's profile files that are not, byte for byte, what is in the profile after a restore."""
    out = []
    for name, digest in snapshot.items():
        if name.endswith(".json") and "/" not in name:
            continue        # the snapshot's own record of itself
        target = profile / name
        if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            out.append(f"rollback: {name} is not what the snapshot holds")
    return out


def unpack_previous(package: Path, place: Path) -> str:
    """Unpacks the last release's portable package into `place` (ThoronPortable/ in it) and returns the
    version it runs. Python's extractall keeps every entry inside `place`."""
    with zipfile.ZipFile(package) as z:
        z.extractall(place)
    current = (place / "ThoronPortable" / "Application" / "current").read_text(encoding="ascii").strip()
    if not VERSION.match(current):
        raise ValueError(f"the previous package names no version it runs ({current[:40]!r})")
    return current


def report_text(problems: list[str], newer: str, older: str, previous: Path | None) -> str:
    """What release.py prepare reads (--update-check): which build was installed over which, by whose updater."""
    return ("Portable update check (tools/qa/portable_update_check.py)\n"
            f"Build: {newer}\n"
            f"From: {older}\n"
            f"Previous package: {previous.name if previous else 'none (the same package, one version older)'}\n"
            f"PORTABLE UPDATE CHECK: {'PASSED' if not problems else 'FAILED'}\n")


def run(chrome_bin: Path, launcher: Path, updater: Path, work: Path,
        previous: Path | None = None) -> tuple[list[str], str, str]:
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    problems: list[str] = []

    def report(step: str, found: list[str], detail) -> None:
        problems.extend(found)
        print(f"{'PASS' if not found else 'FAIL'}  {step}: {detail}")
        for f in found:
            print(f"      {f}")

    made = portable.build(chrome_bin, work / "dist", "win-x64-avx2", launcher=launcher, updater=updater)
    newer, archive = made["version"], made["zip"]
    print(f"package: {archive.name} ({archive.stat().st_size} bytes), Thoron {newer}")

    copy = work / PLACE / "ThoronPortable"
    if previous is None:
        # one version older, made from the same package: the updater that runs is this build's own
        older = OLDER
        shutil.copytree(made["package"], copy)
        app = copy / "Application"
        (app / newer).rename(app / older)
        (app / "current").write_text(older + "\n", encoding="ascii")
    else:
        # the last release itself: its own updater installs this build (THREAT_MODEL U14)
        older = unpack_previous(previous, work / PLACE)
        app = copy / "Application"
        print(f"previous release: {previous.name}, Thoron {older}")
        if older == newer:
            return [f"the previous package is of {older}, this same build"], newer, older

    found = pl._one_start(copy, change=23)
    report("start", pl.started_problems("start", found, copy, older) or
           ([] if found.get("setting") == pc.DEFAULT else [f"start: the setting is {found.get('setting')}"]),
           found.get("executable_path"))

    old_before = tree_hashes(app / older)
    old_updater = app / older / "thoron_update.exe"
    snapshots = copy / "Snapshots"
    code, text = pl._cli(old_updater, f"--root={app}", f"--apply-package={archive}", f"--version={newer}",
                         f"--snapshot-profile={copy / 'User Data'}", f"--snapshots={snapshots}")
    report("update", update_problems(code, text, newer), text.strip().replace("\n", " | "))

    found = pl._one_start(copy, change=37)
    report("again", pl.started_problems("again", found, copy, newer) +
           ([] if found.get("setting") == 23 else [f"again: the setting is {found.get('setting')}, not 23"]),
           found.get("executable_path"))

    code, text = pl._cli(app / newer / "thoron_update.exe", f"--root={app}", "--status")
    report("status", pl.status_problems(text, newer, older) if code == 0 else [f"status gave {code}"],
           text.strip().replace("\n", " | "))

    # A version the package does not have, and a file that is not a package, switch nothing.
    code, text = pl._cli(app / newer / "thoron_update.exe", f"--root={app}", f"--apply-package={archive}",
                         "--version=158.0.8127.3999")
    bad = work / "not-a-package.zip"
    bad.write_bytes(b"not a zip")
    code2, text2 = pl._cli(app / newer / "thoron_update.exe", f"--root={app}", f"--apply-package={bad}",
                           "--version=158.0.8127.3999")
    code3, text3 = pl._cli(app / newer / "thoron_update.exe", f"--root={app}", "--status")
    found = []
    if code != 12 or "no_such_version" not in text:
        found.append(f"refused: a version the package lacks gave {code} {text.strip()!r}")
    if code2 != 12 or "not_a_package" not in text2:
        found.append(f"refused: a file that is not a package gave {code2} {text2.strip()!r}")
    if pl.status_problems(text3, newer, older):
        found.append("refused: something was switched")
    if any(p.name.endswith(".staging") for p in app.iterdir()):
        found.append("refused: a staging folder was left")
    report("refused", found, f"{text.strip()} / {text2.strip()}")

    tool = app / newer / "thoron_update.exe"
    restore = [f"--root={app}", "--rollback", f"--restore-profile={copy / 'User Data'}", f"--snapshots={snapshots}"]
    code, text = pl._cli(tool, *restore)
    found = [] if code == 16 and "--confirm" in text and "is lost" in text else \
        [f"rollback: without --confirm it gave {code} {text.strip()[:160]!r}"]
    code_s, text_s = pl._cli(tool, f"--root={app}", "--status")
    found += pl.status_problems(text_s, newer, older)
    snapshot = snapshots / f"before-{newer}"
    held = tree_hashes(snapshot) if snapshot.is_dir() else {}
    if not held:
        found.append("rollback: the update took no snapshot")
    code, text = pl._cli(tool, *restore, "--confirm")
    if code != 0 or "profile: put back" not in text:
        found.append(f"rollback: --confirm gave {code} {text.strip()[:160]!r}")
    found += restored_problems(held, copy / "User Data")
    if tree_hashes(app / older) != old_before:
        found.append(f"rollback: the folder of {older} is not what it was before the update")
    after = pl._one_start(copy, change=None)
    found += pl.started_problems("rollback", after, copy, older)
    if after.get("setting") != 23:
        found.append(f"rollback: the setting is {after.get('setting')}, not 23 from before the update")
    report("rollback", found, f"{len(held)} files of the snapshot; {after.get('executable_path')}")
    return problems, newer, older


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--chrome-bin", type=Path, required=True)
    p.add_argument("--launcher", type=Path, required=True)
    p.add_argument("--updater", type=Path, required=True)
    p.add_argument("--work", type=Path, required=True, help="a scratch folder; `portable-update` is made in it")
    p.add_argument("--previous", type=Path, help="the last release's portable package (.zip): its own updater "
                                                 "installs this build (THREAT_MODEL U14)")
    p.add_argument("--report", type=Path, help="write the result for release.py prepare --update-check")
    a = p.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    problems, newer, older = run(a.chrome_bin, a.launcher, a.updater, a.work / "portable-update", a.previous)
    if a.report:
        a.report.write_text(report_text(problems, newer, older, a.previous), encoding="utf-8", newline="\n")
    print(f"PORTABLE UPDATE CHECK: {'PASSED' if not problems else f'FAILED ({len(problems)} problem(s))'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
