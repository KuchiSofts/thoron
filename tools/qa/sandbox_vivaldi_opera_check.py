#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Vivaldi and Opera, installed on a clean Windows, found and read by Thoron's import tools (ROADMAP P3.13, P3.15).

Neither browser is on the build PC, so they are installed inside Windows Sandbox, which is gone when it closes:
this one run has networking on to download their current installers from the makers' own addresses. Inside, each
browser is installed for the user without questions, started once with two local pages, and closed the way a
person closes it, so that it writes its session. Then, with Python's own files handed in from the PC (the tools
need nothing else):

    detect    tools/migrate/detect.py lists Vivaldi and Opera with their profiles (P3.13)
    tabs      tools/migrate/sessions.py read finds both local pages among each browser's open tabs (P3.15)

    py -3 -I tools/qa/sandbox_vivaldi_opera_check.py --work <scratch> [--timeout 1800]
Exit status 0 only when both steps pass for both browsers. Nothing is installed on the PC itself.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from xml.sax.saxutils import escape

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.qa import sandbox_install_check as sb  # noqa: E402
from tools.qa.sandbox_import_guide_check import copy_python  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
BROWSERS = ("Vivaldi", "Opera")
MARKS = ("thoron-tab-one", "thoron-tab-two")

RUN = r"""$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
$out = 'C:\ThoronTest\out'
$r = [ordered]@{}
function Save { $r | ConvertTo-Json -Depth 6 | Set-Content -Encoding utf8 (Join-Path $out 'results.json') }
function Mark($step) { $r.reached = $step; Save }
$python = 'C:\ThoronTest\in\python\python.exe'
$tools = 'C:\ThoronTest\in\thoron-main'
function Tool($arguments) {
  $o = Join-Path $env:TEMP 'tool-out.txt'; $e = Join-Path $env:TEMP 'tool-err.txt'
  $p = Start-Process $python -ArgumentList (@('-I') + $arguments) -RedirectStandardOutput $o -RedirectStandardError $e `
         -NoNewWindow -PassThru -WorkingDirectory $tools
  $null = $p.Handle
  if (-not $p.WaitForExit(300000)) { Stop-Process -Id $p.Id -Force; return @{ exit = 'timeout'; text = '' } }
  return @{ exit = $p.ExitCode; text = ("$(Get-Content $o -Raw -ErrorAction SilentlyContinue)") }
}
function CloseAll($name) {
  Get-Process $name -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | ForEach-Object { [void]$_.CloseMainWindow() }
  $end = (Get-Date).AddSeconds(40)
  while ((Get-Process $name -ErrorAction SilentlyContinue) -and (Get-Date) -lt $end) { Start-Sleep -Seconds 1 }
  $r["$($name)_left_running"] = [bool](Get-Process $name -ErrorAction SilentlyContinue)
  Get-Process $name -ErrorAction SilentlyContinue | Stop-Process -Force
}
try {
  $pages = Join-Path $env:USERPROFILE 'pages'
  New-Item -ItemType Directory -Force $pages | Out-Null
  $one = Join-Path $pages 'thoron-tab-one.html'; $two = Join-Path $pages 'thoron-tab-two.html'
  Set-Content -Encoding ascii $one '<title>thoron-tab-one</title>one'
  Set-Content -Encoding ascii $two '<title>thoron-tab-two</title>two'
  $urls = @(([uri]$one).AbsoluteUri, ([uri]$two).AbsoluteUri)
  $downloads = Join-Path $env:USERPROFILE 'Downloads'
  New-Item -ItemType Directory -Force $downloads | Out-Null

  Mark 'vivaldi download'
  $feed = [xml](Invoke-WebRequest -UseBasicParsing 'https://update.vivaldi.com/update/1.0/public/appcast.x64.xml').Content
  $item = $feed.rss.channel.item | Select-Object -First 1
  $vivaldiUrl = $item.enclosure.url
  $r.vivaldi_version = $item.enclosure.version
  $vivaldiSetup = Join-Path $downloads 'Vivaldi.x64.exe'
  Invoke-WebRequest -UseBasicParsing $vivaldiUrl -OutFile $vivaldiSetup
  Mark 'vivaldi install'
  $p = Start-Process $vivaldiSetup -ArgumentList '--vivaldi-silent', '--do-not-launch-chrome' -PassThru
  $null = $p.WaitForExit(600000)
  $vivaldi = Join-Path $env:LOCALAPPDATA 'Vivaldi\Application\vivaldi.exe'
  $r.vivaldi_installed = Test-Path $vivaldi
  if ($r.vivaldi_installed) {
    Mark 'vivaldi start'
    Start-Process $vivaldi -ArgumentList (@('--no-first-run', '--no-default-browser-check') + $urls)
    Start-Sleep -Seconds 30
    CloseAll 'vivaldi'
  }

  Mark 'opera download'
  $operaSetup = Join-Path $downloads 'OperaSetup.exe'
  Invoke-WebRequest -UseBasicParsing 'https://net.geo.opera.com/opera/stable/windows' -OutFile $operaSetup
  Mark 'opera install'
  $p = Start-Process $operaSetup -ArgumentList '--silent', '--allusers=0', '--launchopera=0', '--setdefaultbrowser=0', '--import-browser-data=0', '--enable-stats=0' -PassThru
  $null = $p.WaitForExit(900000)
  $opera = Get-ChildItem (Join-Path $env:LOCALAPPDATA 'Programs\Opera') -Filter 'opera.exe' -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
  $r.opera_installed = [bool]$opera
  if ($opera) {
    Mark 'opera start'
    Start-Process $opera.FullName -ArgumentList (@('--no-first-run', '--no-default-browser-check') + $urls)
    Start-Sleep -Seconds 40
    CloseAll 'opera'
  }

  Mark 'detect'
  $d = Tool @('tools\migrate\detect.py', '--json')
  $r.detect_exit = $d.exit
  $r.detect = $d.text
  Mark 'tabs'
  $vp = Join-Path $env:LOCALAPPDATA 'Vivaldi\User Data\Default'
  $op = Join-Path $env:APPDATA 'Opera Software\Opera Stable\Default'
  if (-not (Test-Path $op)) { $op = Join-Path $env:APPDATA 'Opera Software\Opera Stable' }
  foreach ($pair in @(@('vivaldi', $vp), @('opera', $op))) {
    $t = Tool @('tools\migrate\sessions.py', 'read', '--profile', $pair[1])
    $r["$($pair[0])_tabs_exit"] = $t.exit
    $r["$($pair[0])_tabs"] = $t.text
    $r["$($pair[0])_session_files"] = @(Get-ChildItem (Join-Path $pair[1] 'Sessions') -ErrorAction SilentlyContinue | ForEach-Object { $_.Name })
  }
} catch {
  $r.error = "$_"
}
$r.done = $true
Save
Start-Sleep -Seconds 2
shutdown.exe /s /t 0
"""


def wsb(work: Path) -> str:
    """The Sandbox with networking on (the two installers come from the makers' own addresses)."""
    folders = "".join(
        f"<MappedFolder><HostFolder>{escape(str(work / name))}</HostFolder>"
        f"<SandboxFolder>{sb.INSIDE}\\{name}</SandboxFolder><ReadOnly>{'true' if name == 'in' else 'false'}</ReadOnly>"
        "</MappedFolder>" for name in ("in", "out"))
    return ("<Configuration><VGpu>Disable</VGpu><Networking>Enable</Networking><MemoryInMB>6144</MemoryInMB>"
            "<ClipboardRedirection>Disable</ClipboardRedirection><PrinterRedirection>Disable</PrinterRedirection>"
            f"<MappedFolders>{folders}</MappedFolders><LogonCommand><Command>powershell.exe -NoProfile "
            f"-ExecutionPolicy Bypass -File {sb.INSIDE}\\in\\run.ps1</Command></LogonCommand></Configuration>")


def tab_urls(reading: str) -> list[str]:
    """Every navigation address of every open tab in a sessions.py reading (JSON), in order."""
    try:
        data = json.loads(reading)
    except ValueError:
        return []
    session = data.get("session") if isinstance(data, dict) else None
    urls = []
    for window in (session or {}).get("windows", []):
        for tab in window.get("tabs", []):
            for nav in tab.get("navigations", []):
                urls.append(str(nav.get("url", "")))
    return urls


def problems(found: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    try:
        detected = json.loads(found.get("detect") or "null")
    except ValueError:
        detected = None
    names = [str(b.get("browser", "")) for b in detected if isinstance(b, dict)] if isinstance(detected, list) else []
    for browser in BROWSERS:
        key = browser.lower()
        steps = []
        if not found.get(f"{key}_installed"):
            steps.append(f"{browser}: not installed in the Sandbox")
        if browser not in names:
            steps.append(f"detect: {browser} not listed ({names})")
        urls = tab_urls(found.get(f"{key}_tabs") or "")
        missing = [m for m in MARKS if not any(m in u for u in urls)]
        if missing:
            steps.append(f"tabs: {browser}'s open tabs lack {missing} (files: {found.get(f'{key}_session_files')})")
        out[browser] = steps
    return out


def run(work: Path, timeout: float) -> dict:
    if work.exists():
        shutil.rmtree(work)
    (work / "out").mkdir(parents=True)
    shutil.copytree(REPO / "tools", work / "in/thoron-main/tools", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    copy_python(work / "in/python")
    (work / "in/run.ps1").write_text(RUN, encoding="utf-8-sig", newline="\r\n")
    config = work / "thoron-vivaldi-opera.wsb"
    config.write_text(wsb(work), encoding="utf-8")
    subprocess.Popen([sb.SANDBOX, str(config)])
    results = work / "out/results.json"
    end = time.monotonic() + timeout
    found = sb.read_results(results)
    while time.monotonic() < end and not found.get("done"):
        time.sleep(5)
        found = sb.read_results(results)
    sb.close_sandbox()
    if not found.get("done"):
        found["error"] = f"no end within {timeout:g} s; it got as far as: {found.get('reached', 'nothing')}"
    return found


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--timeout", type=float, default=1800)
    a = p.parse_args(argv)
    sys.stdout.reconfigure(errors="backslashreplace")
    found = run(a.work.resolve(), a.timeout)
    if found.get("error"):
        print(f"VIVALDI AND OPERA: NOT CHECKED ({found['error']})")
        return 1
    found_problems = problems(found)
    for browser, steps in found_problems.items():
        print(f"{'PASS' if not steps else 'FAIL'}  {browser}"
              + (f" {found.get('vivaldi_version', '')}" if browser == "Vivaldi" else ""))
        for step in steps:
            print(f"    {step}")
    failed = any(found_problems.values())
    print("VIVALDI AND OPERA: FAILED" if failed else "VIVALDI AND OPERA: PASSED")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
