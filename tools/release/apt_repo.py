#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Thoron's signed APT repository (ROADMAP P2.10, design 7.5a): a flat repository in one rolling release.

A Chromium-based `.deb` is over 100 MB, more than a GitHub Pages site or a git repository may hold, so the
repository is a *flat* one (`docs/release/APT.md`): its index (`Packages`, `Packages.gz`), its `Release`, the
signed `InRelease` and the detached `Release.gpg` sit beside the packages as the assets of one release that is
replaced at each version (tag `apt`), and apt fetches them from

    https://github.com/<owner>/<repo>/releases/download/apt/InRelease

(the source names `.../releases/download/` and the suite `apt/`, so no request holds a `./`, which a strict
server refuses; the packages' paths in the index are `apt/<file>`), following GitHub's redirect to its file
host. apt checks `InRelease` against the keyring named in the source
(`Signed-By`), and every package against the hashes in the signed index; `Valid-Until` stops an old index from
being served again for good (a replay).

Two x64 builds share one architecture (amd64), so the SSE4.2 build is the package `thoron-browser-sse4`, and the
AVX2 build `thoron-browser`; each conflicts with the other, so `apt upgrade` never swaps one for the other (the
AVX2 build would stop on a processor without AVX2). `variant_deb()` writes the release's own `.deb` that way.

    py -3 -I tools/release/apt_repo.py build --deb <thoron-...-linux-x64-avx2.deb> --deb <...-sse4.deb>
        --deb <...-arm64-armv8.deb> --out <folder> --gnupg-home <dir> --key <fingerprint> [--valid-days 30]
    py -3 -I tools/release/apt_repo.py resign --repo <folder> --gnupg-home <dir> --key <fingerprint>
        (the same packages signed again, before the index's Valid-Until passes)
    py -3 -I tools/release/apt_repo.py sources --repo KuchiSofts/thoron     (the person's .sources file)
The signing key is the owner's APT key (P2.11); a test makes a throwaway one.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import io
import lzma
import subprocess
import sys
import tarfile
from pathlib import Path

if __package__ in (None, ""):  # running as a script: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.release import elf_check  # noqa: E402

PACKAGE = "thoron-browser"
SSE4_PACKAGE = "thoron-browser-sse4"
TAG = "apt"
KEYRING = "thoron-archive-keyring.gpg"
KEYRING_PATH = "/usr/share/keyrings/" + KEYRING
DEFAULT_VALID_DAYS = 30
# variant -> package name (tools/release/release.py's variants)
PACKAGES = {"linux-x64-avx2": PACKAGE, "linux-x64-sse4": SSE4_PACKAGE, "linux-arm64-armv8": PACKAGE}
INDEX_FILES = ("Packages", "Packages.gz")


class AptError(Exception):
    pass


# ----- the .deb (an ar archive: debian-binary, control.tar.*, data.tar.*) ------------------------------------

def _ar(members: list[tuple[str, bytes]], mtime: int) -> bytes:
    out = bytearray(b"!<arch>\n")
    for name, data in members:
        header = (f"{name:<16}{mtime:<12}{0:<6}{0:<6}{'100644':<8}{len(data):<10}`\n").encode("ascii")
        assert len(header) == 60
        out += header + data + (b"\n" if len(data) % 2 else b"")
    return bytes(out)


def _control_tar(member_name: str, data: bytes) -> tarfile.TarFile:
    raw = lzma.decompress(data) if member_name.endswith(".xz") else gzip.decompress(data) \
        if member_name.endswith(".gz") else data
    if member_name.endswith(".zst"):
        raise AptError("control.tar.zst: this tool reads xz, gzip or plain tar")
    return tarfile.open(fileobj=io.BytesIO(raw), mode="r:")


def parse_fields(text: str) -> list[tuple[str, str]]:
    """A control stanza as (field, value) in order; a value's continuation lines are kept as they are."""
    fields: list[tuple[str, str]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        if line[0] in " \t" and fields:
            name, value = fields[-1]
            fields[-1] = (name, value + "\n" + line)
        elif ":" in line:
            name, value = line.split(":", 1)
            fields.append((name.strip(), value.strip()))
        else:
            raise AptError(f"a control line that is not a field: {line[:60]!r}")
    return fields


def format_fields(fields: list[tuple[str, str]]) -> str:
    return "".join(f"{name}: {value}\n" for name, value in fields)


def control_of(deb: bytes) -> list[tuple[str, str]]:
    for name, member in elf_check._ar_members(deb):
        if name.startswith("control.tar"):
            with _control_tar(name, member) as tar:
                for item in tar:
                    if item.isfile() and item.name.lstrip("./") == "control":
                        return parse_fields(tar.extractfile(item).read().decode("utf-8"))
    raise AptError("the .deb has no control file")


def _relations(value: str, add: list[str]) -> str:
    have = [part.strip() for part in value.split(",") if part.strip()]
    for name in add:
        if not any(part.split()[0] == name for part in have):
            have.append(name)
    return ", ".join(have)


def variant_deb(deb: bytes, variant: str) -> bytes:
    """The .deb as the release publishes it: the package named for its variant, conflicting with (and replacing)
    the other x64 build. Only the control file changes; the program files are byte for byte the build's."""
    if variant not in PACKAGES:
        raise AptError(f"no package name for the variant {variant!r}")
    name = PACKAGES[variant]
    # the two x64 builds exclude each other; the ARM64 one is of another architecture
    others = [] if variant == "linux-arm64-armv8" else [SSE4_PACKAGE if name == PACKAGE else PACKAGE]
    members = list(elf_check._ar_members(deb))
    if [m[0] for m in members][:1] != ["debian-binary"] or len(members) != 3:
        raise AptError("not a .deb of three members (debian-binary, control.tar, data.tar)")
    fields = dict(control_of(deb))
    if fields.get("Package") == name and all(
            any(part.split()[0] == other for part in fields.get(rel, "").split(",") if part.strip())
            for other in others for rel in ("Conflicts", "Replaces")):
        return deb  # the release's own .deb, named already: the same file in the release and the repository
    out = []
    for member_name, data in members:
        if member_name.startswith("control.tar"):
            with _control_tar(member_name, data) as tar:
                items = [(item, tar.extractfile(item).read() if item.isfile() else None) for item in tar]
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w", format=tarfile.GNU_FORMAT) as new:
                for item, content in items:
                    if item.isfile() and item.name.lstrip("./") == "control":
                        fields = []
                        for field, value in parse_fields(content.decode("utf-8")):
                            if field == "Package":
                                value = name
                            elif field in ("Conflicts", "Replaces"):
                                value = _relations(value, others)
                            fields.append((field, value))
                        for field in ("Conflicts", "Replaces"):
                            if others and not any(f == field for f, _ in fields):
                                fields.append((field, ", ".join(others)))
                        content = format_fields(fields).encode("utf-8")
                        item.size = len(content)
                    new.addfile(item, io.BytesIO(content) if content is not None else None)
            data = lzma.compress(buf.getvalue(), preset=9)
            member_name = "control.tar.xz"
        out.append((member_name, data))
    mtime = int(dt.datetime.now(dt.timezone.utc).timestamp())
    return _ar(out, mtime)


def deb_name(fields: list[tuple[str, str]]) -> str:
    f = dict(fields)
    return f"{f['Package']}_{f['Version']}_{f['Architecture']}.deb"


# ----- the repository's index and its Release ----------------------------------------------------------------

def packages_stanza(deb: bytes, filename: str) -> str:
    fields = [(n, v) for n, v in control_of(deb) if n not in ("Filename", "Size", "MD5sum", "SHA256", "SHA512")]
    fields += [("Filename", f"{TAG}/{filename}"), ("Size", str(len(deb))),
               ("SHA256", hashlib.sha256(deb).hexdigest()), ("SHA512", hashlib.sha512(deb).hexdigest())]
    return format_fields(fields)


def release_text(files: dict[str, bytes], architectures: list[str], now: dt.datetime, valid_days: int) -> str:
    stamp = "%a, %d %b %Y %H:%M:%S UTC"
    # the suite is the folder the source names (`apt/`): apt warns when a flat repository's index names
    # another one, or none
    lines = ["Origin: Thoron", "Label: Thoron", f"Suite: {TAG}/",
             f"Architectures: {' '.join(sorted(set(architectures)))}",
             f"Date: {now.strftime(stamp)}",
             f"Valid-Until: {(now + dt.timedelta(days=valid_days)).strftime(stamp)}",
             "Acquire-By-Hash: no",
             "Description: Thoron, signed by the owner's APT key"]
    for algo, fn in (("SHA256", hashlib.sha256), ("SHA512", hashlib.sha512)):
        lines.append(f"{algo}:")
        lines += [f" {fn(data).hexdigest()} {len(data):>10} {name}" for name, data in sorted(files.items())]
    return "\n".join(lines) + "\n"


def sign(release: bytes, gnupg_home: Path, key: str) -> tuple[bytes, bytes]:
    """InRelease (clear-signed) and Release.gpg (detached, armoured), with gpg and the key in `gnupg_home`."""
    base = ["gpg", "--homedir", str(gnupg_home), "--batch", "--yes", "--no-tty", "--local-user", key,
            "--digest-algo", "SHA512"]
    inrelease = subprocess.run(base + ["--clearsign"], input=release, capture_output=True)
    detached = subprocess.run(base + ["--armor", "--detach-sign"], input=release, capture_output=True)
    for done in (inrelease, detached):
        if done.returncode != 0 or not done.stdout:
            raise AptError(f"gpg could not sign: {done.stderr.decode('utf-8', 'replace')[-300:]}")
    return inrelease.stdout, detached.stdout


def public_keyring(gnupg_home: Path, key: str) -> bytes:
    done = subprocess.run(["gpg", "--homedir", str(gnupg_home), "--batch", "--export", key], capture_output=True)
    if done.returncode != 0 or not done.stdout:
        raise AptError("gpg could not export the public key")
    return done.stdout


def build(debs: list[tuple[Path, str]], out: Path, gnupg_home: Path, key: str,
          valid_days: int = DEFAULT_VALID_DAYS, now: dt.datetime | None = None) -> list[Path]:
    """The repository's files in `out` (empty or missing): the packages named for their variants, the index,
    Release, InRelease, Release.gpg and the public keyring for `Signed-By`."""
    if out.exists() and any(out.iterdir()):
        raise AptError(f"{out} is not empty")
    if not 1 <= valid_days <= 90:
        raise AptError("--valid-days is 1 to 90: an index that never expires can be served again for good")
    out.mkdir(parents=True, exist_ok=True)
    now = now or dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    stanzas, architectures, written, seen = [], [], [], set()
    for path, variant in debs:
        data = variant_deb(path.read_bytes(), variant)
        fields = dict(control_of(data))
        name = deb_name(control_of(data))
        if (fields["Package"], fields["Architecture"]) in seen:
            raise AptError(f"two packages {fields['Package']} for {fields['Architecture']}")
        seen.add((fields["Package"], fields["Architecture"]))
        (out / name).write_bytes(data)
        written.append(out / name)
        stanzas.append(packages_stanza(data, name))
        architectures.append(fields["Architecture"])
    packages = "\n".join(stanzas).encode("utf-8")
    index = {"Packages": packages, "Packages.gz": gzip.compress(packages, mtime=0)}
    release = release_text(index, architectures, now, valid_days).encode("utf-8")
    inrelease, detached = sign(release, gnupg_home, key)
    files = dict(index, Release=release, InRelease=inrelease, **{"Release.gpg": detached})
    files[KEYRING] = public_keyring(gnupg_home, key)
    for name, data in files.items():
        (out / name).write_bytes(data)
        written.append(out / name)
    return written


def resign(folder: Path, gnupg_home: Path, key: str, valid_days: int = DEFAULT_VALID_DAYS,
           now: dt.datetime | None = None) -> list[Path]:
    """A new Release, InRelease and Release.gpg for the repository in `folder`, its packages and index as they
    are: before the index's Valid-Until passes when no new version came (the index is checked against the
    packages first)."""
    if not 1 <= valid_days <= 90:
        raise AptError("--valid-days is 1 to 90")
    packages = (folder / "Packages").read_bytes()
    if gzip.decompress((folder / "Packages.gz").read_bytes()) != packages:
        raise AptError("Packages.gz is not Packages")
    architectures = []
    for stanza in packages.decode("utf-8").split("\n\n"):
        if not stanza.strip():
            continue
        fields = dict(parse_fields(stanza))
        deb = folder / fields["Filename"].split("/", 1)[-1]
        if not deb.is_file() or hashlib.sha256(deb.read_bytes()).hexdigest() != fields["SHA256"]:
            raise AptError(f"{deb.name} is missing or not the one the index names")
        architectures.append(fields["Architecture"])
    now = now or dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    index = {"Packages": packages, "Packages.gz": (folder / "Packages.gz").read_bytes()}
    release = release_text(index, architectures, now, valid_days).encode("utf-8")
    inrelease, detached = sign(release, gnupg_home, key)
    written = []
    for name, data in (("Release", release), ("InRelease", inrelease), ("Release.gpg", detached),
                       (KEYRING, public_keyring(gnupg_home, key))):
        (folder / name).write_bytes(data)
        written.append(folder / name)
    return written


def sources_text(repo: str) -> str:
    """The person's /etc/apt/sources.list.d/thoron.sources (deb822): the flat repository, its keyring only."""
    return (f"Types: deb\nURIs: https://github.com/{repo}/releases/download/\nSuites: {TAG}/\n"
            f"Signed-By: {KEYRING_PATH}\n")


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build")
    b.add_argument("--deb", type=Path, action="append", required=True,
                   help="a release .deb; its variant is read from its name (thoron-<version>-<variant>.deb)")
    b.add_argument("--out", type=Path, required=True)
    b.add_argument("--gnupg-home", type=Path, required=True)
    b.add_argument("--key", required=True, help="the signing key's fingerprint")
    b.add_argument("--valid-days", type=int, default=DEFAULT_VALID_DAYS)
    r = sub.add_parser("resign", help="sign the same repository again before its index expires")
    r.add_argument("--repo", type=Path, required=True, help="the repository's folder (as build wrote it)")
    r.add_argument("--gnupg-home", type=Path, required=True)
    r.add_argument("--key", required=True)
    r.add_argument("--valid-days", type=int, default=DEFAULT_VALID_DAYS)
    s = sub.add_parser("sources")
    s.add_argument("--repo", required=True)
    a = p.parse_args(argv)
    if a.command == "sources":
        sys.stdout.write(sources_text(a.repo))
        return 0
    if a.command == "resign":
        try:
            for f in resign(a.repo, a.gnupg_home, a.key, a.valid_days):
                print(f.name)
        except (AptError, OSError, KeyError) as e:
            print(f"apt_repo: {e}", file=sys.stderr)
            return 1
        return 0
    debs = []
    for path in a.deb:
        variant = next((v for v in PACKAGES if path.name.endswith(f"-{v}.deb")), None)
        if variant is None:
            print(f"apt_repo: {path.name} names no variant (thoron-<version>-<variant>.deb)", file=sys.stderr)
            return 2
        debs.append((path, variant))
    try:
        for f in build(debs, a.out, a.gnupg_home, a.key, a.valid_days):
            print(f.name)
    except AptError as e:
        print(f"apt_repo: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
