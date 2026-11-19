#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""The Windows portable package (ROADMAP P2.8, P3.12): a folder, and a .zip of it, that runs Thoron without installing.

    ThoronPortable/
        Thoron.exe          the launcher (components/thoron_update/launcher, built as thoron_launcher.exe)
        README.txt
        variant             "win-x64-avx2" or "win-x64-sse4" and a line feed: the processors the build is for
        Application/
            current         the version that starts, and a line feed
            <version>/      the build's Chrome-bin folder as it is, and thoron_update.exe beside its thoron.exe
        User Data/          the profile: never in the package, made by the launcher at the first start

This is the layout of Thoron's own updater (components/thoron_update/swap.h): every version in a folder of its
own and `current` naming the one that starts, so an update is a new version folder put beside the old one and
`current` replaced in one step, and nothing is ever written into `User Data`. The updater lives in the version
folder, so it changes with each version and a running updater is never in a folder being removed.

The launcher is a program, not a script. It finds the package from its own file, says so and starts nothing on
a processor the variant cannot run on (exit 3), starts `Application\\<current>\\thoron.exe` with
`--user-data-dir="<package>\\User Data"` and the rest of its own command line as it got it, makes `User Data`
itself and starts nothing when it cannot (Chromium would then use the PC's own profile folder). It is a window
program, so no console opens. The rules the `.cmd` launcher before it had to keep (code pages, delayed
expansion, a `%NAME%` in the folder's name) are gone with it: no command interpreter reads the folder's name or
the arguments any more. What it still does not do, and what a portable copy leaves on the PC as measured by
tools/qa/portable_check.py, is in docs/release/PORTABLE.md.

A package is refused, and nothing is written, when the build's folder fails `package_audit.py`, holds anything
that looks like a profile or the leftovers of a used browser, holds a link or already holds an updater; when
the launcher or the updater is not a Windows program for x64 (the launcher a window program); and when the
variant is not one of the two the launcher knows. A package is never overwritten. The .zip is reproducible:
the same files give the same bytes (sorted names, one fixed time, no host details), with the same Python and
zlib. `audit` checks a package folder or its .zip, and for a .zip also its name against `variant` and `current`.
    py -3 -I tools/release/portable.py build --chrome-bin <out>\\Chrome-bin --launcher <out>\\thoron_launcher.exe
        --updater <out>\\thoron_update.exe --dist <folder> --variant win-x64-avx2
    py -3 -I tools/release/portable.py audit --package <folder>\\ThoronPortable | <folder>\\thoron-...-portable.zip
"""
import argparse
import hashlib
import os
import re
import shutil
import sys
import time
import zipfile
import zlib
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.release import package_audit  # noqa: E402

FOLDER = "ThoronPortable"
BROWSER_DIR = "Application"
PROFILE_DIR = "User Data"
LAUNCHER = "Thoron.exe"
README = "README.txt"
VARIANT_FILE = "variant"
CURRENT = "current"                 # in BROWSER_DIR
PROGRAM = "thoron.exe"
UPDATER = "thoron_update.exe"       # its name in the build's out dir and in the package
BUILT_LAUNCHER = "thoron_launcher.exe"  # the launcher's name in the build's out dir
TOP = (LAUNCHER, README, VARIANT_FILE, BROWSER_DIR)     # and PROFILE_DIR, which only the launcher makes
VARIANTS = ("win-x64-avx2", "win-x64-sse4")             # the two the launcher knows
EPOCH = 315532800                   # 1980-01-01 00:00:00 UTC: the earliest time a .zip can hold
HEAD = 1 << 16                      # what is read of a program to judge it: its headers are in the first bytes
_VERSION = re.compile(r"^\d+(\.\d+){3}$")
_ZIP_NAME = re.compile(r"^thoron-(\d+(?:\.\d+){3})-(win-[a-z0-9]+-[a-z0-9]+)-portable\.zip$")
# What a profile, or a browser that was installed and used, leaves behind: never part of a package.
_PRIVATE = re.compile(r"(?i)^(user data|local state|preferences|secure preferences|login data|cookies|history|"
                      r"web data|bookmarks|first run|last version|lockfile|devtoolsactiveport|crashpad|"
                      r"(new|old)_thoron\.exe|.*\.(log|dmp))$")
_MACHINE_X64 = 0x8664
_PE32_PLUS = 0x20B
_WINDOW_SUBSYSTEM = 2               # IMAGE_SUBSYSTEM_WINDOWS_GUI: no console window
_EXECUTABLE, _LIBRARY = 0x0002, 0x2000


class PortableError(Exception):
    pass


def zip_name(version: str, variant: str) -> str:
    return f"thoron-{version}-{variant}-portable.zip"


def variant_text(variant: str) -> bytes:
    return f"{variant}\n".encode("ascii")


def current_text(version: str) -> bytes:
    return f"{version}\n".encode("ascii")


def readme_text(version: str, variant: str) -> str:
    made_for = "processors with AVX2" if variant == "win-x64-avx2" else "older processors too (SSE4.2)"
    lines = (
        "Thoron portable for Windows",
        "===========================",
        "",
        f"Start {LAUNCHER}. Nothing is installed.",
        "",
        f"  {LAUNCHER:<15}the launcher: it starts the browser",
        f"  {BROWSER_DIR:<15}the browser, version {version}",
        f"  {PROFILE_DIR:<15}your profile; made at the first start",
        f"  {VARIANT_FILE:<15}{variant}: made for {made_for}",
        "",
        "Bookmarks, history, settings and extensions are kept in the",
        f"{PROFILE_DIR} folder, inside this folder. The folder can be moved,",
        "renamed or kept on a USB drive: the launcher finds everything from",
        "where it is.",
        "",
        "Good to know",
        "",
        f"- Always start with {LAUNCHER}. The browser in {BROWSER_DIR} started on",
        "  its own uses the profile of this PC, not the one in this folder.",
        f"- {LAUNCHER} is a plain Windows program: no console window opens.",
        "- If the processor of this PC cannot run this copy, the launcher",
        "  says so and starts nothing. The win-x64-sse4 package runs on",
        "  older processors.",
        "- Saved passwords and sign-ins are locked to the Windows account they",
        "  were saved with. On another PC or account they cannot be read and",
        "  may be lost. Do not keep passwords in a portable copy yet.",
        "- This copy does not update itself yet. To update by hand: get the",
        "  new package, close Thoron, and replace everything in this folder",
        f"  with the new package's files, except {PROFILE_DIR}. Keep {PROFILE_DIR}.",
        "- To remove Thoron: close it and delete this folder.",
        "- Windows and the browser engine still leave a few traces on the PC,",
        "  such as some registry values. They are listed in",
        "  docs/release/PORTABLE.md of the source.",
        "- If the folder cannot be written (a write-protected drive), the",
        "  launcher says so and starts nothing.",
        "",
        "Source, licence and credits: https://github.com/KuchiSofts/thoron",
        "and chrome://credits in the browser.",
        "",
    )
    return "\r\n".join(lines)


def program_problems(head: bytes | None, name: str, window: bool = False) -> list[str]:
    """Why the first bytes of a file are not a Windows program for x64 (empty when they are). `window`: it must
    be a window program (subsystem 2), which Windows starts without a console."""
    if head is None:
        return [f"{name} is missing"]
    if len(head) < 64 or head[:2] != b"MZ":
        return [f"{name} is not a Windows program: no MZ header"]
    at = int.from_bytes(head[0x3C:0x40], "little")
    if at + 24 + 70 > len(head) or head[at:at + 4] != b"PE\0\0":
        return [f"{name} is not a Windows program: no PE header"]

    def word(offset: int) -> int:
        return int.from_bytes(head[at + offset:at + offset + 2], "little")

    machine, flags, magic, subsystem = word(4), word(22), word(24), word(24 + 68)
    out = []
    if machine != _MACHINE_X64 or magic != _PE32_PLUS:
        out.append(f"{name} is not a program for x64 (machine 0x{machine:04x})")
    if not flags & _EXECUTABLE or flags & _LIBRARY:
        out.append(f"{name} is a library or cannot be run, not a program")
    if window and subsystem != _WINDOW_SUBSYSTEM:
        out.append(f"{name} must be a window program (subsystem 2, no console window), not subsystem {subsystem}")
    return out


def _head(path: Path) -> bytes | None:
    if not path.is_file():
        return None
    with path.open("rb") as f:
        return f.read(HEAD)


def parts_problems(launcher: Path, updater: Path) -> list[str]:
    """Why the launcher and the updater a package is made with may not go into it (empty when they may)."""
    return (program_problems(_head(launcher), f"the launcher {launcher.name}", window=True)
            + program_problems(_head(updater), f"the updater {updater.name}"))


def files(root: Path) -> list[str]:
    """Every file below `root` as a sorted relative path with `/`. A link is refused: it could lead anywhere."""
    out = []
    is_junction = getattr(os.path, "isjunction", lambda p: False)
    for base, dirs, names in os.walk(root):
        for name in dirs + names:
            full = os.path.join(base, name)
            if os.path.islink(full) or is_junction(full):
                raise PortableError(f"{os.path.relpath(full, root)} is a link, not a file or a folder")
        out += [Path(base, name).relative_to(root).as_posix() for name in names]
    return sorted(out)


def browser_version(names: list[str]) -> str:
    versions = sorted({n.split("/", 1)[0] for n in names if "/" in n and _VERSION.match(n.split("/", 1)[0])})
    if len(versions) != 1:
        raise PortableError(f"one version folder is expected beside {PROGRAM}, found {versions or 'none'}")
    return versions[0]


def source_problems(names: list[str], with_updater: bool = False) -> list[str]:
    """Why a browser folder (paths relative to it) may not be packaged (empty when it may). The build's
    Chrome-bin folder has no updater (`with_updater` False); the package's version folder has it beside the
    browser."""
    out = [f"package audit: {p}" for p in package_audit.audit(names, "win")]
    if PROGRAM not in names:
        out.append(f"{PROGRAM} is not at the top of the folder, where the launcher starts it")
    if with_updater and UPDATER not in names:
        out.append(f"{UPDATER} is not beside {PROGRAM}")
    if not with_updater and UPDATER in names:
        out.append(f"the browser folder already holds {UPDATER}; the package's updater is given with --updater")
    try:
        version = browser_version(names)
        if f"{version}/chrome.dll" not in names:
            out.append(f"{version}/chrome.dll is missing")
    except PortableError as e:
        out.append(str(e))
    for n in names:
        if any(_PRIVATE.match(part) for part in n.split("/")):
            out.append(f"profile data or a leftover of a used browser: {n}")
    if len({n.casefold() for n in names}) != len(names):
        out.append("two names differ only in upper and lower case")
    return out


def package_problems(names: list[str], read, variant: str | None = None, version: str | None = None) -> list[str]:
    """The package audit hook: why a package (paths relative to its folder) may not ship (empty when it may).

    `read(name)` gives the first bytes of one of its files. `variant` and `version`, when given, are what the
    package must be (the name of its .zip says them). It covers what `package_audit.py --dir
    <package>/Application/<version> --platform win` checks, and the package's own rules: only the launcher, the
    readme, `variant` and the browser folder at the top; the launcher a window program for x64; `variant` one of
    the two the launcher knows; `current` naming the one version folder there is; the updater beside the
    browser; no profile.
    """
    out = []
    for top in sorted({n.split("/", 1)[0] for n in names} - set(TOP)):
        out.append(f"not part of a package: {top}" + (" (a package never carries a profile)"
                                                      if top.casefold() == PROFILE_DIR.casefold() else ""))
    present = set(names)
    out += [f"{need} is missing" for need in (README, VARIANT_FILE) if need not in present]
    out += program_problems(read(LAUNCHER) if LAUNCHER in present else None, LAUNCHER, window=True)
    if VARIANT_FILE in present:
        said = read(VARIANT_FILE)
        if said not in {variant_text(v) for v in VARIANTS}:
            out.append(f"{VARIANT_FILE} must be one of {', '.join(VARIANTS)} and a line feed, as the launcher reads it")
        elif variant is not None and said != variant_text(variant):
            out.append(f"{VARIANT_FILE} says {said.decode('ascii').strip()}, and the package is named for {variant}")
    prefix = BROWSER_DIR + "/"
    inside = [n[len(prefix):] for n in names if n.startswith(prefix)]
    loose = sorted(n for n in inside if "/" not in n and n != CURRENT)
    out += [f"not part of a package: {BROWSER_DIR}/{n}" for n in loose]
    folders = sorted({n.split("/", 1)[0] for n in inside if "/" in n})
    if len(folders) != 1 or not _VERSION.match(folders[0]):
        out.append(f"one version folder is expected in {BROWSER_DIR}, found {folders or 'none'}")
        return out
    found = folders[0]
    if CURRENT not in inside:
        out.append(f"{BROWSER_DIR}/{CURRENT} is missing")
    elif read(f"{prefix}{CURRENT}") != current_text(found):
        out.append(f"{BROWSER_DIR}/{CURRENT} must name the version folder {found}, and nothing more")
    if version is not None and found != version:
        out.append(f"the version folder is {found}, and the package is named for {version}")
    below = [n[len(found) + 1:] for n in inside if n.startswith(found + "/")]
    out += [f"{BROWSER_DIR}/{found}: {p}" for p in source_problems(below, with_updater=True)]
    try:
        if browser_version(below) != found:
            out.append(f"the version folder {found} holds the browser {browser_version(below)}")
    except PortableError:
        pass                                                    # said by source_problems
    if UPDATER in below:
        out += program_problems(read(f"{prefix}{found}/{UPDATER}"), f"{BROWSER_DIR}/{found}/{UPDATER}")
    if len({n.casefold() for n in names}) != len(names):
        out.append("two names in the package differ only in upper and lower case")
    return out


def zip_problems(archive: Path) -> list[str]:
    """Why a portable .zip may not ship (empty when it may): its name, its entries, its checksums, and the
    package inside it as `package_problems` judges it, with the variant and version of its name."""
    named = _ZIP_NAME.match(archive.name)
    out = [] if named else [f"{archive.name} is not named thoron-<version>-<variant>-portable.zip"]
    try:
        with zipfile.ZipFile(archive) as z:
            infos = z.infolist()
            broken = z.testzip()
            if broken:
                out.append(f"{broken} in the .zip does not match its checksum")
            names, seen = [], set()
            for info in infos:
                name = info.filename
                if not name.startswith(FOLDER + "/") or "\\" in name or ".." in name.split("/"):
                    out.append(f"the .zip holds {name}, outside the one folder {FOLDER}")
                elif name.endswith("/"):
                    out.append(f"the .zip holds a folder entry {name}; a package's .zip holds files only")
                elif name in seen:
                    out.append(f"the .zip holds {name} twice")
                else:
                    seen.add(name)
                    names.append(name[len(FOLDER) + 1:])

            def read(name: str) -> bytes:
                with z.open(f"{FOLDER}/{name}") as f:
                    return f.read(HEAD)

            out += package_problems(sorted(names), read, named and named.group(2), named and named.group(1))
    except (zipfile.BadZipFile, zlib.error, EOFError, OSError) as e:
        out.append(f"the .zip cannot be read: {e}")
    return out


def audit(package: Path, variant: str | None = None) -> list[str]:
    """`package_problems` for a package folder, or `zip_problems` for its .zip."""
    if package.is_file():
        return zip_problems(package)

    def read(name: str) -> bytes | None:
        return _head(package / name)

    return package_problems(files(package), read, variant)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _copy(src: Path, dst: Path, epoch: int) -> None:
    """A checked copy with the fixed time: what was read is what is in the package."""
    read = hashlib.sha256()
    dst.parent.mkdir(parents=True, exist_ok=True)
    with src.open("rb") as f, dst.open("xb") as g:
        for block in iter(lambda: f.read(1 << 20), b""):
            read.update(block)
            g.write(block)
    if sha256(dst) != read.hexdigest():
        raise PortableError(f"{dst.name} was not copied as it was read")
    os.utime(dst, (epoch, epoch))


def _write(dst: Path, data: bytes, epoch: int) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with dst.open("xb") as f:
        f.write(data)
    os.utime(dst, (epoch, epoch))


def write_zip(package: Path, archive: Path, epoch: int = EPOCH) -> None:
    """The package as a .zip with the one folder FOLDER inside: the same files give the same bytes."""
    stamp = time.gmtime(epoch)[:6]
    with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED) as z:
        for name in files(package):
            info = zipfile.ZipInfo(f"{FOLDER}/{name}", date_time=stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0      # the same on every system that builds it
            info.external_attr = 0x20   # a plain Windows file (Python would put its own value for 0)
            info.file_size = (package / name).stat().st_size
            with (package / name).open("rb") as f, z.open(info, "w") as out:
                shutil.copyfileobj(f, out, 1 << 20)


def build(chrome_bin: Path, dist: Path, variant: str, launcher: Path, updater: Path, epoch: int = EPOCH,
          zipped: bool = True) -> dict:
    """Make `dist`/ThoronPortable, and its .zip, from a build's Chrome-bin folder, its launcher and its updater;
    refuse rather than repair."""
    if variant not in VARIANTS:
        raise PortableError(f"variant must be {' or '.join(VARIANTS)} (the two the launcher knows), got {variant!r}")
    if epoch < EPOCH:
        raise PortableError("a .zip cannot hold a time before 1980")
    if not chrome_bin.is_dir():
        raise PortableError("the browser folder is not there")
    problems = parts_problems(launcher, updater)
    names = files(chrome_bin)
    problems += source_problems(names)
    if problems:
        raise PortableError("the build may not be packaged: " + "; ".join(problems))
    version = browser_version(names)
    package = dist / FOLDER
    archive = dist / zip_name(version, variant)
    for target in (package, archive):
        if target.exists():
            raise PortableError(f"{target.name} is already in the output folder; a package is never overwritten")
    home = package / BROWSER_DIR / version
    try:
        for name in names:
            _copy(chrome_bin / name, home / name, epoch)
        _copy(updater, home / UPDATER, epoch)
        _copy(launcher, package / LAUNCHER, epoch)
        _write(package / BROWSER_DIR / CURRENT, current_text(version), epoch)
        _write(package / VARIANT_FILE, variant_text(variant), epoch)
        _write(package / README, readme_text(version, variant).encode("ascii"), epoch)
        problems = audit(package, variant)
        if problems:
            raise PortableError("the package fails its audit: " + "; ".join(problems))
        if zipped:
            write_zip(package, archive, epoch)
            with zipfile.ZipFile(archive) as z:
                packed = {i.filename: i.file_size for i in z.infolist()}
            if packed != {f"{FOLDER}/{n}": (package / n).stat().st_size for n in files(package)}:
                raise PortableError("the .zip does not hold the package's files")
            problems = audit(archive)
            if problems:
                raise PortableError("the .zip fails its audit: " + "; ".join(problems))
    except (PortableError, OSError):
        shutil.rmtree(package, ignore_errors=True)
        archive.unlink(missing_ok=True)
        raise
    return {"version": version, "package": package, "files": len(names) + 5, "zip": archive if zipped else None}


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--chrome-bin", type=Path, required=True, help="the build's Chrome-bin folder")
    b.add_argument("--launcher", type=Path, required=True, help=f"the build's {BUILT_LAUNCHER}")
    b.add_argument("--updater", type=Path, required=True, help=f"the build's {UPDATER}")
    b.add_argument("--dist", type=Path, required=True, help="where the package is written")
    b.add_argument("--variant", required=True, choices=VARIANTS)
    b.add_argument("--epoch", type=int, default=EPOCH, help="the time every file gets, in seconds since 1970 (UTC)")
    b.add_argument("--no-zip", action="store_true")
    a_ = sub.add_parser("audit")
    a_.add_argument("--package", type=Path, required=True, help="a ThoronPortable folder, or its .zip")
    a = p.parse_args(argv)
    try:
        if a.cmd == "audit":
            problems = audit(a.package) if a.package.exists() else ["the package is not there"]
            for problem in problems:
                print(f"portable: {problem}", file=sys.stderr)
            print(f"portable audit: {'OK' if not problems else f'{len(problems)} problem(s)'}")
            return 1 if problems else 0
        made = build(a.chrome_bin, a.dist, a.variant, a.launcher, a.updater, a.epoch, not a.no_zip)
    except (PortableError, OSError) as e:
        print(f"portable: {e}", file=sys.stderr)
        return 2
    print(f"portable: {FOLDER} ({made['files']} files, Thoron {made['version']}, {a.variant})")
    if made["zip"]:
        print(f"portable: {made['zip'].name} ({made['zip'].stat().st_size} bytes, sha256 {sha256(made['zip'])})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
