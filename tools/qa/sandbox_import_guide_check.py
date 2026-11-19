#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""The import guide, sections 1 and 2, followed on a clean Windows (ROADMAP D.2). Windows only.

docs/user/IMPORT.md tells a person to install Python, unpack Thoron's repository, close the browsers, list
them with tools\\migrate\\detect.py and bring Thorium's whole profile over with tools\\migrate\\import_profile.py.
Windows Sandbox (a clean Windows, gone when it closes; networking off) gets Thoron's installer, the repository's
`tools` folder and README, and a copy of Python's own files (the interpreter and its standard library, the
tools need nothing else; a clean Windows has no Python, and the Sandbox no network to fetch one). There is no
Thorium in it, so the script makes a Thorium profile the way Thorium would: Thoron's own program started on
`%LOCALAPPDATA%\\Thorium\\User Data` (the tools know a running browser by its `lockfile`, which any Chromium
makes), with a file put into the profile to follow it. Then, with `python.exe -I` where the guide writes
`py -3 -I` (the same interpreter, without the launcher Python's installer adds):

    detect, running    Thorium is listed with its profile and marked "(running: close it before an import)"
    import, running    the import refuses while Thorium runs
    import, too soon   right after Thorium closed it asks to wait half a minute
    detect             Thorium is listed with its Default profile, not running
    import             into the installed Thoron before its first start: it ends with 0, the report is
                       beside the destination, and the file put into Thorium's profile is in Thoron's
    first start        Thoron starts on the imported profile, and the file is still there
    import, again      into a Thoron that has a profile: it refuses and changes nothing

    py -3 -I tools/qa/sandbox_import_guide_check.py --installer <thoron_AVX2_mini_installer.exe> --work <scratch>
"""
from __future__ import annotations

import argparse
import json
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
function Save { $r | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 (Join-Path $out 'results.json') }
function Trace($text) { Add-Content -Encoding utf8 -Path (Join-Path $out 'trace.txt') -Value "$(Get-Date -Format HH:mm:ss) $text" }
function Mark($step) { $r.reached = $step; Save; Trace "step: $step" }
$python = 'C:\ThoronTest\in\python\python.exe'
function Tool($arguments) {
  # one of the guide's commands: its exit code and what it printed
  $o = Join-Path $env:TEMP 'tool-out.txt'; $e = Join-Path $env:TEMP 'tool-err.txt'
  $p = Start-Process $python -ArgumentList (@('-I') + $arguments) -RedirectStandardOutput $o -RedirectStandardError $e `
         -NoNewWindow -PassThru
  $null = $p.Handle
  if (-not $p.WaitForExit(300000)) { Stop-Process -Id $p.Id -Force; return @{ exit = 'timeout'; text = '' } }
  return @{ exit = $p.ExitCode; text = ("$(Get-Content $o -Raw -ErrorAction SilentlyContinue)" + "$(Get-Content $e -Raw -ErrorAction SilentlyContinue)") }
}
function Windows { Get-Process thoron -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } }
function Close {
  Windows | ForEach-Object { [void]$_.CloseMainWindow() }
  $end = (Get-Date).AddSeconds(30)
  while ((Get-Process thoron -ErrorAction SilentlyContinue) -and (Get-Date) -lt $end) { Start-Sleep -Seconds 1 }
  Get-Process thoron -ErrorAction SilentlyContinue | Stop-Process -Force
}
$app = Join-Path $env:LOCALAPPDATA 'Thoron\Application'
$thorium = "$env:LOCALAPPDATA\Thorium\User Data"
$thoron = "$env:LOCALAPPDATA\Thoron\User Data"
try {
  Mark 'install Thoron (not its first start)'
  $copy = Join-Path $env:TEMP 'installer.exe'
  Copy-Item (Get-ChildItem 'C:\ThoronTest\in\install' -Filter '*.exe' | Select-Object -First 1).FullName $copy
  $p = Start-Process $copy -ArgumentList '--silent', '--do-not-launch-chrome' -PassThru
  $null = $p.WaitForExit(300000)
  $r.installed = Test-Path (Join-Path $app 'thoron.exe')

  Mark 'section 1: the repository unpacked, a terminal in it'
  $repo = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'thoron-main'
  Copy-Item 'C:\ThoronTest\in\thoron-main' $repo -Recurse
  Set-Location $repo

  Mark 'a Thorium profile'
  Start-Process (Join-Path $app 'thoron.exe') -ArgumentList "--user-data-dir=`"$thorium`"", '--no-first-run', 'about:blank' | Out-Null
  Start-Sleep -Seconds 25
  $r.thorium_window = [bool](Windows)
  $r.thorium_profile = Test-Path (Join-Path $thorium 'Local State')

  Mark 'detect while Thorium runs'
  $t = Tool @('tools\migrate\detect.py'); $r.detect_running = $t
  Mark 'import while Thorium runs'
  $t = Tool @('tools\migrate\import_profile.py', '--from', "`"$thorium`"", '--to', "`"$thoron`""); $r.import_running = $t
  Close
  Set-Content -Path (Join-Path $thorium 'Default\thorium-marker.txt') -Value 'came along'
  Mark 'import right after Thorium closed'
  $t = Tool @('tools\migrate\import_profile.py', '--from', "`"$thorium`"", '--to', "`"$thoron`""); $r.import_too_soon = $t
  Start-Sleep -Seconds 40

  Mark 'detect'
  $t = Tool @('tools\migrate\detect.py'); $r.detect = $t
  Mark 'import'
  $t = Tool @('tools\migrate\import_profile.py', '--from', "`"$thorium`"", '--to', "`"$thoron`""); $r.import = $t
  $r.report = Test-Path "$env:LOCALAPPDATA\Thoron\Thoron import report.json"
  $r.marker_copied = Test-Path (Join-Path $thoron 'Default\thorium-marker.txt')

  Mark 'first start on the imported profile'
  Start-Process (Join-Path $app 'thoron.exe') -ArgumentList '--no-first-run', 'about:blank' | Out-Null
  Start-Sleep -Seconds 25
  $r.thoron_window = [bool](Windows)
  Close
  Start-Sleep -Seconds 40
  $r.marker_kept = Test-Path (Join-Path $thoron 'Default\thorium-marker.txt')

  Mark 'import again'
  $t = Tool @('tools\migrate\import_profile.py', '--from', "`"$thorium`"", '--to', "`"$thoron`""); $r.import_again = $t
  $r.marker_after_again = Test-Path (Join-Path $thoron 'Default\thorium-marker.txt')
} catch {
  $r.error = "$_"
}
$r.done = $true
Save
Trace 'done'
Stop-Computer -Force
"""


def _text(r: dict, key: str) -> str:
    return str((r.get(key) or {}).get("text", ""))


def _exit(r: dict, key: str):
    return (r.get(key) or {}).get("exit")


def problems(r: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}

    def check(step: str, ok: bool, text: str) -> None:
        out.setdefault(step, [])
        if not ok:
            out[step].append(text)

    if r.get("error"):
        check("script", False, f"it stopped: {r['error']}")
    check("setup", bool(r.get("installed")) and bool(r.get("thorium_window")) and bool(r.get("thorium_profile", True)),
          "Thoron was not installed, or the Thorium profile could not be made")
    check("detect, running", "Thorium" in _text(r, "detect_running") and
          "(running: close it before an import)" in _text(r, "detect_running"),
          f"Thorium is not listed as running: {_text(r, 'detect_running')[:200]!r}")
    check("import, running", _exit(r, "import_running") not in (0, None) and
          "the source browser is running" in _text(r, "import_running"),
          f"the import did not refuse a running Thorium: {_exit(r, 'import_running')}")
    check("import, too soon", _exit(r, "import_too_soon") not in (0, None) and
          "half a minute" in _text(r, "import_too_soon"),
          f"right after the close it did not ask to wait: {_exit(r, 'import_too_soon')} "
          f"{_text(r, 'import_too_soon')[-160:]!r}")
    detect = _text(r, "detect")
    check("detect", "Thorium" in detect and "Default" in detect and "(running" not in detect,
          f"Thorium's Default profile is not listed as closed: {detect[:200]!r}")
    check("import", _exit(r, "import") == 0, f"the import ended with {_exit(r, 'import')}: "
          f"{_text(r, 'import')[-200:]!r}")
    check("import", bool(r.get("report")), "no Thoron import report.json beside the destination")
    check("import", bool(r.get("marker_copied")), "the file put into Thorium's profile is not in Thoron's")
    check("first start", bool(r.get("thoron_window")) and bool(r.get("marker_kept")),
          "Thoron did not start on the imported profile and keep it")
    check("import, again", _exit(r, "import_again") not in (0, None) and
          "already holds a profile" in _text(r, "import_again") and bool(r.get("marker_after_again")),
          f"a second import did not refuse and leave the profile: {_exit(r, 'import_again')}")
    return out


PYTHON_SKIP = {"site-packages", "test", "tests", "idlelib", "tkinter", "turtledemo", "ensurepip", "__pycache__"}


def copy_python(dest: Path) -> None:
    """The interpreter and its standard library, nothing that was installed into it."""
    base = Path(sys.base_prefix)
    dest.mkdir(parents=True)
    for f in base.glob("*.dll"):
        shutil.copy2(f, dest)
    for name in ("python.exe", "pythonw.exe"):
        shutil.copy2(base / name, dest)
    shutil.copytree(base / "DLLs", dest / "DLLs", ignore=shutil.ignore_patterns("tcl*", "tk*", "_tkinter*"))
    shutil.copytree(base / "Lib", dest / "Lib", ignore=lambda folder, names: [n for n in names if n in PYTHON_SKIP])


def run(installer: Path, work: Path, timeout: float) -> dict:
    if work.exists():
        shutil.rmtree(work)
    for name in ("in/install", "out"):
        (work / name).mkdir(parents=True)
    shutil.copy2(installer, work / "in/install" / installer.name)
    shutil.copytree(REPO / "tools", work / "in/thoron-main/tools",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(REPO / "README.md", work / "in/thoron-main/README.md")
    copy_python(work / "in/python")
    (work / "in/run.ps1").write_text(RUN, encoding="utf-8-sig", newline="\r\n")
    config = work / "thoron-import-guide.wsb"
    config.write_text(sb.wsb(work), encoding="utf-8")
    subprocess.Popen([sb.SANDBOX, str(config)])
    results = work / "out/results.json"
    end = time.monotonic() + timeout
    found = sb.read_results(results)
    while time.monotonic() < end and not found.get("done"):
        time.sleep(5)
        found = sb.read_results(results)
    sb.close_sandbox()
    return found


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--installer", type=Path, required=True)
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--timeout", type=float, default=1500)
    a = p.parse_args(argv)
    found = run(a.installer.resolve(), a.work.resolve(), a.timeout)
    if not found.get("done"):
        print(f"IMPORT GUIDE CHECK: NOT FINISHED (reached {found.get('reached')}; {found.get('error', '')})")
        return 1
    found_problems = problems(found)
    for step, issues in found_problems.items():
        print(f"{'PASS' if not issues else 'FAIL'}  {step}")
        for issue in issues:
            print(f"      {issue}")
    count = sum(len(v) for v in found_problems.values())
    print(f"IMPORT GUIDE CHECK: {'PASSED' if not count else f'FAILED ({count} problem(s))'}")
    return 1 if count else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
