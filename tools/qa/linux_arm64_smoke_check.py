#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""The Linux ARM64 package run under emulation (ROADMAP P2b.3). Run on Windows.

On a clean Ubuntu test machine of tools/qa/wsl_test_vm.py (an x64 machine), Ubuntu's own ARM64 libraries come from
its ports archive (multiarch, `dpkg --add-architecture arm64`) and QEMU's user-mode emulation of AArch64 runs ARM64
programs. Then:

    install     the ARM64 `.deb` installs with apt, its dependencies taken as ARM64 packages, as on an ARM64 PC
    version     `thoron --version` runs under emulation and names Thoron
    page        twice, the browser starts headless with its usual processes (the children it starts are emulated
                too: qemu-user registers itself for ARM64 programs, from the machine's next start on, so the machine
                is restarted between the install and the starts), opens a local page and prints the page after its
                script ran ("arm64 smoke 42": the program, its resources, V8 and Blink work)

The sandbox needs kernel help that user-mode emulation does not give, so these starts on a throwaway profile and a
local page have none (`--no-sandbox`): a test of the program, not of its sandbox, which needs an ARM64 PC (P2b.5).

    py -3 -I tools/qa/linux_arm64_smoke_check.py --deb <thoron-browser_*_arm64.deb> --root <test machines folder>
        --work <scratch> [--machine thoron-test-2604]
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

STEPS = ("install", "version", "page")
PAGE = ("data:text/html,<title>t</title><p id=x>arm64 smoke</p>"
        "<script>document.getElementById('x').textContent += ' ' + (6*7)</script>")

SCRIPT = r"""#!/bin/bash
# Other work may share this WSL machine: if memory runs out, the kernel ends this check's processes first.
echo 1000 > /proc/self/oom_score_adj 2>/dev/null
# As root inside a clean x64 test machine: $1 the ARM64 .deb, $2 the results folder, $3 install or run
set -uo pipefail
DEB="$1"; OUT="$2"; STEP="$3"
mkdir -p "$OUT"; chmod 777 "$OUT"
if [ "$STEP" = install ]; then
  export DEBIAN_FRONTEND=noninteractive
  codename=$(. /etc/os-release && echo "$VERSION_CODENAME")
  dpkg --add-architecture arm64
  # the machine's own sources are for amd64 only; ARM64's come from the ports archive
  f=/etc/apt/sources.list.d/ubuntu.sources
  [ -f "$f" ] && ! grep -q '^Architectures:' "$f" && sed -i '/^Types:/a Architectures: amd64' "$f"
  printf 'Types: deb\nURIs: http://ports.ubuntu.com/ubuntu-ports\nSuites: %s %s-updates %s-security\nComponents: main universe\nArchitectures: arm64\nSigned-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n' \
    "$codename" "$codename" "$codename" > /etc/apt/sources.list.d/ports-arm64.sources
  apt-get update -qq > "$OUT/apt-update.txt" 2>&1
  apt-get install -y -qq qemu-user libc6:arm64 > "$OUT/apt-qemu.txt" 2>&1; echo $? > "$OUT/qemu_exit"
  cp "$DEB" /tmp/thoron-arm64.deb
  apt-get install -y -qq /tmp/thoron-arm64.deb > "$OUT/apt-thoron.txt" 2>&1; echo $? > "$OUT/install_exit"
  exit 0
fi
prog=/opt/kuchisofts/thoron/thoron
file -b "$prog" > "$OUT/file.txt"
timeout 900 qemu-aarch64 -L / "$prog" --version > "$OUT/version.txt" 2>&1; echo $? > "$OUT/version_exit"
for run in first second; do
  work=$(mktemp -d)
  timeout 1800 qemu-aarch64 -L / "$prog" --headless=new --no-zygote --no-sandbox --disable-gpu --no-first-run \
    --user-data-dir="$work/profile" --virtual-time-budget=5000 --dump-dom "$PAGE_URL" \
    > "$OUT/dom-$run.txt" 2> "$OUT/stderr-$run.txt"
  echo $? > "$OUT/$run-exit"
  rm -rf "$work"
done
"""


def problems(read) -> dict[str, list[str]]:
    """What the results say, step by step; `read(name)` gives a result file's text ("" when missing)."""
    out: dict[str, list[str]] = {step: [] for step in STEPS}
    if read("qemu_exit") != "0":
        out["install"].append(f"QEMU and ARM64's C library did not install: {read('apt-qemu.txt')[-300:]}")
    if read("install_exit") != "0":
        out["install"].append(f"the ARM64 package did not install: {read('apt-thoron.txt')[-300:]}")
    if "aarch64" not in read("file.txt"):
        out["install"].append(f"the installed program is not an ARM64 one: {read('file.txt')[:120]}")
    if read("version_exit") != "0" or not read("version.txt").startswith("Thoron "):
        out["version"].append(f"--version gave {read('version_exit')!r}: {read('version.txt')[:120]!r}")
    for run in ("first", "second"):
        if "arm64 smoke 42" not in read(f"dom-{run}.txt"):
            out["page"].append(f"the {run} start gave {read(f'{run}-exit')!r} and no page: "
                               f"{read(f'stderr-{run}.txt')[-200:]!r}")
    return out


def run_machine(name: str, root: Path, work: Path, deb: Path) -> dict[str, list[str]]:
    from tools.qa import linux_package_check as lp
    from tools.qa import wsl_test_vm as vm
    vm.restore(root, name)
    folder = work / name
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    script = folder / "check.sh"
    script.write_bytes(SCRIPT.encode("utf-8"))
    out = folder / "out"
    distro = vm.checked_name(name)
    for step in ("install", "run"):
        if step == "run":
            # the emulation of ARM64 children works from the machine's next start on; only this test machine
            subprocess.run(["wsl.exe", "--terminate", distro], capture_output=True, timeout=120)
        done = subprocess.run(["wsl.exe", "-d", distro, "-u", "root", "--", "env", f"PAGE_URL={PAGE}", "bash",
                               lp.wsl_path(script), lp.wsl_path(deb), lp.wsl_path(out), step],
                              capture_output=True, timeout=3600)
        (folder / f"run-{step}.txt").write_bytes(done.stdout + done.stderr)
    return problems(lambda n: lp.read(out, n))


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--deb", type=Path, required=True)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--machine", action="append")
    a = p.parse_args(argv)
    from tools.qa import wsl_test_vm as vm
    failed = 0
    for name in a.machine or vm.MACHINES:
        print(f"== {name}")
        for step, issues in run_machine(name, a.root, a.work.resolve(), a.deb.resolve()).items():
            print(f"{'PASS' if not issues else 'FAIL'}  {step}")
            for issue in issues:
                print(f"      {issue}")
            failed += len(issues)
    print(f"LINUX ARM64 SMOKE CHECK: {'PASSED' if not failed else f'FAILED ({failed} problem(s))'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
