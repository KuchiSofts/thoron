#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""The update of a Linux portable copy (ROADMAP P3.12, P3.6), run inside a Linux machine by
tools/qa/linux_portable_check.py. Offline: the browser runs headless and nothing is downloaded.

As the Windows check does (tools/qa/portable_launcher_check.py), the build in the package is put in twice: the
package's own version and, beside it, the same files as a newer version, so which one a start runs is told by the
folder `chrome://version` names. In the package's folder:

    start     `./thoron` starts the version `current` names, with the profile in the package; the home page is
              set (a setting of the profile)
    update    the updater of that version, `thoron_update --apply`, puts the newer version in place; the next
              start runs it and keeps the home page
    status    `thoron_update --status` names the newer version as current and the older as previous
    rollback  `thoron_update --rollback --confirm`; the next start runs the older version again, the home page kept

    python3 -I tools/qa/linux_portable_update.py --package <ThoronPortable folder> --out <results.json>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

if __package__ in (None, ""):  # running as a script: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.qa.cdp import WebSocket  # noqa: E402

HOME = "https://example.org/thoron-portable-update"


def newer_than(version: str) -> str:
    parts = version.split(".")
    parts[-1] = str(int(parts[-1]) + 1)
    return ".".join(parts)


def files_list(folder: Path) -> list[dict]:
    """The version's files as the updater checks them: path with '/', size, SHA-256."""
    return [{"path": p.relative_to(folder).as_posix(), "size": p.stat().st_size,
             "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in sorted(folder.rglob("*")) if p.is_file() and not p.is_symlink()]


def _json(url: str, method: str = "GET"):
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, method=method), timeout=10).read())


def _evaluate(target: dict, expression: str):
    ws = WebSocket(target["webSocketDebuggerUrl"])
    try:
        got = ws.call("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True)
        return got.get("result", {}).get("value")
    finally:
        ws.close()


def one_start(package: Path, set_home: bool) -> dict:
    """Start the package through its launcher, read where the browser runs from and its home page, maybe set
    the home page, and close it the normal way."""
    port_file = package / "User Data" / "DevToolsActivePort"
    port_file.unlink(missing_ok=True)
    proc = subprocess.Popen([str(package / "thoron"), "--headless=new", "--no-first-run", "--no-default-browser-check",
                             "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    found: dict = {}
    try:
        end = time.monotonic() + 120
        while time.monotonic() < end and not port_file.is_file():
            time.sleep(0.5)
        port = int(port_file.read_text().split()[0])
        version_page = _json(f"http://127.0.0.1:{port}/json/new?chrome://version", "PUT")
        time.sleep(3)
        found["executable_path"] = _evaluate(version_page, "document.getElementById('executable_path').innerText")
        found["profile_path"] = _evaluate(version_page, "document.getElementById('profile_path').innerText")
        settings = _json(f"http://127.0.0.1:{port}/json/new?chrome://settings/", "PUT")
        time.sleep(3)
        if set_home:
            _evaluate(settings, f"chrome.settingsPrivate.setPref('homepage', '{HOME}', '').then(() => 'set')")
            time.sleep(2)
        found["home"] = _evaluate(settings, "chrome.settingsPrivate.getPref('homepage').then(p => p.value)")
        browser = _json(f"http://127.0.0.1:{port}/json/version")
        ws = WebSocket(browser["webSocketDebuggerUrl"])
        try:
            ws.call("Browser.close")                    # a normal exit: the profile is saved
        except (ConnectionError, OSError):
            pass
        finally:
            ws.close()
        proc.wait(timeout=60)
    except Exception as exc:  # the reason goes into the results
        found["error"] = f"{type(exc).__name__}: {exc}"
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
    time.sleep(2)
    return found


def cli(program: Path, *args: str) -> tuple[int, str]:
    done = subprocess.run([str(program), *args], capture_output=True, text=True, timeout=600)
    return done.returncode, done.stdout + done.stderr


def run(package: Path) -> dict:
    app = package / "Application"
    older = (app / "current").read_text().split()[0]
    newer = newer_than(older)
    out: dict = {"older": older, "newer": newer}
    out["start"] = one_start(package, set_home=True)
    staged = app / f"{newer}.staging"
    shutil.copytree(app / older, staged, symlinks=True)
    listing = package.parent / f"{package.name}.files.json"
    listing.write_text(json.dumps(files_list(staged)), encoding="utf-8")
    out["apply"] = cli(app / older / "thoron_update", f"--root={app}", f"--apply={staged}", f"--version={newer}",
                       f"--files={listing}")
    out["update"] = one_start(package, set_home=False)
    out["status"] = cli(app / newer / "thoron_update", f"--root={app}", "--status")
    out["rollback_cli"] = cli(app / newer / "thoron_update", f"--root={app}", "--rollback", "--confirm")
    out["rollback"] = one_start(package, set_home=False)
    return out


def problems(found: dict, package: str) -> dict[str, list[str]]:
    """What the results say is wrong, step by step."""
    out: dict[str, list[str]] = {"start": [], "update": [], "status": [], "rollback": []}
    older, newer = found.get("older", "?"), found.get("newer", "?")

    def started(step: str, version: str) -> None:
        s = found.get(step) or {}
        if s.get("error"):
            out[step].append(f"{step}: {s['error']}")
        if not str(s.get("executable_path", "")).startswith(f"{package}/Application/{version}/"):
            out[step].append(f"{step}: ran {s.get('executable_path')!r}, not version {version}")
        if not str(s.get("profile_path", "")).startswith(f"{package}/User Data"):
            out[step].append(f"{step}: the profile is {s.get('profile_path')!r}")
        if s.get("home") != HOME:
            out[step].append(f"{step}: the home page is {s.get('home')!r}")
    started("start", older)
    code, text = found.get("apply") or (None, "")
    if code != 0:
        out["update"].append(f"thoron_update --apply gave {code}: {str(text).strip()[-300:]}")
    started("update", newer)
    code, text = found.get("status") or (None, "")
    if code != 0 or not str(text).startswith(f"current: {newer}\nprevious: {older}\n"):
        out["status"].append(f"--status gave {code}: {str(text)[:200]!r}")
    code, text = found.get("rollback_cli") or (None, "")
    if code != 0:
        out["rollback"].append(f"thoron_update --rollback gave {code}: {str(text).strip()[-300:]}")
    started("rollback", older)
    return out


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--package", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args(argv)
    found = run(a.package.resolve())
    a.out.write_text(json.dumps(found), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
