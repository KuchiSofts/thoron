#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Thoron's sandbox under AppArmor on a real Ubuntu kernel (ROADMAP S.5, D.2). Run on Windows.

WSL's kernel has no AppArmor, so the Linux package check cannot see whether the .deb's AppArmor profile lets
the sandbox make its user namespaces on an Ubuntu that restricts them (23.10 and later). This check boots
Ubuntu's own 24.04 cloud image (its checksum list signed by Ubuntu's cloud image key, checked with gpgv) in QEMU
inside a clean test machine of tools/qa/wsl_test_vm.py, without KVM (QEMU emulates the processor, so it is slow),
and inside it, with cloud-init:

    system       the kernel restricts unprivileged user namespaces and AppArmor is on
    deb          the .deb installs, its profile `thoron-browser` is loaded, and its chrome://sandbox reads
                 "You are adequately sandboxed" with the namespace and Seccomp-BPF layers
    portable     the portable copy without a profile of its own: its launcher says what to do, and the browser
                 refuses to run without its sandbox (no page is shown)
    readme       with a profile made as the portable package's README says (the .deb's, with the copy's path),
                 the portable copy's chrome://sandbox reads "You are adequately sandboxed"

The results come back on the VM's second serial port. Nothing of this PC goes into the VM but the packages and
the check's own tools.

    py -3 -I tools/qa/linux_apparmor_vm_check.py --deb <thoron-browser_*.deb> --archive <portable .tar.xz>
        --root <test machines folder> --work <scratch> [--machine thoron-test-2404] [--evidence <file>]
With --evidence the file `release.py prepare --sandbox-evidence` asks of a Linux release (ROADMAP S.5) is written:
the build's version, the kernel's AppArmor state and the chrome://sandbox texts; it stays with the build's records.
Exit status 0 only when every step passes.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

if __package__ in (None, ""):  # running as a script: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

REPO = Path(__file__).resolve().parents[2]
STEPS = ("system", "deb", "portable", "readme")
IMAGE_URL = "https://cloud-images.ubuntu.com/noble/current"
IMAGE = "noble-server-cloudimg-amd64.img"
BEGIN, END = "=====THORON-RESULTS-BEGIN=====", "=====THORON-RESULTS-END====="

# As root in a clean test machine: $1 work folder, $2 the .deb, $3 the portable .tar.xz, $4 tools, $5 image cache
HOST_SCRIPT = r"""#!/bin/bash
set -u
W="$1"; DEB="$2"; ARCHIVE="$3"; TOOLS="$4"; CACHE="$5"
out="$W/out"; rm -rf "$out"; mkdir -p "$out"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq > /dev/null 2>&1
apt-get install -y -qq qemu-system-x86 qemu-utils cloud-image-utils ubuntu-cloudimage-keyring gpgv curl \
  > "$out/apt-host.txt" 2>&1; echo $? > "$out/host_deps_exit"
mkdir -p "$CACHE"; cd "$CACHE" || exit 1
# the image, checked against Ubuntu's signed checksum list (fetched again each run)
curl -fsSL -o SHA256SUMS "@@IMAGE_URL@@/SHA256SUMS" && curl -fsSL -o SHA256SUMS.gpg "@@IMAGE_URL@@/SHA256SUMS.gpg"
gpgv --keyring /usr/share/keyrings/ubuntu-cloudimage-keyring.gpg SHA256SUMS.gpg SHA256SUMS > "$out/gpgv.txt" 2>&1
echo $? > "$out/gpgv_exit"
want=$(grep " \*\?@@IMAGE@@$" SHA256SUMS | cut -d' ' -f1)
if [ -z "$want" ] || [ "$(sha256sum @@IMAGE@@ 2>/dev/null | cut -d' ' -f1)" != "$want" ]; then
  curl -fsSL -o @@IMAGE@@.part "@@IMAGE_URL@@/@@IMAGE@@" && mv @@IMAGE@@.part @@IMAGE@@
fi
[ -n "$want" ] && [ "$(sha256sum @@IMAGE@@ | cut -d' ' -f1)" = "$want" ]; echo $? > "$out/image_exit"
# what the VM fetches from this machine (QEMU's user network: this machine is 10.0.2.2 there)
serve=/var/tmp/serve; rm -rf "$serve"; mkdir -p "$serve"
cp "$DEB" "$serve/thoron.deb"; cp "$ARCHIVE" "$serve/portable.tar.xz"
tar -C "$(dirname "$TOOLS")" -cf "$serve/tools.tar" "$(basename "$TOOLS")"
cp "$W/vm-check.sh" "$serve/vm-check.sh"
( cd "$serve" && exec python3 -m http.server 18099 --bind 0.0.0.0 ) > "$out/http.txt" 2>&1 &
http=$!
vmdir=/var/tmp/vm; rm -rf "$vmdir"; mkdir -p "$vmdir"
cp "$CACHE/@@IMAGE@@" "$vmdir/base.img"   # on this machine's own disk, not the Windows drive
qemu-img create -q -f qcow2 -F qcow2 -b "$vmdir/base.img" "$vmdir/disk.qcow2" 20G
cloud-localds "$vmdir/seed.img" "$W/user-data" "$W/meta-data"
start=$(date +%s)
timeout 9000 qemu-system-x86_64 -machine q35 -cpu max -smp 4 -m 4096 -accel tcg,thread=multi \
  -drive file="$vmdir/disk.qcow2",if=virtio -drive file="$vmdir/seed.img",if=virtio,format=raw \
  -nic user,model=virtio-net-pci -display none -no-reboot \
  -serial file:"$out/console.txt" -serial file:"$out/results.txt" > "$out/qemu.txt" 2>&1
echo $? > "$out/qemu_exit"; echo $(( $(date +%s) - start )) > "$out/vm_seconds"
kill "$http" 2>/dev/null
echo done > "$out/reached"
"""

USER_DATA = """#cloud-config
users:
  - name: tester
    shell: /bin/bash
    lock_passwd: true
runcmd:
  - [bash, -c, "curl -fsS http://10.0.2.2:18099/vm-check.sh -o /root/vm-check.sh && bash /root/vm-check.sh; poweroff"]
"""
META_DATA = "instance-id: thoron-apparmor-check\nlocal-hostname: thoron-apparmor-check\n"

# Inside the VM, as root: the four steps; the results go out on the second serial port.
VM_SCRIPT = r"""#!/bin/bash
set -u
H=http://10.0.2.2:18099
# a folder the user tester can write in (root's own is closed to it)
out=/var/tmp/out; rm -rf "$out"; mkdir -p "$out"; chmod 777 "$out"
{ uname -r; echo "restrict=$(cat /proc/sys/kernel/apparmor_restrict_unprivileged_userns 2>&1)";
  echo "enabled=$(aa-enabled 2>&1)"; } > "$out/system.txt"
mkdir -p /var/tmp/qa; chmod 755 /var/tmp/qa; cd /var/tmp/qa || exit 1
curl -fsS $H/thoron.deb -o thoron.deb && curl -fsS $H/portable.tar.xz -o portable.tar.xz \
  && curl -fsS $H/tools.tar -o tools.tar; echo $? > "$out/fetch_exit"
mkdir -p /opt/qa && tar -xf tools.tar -C /opt/qa
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq > "$out/apt-update.txt" 2>&1
apt-get install -y -qq ./thoron.deb > "$out/apt.txt" 2>&1; echo $? > "$out/install_exit"
aa-status > "$out/aa-status.txt" 2>&1
cp /etc/apparmor.d/thoron-browser "$out/profile.txt" 2>/dev/null
cdp() { runuser -u tester -- python3 -I /opt/qa/tools/qa/cdp.py --browser "$1" --work "/tmp/cdp-$2" \
  --page chrome://sandbox --png "/tmp/$2.png" --text "$out/sandbox-$2.txt" --start-wait 900 --settle 30 \
  > "$out/cdp-$2.txt" 2>&1; echo $? > "$out/cdp_$2_exit"; }
cdp /usr/bin/thoron-browser deb
runuser -u tester -- mkdir -p /home/tester/p
runuser -u tester -- tar -xf portable.tar.xz -C /home/tester/p
prog=$(ls -d /home/tester/p/ThoronPortable/Application/*/thoron | head -1)
runuser -u tester -- timeout 900 /home/tester/p/ThoronPortable/thoron --headless=new --no-first-run \
  --dump-dom about:blank > "$out/portable-stdout.txt" 2> "$out/portable-stderr.txt"
echo $? > "$out/portable_exit"
# the README's way: the .deb's profile with the copy's path
sed -E "s#^profile [^ ]+ [^ ]+#profile thoron-portable-check $prog#" /etc/apparmor.d/thoron-browser \
  > /etc/apparmor.d/thoron-portable-check
cp /etc/apparmor.d/thoron-portable-check "$out/readme-profile.txt"
apparmor_parser -r /etc/apparmor.d/thoron-portable-check > "$out/parser.txt" 2>&1; echo $? > "$out/parser_exit"
cdp "$prog" readme
echo reached > "$out/reached"
{ echo "@@BEGIN@@"; tar -C "$out" -cz . | base64 -w 76; echo "@@END@@"; } > /dev/ttyS1
sync
"""


def _results(serial: str) -> dict[str, str]:
    """The files the VM sent on its second serial port (a gzipped tar in base64 between the markers)."""
    if BEGIN not in serial or END not in serial:
        return {}
    body = serial.split(BEGIN, 1)[1].split(END, 1)[0]
    data = base64.b64decode("".join(re.findall(r"[A-Za-z0-9+/=]+", body)))
    out = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for item in tar:
            if item.isfile() and "/" not in item.name.lstrip("./"):
                out[item.name.lstrip("./")] = tar.extractfile(item).read().decode("utf-8", "replace")
    return out


def problems(found: dict[str, str]) -> dict[str, list[str]]:
    from tools.qa.linux_package_check import sandbox_on
    out: dict[str, list[str]] = {step: [] for step in STEPS}
    system = found.get("system.txt", "")
    if "restrict=1" not in system:
        out["system"].append(f"the kernel does not restrict user namespaces: {system.strip()!r}")
    if "enabled=Yes" not in system:
        out["system"].append(f"AppArmor is not on: {system.strip()!r}")
    if found.get("install_exit", "").strip() != "0":
        out["deb"].append(f"the .deb did not install: {found.get('apt.txt', '')[-300:]}")
    if "thoron-browser" not in found.get("aa-status.txt", ""):
        out["deb"].append("the profile thoron-browser is not loaded")
    out["deb"] += sandbox_on(found.get("sandbox-deb.txt", ""))
    said = found.get("portable-stderr.txt", "")
    if "AppArmor profile" not in said:
        out["portable"].append(f"the launcher did not say what to do: {said[-300:]!r}")
    if "<html" in found.get("portable-stdout.txt", "") or found.get("portable_exit", "").strip() == "0":
        out["portable"].append("the browser ran without its sandbox")
    if found.get("parser_exit", "").strip() != "0":
        out["readme"].append(f"the README's profile did not load: {found.get('parser.txt', '')[-300:]!r}")
    out["readme"] += sandbox_on(found.get("sandbox-readme.txt", ""))
    return out


def evidence_text(found: dict[str, str], version: str, failed: int) -> str:
    """The release's sandbox evidence (release.py sandbox_evidence_problems, platform linux)."""
    def part(title: str, name: str, lines: int = 40) -> str:
        return f"== {title}\n" + "\n".join(found.get(name, "").splitlines()[:lines]) + "\n"
    return (f"Sandbox on (linux/{version}) under AppArmor, Ubuntu's own kernel in a VM\n"
            + part("the system", "system.txt")
            + part("the .deb's chrome://sandbox", "sandbox-deb.txt")
            + part("the portable copy without a profile (it must refuse)", "portable-stderr.txt", 4)
            + part("the portable copy with the README's profile: chrome://sandbox", "sandbox-readme.txt")
            + f"LINUX SANDBOX CHECK: {'PASSED' if not failed else f'FAILED ({failed} problem(s))'}\n")


def run_machine(name: str, root: Path, work: Path, deb: Path, archive: Path) -> tuple[dict[str, list[str]], dict]:
    from tools.qa import linux_package_check as lp
    from tools.qa import wsl_test_vm as vm
    vm.restore(root, name)
    folder = work / name
    if folder.exists():
        shutil.rmtree(folder, onexc=lambda func, path, _exc: (Path(path).chmod(0o700), func(path)))
    folder.mkdir(parents=True)
    host = HOST_SCRIPT.replace("@@IMAGE_URL@@", IMAGE_URL).replace("@@IMAGE@@", IMAGE)
    (folder / "host.sh").write_bytes(host.encode("utf-8"))
    (folder / "vm-check.sh").write_bytes(VM_SCRIPT.replace("@@BEGIN@@", BEGIN).replace("@@END@@", END).encode())
    (folder / "user-data").write_bytes(USER_DATA.encode("utf-8"))
    (folder / "meta-data").write_bytes(META_DATA.encode("utf-8"))
    tools = folder / "tools"
    shutil.copytree(REPO / "tools", tools, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    cache = root / "images"
    done = subprocess.run(["wsl.exe", "-d", vm.checked_name(name), "-u", "root", "--", "bash", lp.wsl_path(folder / "host.sh"),
                           lp.wsl_path(folder), lp.wsl_path(deb), lp.wsl_path(archive), lp.wsl_path(tools),
                           lp.wsl_path(cache)], capture_output=True, timeout=10800)
    (folder / "run-output.txt").write_bytes(done.stdout + done.stderr)
    out = folder / "out"
    for step, file in (("host deps", "host_deps_exit"), ("image signature", "gpgv_exit"), ("image", "image_exit")):
        if lp.read(out, file) != "0":
            return {step: [f"{file} is {lp.read(out, file)!r}"]}, {}
    found = _results(lp.read(out, "results.txt"))
    if not found:
        console = lp.read(out, "console.txt")
        return {"vm": [f"the VM sent no results (exit {lp.read(out, 'qemu_exit')!r}): {console[-500:]}"]}, {}
    (folder / "results.json").write_text(json.dumps(found, indent=1), encoding="utf-8")
    return problems(found), found


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--deb", type=Path, required=True)
    p.add_argument("--archive", type=Path, required=True)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--machine", default="thoron-test-2404")
    p.add_argument("--evidence", type=Path, help="write the release's sandbox evidence (ROADMAP S.5) here")
    a = p.parse_args(argv)
    issues_by_step, found = run_machine(a.machine, a.root, a.work.resolve(), a.deb.resolve(), a.archive.resolve())
    failed = 0
    for step, issues in issues_by_step.items():
        print(f"{'PASS' if not issues else 'FAIL'}  {step}")
        for issue in issues:
            print(f"      {issue}")
        failed += len(issues)
    if found.get("system.txt"):
        print("VM: " + " ".join(found["system.txt"].split()))
    print(f"LINUX APPARMOR VM CHECK: {'PASSED' if not failed else f'FAILED ({failed} problem(s))'}")
    if a.evidence and found:
        from tools.release import apt_repo
        version = dict(apt_repo.control_of(a.deb.read_bytes()))["Version"].split("-")[0].split(":")[-1]
        a.evidence.write_text(evidence_text(found, version, failed), encoding="utf-8")
        print(f"evidence: {a.evidence}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
