#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""ThoronSetup.exe, the one installer for good, with real programs and offline (ROADMAP P3.19).

The build of ThoronSetup for tests (thoron_setup_for_tests.exe: it trusts only the published test key of the
reference tool and takes its release from a folder) is given releases that the reference tool,
tools/update/manifest.py, makes and signs with that test key. The "installer" of a release is a stand-in
program (any program that ends by itself; thoron_update.exe prints its usage). Then:

    good        the release verifies: the stand-in is downloaded, checked and run (exit 0)
    changed     one byte of the installer differs from what the signed manifest names: it is deleted, never
                run (exit 5)
    forged      the manifest's signature does not hold: nothing is downloaded (exit 2)
    expired     the clock is past the manifest's end: nothing is installed (exit 2)
    processor   on a processor without AVX2 the release, which has an AVX2 installer only, has none for it
                (exit 3); on one without SSE4.2 Thoron cannot run at all (exit 3)
    too old     the release asks for a newer updater than this ThoronSetup (exit 7)
    shipped     (with --shipped) the ThoronSetup.exe that ships holds none of the test build's switches and
                not the test key (tools/release/release.py checks it the same way)

    py -3 -I tools/qa/thoron_setup_check.py --setup <out>\\thoron_setup_for_tests.exe
        --stand-in <out>\\thoron_update.exe --work <scratch dir> [--shipped <out>\\ThoronSetup.exe]
"""
import argparse
import hashlib
import shutil
import subprocess
import sys
import time
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.release import release as rel  # noqa: E402
from tools.update import manifest as mf  # noqa: E402

TEST_KEY_PHRASE = b"thoron-update test vectors: a key for tests only, never a release key"
URL = "https://github.com/KuchiSofts/thoron/releases/download/v0.1.2/"
INSTALLER = "thoron-158.0.8127.4500-win-x64-avx2-installer.exe"


def release(folder: Path, installer: bytes, *, min_updater: str = "158.0.8127.3000", forge: bool = False,
            published: int | None = None) -> None:
    """A release in `folder` as Thoron's releases on GitHub serve it, signed with the test key."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / INSTALLER).write_bytes(installer)
    private = hashlib.sha256(TEST_KEY_PHRASE).digest()
    public = mf.public_key_of(private)
    entry = {"url": URL + INSTALLER, "size": len(installer), "sha256": hashlib.sha256(installer).hexdigest()}
    data = mf.build(channel="stable", version="158.0.8127.4500", thoron_version="0.1.2", critical=False,
                    min_updater_version=min_updater, packages={"win-x64-avx2": {"installed": {"full": entry}}},
                    published=published if published is not None else int(time.time()) - 600,
                    allowed_hosts=("github.com",))
    signature = mf.sign(data, private, public, allowed_hosts=("github.com",),
                        now=published if published is not None else int(time.time()))
    if forge:
        signature = bytes([signature[0] ^ 1]) + signature[1:]
    (folder / "update.json").write_bytes(data)
    (folder / "update.json.sig").write_bytes(signature)


def run_setup(setup: Path, folder: Path, message: Path, *extra: str) -> tuple[int, str]:
    message.unlink(missing_ok=True)
    done = subprocess.run([str(setup), f"--from-folder={folder}", f"--message-file={message}", *extra],
                          timeout=300)
    return done.returncode, message.read_text(encoding="utf-8") if message.exists() else ""


CASES = (
    # name, how the release is made, extra switches, exit wanted, words of the message
    ("good", {}, [], 0, "is installed"),
    ("changed", {"change": True}, [], 5, "is not the installer"),
    ("forged", {"forge": True}, [], 2, "cannot verify the release (bad_signature)"),
    ("expired", {}, [f"--now={int(time.time()) + 200 * 86400}"], 2, "expired"),
    ("processor sse4", {}, ["--assume-cpu=sse4"], 3, "no installer for this computer yet"),
    ("processor old", {}, ["--assume-cpu=old"], 3, "too old for Thoron"),
    ("too old", {"min_updater": "158.0.8127.4500"}, [], 7, "Download Thoron Setup again"),
)


def judge(code: int, said: str, want: int, words: str) -> bool:
    return code == want and words in said


def run(setup: Path, stand_in: Path, work: Path) -> list[str]:
    if work.exists():
        shutil.rmtree(work)
    program = stand_in.read_bytes()
    problems = []
    for name, how, extra, want, words in CASES:
        folder = work / name.replace(" ", "-")
        release(folder, program, min_updater=how.get("min_updater", "158.0.8127.3000"), forge=how.get("forge", False))
        if how.get("change"):
            data = bytearray((folder / INSTALLER).read_bytes())
            data[len(data) // 2] ^= 0xFF
            (folder / INSTALLER).write_bytes(bytes(data))
        code, said = run_setup(setup, folder, work / "message.txt", *extra)
        ok = judge(code, said, want, words)
        print(f"{'PASS' if ok else 'FAIL'}  {name}: exit {code}: {said[:110]}")
        if not ok:
            problems.append(f"{name}: exit {code}, not {want}: {said!r}")
    shutil.rmtree(work, ignore_errors=True)
    return problems


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--setup", type=Path, required=True, help="thoron_setup_for_tests.exe")
    p.add_argument("--stand-in", type=Path, required=True, help="a program that ends by itself")
    p.add_argument("--work", type=Path, required=True, help="a scratch folder; `thoron-setup` is made in it")
    p.add_argument("--shipped", type=Path, help="the ThoronSetup.exe that ships")
    a = p.parse_args(argv)
    problems = run(a.setup, a.stand_in, a.work / "thoron-setup")
    if a.shipped:
        found = rel.setup_problems(a.shipped)
        print(f"{'PASS' if not found else 'FAIL'}  shipped: {'; '.join(found) or 'no test switch, no test key'}")
        problems += found
    print(f"THORON SETUP CHECK: {'PASSED' if not problems else f'FAILED ({len(problems)} problem(s))'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
