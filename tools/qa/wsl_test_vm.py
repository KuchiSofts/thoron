#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Ubuntu test machines that go back to a clean state in one step (ROADMAP Q.6), as WSL distributions.

Each test machine is its own WSL distribution named `thoron-test-<release>` (Ubuntu 24.04 and 26.04 LTS from
Microsoft's store images), with a plain user `tester` who may use sudo, and nothing else installed. Its clean
state is a snapshot made right after that (`wsl --export`). `restore` throws the machine away and imports the
snapshot again: one step, a minute or so, whatever a test did to it. Only distributions whose name starts with
`thoron-test-` are ever touched; a person's own distributions are never named, stopped or changed.

    py -3 -I tools/qa/wsl_test_vm.py list --root <folder with clean\\ and the machines' folders>
    py -3 -I tools/qa/wsl_test_vm.py restore --root <folder> --name thoron-test-2404
    py -3 -I tools/qa/wsl_test_vm.py run --root <folder> --name thoron-test-2604 -- <command and arguments>

What WSL is not: it has no AppArmor by default (so the AppArmor side of Chromium's sandbox, P2.9 and S.5, is not
what a desktop Ubuntu has), and its desktop is WSLg (Wayland and X11 windows, no GNOME or KDE session).
"""
import argparse
import subprocess
import sys
from pathlib import Path

PREFIX = "thoron-test-"
MACHINES = ("thoron-test-2404", "thoron-test-2604")


class VmError(RuntimeError):
    pass


def _wsl(*args: str, timeout: float = 900) -> subprocess.CompletedProcess:
    return subprocess.run(["wsl.exe", *args], capture_output=True, timeout=timeout)


def _text(raw: bytes) -> str:
    """wsl.exe's own messages are UTF-16; a command's output inside a distribution is not."""
    if raw[:2] == b"\xff\xfe" or (len(raw) > 1 and raw[1:2] == b"\x00"):
        return raw.decode("utf-16-le", errors="replace")
    return raw.decode("utf-8", errors="replace")


def checked_name(name: str) -> str:
    if not name.startswith(PREFIX) or not name[len(PREFIX):].replace("-", "").isalnum():
        raise VmError(f"{name!r} is not a test machine (its name must start with {PREFIX!r})")
    return name


def installed() -> list[str]:
    out = _text(_wsl("--list", "--quiet", timeout=60).stdout)
    return [line.strip().strip("\x00") for line in out.splitlines() if line.strip().strip("\x00")]


def snapshot(root: Path, name: str) -> Path:
    return root / "clean" / f"{checked_name(name)}.tar"


def restore(root: Path, name: str) -> None:
    """The machine thrown away and imported again from its clean snapshot."""
    name = checked_name(name)
    tar = snapshot(root, name)
    if not tar.is_file():
        raise VmError(f"no clean snapshot of {name} at {tar}")
    if name in installed():
        done = _wsl("--unregister", name)
        if done.returncode:
            raise VmError(f"{name} could not be removed: {_text(done.stdout + done.stderr).strip()}")
    place = root / name
    place.mkdir(parents=True, exist_ok=True)
    done = _wsl("--import", name, str(place), str(tar))
    if done.returncode:
        raise VmError(f"{name} could not be imported: {_text(done.stdout + done.stderr).strip()}")


def run(name: str, command: list[str], timeout: float) -> int:
    """`command` as the machine's user `tester`; its output is passed on."""
    done = _wsl("-d", checked_name(name), "-u", "tester", "--", *command, timeout=timeout)
    sys.stdout.write(_text(done.stdout))
    sys.stderr.write(_text(done.stderr))
    return done.returncode


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="action", required=True)
    for action in ("list", "restore", "run"):
        s = sub.add_parser(action)
        s.add_argument("--root", required=True, type=Path)
        if action != "list":
            s.add_argument("--name", required=True)
        if action == "run":
            s.add_argument("--timeout", type=float, default=3600)
            s.add_argument("command", nargs=argparse.REMAINDER)
    a = p.parse_args(argv)
    try:
        if a.action == "list":
            have = set(installed())
            for name in MACHINES:
                print(f"{name}: {'installed' if name in have else 'not installed'}, clean snapshot "
                      f"{'there' if snapshot(a.root, name).is_file() else 'missing'}")
            return 0
        if a.action == "restore":
            restore(a.root, a.name)
            print(f"{a.name}: restored to its clean snapshot")
            return 0
        command = a.command[1:] if a.command[:1] == ["--"] else a.command
        return run(a.name, command, a.timeout)
    except (VmError, OSError, subprocess.TimeoutExpired) as e:
        print(f"error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
