#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Thoron's Linux package on clean Ubuntu machines (ROADMAP P2.4, P2.9, P2.21, P2.6, S.5). Run on Windows.

On each test machine of tools/qa/wsl_test_vm.py (Ubuntu 24.04 and 26.04, WSL distributions put back to their
clean state first; networking on for apt and, with --online, for the Widevine step) this check, as root and as
the plain user `tester`:

    install      installs the .deb with apt, which brings what it depends on; its files are listed
    names        no installed file or folder is named after Thorium, no Widevine module is in it, and none of
                 upstream's extras (tools/release/package_audit.py's rules)
    coexists     upstream's thorium-browser .deb installs beside it: no file belongs to both, `thoron` and
                 `thorium-browser` are both there with a desktop entry each, each opens on the machine's
                 display (WSLg) for 20 s, and each keeps its profile in its own folder (~/.config/thoron,
                 ~/.config/thorium)
    sandbox      chrome://sandbox, read through DevTools (tools/qa/cdp.py), reports the sandbox as on: the
                 Seccomp-BPF layer and the namespace layer; the page's text is kept as the release's evidence
    lintian      lintian finds no error in the package, with the tags Chromium's own lint step accepts for its
                 packages (installed into /opt, libraries linked in, a set-user-id sandbox helper)
    upgrade      the same package with a higher version installs over it and leaves the profile byte for
                 byte as it was; Thoron opens it again afterwards
    remove       `apt remove` takes the program and its command away and leaves the person's profile
    widevine     (--online) tools/qa/widevine_check.py on the installed browser: the module is fetched when
                 asked for and a page gets Widevine keys (no playback: the machine has no sound)
    network      (--netlog) tools/qa/netlog_hosts.py on the installed browser: the hosts a fresh profile
                 contacts on its own, written next to the results (hosts.md) for docs/security/NETWORK.md

What WSL is not: it has no AppArmor (so chrome://sandbox runs without the AppArmor profile a desktop Ubuntu
needs for user namespaces; the .deb's profile is installed but not loaded) and no GNOME or KDE session.

    py -3 -I tools/qa/linux_package_check.py --deb <thoron-browser_*.deb> --upstream <thorium-browser_*.deb>
        --root <test machines folder> --work <scratch> [--machine thoron-test-2404] [--online]
Exit status 0 only when every step passes on every machine.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path, PureWindowsPath

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.qa import wsl_test_vm as vm  # noqa: E402
from tools.release import package_audit as audit  # noqa: E402

REPO = Path(__file__).resolve().parents[2]

SCRIPT = r"""#!/bin/bash
# Run as root inside a clean test machine: $1 work folder, $2 Thoron's .deb, $3 upstream's .deb, $4 tools, $5 online,
# $6 network log
set -u
W="$1"; DEB="$2"; UP="$3"; TOOLS="$4"; ONLINE="$5"; NETLOG="$6"
out="$W/out"; rm -rf "$out"; mkdir -p "$out"
export DEBIAN_FRONTEND=noninteractive
step() { echo "$1" > "$out/reached"; }
as_tester() { runuser -u tester -- env HOME=/home/tester DISPLAY=:0 WAYLAND_DISPLAY=wayland-0 \
  XDG_RUNTIME_DIR=/mnt/wslg/runtime-dir PULSE_SERVER=/mnt/wslg/PulseServer "$@"; }
opens() {  # $1 program, $2 name for the files: opens on the display for 20 s, then closes
  as_tester bash -c "'$1' --no-first-run --no-default-browser-check about:blank > '$out/$2-run.txt' 2>&1 & p=\$!; sleep 20; \
    if kill -0 \$p 2>/dev/null; then echo running > '$out/$2-ran'; kill -TERM \$p; sleep 5; kill -KILL \$p 2>/dev/null; fi; true"
}
cp "$DEB" /tmp/thoron.deb; cp "$UP" /tmp/upstream.deb
step install
apt-get update -qq > "$out/apt-update.txt" 2>&1
apt-get install -y -qq /tmp/thoron.deb > "$out/apt-install.txt" 2>&1; echo $? > "$out/install_exit"
dpkg -L thoron-browser > "$out/files.txt" 2>&1
while read -r f; do [ -f "$f" ] && echo "$f"; done < "$out/files.txt" > "$out/regular-files.txt"
dpkg-query -W -f='${Version}' thoron-browser > "$out/version.txt" 2>&1
# the machine's display (WSLg) comes up a little after the machine starts
for i in $(seq 90); do [ -S /tmp/.X11-unix/X0 ] && [ -S /mnt/wslg/runtime-dir/wayland-0 ] && break; sleep 1; done
[ -S /tmp/.X11-unix/X0 ] && echo yes > "$out/display" || echo no > "$out/display"
step coexists
apt-get install -y -qq /tmp/upstream.deb > "$out/apt-upstream.txt" 2>&1; echo $? > "$out/upstream_exit"
dpkg -L thorium-browser > "$out/upstream-files.txt" 2>&1
while read -r f; do [ -f "$f" ] && echo "$f"; done < "$out/upstream-files.txt" > "$out/upstream-regular-files.txt"
command -v thoron-browser > "$out/which-thoron.txt"; command -v thorium-browser > "$out/which-thorium.txt"
ls /usr/share/applications > "$out/desktop.txt"
opens thoron-browser thoron
opens thorium-browser thorium
ls -A /home/tester/.config > "$out/config-dirs.txt" 2>&1
step sandbox
as_tester python3 -I "$TOOLS/qa/cdp.py" --browser /usr/bin/thoron-browser --work /tmp/cdp --page chrome://sandbox \
  --png /tmp/sandbox.png --text "$out/sandbox.txt" > "$out/cdp.txt" 2>&1
step lintian
apt-get install -y -qq lintian > "$out/apt-lintian.txt" 2>&1
# with the tags Chromium's own lint step accepts for its packages (chrome/installer/linux/debian/lint_package.py):
# a browser that is no distribution's package installs into /opt, links some libraries in, and its sandbox helper
# is set-user-id
lintian --no-tag-display-limit --suppress-tags dir-or-file-in-opt,embedded-library,setuid-binary \n  /tmp/thoron.deb > "$out/lintian.txt" 2>&1; echo $? > "$out/lintian_exit"
step upgrade
before=$(cd /home/tester/.config/thoron && find . -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum)
rm -rf /tmp/up && dpkg-deb -R /tmp/thoron.deb /tmp/up
sed -i "s/^Version: \(.*\)$/Version: \1+upgradetest1/" /tmp/up/DEBIAN/control
dpkg-deb -Zgzip -z1 -b /tmp/up /tmp/thoron-up.deb > "$out/repack.txt" 2>&1
apt-get install -y -qq /tmp/thoron-up.deb > "$out/apt-upgrade.txt" 2>&1; echo $? > "$out/upgrade_exit"
dpkg-query -W -f='${Version}' thoron-browser > "$out/version-after.txt" 2>&1
after=$(cd /home/tester/.config/thoron && find . -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum)
[ "$before" = "$after" ] && echo same > "$out/profile-kept" || echo changed > "$out/profile-kept"
opens thoron-browser thoron-again
if [ "$ONLINE" = 1 ]; then
  step widevine
  as_tester python3 -I "$TOOLS/qa/widevine_check.py" --browser /usr/bin/thoron-browser --work /tmp/widevine --no-playback \
    > "$out/widevine.txt" 2>&1; echo $? > "$out/widevine_exit"
fi
if [ "$NETLOG" = 1 ]; then
  step network
  as_tester python3 -I "$TOOLS/qa/netlog_hosts.py" --browser /usr/bin/thoron-browser --work /tmp/netlog --seconds 240 --runs 2 \
    --label "Thoron 158 on Linux" --md "$out/hosts.md" --json "$out/hosts.json" > "$out/netlog.txt" 2>&1
  echo $? > "$out/netlog_exit"
fi
step remove
apt-get remove -y -qq thoron-browser > "$out/apt-remove.txt" 2>&1; echo $? > "$out/remove_exit"
{ [ -e /opt/kuchisofts/thoron ] && echo program; [ -e /usr/bin/thoron-browser ] && echo command
  [ -d /home/tester/.config/thoron/Default ] && echo profile; } > "$out/after-remove.txt"
step done
"""


def wsl_path(path: Path) -> str:
    """A Windows path as WSL sees it: C:\\a\\b is /mnt/c/a/b."""
    p = PureWindowsPath(path)
    return "/mnt/" + p.drive[0].lower() + "/" + "/".join(p.parts[1:])


def read(folder: Path, name: str) -> str:
    try:
        return (folder / name).read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def sandbox_on(text: str) -> list[str]:
    """What chrome://sandbox's text says is missing; empty when the page says the sandbox is on."""
    problems = []
    if not text:
        return ["chrome://sandbox could not be read"]
    flat = " ".join(text.split())
    for layer in ("Seccomp-BPF sandbox", "Namespace"):
        if layer.lower() not in flat.lower():
            problems.append(f"chrome://sandbox does not list {layer}")
    if re.search(r"(?i)you are not adequately sandboxed", flat):
        problems.append("chrome://sandbox says the browser is not adequately sandboxed")
    elif not re.search(r"(?i)you are adequately sandboxed", flat):
        problems.append("chrome://sandbox does not say the browser is adequately sandboxed")
    return problems


def lintian_errors(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith("E: ")]


def owned_files(listing: str) -> set[str]:
    """The regular files of a package, from the machine's own listing of them (folders such as /usr or /opt are
    shared by every package)."""
    return {line.strip() for line in listing.splitlines() if line.startswith("/")}


def problems(found: Path, online: bool) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {"install": [], "names": [], "coexists": [], "sandbox": [], "lintian": [],
                                 "upgrade": [], "remove": []}
    if online:
        out["widevine"] = []
    if read(found, "reached") != "done":
        out["install"].append(f"the run stopped at {read(found, 'reached') or 'its start'}")
    if read(found, "install_exit") != "0":
        out["install"].append(f"apt could not install the package: {read(found, 'apt-install.txt')[-400:]}")
    files = read(found, "files.txt")
    if "/opt/kuchisofts/thoron/thoron" not in files:
        out["install"].append("the program /opt/kuchisofts/thoron/thoron is not among the package's files")
    paths = [p for p in files.splitlines() if p.startswith("/")]
    for issue in audit.audit(paths, "linux"):
        out["names"].append(issue)
    if read(found, "upstream_exit") != "0":
        out["coexists"].append(f"upstream's thorium-browser did not install beside it: "
                               f"{read(found, 'apt-upstream.txt')[-400:]}")
    both = owned_files(read(found, "regular-files.txt")) & owned_files(read(found, "upstream-regular-files.txt"))
    if both:
        out["coexists"].append(f"files that belong to both packages: {sorted(both)[:5]}")
    if not read(found, "which-thoron.txt") or not read(found, "which-thorium.txt"):
        out["coexists"].append("`thoron-browser` or `thorium-browser` is not on the PATH")
    desktop = read(found, "desktop.txt").split()
    if not any(d.startswith("thoron") for d in desktop) or not any(d.startswith("thorium") for d in desktop):
        out["coexists"].append(f"a desktop entry is missing: {[d for d in desktop if 'thor' in d]}")
    for name in ("thoron", "thorium"):
        if read(found, f"{name}-ran") != "running":
            out["coexists"].append(f"{name} did not stay open for 20 s: {read(found, f'{name}-run.txt')[-300:]}")
    dirs = read(found, "config-dirs.txt").split()
    if "thoron" not in dirs or "thorium" not in dirs:
        out["coexists"].append(f"the two profiles are not in their own folders: ~/.config holds {dirs}")
    out["sandbox"] += sandbox_on(read(found, "sandbox.txt"))
    errors = lintian_errors(read(found, "lintian.txt"))
    if errors or not read(found, "lintian.txt") and read(found, "lintian_exit") != "0":
        out["lintian"] += errors[:20] or [f"lintian did not run: {read(found, 'apt-lintian.txt')[-200:]}"]
    if read(found, "upgrade_exit") != "0":
        out["upgrade"].append(f"the higher version did not install: {read(found, 'apt-upgrade.txt')[-400:]}")
    if not read(found, "version-after.txt").endswith("+upgradetest1"):
        out["upgrade"].append(f"the version after the upgrade is {read(found, 'version-after.txt')!r}")
    if read(found, "profile-kept") != "same":
        out["upgrade"].append("the upgrade changed the profile")
    if read(found, "thoron-again-ran") != "running":
        out["upgrade"].append("Thoron did not open again after the upgrade")
    if online and read(found, "widevine_exit") != "0":
        out["widevine"].append(f"tools/qa/widevine_check.py: {read(found, 'widevine.txt')[-500:]}")
    left = read(found, "after-remove.txt").split()
    if read(found, "remove_exit") != "0":
        out["remove"].append(f"apt could not remove the package: {read(found, 'apt-remove.txt')[-300:]}")
    if "program" in left or "command" in left:
        out["remove"].append(f"the removal left Thoron's {' and '.join(x for x in left if x != 'profile')}")
    if "profile" not in left:
        out["remove"].append("the removal took the profile with it")
    return out


def run_machine(name: str, root: Path, work: Path, deb: Path, upstream: Path, online: bool, netlog: bool) -> dict:
    vm.restore(root, name)
    folder = work / name
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    script = folder / "check.sh"
    script.write_bytes(SCRIPT.encode("utf-8"))
    tools = folder / "tools"
    shutil.copytree(REPO / "tools", tools, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    done = subprocess.run(["wsl.exe", "-d", vm.checked_name(name), "-u", "root", "--", "bash", wsl_path(script),
                           wsl_path(folder), wsl_path(deb), wsl_path(upstream), wsl_path(tools), "1" if online else "0", "1" if netlog else "0"],
                          capture_output=True, timeout=3600)
    (folder / "run-output.txt").write_bytes(done.stdout + done.stderr)
    found = problems(folder / "out", online)
    sandbox_text = read(folder / "out", "sandbox.txt")
    return {"machine": name, "version": read(folder / "out", "version.txt"), "problems": found,
            "sandbox_evidence": sandbox_text}


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--deb", type=Path, required=True)
    p.add_argument("--upstream", type=Path, required=True)
    p.add_argument("--root", type=Path, required=True, help="the test machines' folder (wsl_test_vm.py --root)")
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--machine", action="append", choices=vm.MACHINES)
    p.add_argument("--online", action="store_true")
    p.add_argument("--netlog", action="store_true", help="also log the hosts a fresh profile contacts (S.10)")
    p.add_argument("--json", type=Path)
    a = p.parse_args(argv)
    sys.stdout.reconfigure(errors="backslashreplace")
    results = [run_machine(m, a.root, a.work.resolve(), a.deb.resolve(), a.upstream.resolve(), a.online, a.netlog)
               for m in (a.machine or vm.MACHINES)]
    failed = 0
    for r in results:
        print(f"== {r['machine']} (thoron-browser {r['version']})")
        for step, issues in r["problems"].items():
            print(f"{'PASS' if not issues else 'FAIL'}  {step}")
            for issue in issues:
                print(f"      {issue}")
            failed += len(issues)
    if a.json:
        a.json.write_text(json.dumps(results, indent=1), encoding="utf-8")
    print(f"LINUX PACKAGE CHECK: {'PASSED' if not failed else f'FAILED ({failed} problem(s))'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
