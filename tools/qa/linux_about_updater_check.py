#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""The About page and the updater of a Linux copy (ROADMAP P3.23), as tools/qa/about_updater_check.py checks them
on Windows. Run on Windows.

On a clean Ubuntu test machine of tools/qa/wsl_test_vm.py, as the user `tester`, headless, with every outside name
unresolvable and a network log, tools/qa/about_updater_check.py runs twice:

    deb         the copy the `.deb` installed (updated by apt; the updater only says what is out)
    portable    a portable copy unpacked from the `.tar.xz` (it updates itself: its version folder sits beside
                `current`)

Without a release key (every build until P2.11) each shows no update line on chrome://settings/help and asks no
host, neither on its own nor when the page opens; with --expect-key each shows a line and asked github.com.

    py -3 -I tools/qa/linux_about_updater_check.py --deb <thoron-browser_*.deb> --archive <portable .tar.xz>
        --root <test machines folder> --work <scratch> [--machine thoron-test-2604] [--expect-key]
Exit status 0 only when both pass.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

if __package__ in (None, ""):  # running as a script: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

REPO = Path(__file__).resolve().parents[2]
STEPS = ("deb", "portable")

SCRIPT = r"""#!/bin/bash
# As root inside a clean test machine: $1 work folder, $2 the .deb, $3 the portable .tar.xz, $4 tools, $5 --expect-key or ""
set -u
W="$1"; DEB="$2"; ARCHIVE="$3"; TOOLS="$4"; KEY="$5"
out="$W/out"; rm -rf "$out"; mkdir -p "$out"; chmod 777 "$out"
export DEBIAN_FRONTEND=noninteractive
cp "$DEB" /tmp/thoron.deb
apt-get update -qq > "$out/apt-update.txt" 2>&1
apt-get install -y -qq /tmp/thoron.deb > "$out/apt-install.txt" 2>&1; echo $? > "$out/install_exit"
runuser -u tester -- mkdir -p /home/tester/portable
runuser -u tester -- tar -xf "$ARCHIVE" -C /home/tester/portable; echo $? > "$out/unpack_exit"
prog=$(ls -d /home/tester/portable/ThoronPortable/Application/*/thoron | head -1)
for step in deb portable; do
  [ "$step" = deb ] && browser=/opt/kuchisofts/thoron/thoron || browser="$prog"
  runuser -u tester -- env HOME=/home/tester python3 -I "$TOOLS/qa/about_updater_check.py" --browser "$browser" \
    --work "/tmp/about-$step" $KEY > "$out/$step.txt" 2>&1
  echo $? > "$out/${step}_exit"
done
"""


def problems(read) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {step: [] for step in STEPS}
    if read("install_exit") != "0":
        out["deb"].append(f"the .deb did not install: {read('apt-install.txt')[-300:]}")
    if read("unpack_exit") != "0":
        out["portable"].append("the portable package did not unpack")
    for step in STEPS:
        if read(f"{step}_exit") != "0":
            out[step].append(f"about_updater_check: {read(f'{step}.txt')[-400:].strip()}")
    return out


def run_machine(name: str, root: Path, work: Path, deb: Path, archive: Path, expect_key: bool) -> dict[str, list[str]]:
    from tools.qa import linux_package_check as lp
    from tools.qa import wsl_test_vm as vm
    vm.restore(root, name)
    folder = work / name
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    script = folder / "check.sh"
    script.write_bytes(SCRIPT.encode("utf-8"))
    tools = folder / "tools"
    shutil.copytree(REPO / "tools", tools, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    done = subprocess.run(["wsl.exe", "-d", vm.checked_name(name), "-u", "root", "--", "bash", lp.wsl_path(script),
                           lp.wsl_path(folder), lp.wsl_path(deb), lp.wsl_path(archive), lp.wsl_path(tools),
                           "--expect-key" if expect_key else ""], capture_output=True, timeout=2400)
    (folder / "run-output.txt").write_bytes(done.stdout + done.stderr)
    return problems(lambda n: lp.read(folder / "out", n))


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--deb", type=Path, required=True)
    p.add_argument("--archive", type=Path, required=True)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--machine", action="append")
    p.add_argument("--expect-key", action="store_true")
    a = p.parse_args(argv)
    from tools.qa import wsl_test_vm as vm
    failed = 0
    for name in a.machine or vm.MACHINES:
        print(f"== {name}")
        for step, issues in run_machine(name, a.root, a.work.resolve(), a.deb.resolve(), a.archive.resolve(),
                                        a.expect_key).items():
            print(f"{'PASS' if not issues else 'FAIL'}  {step}")
            for issue in issues:
                print(f"      {issue}")
            failed += len(issues)
    print(f"LINUX ABOUT UPDATER CHECK: {'PASSED' if not failed else f'FAILED ({failed} problem(s))'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
