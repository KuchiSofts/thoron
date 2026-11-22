#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""The Linux SSE4 package on an emulated processor without AVX (ROADMAP P2.7). Run on Windows.

On a clean Ubuntu test machine of tools/qa/wsl_test_vm.py, the SSE4 `.deb` is installed with apt and the browser runs
headless under QEMU's user-mode emulation of an Intel Westmere (2010: SSE4.2, no AVX), every process of it: the
browser process directly, and its renderer, utility and GPU processes through Chromium's own launch prefixes
(`--renderer-cmd-prefix`, `--utility-cmd-prefix`, `--gpu-launcher`). An AVX instruction outside the code that picks
one at run time stops a process with an illegal instruction. As a control, the AVX2 package the same way must
fail: that shows the emulation really refuses AVX.

    install     both packages install with apt (each in turn, they share their name)
    version     `thoron --version` of the SSE4 package runs on the emulated Westmere
    page        twice, the SSE4 browser opens a local page and prints it after its script ran ("sse4 smoke 42")
    control     the AVX2 browser on the same emulated processor does not print the page

The sandbox needs kernel help that user-mode emulation does not give, so these starts on a throwaway profile and a
local page have none (`--no-sandbox`).

    py -3 -I tools/qa/linux_sse4_smoke_check.py --deb <thoron-browser_*_SSE4.deb> --control <thoron-browser_*_AVX2.deb>
        --root <test machines folder> --work <scratch> [--machine thoron-test-2604]
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

STEPS = ("install", "version", "page", "control")
CPU = "Westmere"
PAGE = ("data:text/html,<title>t</title><p id=x>sse4 smoke</p>"
        "<script>document.getElementById('x').textContent += ' ' + (6*7)</script>")

SCRIPT = r"""#!/bin/bash
# Other work may share this WSL machine: if memory runs out, the kernel ends this check's processes first.
echo 1000 > /proc/self/oom_score_adj 2>/dev/null
# As root inside a clean test machine: $1 the SSE4 .deb, $2 the AVX2 .deb, $3 the results folder
set -uo pipefail
SSE4="$1"; AVX2="$2"; OUT="$3"
mkdir -p "$OUT"; chmod 777 "$OUT"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq > "$OUT/apt-update.txt" 2>&1
apt-get install -y -qq qemu-user > "$OUT/apt-qemu.txt" 2>&1; echo $? > "$OUT/qemu_exit"
prog=/opt/kuchisofts/thoron/thoron
q="qemu-x86_64 -cpu $CPU"
start_page() {  # $1 name for the files
  work=$(mktemp -d)
  timeout 1800 $q "$prog" --headless=new --no-zygote --no-sandbox --disable-gpu --no-first-run \
    --renderer-cmd-prefix="$q" --utility-cmd-prefix="$q" --gpu-launcher="$q" \
    --user-data-dir="$work/profile" --virtual-time-budget=5000 --dump-dom "$PAGE_URL" \
    > "$OUT/dom-$1.txt" 2> "$OUT/stderr-$1.txt"
  echo $? > "$OUT/$1-exit"
  rm -rf "$work"
}
cp "$SSE4" /tmp/sse4.deb; cp "$AVX2" /tmp/avx2.deb
apt-get install -y -qq /tmp/sse4.deb > "$OUT/apt-sse4.txt" 2>&1; echo $? > "$OUT/sse4_exit"
timeout 900 $q "$prog" --version > "$OUT/version.txt" 2>&1; echo $? > "$OUT/version_exit"
start_page first
start_page second
apt-get install -y -qq --allow-downgrades /tmp/avx2.deb > "$OUT/apt-avx2.txt" 2>&1; echo $? > "$OUT/avx2_exit"
start_page control
"""


def problems(read) -> dict[str, list[str]]:
    """What the results say, step by step; `read(name)` gives a result file's text ("" when missing)."""
    out: dict[str, list[str]] = {step: [] for step in STEPS}
    for name, what in (("qemu_exit", "QEMU"), ("sse4_exit", "the SSE4 package"), ("avx2_exit", "the AVX2 package")):
        if read(name) != "0":
            out["install"].append(f"{what} did not install (exit {read(name)!r})")
    if read("version_exit") != "0" or not read("version.txt").startswith("Thoron "):
        out["version"].append(f"--version gave {read('version_exit')!r}: {read('version.txt')[:120]!r}")
    for run in ("first", "second"):
        if "sse4 smoke 42" not in read(f"dom-{run}.txt"):
            out["page"].append(f"the {run} start gave {read(f'{run}-exit')!r} and no page: "
                               f"{read(f'stderr-{run}.txt')[-200:]!r}")
    if "sse4 smoke 42" in read("dom-control.txt"):
        out["control"].append("the AVX2 package printed the page on a processor without AVX: the emulation did not "
                              "refuse AVX, so the SSE4 result shows nothing")
    elif read("avx2_exit") == "0" and not read("control-exit"):
        out["control"].append("the AVX2 package's start left no result")
    return out


def run_machine(name: str, root: Path, work: Path, deb: Path, control: Path) -> dict[str, list[str]]:
    from tools.qa import linux_package_check as lp
    from tools.qa import wsl_test_vm as vm
    vm.restore(root, name)
    folder = work / name
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    script = folder / "check.sh"
    script.write_bytes(SCRIPT.replace("$CPU", CPU).encode("utf-8"))
    out = folder / "out"
    done = subprocess.run(["wsl.exe", "-d", vm.checked_name(name), "-u", "root", "--", "env", f"PAGE_URL={PAGE}",
                           "bash", lp.wsl_path(script), lp.wsl_path(deb), lp.wsl_path(control), lp.wsl_path(out)],
                          capture_output=True, timeout=7200)
    (folder / "run-output.txt").write_bytes(done.stdout + done.stderr)
    return problems(lambda n: lp.read(out, n))


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--deb", type=Path, required=True)
    p.add_argument("--control", type=Path, required=True)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--machine", action="append")
    a = p.parse_args(argv)
    from tools.qa import wsl_test_vm as vm
    failed = 0
    for name in a.machine or vm.MACHINES:
        print(f"== {name}")
        for step, issues in run_machine(name, a.root, a.work.resolve(), a.deb.resolve(), a.control.resolve()).items():
            print(f"{'PASS' if not issues else 'FAIL'}  {step}")
            for issue in issues:
                print(f"      {issue}")
            failed += len(issues)
    print(f"LINUX SSE4 SMOKE CHECK: {'PASSED' if not failed else f'FAILED ({failed} problem(s))'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
