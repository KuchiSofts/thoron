#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""The key ceremony (ROADMAP P2.11, docs/release/KEYS.md) in a Windows Sandbox with no network. The keys exist
unencrypted only inside the Sandbox, which Windows deletes when it shuts down; what comes out is the encrypted
backup and the public halves.

    py -3 -I tools/release/key_ceremony_sandbox.py --out <new folder> [--make-passphrase <new file>]
        [--copy-to <folder>]...

A console window opens in the Sandbox. Type the backup's passphrase there: twice for the backup, once more for the
restore test. Then <out> holds thoron-keys-<date>.thoronkeys and public/, and the Sandbox shuts itself down.
With --make-passphrase nobody types: a random passphrase (39 characters, about 158 bits) is made and written only
to that new file, which only this account may read; it is refused in a git repository or a synchronised folder,
and the Sandbox reads it from a folder it may only read. Keep a copy of it apart from this computer (a password
manager, or paper). --copy-to copies the backup to more places (a cloud folder is fine: it is encrypted) and
checks each copy byte for byte.
Needs Windows Sandbox, this Python with the cryptography package, and Git for Windows (for its GnuPG); the
Sandbox sees them in folders it may only read, and can write only to <out>.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from xml.sax.saxutils import escape

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.release import key_ceremony as kc  # noqa: E402

SANDBOX = Path(r"C:\Windows\System32\WindowsSandbox.exe")
INSIDE = r"C:\Ceremony"
RESULT = "ceremony-result.json"
REPO = Path(__file__).resolve().parents[2]
PASSPHRASE_LETTERS = "abcdefghjkmnpqrstuvwxyz23456789"   # 31, none that looks like another
MODULES = ("tools/__init__.py", "tools/release/__init__.py", "tools/release/key_ceremony.py",
           "tools/release/version.py", "tools/update/__init__.py", "tools/update/manifest.py")

# What runs in the Sandbox. It reads no network (it has none) and writes only to the out folder.
CEREMONY = r'''
import contextlib, getpass, io, json, os, shutil, sys, time, traceback
from pathlib import Path
HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "out"
sys.path[:0] = [str(HERE / "site"), str(HERE)]
os.environ["PATH"] = str(HERE.parent / "git" / "usr" / "bin") + os.pathsep + os.environ.get("PATH", "")
result = {"done": False, "steps": []}
GIVEN = (HERE / "passphrase.txt").is_file()


def save():
    (OUT / "ceremony-result.json").write_text(json.dumps(result, indent=1), encoding="utf-8")


def step(name, *args):
    result["steps"].append(name)
    save()
    print(f"\n== {name}", flush=True)
    if args:
        said = io.StringIO()
        with contextlib.redirect_stderr(said):
            code = kc.main(list(args))
        sys.stderr.write(said.getvalue())
        if code != 0:
            raise SystemExit(f"{name} did not finish: {said.getvalue().strip()[-600:]}")


keys = Path(os.environ["USERPROFILE"]) / "thoron-keys"
try:
    from tools.release import key_ceremony as kc
    if GIVEN:
        secret = (HERE / "passphrase.txt").read_text(encoding="utf-8").strip()
        getpass.getpass = lambda prompt="": secret
        print("The passphrase is read from the file the ceremony was given; nothing is typed.")
    print("Thoron key ceremony. This Sandbox has no network; the keys are made here and only their encrypted backup"
          " and their public halves leave it.")
    step("no network")
    if kc.network_route():
        raise SystemExit("this Sandbox has a network route; nothing was made")
    backup = OUT / f"thoron-keys-{time.strftime('%Y-%m-%d', time.gmtime())}.thoronkeys"
    step("make", "make", "--out", str(keys))
    step("backup", "backup", "--keys", str(keys), "--out", str(backup))
    step("public halves")
    shutil.copytree(keys / "public", OUT / "public")
    step("lock", "lock", "--keys", str(keys))
    if not GIVEN:
        print("\nThe restore test reads the backup back: type the passphrase once more.")
    step("restore-test", "restore-test", "--backup", str(backup), "--public", str(OUT / "public"))
    result.update(done=True, ok=True, backup=backup.name)
except BaseException as exc:
    result.update(done=True, ok=False, error=f"{type(exc).__name__}: {exc}")
    traceback.print_exc()
finally:
    if keys.exists():
        kc.wipe(keys)
    save()
if not GIVEN:
    input("\nThe ceremony is over" + ("" if result.get("ok") else ", and it did NOT finish") +
          ". Press Enter: the Sandbox shuts down and everything in it is deleted. ")
os.system("shutdown /s /f /t 0")
'''


def git_folder() -> Path:
    """Git for Windows' folder: the one whose usr\\bin holds gpg.exe."""
    found = shutil.which("gpg")
    candidates = ([Path(found).resolve().parents[2]] if found else []) + [Path(r"C:\Program Files\Git")]
    for folder in candidates:
        if (folder / "usr" / "bin" / "gpg.exe").is_file() and (folder / "usr" / "bin" / "msys-2.0.dll").is_file():
            return folder
    raise kc.CeremonyError("Git for Windows is needed (its GnuPG makes the APT key): https://git-scm.com")


def stage(work: Path, passphrase: str | None) -> dict[str, Path]:
    """The Sandbox's folders: what it reads (the ceremony, cryptography, Python, Git) and what it writes."""
    import cryptography
    inside = work / "in"
    for name in MODULES:
        (inside / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / name, inside / name)
    shutil.copytree(Path(cryptography.__file__).parent, inside / "site" / "cryptography",
                    ignore=shutil.ignore_patterns("__pycache__"))
    (inside / "ceremony.py").write_text(CEREMONY, encoding="utf-8", newline="\r\n")
    if passphrase is not None:
        (inside / "passphrase.txt").write_text(passphrase, encoding="utf-8")
    return {"in": inside, "python": Path(sys.base_prefix), "git": git_folder()}


def wsb(read_only: dict[str, Path], out: Path) -> str:
    folders = "".join(
        f"<MappedFolder><HostFolder>{escape(str(host))}</HostFolder><SandboxFolder>{INSIDE}\\{name}</SandboxFolder>"
        f"<ReadOnly>{'false' if name == 'out' else 'true'}</ReadOnly></MappedFolder>"
        for name, host in [*read_only.items(), ("out", out)])
    return ("<Configuration><Networking>Disable</Networking><VGpu>Disable</VGpu><MemoryInMB>4096</MemoryInMB>"
            "<ClipboardRedirection>Disable</ClipboardRedirection><PrinterRedirection>Disable</PrinterRedirection>"
            "<AudioInput>Disable</AudioInput><VideoInput>Disable</VideoInput>"
            f"<MappedFolders>{folders}</MappedFolders><LogonCommand><Command>cmd.exe /c start \"Thoron key "
            f"ceremony\" {INSIDE}\\python\\python.exe -I {INSIDE}\\in\\ceremony.py</Command></LogonCommand>"
            "</Configuration>")


def sandbox_running() -> bool:
    listed = subprocess.run(["tasklist", "/FI", "IMAGENAME eq WindowsSandboxClient.exe"], capture_output=True,
                            text=True).stdout
    return "WindowsSandboxClient.exe" in listed


def read_result(out: Path) -> dict:
    try:
        return json.loads((out / RESULT).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def make_passphrase(path: Path) -> str:
    """A new random passphrase, written only to the new file `path`, which only this account may read."""
    import secrets
    problem = kc.private_place_problem(path.parent)
    if problem:
        raise kc.CeremonyError(problem.replace("private keys", "the passphrase"))
    words = ["".join(secrets.choice(PASSPHRASE_LETTERS) for _ in range(4)) for _ in range(8)]
    passphrase = "-".join(words)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "x", encoding="ascii", newline="\n") as f:
            f.write(passphrase + "\n")
    except FileExistsError:
        raise kc.CeremonyError(f"{path} exists; a passphrase file is never written over") from None
    if sys.platform == "win32":
        import getpass as gp
        subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", f"{gp.getuser()}:F"], capture_output=True,
                       check=True)
    return passphrase


def copy_backup(backup: Path, folders: list[Path]) -> list[Path]:
    """The backup copied into each folder (never over a file), each copy checked byte for byte."""
    import hashlib
    want = hashlib.sha256(backup.read_bytes()).hexdigest()
    copies = []
    for folder in folders:
        folder.mkdir(parents=True, exist_ok=True)
        copy = folder / backup.name
        if copy.exists():
            raise kc.CeremonyError(f"{copy} exists; a backup is never written over a file")
        shutil.copyfile(backup, copy)
        if hashlib.sha256(copy.read_bytes()).hexdigest() != want:
            raise kc.CeremonyError(f"{copy} does not read back as the backup")
        copies.append(copy)
    return copies


def run(out: Path, timeout: float, passphrase: str | None = None) -> dict:
    if not SANDBOX.is_file():
        raise kc.CeremonyError("Windows Sandbox is not turned on (Windows features: Windows Sandbox)")
    if sandbox_running():
        raise kc.CeremonyError("a Windows Sandbox is open; close it first (only one can run)")
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise kc.CeremonyError(f"{out} exists and is not an empty folder")
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="thoron-ceremony-"))
    try:
        config = work / "ceremony.wsb"
        config.write_text(wsb(stage(work, passphrase), out.resolve()), encoding="utf-8")
        subprocess.Popen([str(SANDBOX), str(config)])
        end = time.monotonic() + timeout
        found = read_result(out)
        while time.monotonic() < end and not found.get("done"):
            time.sleep(3)
            found = read_result(out)
        if not found.get("done"):
            found["error"] = f"no end within {timeout:g} s; it got as far as: {(found.get('steps') or ['nothing'])[-1]}"
        grace = time.monotonic() + 90
        while time.monotonic() < grace and sandbox_running():
            time.sleep(3)
        if sandbox_running():     # it shuts itself down; this is the one this run opened (only one can run)
            for name in ("WindowsSandboxClient.exe", "WindowsSandbox.exe"):
                subprocess.run(["taskkill", "/IM", name, "/F"], capture_output=True)
    finally:
        kc.wipe(work)             # the staged passphrase too
    if found.get("ok"):
        info = kc.read_public(out / kc.PUBLIC)
        backup = out / found["backup"]
        if not backup.is_file() or not backup.read_bytes().startswith(kc.MAGIC):
            raise kc.CeremonyError(f"{backup} is not a key backup")
        found["public"] = info
    return found


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", type=Path, required=True, help="a new folder: the encrypted backup and public/")
    p.add_argument("--make-passphrase", type=Path, help="a new file: a random passphrase is made and kept there")
    p.add_argument("--copy-to", type=Path, action="append", default=[], help="another folder for the backup")
    p.add_argument("--timeout", type=float, default=7200, help="seconds to wait for the ceremony")
    a = p.parse_args(argv)
    try:
        passphrase = make_passphrase(a.make_passphrase) if a.make_passphrase else None
        found = run(a.out, a.timeout, passphrase)
        if not found.get("ok"):
            print(f"key ceremony: it did not finish: {found.get('error', 'no reason given')}", file=sys.stderr)
            return 1
        copies = copy_backup(a.out / found["backup"], a.copy_to)
    except kc.CeremonyError as exc:
        print(f"key ceremony: {exc}", file=sys.stderr)
        return 1
    print(f"key ceremony: done. The encrypted backup is {a.out / found['backup']}"
          + "".join(f", and {c}" for c in copies) + f"; the public halves are in {a.out / kc.PUBLIC}.")
    if a.make_passphrase:
        print(f"The passphrase is only in {a.make_passphrase}: keep a copy apart from this computer.")
    elif not copies:
        print("Copy the backup to a second place.")
    print("\n".join(kc.where_they_go(found["public"])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
