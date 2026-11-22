#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Thoron installed for one Linux user, with its update timer (ROADMAP P3.10, design 7.5a). Run on Windows.

On a clean Ubuntu test machine of tools/qa/wsl_test_vm.py, the user `tester` (with a systemd user manager, as a
desktop login gives one) unpacks the portable package and, with a `sudo` on its path that only writes down that it
was asked, runs its `install-for-this-user`:

    no admin     the install and the removal never ask for `sudo` (or anything else that needs root)
    install      the program in ~/.local/share/thoron (no profile there), a menu entry, the user timer
                 thoron-update.timer enabled
    timer run    the timer's job (thoron-update.service) runs Thoron headless once, on a profile folder of its own,
                 and ends with success within a few minutes
    profile      the installed copy keeps its profile in ~/.config/thoron, as the .deb's (a headless start in
                 ~/.config/thoron-headless, as Chromium does), never in its program folder
    removed      `--remove` takes away the program, the menu entry and the timer; the profile stays, and nothing
                 of Thoron is left in the user's folder but its profiles, the NSS certificate store Chromium
                 makes for the user (~/.local/share/pki) and the unpacked package

    py -3 -I tools/qa/linux_per_user_install_check.py --archive <thoron-*-linux-x64-*-portable.tar.xz>
        --deb <thoron-browser_*.deb> --root <test machines folder> --work <scratch> [--machine thoron-test-2604]
(The .deb only brings the libraries the browser needs, as a desktop has them, and is removed again.)
Exit status 0 only when every step passes.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

if __package__ in (None, ""):  # running as a script: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

STEPS = ("no admin", "install", "timer run", "profile", "removed")

SCRIPT = r"""#!/bin/bash
# Other work may share this WSL machine: if memory runs out, the kernel ends this check's processes first.
echo 1000 > /proc/self/oom_score_adj 2>/dev/null
# As root inside a clean test machine: $1 work folder, $2 the portable .tar.xz, $3 the .deb (for its dependencies)
set -u
W="$1"; ARCHIVE="$2"; DEB="$3"
out="$W/out"; rm -rf "$out"; mkdir -p "$out"; chmod 777 "$out"
# what the browser needs to run, as a desktop has it: the .deb's dependencies, the .deb itself removed again
export DEBIAN_FRONTEND=noninteractive
cp "$DEB" /tmp/thoron.deb
apt-get update -qq > /dev/null 2>&1
apt-get install -y -qq /tmp/thoron.deb > "$out/apt-deps.txt" 2>&1; echo $? > "$out/deps_exit"
dpkg -r thoron-browser >> "$out/apt-deps.txt" 2>&1
uid=$(id -u tester)
loginctl enable-linger tester
for i in $(seq 60); do [ -S "/run/user/$uid/bus" ] && break; sleep 1; done
as_tester() { runuser -u tester -- env HOME=/home/tester XDG_RUNTIME_DIR="/run/user/$uid" \
  DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$uid/bus" PATH="/home/tester/fake-bin:/usr/bin:/bin" "$@"; }
# a sudo that only writes down that it was asked
mkdir -p /home/tester/fake-bin
printf '#!/bin/sh\necho "sudo $*" >> %s/sudo-asked.txt\nexit 1\n' "$out" > /home/tester/fake-bin/sudo
chmod 755 /home/tester/fake-bin/sudo; chown -R tester: /home/tester/fake-bin
as_tester mkdir -p /home/tester/Downloads/thoron
as_tester tar -xf "$ARCHIVE" -C /home/tester/Downloads/thoron
pkg=/home/tester/Downloads/thoron/ThoronPortable
( cd /home/tester && find . -path ./Downloads -prune -o -print | sort ) > "$out/before.txt"
as_tester "$pkg/install-for-this-user" > "$out/install.txt" 2>&1; echo $? > "$out/install_exit"
dest=/home/tester/.local/share/thoron
ls -A "$dest" > "$out/dest.txt" 2>&1
as_tester systemctl --user is-enabled thoron-update.timer > "$out/timer-enabled.txt" 2>&1
as_tester systemctl --user list-timers --all > "$out/timers.txt" 2>&1
start=$(date +%s)
as_tester timeout 600 systemctl --user start thoron-update.service > "$out/service-start.txt" 2>&1
echo $? > "$out/service_exit"; echo $(( $(date +%s) - start )) > "$out/service_seconds"
as_tester systemctl --user show -p Result -p ExecMainStatus thoron-update.service > "$out/service-show.txt" 2>&1
as_tester timeout 300 "$dest/thoron" --headless=new --no-first-run --dump-dom about:blank > /dev/null 2>&1
ls -d /home/tester/.config/thoron* 2>/dev/null > "$out/profiles.txt"
ls -A "$dest" > "$out/dest-after-start.txt" 2>&1
( cd /home/tester && find . -path ./Downloads -prune -o -print | sort ) > "$out/installed.txt"
as_tester "$dest/install-for-this-user" --remove > "$out/remove.txt" 2>&1; echo $? > "$out/remove_exit"
as_tester systemctl --user list-timers --all > "$out/timers-after.txt" 2>&1
( cd /home/tester && find . -path ./Downloads -prune -o -print | sort ) > "$out/after.txt"
echo done > "$out/reached"
"""


def _lines(text: str) -> set[str]:
    return {line for line in text.splitlines() if line.strip()}


def problems(read) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {step: [] for step in STEPS}
    if read("deps_exit") != "0":
        out["install"].append(f"the browser's libraries did not install: {read('apt-deps.txt')[-200:]}")
    if read("sudo-asked.txt"):
        out["no admin"].append(f"administrator rights were asked for: {read('sudo-asked.txt')[:200]}")
    if read("install_exit") != "0":
        out["install"].append(f"the install ended with {read('install_exit')!r}: {read('install.txt')[-300:]}")
    dest = _lines(read("dest.txt"))
    for name in ("Application", "thoron", "per-user", "install-for-this-user"):
        if name not in dest:
            out["install"].append(f"~/.local/share/thoron holds no {name}")
    if "User Data" in dest:
        out["install"].append("~/.local/share/thoron holds a profile folder")
    if read("timer-enabled.txt").strip() != "enabled" or "thoron-update.timer" not in read("timers.txt"):
        out["install"].append(f"the timer is not enabled: {read('timer-enabled.txt').strip()!r}")
    shown = read("service-show.txt")
    if read("service_exit") != "0" or "Result=success" not in shown or "ExecMainStatus=0" not in shown:
        out["timer run"].append(f"the timer's job gave {read('service_exit')!r}: {shown.strip()!r} "
                                f"{read('service-start.txt')[-200:]!r}")
    elif int(read("service_seconds") or "9999") > 300:
        out["timer run"].append(f"the timer's job took {read('service_seconds')} s")
    # a headless start keeps its profile in ~/.config/thoron-headless (Chromium's rule), a start with a window
    # in ~/.config/thoron: both are the usual ones, never in the program's folder
    if not read("profiles.txt").strip():
        out["profile"].append("the installed copy made no profile in ~/.config")
    if "User Data" in _lines(read("dest-after-start.txt")):
        out["profile"].append("the installed copy made a profile in its program folder")
    if read("remove_exit") != "0":
        out["removed"].append(f"--remove ended with {read('remove_exit')!r}: {read('remove.txt')[-200:]}")
    if "thoron-update" in read("timers-after.txt"):
        out["removed"].append("the timer is still there")
    left = _lines(read("after.txt")) - _lines(read("before.txt"))
    # the browser's own data stays, as a profile does: its profiles, and the NSS certificate store Chromium
    # makes for the user on Linux (~/.local/share/pki, shared by every program that uses NSS)
    left = {p for p in left if not (p.startswith("./.config/thoron") or p.startswith("./.local/share/pki"))}
    # what the system makes in a user's folder that is not Thoron's (an empty folder systemd made stays)
    left = {p for p in left if p not in ("./.config", "./.local", "./.local/share", "./.config/systemd",
                                         "./.config/systemd/user", "./.local/share/applications",
                                         "./.local/share/systemd", "./.local/share/systemd/timers")
            and not p.startswith("./.cache/") and p != "./.cache"}
    if left:
        out["removed"].append(f"left in the user's folder: {sorted(left)[:8]}")
    return out


def run_machine(name: str, root: Path, work: Path, archive: Path, deb: Path) -> dict[str, list[str]]:
    from tools.qa import linux_package_check as lp
    from tools.qa import wsl_test_vm as vm
    vm.restore(root, name)
    folder = work / name
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    script = folder / "check.sh"
    script.write_bytes(SCRIPT.encode("utf-8"))
    done = subprocess.run(["wsl.exe", "-d", vm.checked_name(name), "-u", "root", "--", "bash", lp.wsl_path(script),
                           lp.wsl_path(folder), lp.wsl_path(archive), lp.wsl_path(deb)], capture_output=True,
                          timeout=3600)
    (folder / "run-output.txt").write_bytes(done.stdout + done.stderr)
    return problems(lambda n: lp.read(folder / "out", n))


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--archive", type=Path, required=True)
    p.add_argument("--deb", type=Path, required=True)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--machine", action="append")
    a = p.parse_args(argv)
    from tools.qa import wsl_test_vm as vm
    failed = 0
    for name in a.machine or vm.MACHINES:
        print(f"== {name}")
        for step, issues in run_machine(name, a.root, a.work.resolve(), a.archive.resolve(), a.deb.resolve()).items():
            print(f"{'PASS' if not issues else 'FAIL'}  {step}")
            for issue in issues:
                print(f"      {issue}")
            failed += len(issues)
    print(f"LINUX PER-USER INSTALL CHECK: {'PASSED' if not failed else f'FAILED ({failed} problem(s))'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
