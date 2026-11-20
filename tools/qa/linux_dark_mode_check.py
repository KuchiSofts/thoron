#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Thoron on Linux follows the desktop's light and dark style while it runs (ROADMAP P2.22). Run on Windows.

Chromium 158 reads the desktop's style from the XDG desktop portal (`org.freedesktop.appearance`
`color-scheme`, what GNOME's and KDE's Settings write) and listens for its changes; Thorium's own patch for this
was not carried over to 158. This check proves it on a clean Ubuntu test machine of tools/qa/wsl_test_vm.py:
the .deb is installed with the portal and its GTK backend, and in a D-Bus session of the user `tester` on the
machine's display (WSLg) Thoron is started with DevTools on 127.0.0.1 and a throwaway profile. Then the
desktop's style is switched as GNOME's Settings switch it (`gsettings set org.gnome.desktop.interface
color-scheme`), without restarting anything:

    starts light  with the style "default" a web page and Thoron's own Settings page see a light scheme
                  (`prefers-color-scheme: light`)
    goes dark     after "prefer-dark" both see a dark scheme within 10 s
    back light    after "default" again both are light again within 10 s

    py -3 -I tools/qa/linux_dark_mode_check.py --deb <thoron-browser_*.deb> --root <test machines folder>
        --work <scratch> [--machine thoron-test-2404]
Exit status 0 only when every step passes on every machine.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

if __package__ in (None, ""):  # running as a script: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

REPO = Path(__file__).resolve().parents[2]
STEPS = (("starts light", "default", False), ("goes dark", "prefer-dark", True), ("back light", "default", False))

SCRIPT = r"""#!/bin/bash
# As root inside a clean test machine: $1 work folder, $2 Thoron's .deb, $3 tools
set -u
W="$1"; DEB="$2"; TOOLS="$3"
out="$W/out"; rm -rf "$out"; mkdir -p "$out"; chmod 777 "$out"
export DEBIAN_FRONTEND=noninteractive
cp "$DEB" /tmp/thoron.deb
apt-get update -qq > "$out/apt-update.txt" 2>&1
apt-get install -y -qq /tmp/thoron.deb dbus-x11 dbus-user-session xdg-desktop-portal xdg-desktop-portal-gtk \
  dconf-cli dconf-gsettings-backend gsettings-desktop-schemas > "$out/apt-install.txt" 2>&1
echo $? > "$out/install_exit"
# the machine's display (WSLg) comes up a little after the machine starts
for i in $(seq 90); do [ -S /tmp/.X11-unix/X0 ] && [ -S /mnt/wslg/runtime-dir/wayland-0 ] && break; sleep 1; done
[ -S /tmp/.X11-unix/X0 ] && echo yes > "$out/display" || echo no > "$out/display"
mkdir -p /home/tester/.config/xdg-desktop-portal
printf '[preferred]\ndefault=gtk\n' > /home/tester/.config/xdg-desktop-portal/portals.conf
chown -R tester:tester /home/tester/.config
runuser -u tester -- env HOME=/home/tester DISPLAY=:0 WAYLAND_DISPLAY=wayland-0 XDG_RUNTIME_DIR=/mnt/wslg/runtime-dir \
  XDG_CURRENT_DESKTOP=GNOME dbus-run-session -- bash -c "
    gsettings set org.gnome.desktop.interface color-scheme default
    portal=\$(ls /usr/libexec/xdg-desktop-portal /usr/lib/xdg-desktop-portal 2>/dev/null | head -1)
    gtkportal=\$(ls /usr/libexec/xdg-desktop-portal-gtk /usr/lib/xdg-desktop-portal-gtk 2>/dev/null | head -1)
    \$gtkportal > '$out/portal-gtk.txt' 2>&1 &
    sleep 2
    \$portal > '$out/portal.txt' 2>&1 &
    sleep 3
    python3 -I '$TOOLS/qa/linux_dark_mode_check.py' probe --browser /usr/bin/thoron-browser --out '$out/probe.json' \
      > '$out/probe.txt' 2>&1
  "
echo done > "$out/reached"
"""


# ----- inside the test machine -------------------------------------------------------------------------------

SCHEME_JS = "matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'"


def _targets(port: int) -> list[dict]:
    import urllib.request
    return json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=10).read())


def _open(port: int, url: str) -> dict:
    import urllib.request
    req = urllib.request.Request(f"http://127.0.0.1:{port}/json/new?{url}", method="PUT")
    return json.loads(urllib.request.urlopen(req, timeout=10).read())


def _evaluate(target: dict, expression: str):
    from tools.qa import cdp
    ws = cdp.WebSocket(target["webSocketDebuggerUrl"])
    try:
        return ws.call("Runtime.evaluate", expression=expression, returnByValue=True)["result"].get("value")
    finally:
        ws.close()


def probe(browser: Path, out: Path) -> int:
    """Run in the machine's D-Bus session: start Thoron, switch the style, read what pages see."""
    import tempfile
    from tools.qa.bench import _stop
    work = Path(tempfile.mkdtemp(prefix="thoron-dark-"))
    profile = work / "profile"
    port_file = profile / "DevToolsActivePort"
    proc = subprocess.Popen([str(browser), f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
                             "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0",
                             "data:text/html,<title>page</title>light or dark"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    results: dict = {"steps": {}}
    try:
        end = time.monotonic() + 30
        while time.monotonic() < end and not port_file.is_file():
            time.sleep(0.5)
        port = int(port_file.read_text().split()[0])
        time.sleep(3)
        page = next(x for x in _targets(port) if x.get("url", "").startswith("data:"))
        settings = _open(port, "chrome://settings/appearance")
        time.sleep(4)
        for name, style, dark in STEPS:
            subprocess.run(["gsettings", "set", "org.gnome.desktop.interface", "color-scheme", style], check=False)
            want = "dark" if dark else "light"
            seen = {}
            end = time.monotonic() + 10
            while time.monotonic() < end:
                seen = {"page": _evaluate(page, SCHEME_JS), "settings": _evaluate(settings, SCHEME_JS)}
                if seen == {"page": want, "settings": want}:
                    break
                time.sleep(0.5)
            results["steps"][name] = {"want": want, "seen": seen}
    except Exception as exc:  # the reason goes into the results; the host reads it
        results["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        _stop(proc, work)
    out.write_text(json.dumps(results), encoding="utf-8")
    return 0


# ----- on Windows ----------------------------------------------------------------------------------------------

def problems(found: dict) -> list[str]:
    out = []
    if found.get("error"):
        out.append(f"the probe stopped: {found['error']}")
    steps = found.get("steps") or {}
    for name, _style, dark in STEPS:
        step = steps.get(name)
        want = "dark" if dark else "light"
        if not step:
            out.append(f"{name}: not reached")
        elif step.get("seen") != {"page": want, "settings": want}:
            out.append(f"{name}: wanted {want}, the page and Settings saw {step.get('seen')}")
    return out


def run_machine(name: str, root: Path, work: Path, deb: Path) -> list[str]:
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
                           lp.wsl_path(folder), lp.wsl_path(deb), lp.wsl_path(tools)], capture_output=True, timeout=1800)
    (folder / "run-output.txt").write_bytes(done.stdout + done.stderr)
    out = folder / "out"
    if lp.read(out, "install_exit") != "0":
        return [f"the packages did not install: {lp.read(out, 'apt-install.txt')[-400:]}"]
    try:
        found = json.loads(lp.read(out, "probe.json") or "{}")
    except ValueError:
        found = {}
    if not found:
        return [f"the probe wrote nothing: {lp.read(out, 'probe.txt')[-400:]}"]
    return problems(found)


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command")
    pr = sub.add_parser("probe", help="inside a test machine (used by the check itself)")
    pr.add_argument("--browser", type=Path, required=True)
    pr.add_argument("--out", type=Path, required=True)
    p.add_argument("--deb", type=Path)
    p.add_argument("--root", type=Path)
    p.add_argument("--work", type=Path)
    p.add_argument("--machine", action="append")
    a = p.parse_args(argv)
    if a.command == "probe":
        return probe(a.browser, a.out)
    if not (a.deb and a.root and a.work):
        p.error("--deb, --root and --work are needed")
    from tools.qa import wsl_test_vm as vm
    failed = 0
    for name in a.machine or vm.MACHINES:
        issues = run_machine(name, a.root, a.work.resolve(), a.deb.resolve())
        print(f"{'PASS' if not issues else 'FAIL'}  {name}")
        for issue in issues:
            print(f"      {issue}")
        failed += len(issues)
    print(f"LINUX DARK MODE CHECK: {'PASSED' if not failed else f'FAILED ({failed} problem(s))'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
