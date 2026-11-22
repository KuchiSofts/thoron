#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Authenticode signatures of Thoron's Windows programs and libraries (ROADMAP S.8). Windows only.

    sign    every .exe and .dll given (files, or folders taken whole) is signed with signtool: the code signing
            certificate is picked from the Windows certificate store by its SHA-1 thumbprint (so its private key
            stays in the store or on the hardware token its issuer requires, never in a file or on a command
            line), with SHA-256 digests and an RFC 3161 timestamp from the given server, so the signature stays
            valid after the certificate expires; then every file is checked as below
    check   every .exe and .dll is Authenticode-signed, Windows trusts the signature (its status is Valid) and it
            carries a timestamp

The release (tools/release/release.py prepare --authenticode-command) and the installer's archive step
(chrome/tools/build/win/create_installer_archive.py, the GN argument thoron_authenticode_command_file) run the
`sign` command a person writes once, as a JSON list in a file:

    ["py", "-3", "-I", "C:/thoron/tools/release/authenticode.py", "sign", "--thumbprint", "<SHA-1>",
     "--timestamp", "<RFC 3161 URL of the certificate's issuer>"]

to which the files to sign are appended.

    py -3 -I tools/release/authenticode.py sign --thumbprint <SHA-1> --timestamp <URL> [--signtool <signtool.exe>]
        [--description Thoron] <file or folder> ...
    py -3 -I tools/release/authenticode.py check <file or folder> ...
Exit status 0 when every file is signed and checks.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SUFFIXES = (".exe", ".dll")
BATCH = 50                     # files per signtool call (a command line has a length limit)
_THUMBPRINT = re.compile(r"^[0-9A-Fa-f]{40}$")
_TIMESTAMP = re.compile(r"^https?://[^\s\"']+$")
SDK_BIN = Path(r"C:\Program Files (x86)\Windows Kits\10\bin")

# One PowerShell call reads every file's signature: its status, whether a timestamp countersigns it, its signer.
CHECK_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
foreach ($f in (Get-Content -LiteralPath $args[0] -Encoding UTF8)) {
  if (-not $f) { continue }
  $s = Get-AuthenticodeSignature -LiteralPath $f
  [pscustomobject]@{ path = [string]$f; status = [string]$s.Status; timestamped = [bool]$s.TimeStamperCertificate;
                     signer = [string]$s.SignerCertificate.Subject } | ConvertTo-Json -Compress
}
"""


class SigningError(RuntimeError):
    pass


def files_of(paths: list[Path]) -> list[Path]:
    """Every .exe and .dll of `paths`: a folder whole (recursively), a file as it is."""
    found: list[Path] = []
    for path in paths:
        if path.is_dir():
            found += sorted(p for p in path.rglob("*") if p.is_file() and p.suffix.lower() in SUFFIXES)
        elif path.is_file():
            if path.suffix.lower() not in SUFFIXES:
                raise SigningError(f"{path.name}: not a program or library (.exe, .dll)")
            found.append(path)
        else:
            raise SigningError(f"{path}: not there")
    return found


def find_signtool() -> Path | None:
    """The newest x64 signtool.exe of the Windows SDK, or None."""
    def version(folder: Path) -> tuple[int, ...]:
        return tuple(int(p) for p in folder.name.split(".") if p.isdigit())
    candidates = [d / "x64" / "signtool.exe" for d in SDK_BIN.glob("10.*") if (d / "x64" / "signtool.exe").is_file()]
    return max(candidates, key=lambda p: version(p.parent.parent)) if candidates else None


def sign_commands(signtool: Path, thumbprint: str, timestamp: str, description: str,
                  files: list[Path]) -> list[list[str]]:
    """signtool's command lines for `files`, in batches."""
    if not _THUMBPRINT.match(thumbprint):
        raise SigningError("the thumbprint is the certificate's SHA-1: 40 hexadecimal characters")
    if not _TIMESTAMP.match(timestamp):
        raise SigningError("the timestamp server is an http or https address (RFC 3161, the issuer's)")
    head = [str(signtool), "sign", "/sha1", thumbprint.upper(), "/fd", "sha256", "/tr", timestamp, "/td", "sha256",
            "/d", description]
    return [head + [str(f) for f in files[i:i + BATCH]] for i in range(0, len(files), BATCH)]


def check(files: list[Path], run=subprocess.run) -> dict[Path, str]:
    """The problem of each file that is not signed, not trusted or not timestamped; empty when all are."""
    if not files:
        return {}
    with tempfile.TemporaryDirectory() as tmp:
        listing = Path(tmp) / "files.txt"
        listing.write_text("\n".join(str(f) for f in files), encoding="utf-8")
        script = Path(tmp) / "check.ps1"
        script.write_text(CHECK_SCRIPT, encoding="utf-8-sig")
        done = run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script),
                    str(listing)], capture_output=True, text=True, timeout=1800)
    seen: dict[str, dict] = {}
    for line in (done.stdout or "").splitlines():
        line = line.strip()
        if line.startswith("{"):
            entry = json.loads(line)
            seen[os.path.normcase(entry["path"])] = entry
    problems: dict[Path, str] = {}
    for f in files:
        entry = seen.get(os.path.normcase(str(f)))
        if entry is None:
            problems[f] = f"its signature could not be read ({(done.stderr or '').strip()[:200]})"
        elif entry["status"] != "Valid":
            problems[f] = f"not signed as Windows trusts it ({entry['status']})"
        elif not entry["timestamped"]:
            problems[f] = f"signed by {entry['signer']} but without a timestamp"
    return problems


def sign(files: list[Path], thumbprint: str, timestamp: str, signtool: Path | None = None,
         description: str = "Thoron", run=subprocess.run) -> None:
    """Signs `files`, then checks them; raises SigningError on any problem."""
    tool = signtool or find_signtool()
    if tool is None:
        raise SigningError("no signtool.exe: install the Windows SDK's signing tools, or give --signtool")
    for command in sign_commands(tool, thumbprint, timestamp, description, files):
        done = run(command, capture_output=True, text=True, timeout=3600)
        if done.returncode != 0:
            raise SigningError(f"signtool stopped with {done.returncode}: "
                               f"{((done.stdout or '') + (done.stderr or '')).strip()[-600:]}")
    problems = check(files, run)
    if problems:
        raise SigningError("; ".join(f"{p.name}: {why}" for p, why in problems.items()))


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="action", required=True)
    s = sub.add_parser("sign")
    s.add_argument("--thumbprint", required=True)
    s.add_argument("--timestamp", required=True)
    s.add_argument("--signtool", type=Path)
    s.add_argument("--description", default="Thoron")
    s.add_argument("paths", nargs="+", type=Path)
    c = sub.add_parser("check")
    c.add_argument("paths", nargs="+", type=Path)
    a = p.parse_args(argv)
    sys.stdout.reconfigure(errors="backslashreplace")
    try:
        files = files_of(a.paths)
        if not files:
            raise SigningError("no .exe or .dll to sign")
        if a.action == "sign":
            sign(files, a.thumbprint, a.timestamp, a.signtool, a.description)
            print(f"authenticode: {len(files)} file(s) signed, timestamped and checked")
            return 0
        problems = check(files)
    except SigningError as exc:
        print(f"authenticode: {exc}", file=sys.stderr)
        return 1
    for path, why in problems.items():
        print(f"NOT SIGNED  {path}: {why}")
    print(f"authenticode: {len(files) - len(problems)} of {len(files)} file(s) signed and timestamped")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
