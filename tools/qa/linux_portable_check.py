#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""The Linux portable package on a clean Ubuntu machine (ROADMAP P2.9, P3.12). Run on Windows.

On a test machine of tools/qa/wsl_test_vm.py, put back to its clean state, the user `tester` unpacks the
.tar.xz into a folder whose name has a space and accented and Cyrillic letters, with nothing installed but
what the browser needs to run (apt, from the .deb's own dependency list), and:

    starts      `./thoron` starts the browser (headless: the test machines' display is not always there) and
                it answers on DevTools; the
                profile is the package's own `User Data`, which the launcher made, and nothing appears in
                ~/.config/thoron (crash reports included)
    moved       the folder is moved to another name and started again: the profile comes along and is used
    sandbox     chrome://sandbox of that browser, read through DevTools, says it is adequately sandboxed
    update      (when the package carries `thoron_update`) the moved copy updates itself to a newer version and
                back, keeping its profile (tools/qa/linux_portable_update.py)
                (WSL has no AppArmor; on Ubuntu with it, the launcher says what an administrator must allow)

    py -3 -I tools/qa/linux_portable_check.py --archive <thoron-*-linux-x64-avx2-portable.tar.xz>
        --deb <the same release's .deb, for its dependency list> --root <test machines folder> --work <scratch>
Exit status 0 only when every step passes.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

REPO = Path(__file__).resolve().parents[2]
MACHINE = "thoron-test-2404"
FOLDER = "Thoron portable é Тест"
MOVED = "Thoron moved ü Ж"

SCRIPT = r"""#!/bin/bash
# As root in a clean test machine: $1 work folder, $2 the .tar.xz, $3 the .deb (for what it depends on)
set -u
W="$1"; TAR="$2"; DEB="$3"
out="$W/out"; rm -rf "$out"; mkdir -p "$out"; chmod 777 "$out"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq > "$out/apt-update.txt" 2>&1
# what the browser needs to run, as apt resolves the .deb's dependencies; then the package itself goes
cp "$DEB" /tmp/thoron.deb
apt-get install -y -qq /tmp/thoron.deb > "$out/apt-deps.txt" 2>&1; echo $? > "$out/deps_exit"
dpkg -r thoron-browser >> "$out/apt-deps.txt" 2>&1
as_tester() { runuser -u tester -- env HOME=/home/tester DISPLAY=:0 WAYLAND_DISPLAY=wayland-0 \
  XDG_RUNTIME_DIR=/mnt/wslg/runtime-dir "$@"; }
dir="/home/tester/__FOLDER__"
as_tester mkdir -p "$dir"
as_tester tar -xJf "$TAR" -C "$dir"; echo $? > "$out/unpack_exit"
# the machine's display (WSLg's Wayland; its X11 socket is not always there) comes up a little after the
# machine starts
for i in $(seq 90); do [ -S /mnt/wslg/runtime-dir/wayland-0 ] && break; sleep 1; done
[ -S /mnt/wslg/runtime-dir/wayland-0 ] && echo yes > "$out/display" || echo no > "$out/display"
pkg="$dir/ThoronPortable"
start() {  # $1 package folder, $2 name: the launcher with DevTools on 127.0.0.1, until it answers (at most 60 s)
  # (the first start on a freshly made machine takes a while: fonts and caches are made then)
  as_tester bash -c "cd \"\$1\" || exit 1; ./thoron --no-first-run --no-default-browser-check --headless=new --remote-debugging-port=9445 \
    about:blank > '$out/$2-run.txt' 2>&1 & p=\$!; \
    for i in \$(seq 60); do sleep 1; curl -s http://127.0.0.1:9445/json/version > '$out/$2-version.json' && \
      [ -s '$out/$2-version.json' ] && break; done; sleep 10; \
    if kill -0 \$p 2>/dev/null; then echo running > '$out/$2-ran'; kill -TERM \$p; sleep 8; kill -KILL \$p 2>/dev/null; fi; true" _ "$1"
}
apt-get install -y -qq curl > /dev/null 2>&1
start "$pkg" first
ls -A "$pkg" > "$out/package-after.txt"
[ -f "$pkg/User Data/Local State" ] && echo yes > "$out/profile-made"
[ -e /home/tester/.config/thoron ] && echo yes > "$out/config-thoron"
as_tester env BREAKPAD_DUMP_LOCATION=/tmp/cdp-crash python3 -I "$W/tools/qa/cdp.py" --browser "$pkg/Application/$(head -n1 "$pkg/Application/current")/thoron" \
  --work /tmp/cdp --page chrome://sandbox --png /tmp/sandbox.png --text "$out/sandbox.txt" > "$out/cdp.txt" 2>&1
moved="/home/tester/__MOVED__"
as_tester mv "$dir" "$moved"
before=$(stat -c %s "$moved/ThoronPortable/User Data/Local State" 2>/dev/null)
start "$moved/ThoronPortable" moved
grep -q "profile.*__MOVED__\|__MOVED__" "$moved/ThoronPortable/User Data/Local State" 2>/dev/null; echo $? > "$out/moved-named"
[ -f "$moved/ThoronPortable/User Data/Local State" ] && echo yes > "$out/moved-profile"
[ -e /home/tester/.config/thoron ] && echo yes >> "$out/config-thoron"
# the update of the moved copy (tools/qa/linux_portable_update.py), when the package carries its updater
if [ -x "$moved/ThoronPortable/Application/$(head -n1 "$moved/ThoronPortable/Application/current")/thoron_update" ]; then
  as_tester python3 -I "$W/tools/qa/linux_portable_update.py" --package "$moved/ThoronPortable" \
    --out "$out/update.json" > "$out/update.txt" 2>&1
fi
echo done > "$out/reached"
"""


def read(folder: Path, name: str) -> str:
    try:
        return (folder / name).read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def problems(out: Path) -> dict[str, list[str]]:
    from tools.qa.linux_package_check import sandbox_on
    found: dict[str, list[str]] = {"starts": [], "moved": [], "sandbox": []}
    if read(out, "reached") != "done":
        found["starts"].append(f"the run stopped (deps {read(out, 'deps_exit')!r}, unpack {read(out, 'unpack_exit')!r})")
    if read(out, "first-ran") != "running":
        found["starts"].append(f"the browser did not stay open 20 s: {read(out, 'first-run.txt')[-300:]}")
    if '"Browser"' not in read(out, "first-version.json"):
        found["starts"].append(f"DevTools did not answer: {read(out, 'first-version.json')[:200]!r}")
    if read(out, "profile-made") != "yes":
        found["starts"].append("the package's own User Data holds no profile")
    if read(out, "config-thoron"):
        found["starts"].append("the portable copy wrote into ~/.config/thoron")
    if read(out, "moved-ran") != "running" or read(out, "moved-profile") != "yes":
        found["moved"].append("after the move the browser did not open on the package's own profile")
    found["sandbox"] += sandbox_on(read(out, "sandbox.txt"))
    update = read(out, "update.json")
    if not update and read(out, "update.txt"):
        found["update"] = [f"the update ran and wrote no results: {read(out, 'update.txt')[-300:]}"]
    if update:
        import json
        from tools.qa import linux_portable_update as lu
        try:
            steps = lu.problems(json.loads(update), f"/home/tester/{MOVED}/ThoronPortable")
        except ValueError:
            steps = {"update": [f"the update's results could not be read: {update[:200]!r}"]}
        for step, issues in steps.items():
            found[f"update: {step}"] = issues
    return found


def main(argv: list[str]) -> int:
    from tools.qa import linux_package_check as lp
    from tools.qa import wsl_test_vm as vm
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--archive", type=Path, required=True)
    p.add_argument("--deb", type=Path, required=True)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--machine", default=MACHINE, choices=vm.MACHINES)
    a = p.parse_args(argv)
    sys.stdout.reconfigure(errors="backslashreplace")
    vm.restore(a.root, a.machine)
    work = a.work.resolve()
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    shutil.copytree(REPO / "tools", work / "tools", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    script = work / "check.sh"
    script.write_bytes(SCRIPT.replace("__FOLDER__", FOLDER).replace("__MOVED__", MOVED).encode("utf-8"))
    done = subprocess.run(["wsl.exe", "-d", vm.checked_name(a.machine), "-u", "root", "--", "bash", lp.wsl_path(script),
                           lp.wsl_path(work), lp.wsl_path(a.archive.resolve()), lp.wsl_path(a.deb.resolve())],
                          capture_output=True, timeout=2400)
    (work / "run-output.txt").write_bytes(done.stdout + done.stderr)
    failed = 0
    for step, issues in problems(work / "out").items():
        print(f"{'PASS' if not issues else 'FAIL'}  {step}")
        for issue in issues:
            print(f"      {issue}")
        failed += len(issues)
    print(f"LINUX PORTABLE CHECK: {'PASSED' if not failed else f'FAILED ({failed} problem(s))'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
