#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""The Windows portable package (ROADMAP P2.8): a folder, and a .zip of it, that runs Thoron without installing.

    ThoronPortable/
        Thoron.cmd      the launcher
        README.txt
        Application/    the build's Chrome-bin folder as it is: thoron.exe and the version folder
        User Data/      the profile: not in the package, made at the first start

`Application` and `User Data` are the names an installed Thoron uses, so the update steps of the design (a new
version folder staged beside the old one, nothing ever written into `User Data`) fit a portable folder as it is.

The launcher starts `Application\\thoron.exe` with `--user-data-dir` set to the `User Data` folder beside itself
and passes every argument on. It is a `.cmd` for now: plain text anyone can read, made without a compiler, and
the same bytes in every build. ROADMAP P3.12 replaces it with a program. What a `.cmd` gets wrong when written
carelessly, and what this one does about it (`launcher_problems` keeps the rules, the tests run each case):
  - code pages: the file is ASCII, so it reads the same in every code page, and the folder's own name never
    passes through one: cmd.exe keeps it as it got it from Windows;
  - `%` and `&` in the folder's name: every path is quoted, and a value is put into a line once and never read
    again as a command (no `call` with a path, no `for /f`);
  - `!` in the folder's name: delayed expansion is switched off, also when the PC has it on by default;
  - a start by the bare name through the search path, where `%~dp0` is wrong: the folder is read inside a called
    label, where it is right;
  - the console window: `start` does not wait, so the window closes at once instead of staying for the whole
    session; it still shows for a moment, which only a program can avoid (P3.12);
  - the working directory is left alone, and so is the browser's environment;
  - a profile folder that cannot be made (a write-protected drive): Chromium would then use the PC's own
    profile folder instead, so the launcher makes the folder itself and starts nothing when it cannot.
Known limits of any `.cmd`: a folder whose name holds the name of an existing environment variable between two
`%` (such as `%TEMP%`) cannot start it, because cmd.exe replaces that before the launcher runs; and an argument
with `&` must be quoted, as for any command typed at a prompt. The whole account, with what a portable copy
still leaves on the PC as measured by tools/qa/portable_check.py, is in docs/release/PORTABLE.md.

A package is refused, and nothing is written, when the build's folder fails `package_audit.py`, holds anything
that looks like a profile or the leftovers of a used browser, or holds a link. The .zip is reproducible: the
same files give the same bytes (sorted names, one fixed time, no host details), with the same Python and zlib.
    py -3 -I tools/release/portable.py build --chrome-bin <out>\\Chrome-bin --dist <folder> --variant win-x64-avx2
    py -3 -I tools/release/portable.py audit --package <folder>\\ThoronPortable
"""
import argparse
import hashlib
import os
import re
import shutil
import sys
import time
import zipfile
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.release import package_audit  # noqa: E402

FOLDER = "ThoronPortable"
BROWSER_DIR = "Application"
PROFILE_DIR = "User Data"
LAUNCHER = "Thoron.cmd"
README = "README.txt"
PROGRAM = "thoron.exe"
_VAR = "THORON_PORTABLE_DIR"
HERE = f"%{_VAR}%"                  # in the launcher: its own folder, with the last backslash
EPOCH = 315532800                   # 1980-01-01 00:00:00 UTC: the earliest time a .zip can hold
_VARIANT = re.compile(r"^win-(x64|arm64)-[a-z0-9]+$")
_VERSION = re.compile(r"^\d+(\.\d+){3}$")
# What a profile, or a browser that was installed and used, leaves behind: never part of a package.
_PRIVATE = re.compile(r"(?i)^(user data|local state|preferences|secure preferences|login data|cookies|history|"
                      r"web data|bookmarks|first run|last version|lockfile|devtoolsactiveport|crashpad|"
                      r"(new|old)_thoron\.exe|.*\.(log|dmp))$")

START = (f'set "{_VAR}=" & start "" "{HERE}{BROWSER_DIR}\\{PROGRAM}" '
         f'--user-data-dir="{HERE}{PROFILE_DIR}" --no-default-browser-check %*')
MAKE = f'if not exist "{HERE}{PROFILE_DIR}\\" md "{HERE}{PROFILE_DIR}"'     # the one thing the launcher writes
LAUNCHER_TEXT = "\r\n".join((
    "@echo off",
    "rem Thoron portable launcher.",
    f"rem It starts the browser in the {BROWSER_DIR} folder beside this file and keeps",
    f"rem the profile in the {PROFILE_DIR} folder beside this file. Both are found from",
    "rem where this file is, so the folder can be moved or renamed at any time.",
    "rem Arguments are passed on to the browser as they are.",
    "setlocal EnableExtensions DisableDelayedExpansion",
    "call :locate",
    f'if not exist "{HERE}{BROWSER_DIR}\\{PROGRAM}" goto missing',
    "rem The browser falls back to the profile folder of this PC when it cannot",
    "rem make the one it is given, so the folder is made here, or nothing starts.",
    MAKE,
    f'if not exist "{HERE}{PROFILE_DIR}\\" goto unwritable',
    START,
    "exit /b %errorlevel%",
    "",
    ":locate",
    "rem Inside a called label this is the folder of this file in every case, also",
    "rem when the file was started by its bare name through the search path.",
    f'set "{_VAR}=%~dp0"',
    "exit /b 0",
    "",
    ":missing",
    f"echo Thoron cannot start: {BROWSER_DIR}\\{PROGRAM} is not beside this launcher.",
    f"echo Extract the whole package and start {LAUNCHER} from inside its folder.",
    "pause",
    "exit /b 1",
    "",
    ":unwritable",
    f"echo Thoron cannot start: the folder {PROFILE_DIR} cannot be made beside this launcher.",
    "echo Put the package where files can be written, such as a drive that is not",
    "echo write-protected.",
    "pause",
    "exit /b 1",
    "",
))


class PortableError(Exception):
    pass


def launcher_problems(text: str) -> list[str]:
    """The rules a launcher must keep (empty when it does); each one is a way a `.cmd` goes wrong."""
    out = []
    if not text.isascii():
        out.append("not ASCII: it would read differently in another code page")
    if "\n" in text.replace("\r\n", "") or "\r" in text.replace("\r\n", "") or not text.endswith("\r\n"):
        out.append("lines must end with CR LF: cmd.exe loses labels in a file with bare line feeds")
    lines = text.replace("\r\n", "\n").split("\n")
    code = [l for l in lines if l and not l.lower().startswith("rem ")]
    if lines[0] != "@echo off":
        out.append("the first line must be `@echo off`")
    if "setlocal EnableExtensions DisableDelayedExpansion" not in code:
        out.append("delayed expansion must be switched off and the extensions on (`!` in a path, `%~dp0`)")
    if "!" in text or re.search(r"(?i)enabledelayedexpansion", text):
        out.append("`!` or delayed expansion: a `!` in the folder's name would be lost")
    if [l for l in lines if l.lower().startswith("rem ") and re.search(r"[%&|<>^]", l)]:
        out.append("a comment holds a character cmd.exe acts on")
    changing = r"(?i)\b(md|mkdir|rd|rmdir|del|erase|copy|xcopy|robocopy|move|ren|rename|reg|mklink)\b"
    if re.search(r"[|<>]", text) or code.count(MAKE) != 1 or \
            [l for l in code if l != MAKE and not l.lower().startswith("echo ") and re.search(changing, l)]:
        out.append("the launcher writes one thing, its own profile folder: no pipe, redirection or other change")
    if [l for l in code if re.match(r"(?i)\s*(cd|chdir|pushd|popd)\b", l)]:
        out.append("the working directory must be left alone")
    if [l for l in code if re.match(r"(?i)\s*call\b", l) and l.strip().lower() != "call :locate"]:
        out.append("`call` reads its line twice: never with a path or the arguments")
    if [l for l in code if re.search(r"(?i)\bexit\b(?!\s+/b)", l)]:
        out.append("`exit` without /b would close the prompt the launcher was called from")
    if code.count(START) != 1 or len([l for l in code if re.search(r"(?i)(^|&)\s*start\b", l)]) != 1:
        out.append("exactly one start line, as this tool writes it: an empty title, quoted paths, `%*` last")
    allowed = {HERE, "%~dp0", "%*", "%errorlevel%"}
    for l in code:
        rest = l
        for token in sorted(allowed, key=len, reverse=True):
            rest = rest.replace(token, "")
        if "%" in rest:
            out.append(f"a variable other than the launcher's own folder: {l.strip()[:60]}")
    if re.search(r"(?i)(?<![a-z])[a-z]:[\\/]|\\\\", text):
        out.append("an absolute path: everything is found from where the launcher is")
    if f'{HERE}"' in text or '%~dp0"' in text.replace(f'{_VAR}=%~dp0"', ""):
        out.append("the folder alone in quotes ends with a backslash before the quote, which escapes it")
    for l in code:
        if l.count('"') % 2:
            out.append(f"an odd number of quotes: {l.strip()[:60]}")
    return out


def readme_text(version: str) -> str:
    lines = (
        "Thoron portable for Windows",
        "===========================",
        "",
        f"Start {LAUNCHER}. Nothing is installed.",
        "",
        f"  {LAUNCHER:<15}the launcher",
        f"  {BROWSER_DIR:<15}the browser, version {version}",
        f"  {PROFILE_DIR:<15}your profile; the browser makes it at the first start",
        "",
        "Bookmarks, history, settings and extensions are kept in the",
        f"{PROFILE_DIR} folder, inside this folder. The folder can be moved,",
        "renamed or kept on a USB drive: the launcher finds everything from",
        "where it is.",
        "",
        "Good to know",
        "",
        f"- Always start with {LAUNCHER}. {BROWSER_DIR}\\{PROGRAM} started on its",
        "  own uses the profile of this PC, not the one in this folder.",
        "- A console window shows for a moment at the start: the launcher.",
        "- Saved passwords and sign-ins are locked to the Windows account they",
        "  were saved with. On another PC or account they cannot be read and",
        "  may be lost. Do not keep passwords in a portable copy yet.",
        "- This copy does not update itself. To update: get the new package,",
        f"  close Thoron, and replace the {BROWSER_DIR} folder with the new one.",
        f"  Keep {PROFILE_DIR}.",
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


def source_problems(names: list[str]) -> list[str]:
    """Why a browser folder (paths relative to it) may not be packaged (empty when it may)."""
    out = [f"package audit: {p}" for p in package_audit.audit(names, "win")]
    if PROGRAM not in names:
        out.append(f"{PROGRAM} is not at the top of the folder, where the launcher starts it")
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


def package_problems(names: list[str], launcher: bytes | None) -> list[str]:
    """The package audit hook: why a package (paths relative to its folder) may not ship (empty when it may).

    It covers what `package_audit.py --dir <package>/Application --platform win` checks, and the package's own
    rules: only the launcher, the readme and the browser folder, the launcher as this tool writes it, no profile.
    """
    out = []
    for top in sorted({n.split("/", 1)[0] for n in names} - {LAUNCHER, README, BROWSER_DIR}):
        out.append(f"not part of a package: {top}" + (" (a package never carries a profile)"
                                                      if top.casefold() == PROFILE_DIR.casefold() else ""))
    out += [f"{need} is missing" for need in (LAUNCHER, README) if need not in names]
    if launcher is not None and launcher != LAUNCHER_TEXT.encode("ascii"):
        out.append(f"{LAUNCHER} is not the launcher this tool writes")
    prefix = BROWSER_DIR + "/"
    return out + source_problems([n[len(prefix):] for n in names if n.startswith(prefix)])


def audit(package: Path) -> list[str]:
    launcher = package / LAUNCHER
    return package_problems(files(package), launcher.read_bytes() if launcher.is_file() else None)


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


def build(chrome_bin: Path, dist: Path, variant: str, epoch: int = EPOCH, zipped: bool = True) -> dict:
    """Make `dist`/ThoronPortable, and its .zip, from a build's Chrome-bin folder; refuse rather than repair."""
    if not _VARIANT.match(variant):
        raise PortableError(f"variant must look like win-x64-avx2, got {variant!r}")
    if epoch < EPOCH:
        raise PortableError("a .zip cannot hold a time before 1980")
    if not chrome_bin.is_dir():
        raise PortableError("the browser folder is not there")
    names = files(chrome_bin)
    problems = source_problems(names)
    if problems:
        raise PortableError("the browser folder may not be packaged: " + "; ".join(problems))
    version = browser_version(names)
    package = dist / FOLDER
    archive = dist / f"thoron-{version}-{variant}-portable.zip"
    for target in (package, archive):
        if target.exists():
            raise PortableError(f"{target.name} is already in the output folder; a package is never overwritten")
    try:
        for name in names:
            _copy(chrome_bin / name, package / BROWSER_DIR / name, epoch)
        for name, text in ((LAUNCHER, LAUNCHER_TEXT), (README, readme_text(version))):
            (package / name).write_bytes(text.encode("ascii"))
            os.utime(package / name, (epoch, epoch))
        problems = launcher_problems(LAUNCHER_TEXT) + audit(package)
        if problems:
            raise PortableError("the package fails its audit: " + "; ".join(problems))
        if zipped:
            write_zip(package, archive, epoch)
            with zipfile.ZipFile(archive) as z:
                packed = {i.filename: i.file_size for i in z.infolist()}
            if packed != {f"{FOLDER}/{n}": (package / n).stat().st_size for n in files(package)}:
                raise PortableError("the .zip does not hold the package's files")
    except (PortableError, OSError):
        shutil.rmtree(package, ignore_errors=True)
        archive.unlink(missing_ok=True)
        raise
    return {"version": version, "package": package, "files": len(names) + 2, "zip": archive if zipped else None}


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--chrome-bin", type=Path, required=True, help="the build's Chrome-bin folder")
    b.add_argument("--dist", type=Path, required=True, help="where the package is written")
    b.add_argument("--variant", required=True, help="such as win-x64-avx2")
    b.add_argument("--epoch", type=int, default=EPOCH, help="the time every file gets, in seconds since 1970 (UTC)")
    b.add_argument("--no-zip", action="store_true")
    a_ = sub.add_parser("audit")
    a_.add_argument("--package", type=Path, required=True, help="a ThoronPortable folder")
    a = p.parse_args(argv)
    try:
        if a.cmd == "audit":
            problems = audit(a.package) if a.package.is_dir() else ["the package folder is not there"]
            for problem in problems:
                print(f"portable: {problem}", file=sys.stderr)
            print(f"portable audit: {'OK' if not problems else f'{len(problems)} problem(s)'}")
            return 1 if problems else 0
        made = build(a.chrome_bin, a.dist, a.variant, a.epoch, not a.no_zip)
    except (PortableError, OSError) as e:
        print(f"portable: {e}", file=sys.stderr)
        return 2
    print(f"portable: {FOLDER} ({made['files']} files, Thoron {made['version']})")
    if made["zip"]:
        print(f"portable: {made['zip'].name} ({made['zip'].stat().st_size} bytes, sha256 {sha256(made['zip'])})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
