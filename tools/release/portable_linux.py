#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""The Linux portable package (ROADMAP P2.9, P3.12): a folder, and a .tar.xz of it, that runs Thoron without
installing, in the same layout as the Windows one (tools/release/portable.py):

    ThoronPortable/
        thoron              the launcher: a POSIX shell script (Linux has no window to hide)
        README.txt
        variant             "linux-x64-avx2", "linux-x64-sse4" or "linux-arm64-armv8" (as update manifests name them) and a line feed
        Application/
            current         the version that starts, and a line feed
            <version>/      the files the .deb installs into /opt/kuchisofts/thoron, as they are
        User Data/          the profile: never in the package, made by the launcher at the first start

The files come from the release's own .deb (read with this module's own `ar` and tar reading, nothing is run), so
the portable copy and the installed one are the same build. The launcher finds the package from its own path
(symbolic links followed), checks the processor against `variant` (avx2 or sse4_2 in /proc/cpuinfo, or an
AArch64 machine) and starts nothing on one the build cannot run on (exit 3), reads `current` (a version and
nothing else, or exit 4), makes `User Data` (or exit 5), keeps the crash reports in it too (Chromium on Linux
puts them beside the default profile otherwise: BREAKPAD_DUMP_LOCATION) and replaces itself with
`Application/<current>/thoron --user-data-dir=<package>/User Data` and its own arguments as it got them: no
argument is read by a shell a second time, so spaces and any letters in the folder's name or the arguments are
kept. It never turns the sandbox off. Where Ubuntu (23.10 and later) lets only programs named in an AppArmor
profile make user namespaces, a portable copy has no profile of its own (only an administrator can install one):
the launcher says so and how, and starts the browser all the same, which then says it cannot sandbox and stops.

    py -3 -I tools/release/portable_linux.py build --deb <thoron-browser_*.deb> --variant linux-x64-avx2 --dist <folder>
        [--updater <out>/thoron_update]
    py -3 -I tools/release/portable_linux.py audit --archive <dist>/thoron-<version>-linux-x64-avx2-portable.tar.xz
"""
from __future__ import annotations

import argparse
import io
import lzma
import re
import shutil
import sys
import tarfile
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.release import elf_check  # noqa: E402

FOLDER = "ThoronPortable"
BROWSER_DIR = "Application"
PROFILE_DIR = "User Data"
LAUNCHER = "thoron"
README = "README.txt"
# installs the folder's Thoron for the current user (P3.10); the launcher of that copy sees the file `per-user`
INSTALLER = "install-for-this-user"
PER_USER = "per-user"
VARIANT_FILE = "variant"
CURRENT = "current"
INSTALLED = "opt/kuchisofts/thoron/"            # where the .deb puts the browser
PROGRAM = "thoron"
UPDATER = "thoron_update"                       # the updater's command line, in the version folder
VARIANTS = {"linux-x64-avx2": "avx2", "linux-x64-sse4": "sse4_2", "linux-arm64-armv8": "aarch64"}
EPOCH = 315532800                               # 1980-01-01 00:00:00 UTC, as the Windows package
_VERSION = re.compile(r"^\d+(\.\d+){3}$")
_DEB_VERSION = re.compile(r"^Version:\s*(\d+(?:\.\d+){3})", re.M)
_PRIVATE = re.compile(r"(?i)(^|/)(user data|local state|preferences|secure preferences|login data|cookies|history|"
                      r"web data|bookmarks|singletonlock|lockfile)(/|$)")

LAUNCHER_TEXT = r"""#!/bin/sh
# Thoron portable (ROADMAP P3.12): starts the version Application/current names, with the profile in this folder.
# Nothing is written outside the folder by this script; the browser keeps its profile in "User Data" beside it.
here=$(dirname -- "$(readlink -f -- "$0")") || exit 1
variant=$(head -n 1 -- "$here/variant" 2>/dev/null)
case "$variant" in
  linux-x64-avx2) need=avx2 ;;
  linux-x64-sse4) need=sse4_2 ;;
  linux-arm64-armv8) need=aarch64 ;;
  *) echo "Thoron: this package names no variant it knows ($variant)." >&2; exit 3 ;;
esac
if [ "$need" = aarch64 ]; then
  [ "$(uname -m)" = aarch64 ] || { echo "Thoron: this package is for ARM64 processors; this one is $(uname -m)." >&2; exit 3; }
else
  [ "$(uname -m)" = x86_64 ] && grep -qw -- "$need" /proc/cpuinfo || {
    echo "Thoron: this package needs a processor with $need ($variant); take the other x64 package." >&2; exit 3; }
fi
current=$(head -n 1 -- "$here/Application/current" 2>/dev/null)
case "$current" in
  ''|*[!0-9.]*) echo "Thoron: Application/current names no version." >&2; exit 4 ;;
esac
program="$here/Application/$current/thoron"
[ -x "$program" ] || { echo "Thoron: $program is not there." >&2; exit 4; }
if [ "$(cat /proc/sys/kernel/apparmor_restrict_unprivileged_userns 2>/dev/null)" = 1 ]; then
  echo "Thoron: this Linux lets only programs with an AppArmor profile use the sandbox. This copy has none;" >&2
  echo "an administrator can add one (README.txt, 'The sandbox'), or install the .deb, which brings its own." >&2
fi
# a copy installed for this user (install-for-this-user): the profile is ~/.config/thoron, as the .deb's
[ ! -f "$here/per-user" ] || exec "$program" "$@"
mkdir -p -- "$here/User Data" || { echo "Thoron: cannot make the profile folder in $here." >&2; exit 5; }
# Chromium on Linux keeps its crash reports beside the default profile (~/.config/thoron) whatever the profile
# folder; this keeps them in the package's own.
BREAKPAD_DUMP_LOCATION="$here/User Data/Crash Reports"
export BREAKPAD_DUMP_LOCATION
# a copy locked with a passphrase (ROADMAP P4.9): asked for here and handed to the browser on its input, never on its
# command line. The browser stops with 81 for a passphrase that does not open the copy (asked again), 82 when the
# copy cannot be unlocked (said on stderr) and 83 when it was started without what was asked here.
desktop() { [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] && command -v "$1" > /dev/null 2>&1; }
say() {
  echo "Thoron: $1" >&2
  if desktop zenity; then zenity --error --title=Thoron --text="$1" 2> /dev/null
  elif desktop kdialog; then kdialog --title Thoron --error "$1" 2> /dev/null
  fi
}
data="$here/User Data"
# a second start while this copy is open goes to the open browser, which needs no passphrase
lock=$(readlink -- "$data/SingletonLock" 2>/dev/null)
if [ -n "$lock" ] && [ "${lock%-*}" = "$(uname -n)" ] && kill -0 "${lock##*-}" 2>/dev/null; then
  exec "$program" --user-data-dir="$data" "$@"
fi
if [ ! -f "$data/Thoron Portable Key" ]; then
  if grep -q '"thoron_portable":{[^}]*"locked":true' "$data/Local State" 2>/dev/null; then
    text="This copy was locked with a passphrase, and its key file \"Thoron Portable Key\" is missing. Put it back from a backup of this copy, or start Thoron without its saved passwords and sign-ins."
    if desktop zenity; then
      zenity --question --title=Thoron --text="$text" --ok-label="Start without them" --cancel-label=Quit 2> /dev/null || exit 0
    elif desktop kdialog; then
      kdialog --title Thoron --yesno "$text" --yes-label "Start without them" --no-label Quit 2> /dev/null || exit 0
    else
      say "$text Start it with --thoron-portable-start-without-key to do without them."
      exit 82
    fi
    exec "$program" --user-data-dir="$data" --thoron-portable-start-without-key "$@"
  fi
  exec "$program" --user-data-dir="$data" "$@"
fi
ask() {
  prompt="This copy of Thoron is locked. Type its passphrase, or its recovery key:"
  if desktop zenity; then
    zenity --entry --hide-text --title=Thoron --text="$prompt" 2> /dev/null
  elif desktop kdialog; then
    kdialog --title Thoron --password "$prompt" 2> /dev/null
  elif [ -t 0 ]; then
    printf '%s ' "$prompt" >&2
    stty -echo 2> /dev/null; IFS= read -r typed; stty echo 2> /dev/null; printf '\n' >&2
    printf '%s' "$typed"
  else
    echo "Thoron: this copy is locked; start it from a desktop or a terminal to type its passphrase." >&2
    return 1
  fi
}
# first without a question: a PC remembered in this user's keyring opens the copy, and 83 means the passphrase is
# needed
"$program" --user-data-dir="$data" "$@" < /dev/null
rc=$?
tries=0
while [ "$rc" = 83 ] || [ "$rc" = 81 ]; do
  if [ "$rc" = 81 ]; then
    tries=$((tries + 1))
    echo "Thoron: that passphrase does not open this copy." >&2
    [ "$tries" -lt 5 ] || { say "that passphrase does not open this copy."; exit 81; }
  fi
  secret=$(ask) || exit 0
  # printf is built into the shell, so what was typed is in no process's command line
  printf 'passphrase\n%s' "$secret" | "$program" --user-data-dir="$data" --thoron-portable-secret-fd=0 "$@"
  rc=$?
  secret=
done
if [ "$rc" = 82 ]; then
  why=$(head -c 2000 -- "$data/Thoron Unlock Problem" 2>/dev/null)
  rm -f -- "$data/Thoron Unlock Problem"
  say "${why:-this copy cannot be unlocked.}"
fi
exit "$rc"
"""


INSTALLER_TEXT = r"""#!/bin/sh
# Thoron (ROADMAP P3.10, design 7.5a): installs this folder's Thoron for the current user only, with no
# administrator rights: the program into ~/.local/share/thoron (the profile is ~/.config/thoron, as the .deb's), a
# menu entry, and a systemd user timer with which Thoron looks for an update once a day while it is closed.
#   ./install-for-this-user           install, or put this folder's version in place of an earlier install's
#   ./install-for-this-user --remove  remove the program, the menu entry and the timer; the profile stays
set -eu
here=$(dirname -- "$(readlink -f -- "$0")")
data=${XDG_DATA_HOME:-$HOME/.local/share}
config=${XDG_CONFIG_HOME:-$HOME/.config}
dest="$data/thoron"
units="$config/systemd/user"
desktop="$data/applications/thoron-user.desktop"
if [ "${1:-}" = --remove ]; then
  systemctl --user disable --now thoron-update.timer > /dev/null 2>&1 || true
  rm -f -- "$units/thoron-update.timer" "$units/thoron-update.service" "$desktop" \
    "$data/systemd/timers/stamp-thoron-update.timer"
  systemctl --user daemon-reload > /dev/null 2>&1 || true
  rm -rf -- "$dest"
  echo "Thoron is removed for this user; the profile stays in $config/thoron."
  exit 0
fi
[ "$here" != "$dest" ] || { echo "Thoron: this is the installed copy; run the file of a new folder." >&2; exit 2; }
current=$(head -n 1 -- "$here/Application/current")
[ -x "$here/Application/$current/thoron" ] || { echo "Thoron: $here holds no program to install." >&2; exit 4; }
mkdir -p -- "$dest" "$units" "$data/applications"
# the program and its versions, never a profile: a portable folder's "User Data" stays where it is
rm -rf -- "$dest/Application.new"
cp -a -- "$here/Application" "$dest/Application.new"
rm -rf -- "$dest/Application.old"
[ ! -d "$dest/Application" ] || mv -- "$dest/Application" "$dest/Application.old"
mv -- "$dest/Application.new" "$dest/Application"
rm -rf -- "$dest/Application.old"
for f in thoron variant README.txt install-for-this-user; do cp -- "$here/$f" "$dest/$f"; done
: > "$dest/per-user"
icon="$dest/Application/$current/product_logo_256.png"
[ -f "$icon" ] || icon=thoron
cat > "$desktop" <<DESKTOP
[Desktop Entry]
Version=1.0
Type=Application
Name=Thoron
GenericName=Web Browser
Exec="$dest/thoron" %U
Icon=$icon
Terminal=false
Categories=Network;WebBrowser;
MimeType=text/html;x-scheme-handler/http;x-scheme-handler/https;
StartupWMClass=thoron
DESKTOP
cat > "$units/thoron-update.service" <<SERVICE
[Unit]
Description=Thoron looks for an update (the copy installed for this user)

[Service]
Type=oneshot
ExecStart="$dest/thoron" --headless=new --no-first-run --user-data-dir="$dest/Update/scheduled" --thoron-scheduled-update
Nice=10
SERVICE
cat > "$units/thoron-update.timer" <<TIMER
[Unit]
Description=Thoron looks for an update once a day

[Timer]
OnCalendar=daily
RandomizedDelaySec=1h
Persistent=true

[Install]
WantedBy=timers.target
TIMER
if systemctl --user daemon-reload > /dev/null 2>&1 && systemctl --user enable --now thoron-update.timer > /dev/null 2>&1; then
  echo "Thoron is installed for $(id -un) in $dest, and looks for updates once a day."
else
  echo "Thoron is installed for $(id -un) in $dest; this system has no systemd user manager, so it looks for"
  echo "updates only while it runs."
fi
"""


class PackageError(ValueError):
    pass


def tar_name(version: str, variant: str) -> str:
    return f"thoron-{version}-{variant}-portable.tar.xz"


def readme_text(version: str, variant: str) -> str:
    return f"""Thoron {version} portable for Linux ({variant})

Start it with the `thoron` file in this folder (from a terminal: ./thoron, or open it from your file manager).
Your profile is kept in the "User Data" folder beside it, which the first start makes. Move or copy the whole
folder to take Thoron with you; nothing is installed and nothing is written outside the folder by the package.

The sandbox
Ubuntu 23.10 and later let only programs named in an AppArmor profile use the user namespaces Chromium's
sandbox needs. A portable copy has no profile of its own, so on such a system Thoron says it cannot sandbox and
stops; it never runs without the sandbox. An administrator can allow this folder's program with a profile like
the one the .deb installs (/etc/apparmor.d/thoron-browser), with the path of Application/{version}/thoron,
then `sudo apparmor_parser -r <that file>`. Or install the .deb, which brings it.

Variants: linux-x64-avx2 needs a processor with AVX2 (most from 2013 on); linux-x64-sse4 runs on older x64
ones; linux-arm64-armv8 on 64-bit ARM. The launcher says so and starts nothing on a processor the package cannot run.

For this user only
`./install-for-this-user` puts this version into ~/.local/share/thoron with a menu entry and a systemd user
timer, with which Thoron looks for an update once a day while it is closed; no administrator rights are
needed (but for the sandbox above). That copy keeps its profile in ~/.config/thoron, as the .deb does, and
`~/.local/share/thoron/install-for-this-user --remove` takes it away again; the profile stays.

A passphrase
chrome://thoron-portable locks this copy's saved passwords and cookies with a passphrase, with a recovery key
to write down. From the next start the `thoron` file asks for it (a desktop dialog with zenity or kdialog, or in
the terminal) and hands it to Thoron on its input, never on its command line; a PC remembered in the desktop's
keyring ("Remember this PC" on that page) is not asked. The first start after the lock
encrypts the saved passwords and cookies again with the copy's own key, after a checked copy of each database,
which is wiped once every value reads back. Keep the file "User Data/Thoron Portable Key" with the copy and in
its backups: without it and without the passphrase they cannot be opened.
"""


def deb_version(control: bytes) -> str:
    found = _DEB_VERSION.search(control.decode("utf-8", "replace"))
    if not found:
        raise PackageError("the .deb's control file names no version of the form a.b.c.d")
    return found.group(1)


def read_deb(deb: Path) -> tuple[str, list[tuple[tarfile.TarInfo, bytes | None]]]:
    """The .deb's version and its entries under /opt/kuchisofts/thoron (files with their bytes, links and
    folders with none)."""
    version, entries = None, []
    for name, member in elf_check._ar_members(deb.read_bytes()):
        if name.startswith("control.tar"):
            raw = lzma.decompress(member) if name.endswith(".xz") else member
            with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz" if name.endswith(".gz") else "r:") as tar:
                for item in tar:
                    if item.name.lstrip("./") == "control" and item.isfile():
                        version = deb_version(tar.extractfile(item).read())
        elif name.startswith("data.tar"):
            if name.endswith(".zst"):
                raise PackageError("data.tar.zst: this reader takes xz, gzip or plain tar")
            raw = lzma.decompress(member) if name.endswith(".xz") else member
            with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz" if name.endswith(".gz") else "r:") as tar:
                for item in tar:
                    path = item.name.lstrip("./")
                    if path.startswith(INSTALLED) and path != INSTALLED.rstrip("/"):
                        data = tar.extractfile(item).read() if item.isfile() else None
                        entries.append((item, data))
    if not version:
        raise PackageError("the .deb has no control file with a version")
    if not entries:
        raise PackageError(f"the .deb installs nothing into /{INSTALLED}")
    return version, entries


def build(deb: Path, dist: Path, variant: str, epoch: int = EPOCH, updater: Path | None = None) -> Path:
    if variant not in VARIANTS:
        raise PackageError(f"unknown variant {variant!r}")
    version, entries = read_deb(deb)
    names = [item.name.lstrip("./")[len(INSTALLED):] for item, _ in entries]
    if PROGRAM not in names:
        raise PackageError(f"the .deb has no /{INSTALLED}{PROGRAM}")
    dist.mkdir(parents=True, exist_ok=True)
    archive = dist / tar_name(version, variant)
    if updater is not None and not updater.is_file():
        raise PackageError(f"no updater at {updater}")
    top = [(LAUNCHER, LAUNCHER_TEXT.encode(), 0o755), (INSTALLER, INSTALLER_TEXT.encode(), 0o755),
           (README, readme_text(version, variant).encode(), 0o644),
           (VARIANT_FILE, f"{variant}\n".encode(), 0o644),
           (f"{BROWSER_DIR}/{CURRENT}", f"{version}\n".encode(), 0o644)]
    with lzma.open(archive, "wb", preset=9) as xz, tarfile.open(fileobj=xz, mode="w", format=tarfile.PAX_FORMAT) as tar:
        def add_dir(path: str) -> None:
            info = tarfile.TarInfo(path)
            info.type, info.mode, info.mtime = tarfile.DIRTYPE, 0o755, epoch
            tar.addfile(info)
        for path in (FOLDER, f"{FOLDER}/{BROWSER_DIR}", f"{FOLDER}/{BROWSER_DIR}/{version}"):
            add_dir(path)
        for name, data, mode in top:
            info = tarfile.TarInfo(f"{FOLDER}/{name}")
            info.size, info.mode, info.mtime = len(data), mode, epoch
            tar.addfile(info, io.BytesIO(data))
        for (item, data), name in sorted(zip(entries, names), key=lambda pair: pair[1]):
            info = tarfile.TarInfo(f"{FOLDER}/{BROWSER_DIR}/{version}/{name.rstrip('/')}")
            info.mtime, info.uid, info.gid, info.uname, info.gname = epoch, 0, 0, "", ""
            info.mode = item.mode & 0o755                       # no set-user-id bit: a portable copy has no root
            if item.isdir():
                info.type = tarfile.DIRTYPE
                tar.addfile(info)
            elif item.issym():
                info.type, info.linkname = tarfile.SYMTYPE, item.linkname
                tar.addfile(info)
            elif item.isfile():
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        if updater is not None:
            # Thoron's own updater lives in the version folder, as in the Windows package (swap.h)
            data = updater.read_bytes()
            info = tarfile.TarInfo(f"{FOLDER}/{BROWSER_DIR}/{version}/{UPDATER}")
            info.size, info.mode, info.mtime = len(data), 0o755, epoch
            tar.addfile(info, io.BytesIO(data))
    problems = audit(archive, variant)
    if problems:
        archive.unlink()
        raise PackageError("; ".join(problems))
    return archive


def audit(archive: Path, variant: str | None = None) -> list[str]:
    """What is wrong with a portable .tar.xz (empty when it is fine)."""
    problems = []
    with tarfile.open(archive, "r:xz") as tar:
        items = {item.name: item for item in tar}
        def text(name: str) -> str:
            item = items.get(f"{FOLDER}/{name}")
            return tar.extractfile(item).read().decode("utf-8", "replace") if item and item.isfile() else ""
        current = text(f"{BROWSER_DIR}/{CURRENT}").strip()
        named = text(VARIANT_FILE).strip()
        launcher = items.get(f"{FOLDER}/{LAUNCHER}")
        program = items.get(f"{FOLDER}/{BROWSER_DIR}/{current}/{PROGRAM}")
        for name, item in items.items():
            if not name.startswith(f"{FOLDER}/") and name != FOLDER:
                problems.append(f"outside the package folder: {name}")
            if _PRIVATE.search(name[len(FOLDER):]):
                problems.append(f"a profile's file in the package: {name}")
            if item.mode & 0o6000:
                problems.append(f"a set-user-id or set-group-id file: {name}")
            if item.issym() and (item.linkname.startswith("/") or ".." in item.linkname.split("/")):
                problems.append(f"a link that leads out of the package: {name} -> {item.linkname}")
        if not _VERSION.match(current):
            problems.append(f"Application/current names no version: {current!r}")
        if named not in VARIANTS or (variant and named != variant):
            problems.append(f"the variant file says {named!r}" + (f", not {variant}" if variant else ""))
        if not launcher or not launcher.isfile() or not launcher.mode & 0o100:
            problems.append("the launcher is missing or cannot be run")
        elif tar.extractfile(launcher).read().decode() != LAUNCHER_TEXT:
            problems.append("the launcher is not this tool's")
        installer = items.get(f"{FOLDER}/{INSTALLER}")
        if not installer or not installer.isfile() or not installer.mode & 0o100:
            problems.append(f"{INSTALLER} is missing or cannot be run")
        elif tar.extractfile(installer).read().decode() != INSTALLER_TEXT:
            problems.append(f"{INSTALLER} is not this tool's")
        if f"{FOLDER}/{PER_USER}" in items:
            problems.append(f"the package holds the mark {PER_USER} of an installed copy")
        if not program or not program.isfile() or not program.mode & 0o100:
            problems.append(f"the program Application/{current}/{PROGRAM} is missing or cannot be run")
        if f"{FOLDER}/{PROFILE_DIR}" in items:
            problems.append("the package holds a profile folder")
        if named in VARIANTS:
            elves = [(n, tar.extractfile(i).read()) for n, i in items.items() if i.isfile() and i.size >= 64]
            elf_problems, count = elf_check.check(
                [(n.replace(f"{FOLDER}/{BROWSER_DIR}/{current}/", elf_check.PROGRAM.rsplit("/", 1)[0] + "/"), d)
                 for n, d in elves], "linux-arm64" if named == "linux-arm64-armv8" else "linux-x64")
            problems += elf_problems
    return problems


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build")
    b.add_argument("--deb", type=Path, required=True)
    b.add_argument("--variant", choices=sorted(VARIANTS), required=True)
    b.add_argument("--dist", type=Path, required=True)
    b.add_argument("--updater", type=Path, help="the build's thoron_update, put beside the program (P3.12)")
    au = sub.add_parser("audit")
    au.add_argument("--archive", type=Path, required=True)
    au.add_argument("--variant", choices=sorted(VARIANTS))
    a = p.parse_args(argv)
    try:
        if a.command == "build":
            archive = build(a.deb, a.dist, a.variant, updater=a.updater)
            print(f"wrote {archive} ({archive.stat().st_size} bytes)")
            return 0
        problems = audit(a.archive, a.variant)
    except (PackageError, OSError, tarfile.TarError, lzma.LZMAError, elf_check.ElfError) as exc:
        print(f"PORTABLE (Linux): {exc}")
        return 1
    for problem in problems:
        print(f"  {problem}")
    print(f"PORTABLE (Linux): {'PASSED' if not problems else f'FAILED ({len(problems)} problem(s))'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
