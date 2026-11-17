#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""What a portable copy leaves on a PC that never had Thoron (ROADMAP P3.10, P3.12). Windows only.

docs/release/PORTABLE.md lists what a portable copy writes outside its folder, measured on a PC that has an
installed Thoron, where the check cannot tell the portable copy's writes from the installed one's. Windows
Sandbox is a PC that never had Thoron (a clean Windows, gone when it closes; networking off). In it the
portable package is unpacked to a folder, and before and after two starts of its launcher (each with a
window, closed the way a person closes it, the second one after the folder was moved) this is written down:

    registry      every key and value under HKEY_CURRENT_USER (reg export)
    tasks         the scheduled tasks
    folders       the names under %LOCALAPPDATA%, %APPDATA% and %TEMP%, two levels deep

The two snapshots are compared here: what is new or changed after the starts is the portable copy's trace.

    py -3 -I tools/qa/sandbox_portable_traces.py --chrome-bin <Chrome-bin> --launcher <out>\\thoron_launcher.exe
        --updater <out>\\thoron_update.exe --work <scratch> [--md <report.md>]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.qa import sandbox_install_check as sb  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
RUN = r"""$ErrorActionPreference = 'Continue'
$out = 'C:\ThoronTest\out'
$r = [ordered]@{}
function Trace($text) { Add-Content -Encoding utf8 -Path (Join-Path $out 'trace.txt') -Value "$(Get-Date -Format HH:mm:ss) $text" }
function Snapshot($name) {
  reg.exe export HKCU (Join-Path $out "$name-hkcu.reg") /y | Out-Null
  schtasks.exe /query /fo csv /nh 2>$null | Set-Content -Encoding utf8 (Join-Path $out "$name-tasks.csv")
  $names = foreach ($root in @($env:LOCALAPPDATA, $env:APPDATA, $env:TEMP)) {
    Get-ChildItem $root -ErrorAction SilentlyContinue | ForEach-Object {
      $_.FullName
      if ($_.PSIsContainer) { Get-ChildItem $_.FullName -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName } }
    }
  }
  $names | Sort-Object | Set-Content -Encoding utf8 (Join-Path $out "$name-folders.txt")
}
function StartAndClose($launcher) {
  Start-Process $launcher -ArgumentList '--no-first-run', 'about:blank' | Out-Null
  Start-Sleep -Seconds 25
  $r["windows_$($r.Count)"] = @(Get-Process thoron -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 }).Count
  Get-Process thoron -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | ForEach-Object { [void]$_.CloseMainWindow() }
  $end = (Get-Date).AddSeconds(30)
  while ((Get-Process thoron -ErrorAction SilentlyContinue) -and (Get-Date) -lt $end) { Start-Sleep -Seconds 1 }
  Get-Process thoron -ErrorAction SilentlyContinue | Stop-Process -Force
  Start-Sleep -Seconds 3
}
try {
  $folder = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'Portable test'
  New-Item -ItemType Directory -Force $folder | Out-Null
  Trace 'unpack'
  Expand-Archive -Path (Get-ChildItem 'C:\ThoronTest\in' -Filter '*.zip' | Select-Object -First 1).FullName -DestinationPath $folder
  $r.unpacked = Test-Path (Join-Path $folder 'ThoronPortable\Thoron.exe')
  Trace 'before'
  Snapshot 'before'
  Trace 'start 1'
  StartAndClose (Join-Path $folder 'ThoronPortable\Thoron.exe')
  $moved = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Thoron moved'
  Move-Item (Join-Path $folder 'ThoronPortable') $moved
  Trace 'start 2 after the move'
  StartAndClose (Join-Path $moved 'Thoron.exe')
  $r.profile = Test-Path (Join-Path $moved 'User Data\Local State')
  Trace 'after'
  Snapshot 'after'
} catch {
  $r.error = "$_"
}
$r.done = $true
$r | ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $out 'results.json')
Trace 'done'
Stop-Computer -Force
"""
_KEY = re.compile(r"^\[(.+)\]$")


def reg_entries(text: str) -> dict[str, dict[str, str]]:
    """A `reg export` file as {key: {value name: data}} (a value's data may span lines ending in a backslash)."""
    keys: dict[str, dict[str, str]] = {}
    current = None
    pending = ""
    for raw in text.splitlines():
        line = pending + raw.strip() if pending else raw.rstrip()
        if line.endswith("\\") and current is not None and not _KEY.match(line):
            pending = line[:-1]
            continue
        pending = ""
        match = _KEY.match(line)
        if match:
            current = match.group(1)
            keys.setdefault(current, {})
        elif current is not None and "=" in line:
            name, _, data = line.partition("=")
            keys[current][name] = data
    return keys


def reg_changes(before: dict, after: dict) -> list[str]:
    out = []
    for key in sorted(after):
        if key not in before:
            out.append(f"new key {key}" + (f" ({len(after[key])} value(s))" if after[key] else ""))
            continue
        for name in sorted(after[key]):
            if name not in before[key]:
                out.append(f"new value {key} {name}")
            elif after[key][name] != before[key][name]:
                out.append(f"changed value {key} {name}")
    return out


def line_changes(before: str, after: str) -> list[str]:
    old = set(before.splitlines())
    return sorted(line for line in set(after.splitlines()) - old if line.strip())


def task_changes(before: str, after: str) -> list[str]:
    """New scheduled tasks, by name (a task's line also holds its next run time, which Windows changes)."""
    name = lambda text: {line.split('","')[0].strip('"') for line in text.splitlines() if line.strip()}
    return sorted(name(after) - name(before))


# Windows changes these under HKCU by itself while a program runs (what Explorer and the shell record about
# programs, window places, the notification area): Windows' own record, not Thoron's.
WINDOWS_OWN = re.compile(r"(?i)\\Software\\Microsoft\\Windows\\(CurrentVersion\\(Explorer|Search|Notifications|"
                         r"CloudStore|Shell Extensions|Internet Settings|ContentDeliveryManager|PushNotifications|FileAssociations|"
                         r"Store|BackgroundAccessApplications|CapabilityAccessManager)|Shell(NoRoam)?|Winlogon)|"
                         r"\\Software\\Classes\\Local Settings|\\Software\\Microsoft\\(Windows NT|InputPersonalization|"
                         r"Input|CTF|IdentityCRL|Office|OneDrive|Edge|EdgeUpdate|Speech_OneCore)|\\System\\GameConfigStore")


def traces(out: Path) -> dict[str, list[str]]:
    read = lambda name: (out / name).read_text(encoding="utf-16" if name.endswith(".reg") else "utf-8-sig",
                                               errors="replace") if (out / name).is_file() else ""
    registry = reg_changes(reg_entries(read("before-hkcu.reg")), reg_entries(read("after-hkcu.reg")))
    return {"registry": [c for c in registry if not WINDOWS_OWN.search(c)],
            "registry_windows_own": [c for c in registry if WINDOWS_OWN.search(c)],
            "tasks": task_changes(read("before-tasks.csv"), read("after-tasks.csv")),
            "folders": [re.sub(r"(?i)^C:\\Users\\[^\\]+", "%USERPROFILE%", f)  # privacy-check: allow (it hides them)
                        for f in line_changes(read("before-folders.txt"), read("after-folders.txt"))]}


def report(found: dict[str, list[str]]) -> str:
    lines = ["What a portable copy left on a PC that never had Thoron (two starts, the second after a move):", ""]
    for name, title in (("registry", "Registry under HKEY_CURRENT_USER"), ("tasks", "Scheduled tasks"),
                        ("folders", "Names in %LOCALAPPDATA%, %APPDATA% and %TEMP%")):
        lines.append(f"{title}: " + ("none" if not found[name] else ""))
        lines += [f"- {c}" for c in found[name]]
    lines.append(f"(Windows' own records of the run left aside: {len(found['registry_windows_own'])} registry "
                 "change(s) under Explorer, the shell and the like.)")
    return "\n".join(lines) + "\n"


def run(chrome_bin: Path, launcher: Path, updater: Path, work: Path, timeout: float) -> tuple[dict, dict]:
    if work.exists():
        shutil.rmtree(work)
    (work / "in").mkdir(parents=True)
    (work / "out").mkdir()
    made = subprocess.run([sys.executable, "-I", str(REPO / "tools/release/portable.py"), "build", "--chrome-bin",
                           str(chrome_bin), "--launcher", str(launcher), "--updater", str(updater), "--dist",
                           str(work / "dist"), "--variant", "win-x64-avx2"], capture_output=True, text=True)
    if made.returncode:
        return {"error": f"the portable package could not be made: {made.stdout[-300:]} {made.stderr[-300:]}"}, {}
    shutil.copy2(next((work / "dist").glob("*-portable.zip")), work / "in")
    (work / "in" / "run.ps1").write_text(RUN, encoding="utf-8-sig", newline="\r\n")
    config = work / "thoron-portable.wsb"
    config.write_text(sb.wsb(work), encoding="utf-8")
    subprocess.Popen([sb.SANDBOX, str(config)])
    results = work / "out" / "results.json"
    end = time.monotonic() + timeout
    found = sb.read_results(results)
    while time.monotonic() < end and not found.get("done"):
        time.sleep(5)
        found = sb.read_results(results)
    sb.close_sandbox()
    return found, traces(work / "out")


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--chrome-bin", type=Path, required=True)
    p.add_argument("--launcher", type=Path, required=True)
    p.add_argument("--updater", type=Path, required=True)
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--timeout", type=float, default=900)
    p.add_argument("--md", type=Path)
    a = p.parse_args(argv)
    found, left = run(a.chrome_bin.resolve(), a.launcher.resolve(), a.updater.resolve(), a.work.resolve(), a.timeout)
    print(json.dumps(found))
    if found.get("error") or not found.get("done") or not found.get("profile"):
        print(f"PORTABLE TRACES: NOT MEASURED ({found.get('error') or 'the run did not end with a profile'})")
        return 1
    text = report(left)
    print(text)
    if a.md:
        a.md.write_text(text, encoding="utf-8", newline="\n")
    clean = not (left["registry"] or left["tasks"] or left["folders"])
    print(f"PORTABLE TRACES: {'NONE' if clean else 'FOUND'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
