#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Saved passwords on Linux with GNOME's keyring (ROADMAP P3.16, P5.8). Run on Windows.

On Linux Chromium keeps the key of saved passwords in the desktop's keyring (GNOME's through libsecret),
under the name `Chromium Safe Storage`; Thoron keeps that name, so a Thorium profile copied into Thoron keeps
its passwords readable without moving a key. On a clean Ubuntu test machine of tools/qa/wsl_test_vm.py, Thoron
and upstream's thorium-browser are installed with GNOME's keyring; in a D-Bus session of the user `tester`
(the keyring unlocked with a made-up password) on the machine's display, through DevTools on 127.0.0.1:

    thorium saves   Thorium saves a made-up password on its password page (the store it would use for a
                    form); Login Data holds it encrypted with the keyring's key ("v11"), never in plain text
    imported        the profile is copied into Thoron (tools/migrate/import_profile.py, verified by SHA-256)
                    and Thoron shows that password, readable, on its own password page
    thoron saves    Thoron saves a second made-up password; after a restart both are there and readable,
                    and Login Data holds both encrypted ("v11")
    one key         the keyring holds the key under `Chromium Safe Storage`, once (Thoron and Thorium share it)

KDE's KWallet asks a person to create a wallet the first time, which a test cannot answer; it is not checked
here.

    py -3 -I tools/qa/linux_keyring_check.py --deb <thoron-browser_*.deb> --upstream <thorium-browser_*.deb>
        --root <test machines folder> --work <scratch> [--machine thoron-test-2404]
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
FIRST = {"url": "https://example.org/login", "username": "thoron-keyring-test", "password": "made-up-secret-one"}
SECOND = {"url": "https://example.com/sign-in", "username": "thoron-keyring-test", "password": "made-up-secret-two"}
STEPS = ("thorium saves", "imported", "thoron saves", "one key")

SCRIPT = r"""#!/bin/bash
# As root inside a clean test machine: $1 work folder, $2 Thoron's .deb, $3 upstream's .deb, $4 tools
set -u
W="$1"; DEB="$2"; UP="$3"; TOOLS="$4"
out="$W/out"; rm -rf "$out"; mkdir -p "$out"; chmod 777 "$out"
export DEBIAN_FRONTEND=noninteractive
cp "$DEB" /tmp/thoron.deb; cp "$UP" /tmp/upstream.deb
apt-get update -qq > "$out/apt-update.txt" 2>&1
apt-get install -y -qq /tmp/thoron.deb /tmp/upstream.deb dbus-x11 gnome-keyring libsecret-tools sqlite3 \
  > "$out/apt-install.txt" 2>&1
echo $? > "$out/install_exit"
runuser -u tester -- env HOME=/home/tester DISPLAY=:0 WAYLAND_DISPLAY=wayland-0 XDG_RUNTIME_DIR=/mnt/wslg/runtime-dir \
  XDG_CURRENT_DESKTOP=GNOME dbus-run-session -- bash -c "
    eval \$(printf 'made-up-keyring-password' | gnome-keyring-daemon --unlock --components=secrets)
    export GNOME_KEYRING_CONTROL SSH_AUTH_SOCK
    python3 -I '$TOOLS/qa/linux_keyring_check.py' probe --tools '$TOOLS' --out '$out/probe.json' > '$out/probe.txt' 2>&1
    secret-tool search --all application chromium > '$out/keyring-chromium.txt' 2>&1
    secret-tool search --all application thorium > '$out/keyring-thorium.txt' 2>&1
    secret-tool search --all application thoron > '$out/keyring-thoron.txt' 2>&1
  "
echo done > "$out/reached"
"""


# ----- inside the test machine -------------------------------------------------------------------------------

def _json_get(url: str):
    import urllib.request
    return json.loads(urllib.request.urlopen(url, timeout=10).read())


def _evaluate(target: dict, expression: str):
    from tools.qa import cdp
    ws = cdp.WebSocket(target["webSocketDebuggerUrl"])
    try:
        got = ws.call("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True)
        return got.get("result", {}).get("value", got.get("exceptionDetails"))
    finally:
        ws.close()


class Browser:
    """A browser started on the display with DevTools on 127.0.0.1 and GNOME's keyring for passwords."""

    def __init__(self, program: str, profile: Path):
        self.profile = profile
        (profile / "DevToolsActivePort").unlink(missing_ok=True)
        self.proc = subprocess.Popen([program, f"--user-data-dir={profile}", "--no-first-run",
                                      "--no-default-browser-check", "--password-store=gnome-libsecret", "--disable-gpu",
                                      "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0",
                                      "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     start_new_session=True)
        end = time.monotonic() + 120       # a first start on a freshly made machine takes a while
        while time.monotonic() < end and not (profile / "DevToolsActivePort").is_file():
            time.sleep(0.5)
        self.port = int((profile / "DevToolsActivePort").read_text().split()[0])
        time.sleep(3)
        import urllib.request
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/json/new?chrome://password-manager/passwords",
                                     method="PUT")
        self.page = json.loads(urllib.request.urlopen(req, timeout=10).read())
        time.sleep(4)

    def evaluate(self, expression: str):
        return _evaluate(self.page, expression)

    def add(self, entry: dict):
        return self.evaluate(
            "chrome.passwordsPrivate.addPassword({url: %s, username: %s, password: %s, note: '', "
            "useAccountStore: false}).then(() => 'added', e => 'failed: ' + e)"
            % (json.dumps(entry["url"]), json.dumps(entry["username"]), json.dumps(entry["password"])))

    def readable(self) -> dict:
        """Every saved password's site and whether its plain text reads back, by site."""
        value = self.evaluate(
            "(async () => { const out = {}; const list = await chrome.passwordsPrivate.getSavedPasswordList();"
            " for (const p of list) { let text = null; try { text = await chrome.passwordsPrivate"
            ".requestPlaintextPassword(p.id, 'VIEW'); } catch (e) { text = 'error: ' + e; }"
            " out[(p.affiliatedDomains[0] || {}).signonRealm || String(p.id)] = text; } return JSON.stringify(out); })()")
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return {"error": str(value)}

    def close(self) -> None:
        import os
        import signal
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)       # as when the session ends: the profile is saved
            self.proc.wait(timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except OSError:
                pass
        time.sleep(2)


def _stored(profile: Path) -> list[str]:
    """The first three bytes of every saved password's encrypted value in Login Data ("v11": GNOME's key)."""
    import sqlite3
    db = sqlite3.connect(f"file:{profile / 'Default' / 'Login Data'}?mode=ro", uri=True)
    try:
        return [bytes(row[0][:3]).decode("ascii", "replace") for row in db.execute("SELECT password_value FROM logins")]
    finally:
        db.close()


def _plain_in(profile: Path) -> bool:
    data = (profile / "Default" / "Login Data").read_bytes()
    return any(e["password"].encode() in data for e in (FIRST, SECOND))


def probe(tools: Path, out: Path) -> int:
    home = Path.home()
    thorium, thoron = home / ".config/thorium", home / ".config/thoron"
    found: dict = {}
    try:
        b = Browser("/usr/bin/thorium-browser", thorium)
        found["thorium_added"] = b.add(FIRST)
        time.sleep(3)
        b.close()
        found["thorium_stored"] = _stored(thorium)
        found["thorium_plain"] = _plain_in(thorium)
        time.sleep(35)        # the copy waits until the closed browser has written its last files
        copy = subprocess.run([sys.executable, "-I", str(tools / "migrate" / "import_profile.py"), "--from", str(thorium),
                               "--to", str(thoron)], capture_output=True, text=True, timeout=600)
        found["import_exit"] = copy.returncode
        found["import_text"] = (copy.stdout + copy.stderr)[-600:]
        b = Browser("/usr/bin/thoron-browser", thoron)
        found["imported_readable"] = b.readable()
        found["thoron_added"] = b.add(SECOND)
        time.sleep(3)
        b.close()
        b = Browser("/usr/bin/thoron-browser", thoron)
        found["after_restart"] = b.readable()
        b.close()
        found["thoron_stored"] = _stored(thoron)
        found["thoron_plain"] = _plain_in(thoron)
    except Exception as exc:  # the reason goes into the results; the host reads it
        found["error"] = f"{type(exc).__name__}: {exc}"
    out.write_text(json.dumps(found), encoding="utf-8")
    return 0


# ----- on Windows ----------------------------------------------------------------------------------------------

def _site(entry: dict) -> str:
    return entry["url"].split("/")[2]


def problems(found: dict, keyring: dict[str, str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {step: [] for step in STEPS}
    if found.get("error"):
        out["thorium saves"].append(f"the probe stopped: {found['error']}")
    if found.get("thorium_added") != "added" or found.get("thorium_stored") != ["v11"] or found.get("thorium_plain"):
        out["thorium saves"].append(f"Thorium: added {found.get('thorium_added')!r}, stored as "
                                    f"{found.get('thorium_stored')!r}, plain text in the file: {found.get('thorium_plain')}")
    readable = found.get("imported_readable") or {}
    if found.get("import_exit") != 0:
        out["imported"].append(f"the copy failed: {found.get('import_text')!r}")
    if not any(_site(FIRST) in site and text == FIRST["password"] for site, text in readable.items()):
        out["imported"].append(f"Thoron does not read Thorium's password: {readable}")
    after = found.get("after_restart") or {}
    for entry in (FIRST, SECOND):
        if not any(_site(entry) in site and text == entry["password"] for site, text in after.items()):
            out["thoron saves"].append(f"after a restart {_site(entry)} is not readable: {after}")
    if found.get("thoron_added") != "added" or sorted(found.get("thoron_stored") or []) != ["v11", "v11"] \
            or found.get("thoron_plain"):
        out["thoron saves"].append(f"Thoron: added {found.get('thoron_added')!r}, stored as "
                                   f"{found.get('thoron_stored')!r}, plain text in the file: {found.get('thoron_plain')}")
    keys = [block for block in keyring.get("chromium", "").split("[/") if "Chromium Safe Storage" in block]
    if len(keys) != 1:
        out["one key"].append(f"{len(keys)} `Chromium Safe Storage` entries in the keyring (want 1)")
    for app in ("thorium", "thoron"):
        if "label = " in keyring.get(app, ""):
            out["one key"].append(f"the keyring holds an entry of its own for {app}")
    return out


def run_machine(name: str, root: Path, work: Path, deb: Path, upstream: Path) -> dict[str, list[str]]:
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
                           lp.wsl_path(folder), lp.wsl_path(deb), lp.wsl_path(upstream), lp.wsl_path(tools)],
                          capture_output=True, timeout=1800)
    (folder / "run-output.txt").write_bytes(done.stdout + done.stderr)
    out = folder / "out"
    if lp.read(out, "install_exit") != "0":
        return {"install": [f"the packages did not install: {lp.read(out, 'apt-install.txt')[-400:]}"]}
    try:
        found = json.loads(lp.read(out, "probe.json") or "{}")
    except ValueError:
        found = {}
    if not found:
        return {"probe": [f"the probe wrote nothing: {lp.read(out, 'probe.txt')[-400:]}"]}
    keyring = {app: lp.read(out, f"keyring-{app}.txt") for app in ("chromium", "thorium", "thoron")}
    return problems(found, keyring)


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command")
    pr = sub.add_parser("probe", help="inside a test machine (used by the check itself)")
    pr.add_argument("--tools", type=Path, required=True)
    pr.add_argument("--out", type=Path, required=True)
    p.add_argument("--deb", type=Path)
    p.add_argument("--upstream", type=Path)
    p.add_argument("--root", type=Path)
    p.add_argument("--work", type=Path)
    p.add_argument("--machine", action="append")
    a = p.parse_args(argv)
    if a.command == "probe":
        return probe(a.tools, a.out)
    if not (a.deb and a.upstream and a.root and a.work):
        p.error("--deb, --upstream, --root and --work are needed")
    from tools.qa import wsl_test_vm as vm
    failed = 0
    for name in a.machine or vm.MACHINES:
        print(f"== {name}")
        for step, issues in run_machine(name, a.root, a.work.resolve(), a.deb.resolve(), a.upstream.resolve()).items():
            print(f"{'PASS' if not issues else 'FAIL'}  {step}")
            for issue in issues:
                print(f"      {issue}")
            failed += len(issues)
    print(f"LINUX KEYRING CHECK: {'PASSED' if not failed else f'FAILED ({failed} problem(s))'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
