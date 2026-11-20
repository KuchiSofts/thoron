#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""The Import guide's sections for Chrome and Firefox, followed on a clean Windows (ROADMAP D.2). Windows only.

Neither browser is on a clean Windows, so both are installed inside Windows Sandbox, which is gone when it
closes: this run has networking on, to download Chrome's installer and Firefox's from their makers' own addresses.
Thoron is installed for the user. Each browser is started once with two local pages (served on 127.0.0.1 by
tools/qa/session_golden.py's server) and closed the way a person closes it, so that it writes its session. Then
docs/user/IMPORT.md section 3 is followed as written, with Python's own files handed in from the PC:

    first start  Thoron is started once and closed (step 1)
    chrome       `sessions.py read` on Chrome's profile lists both pages; `sessions.py import --set-aside
                 --restore-on-next-start` copies the session; Thoron's next start opens both pages
    firefox      `firefox_sessions.py read` on Firefox's sessionstore.jsonlz4 lists both pages;
                 `firefox_sessions.py import --set-aside --restore-on-next-start` writes them as Thoron's;
                 Thoron's next start opens both pages

    py -3 -I tools/qa/sandbox_import_chrome_firefox_check.py --installer <thoron_AVX2_mini_installer.exe>
        --work <scratch> [--timeout 2400]
Exit status 0 only when every step passes. Nothing is installed on the PC itself.
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
from tools.qa.sandbox_import_guide_check import copy_python  # noqa: E402
from tools.qa.sandbox_vivaldi_opera_check import tab_urls, wsb  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
MARKS = ("thoron-guide-one", "thoron-guide-two")

RUN = r"""$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
$out = 'C:\ThoronTest\out'
$r = [ordered]@{}
function Save { $r | ConvertTo-Json -Depth 6 | Set-Content -Encoding utf8 (Join-Path $out 'results.json') }
function Mark($step) { $r.reached = $step; Save }
$python = 'C:\ThoronTest\in\python\python.exe'
$tools = 'C:\ThoronTest\in\thoron-main'
$port = 9336
function Tool($arguments) {
  $o = Join-Path $env:TEMP 'tool-out.txt'; $e = Join-Path $env:TEMP 'tool-err.txt'
  $p = Start-Process $python -ArgumentList (@('-I') + $arguments) -RedirectStandardOutput $o -RedirectStandardError $e `
         -NoNewWindow -PassThru -WorkingDirectory $tools
  $null = $p.Handle
  if (-not $p.WaitForExit(300000)) { Stop-Process -Id $p.Id -Force; return @{ exit = 'timeout'; text = '' } }
  return @{ exit = $p.ExitCode; text = ("$(Get-Content $o -Raw -ErrorAction SilentlyContinue)");
           errors = ("$(Get-Content $e -Raw -ErrorAction SilentlyContinue)") }
}
function CloseAll($name) {
  Get-Process $name -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | ForEach-Object { [void]$_.CloseMainWindow() }
  $end = (Get-Date).AddSeconds(45)
  while ((Get-Process $name -ErrorAction SilentlyContinue) -and (Get-Date) -lt $end) { Start-Sleep -Seconds 1 }
  $r["$($name)_left_running"] = [bool](Get-Process $name -ErrorAction SilentlyContinue)
  Get-Process $name -ErrorAction SilentlyContinue | Stop-Process -Force
  Start-Sleep -Seconds 2
}
$app = Join-Path $env:LOCALAPPDATA 'Thoron\Application\thoron.exe'
$thoronProfile = Join-Path $env:LOCALAPPDATA 'Thoron\User Data\Default'
function ThoronOpens($label) {
  # Thoron's next start, with DevTools on 127.0.0.1: the addresses of its open pages
  Start-Process $app -ArgumentList '--no-first-run', '--no-default-browser-check', "--remote-debugging-port=$port" | Out-Null
  Start-Sleep -Seconds 25
  $pages = @()
  try { $pages = @((Invoke-RestMethod "http://127.0.0.1:$port/json/list" -TimeoutSec 10) | Where-Object { $_.type -eq 'page' } | ForEach-Object { $_.url }) } catch {}
  $r["$($label)_opened"] = $pages
  CloseAll 'thoron'
}
try {
  $serve = Join-Path $env:TEMP 'serve.py'
  Set-Content -Encoding ascii $serve @'
import sys, time
sys.path.insert(0, r"C:\ThoronTest\in\thoron-main")
from tools.qa.session_golden import PageServer
server = PageServer(47640)
server.__enter__()
time.sleep(7200)
'@
  $server = Start-Process $python -ArgumentList '-I', ('"' + $serve + '"') -PassThru -WindowStyle Hidden
  Start-Sleep -Seconds 3
  $urls = @('http://127.0.0.1:47640/p/thoron-guide-one', 'http://127.0.0.1:47640/p/thoron-guide-two')
  $downloads = Join-Path $env:USERPROFILE 'Downloads'
  New-Item -ItemType Directory -Force $downloads | Out-Null

  Mark 'install Thoron'
  $copy = Join-Path $env:TEMP 'installer.exe'
  Copy-Item (Get-ChildItem 'C:\ThoronTest\in\install' -Filter '*.exe' | Select-Object -First 1).FullName $copy
  $p = Start-Process $copy -ArgumentList '--silent', '--do-not-launch-chrome' -PassThru
  $null = $p.WaitForExit(300000)
  $r.thoron_installed = Test-Path $app

  Mark 'network'
  for ($i = 0; $i -lt 90; $i++) { try { [void][System.Net.Dns]::GetHostAddresses('dl.google.com'); break } catch { Start-Sleep -Seconds 2 } }

  Mark 'chrome'
  $chromeMsi = Join-Path $downloads 'googlechromestandaloneenterprise64.msi'
  Invoke-WebRequest -UseBasicParsing 'https://dl.google.com/dl/chrome/install/googlechromestandaloneenterprise64.msi' -OutFile $chromeMsi
  $p = Start-Process msiexec.exe -ArgumentList '/i', ('"' + $chromeMsi + '"'), '/qn', '/norestart' -PassThru
  $null = $p.WaitForExit(900000)
  $chrome = @('C:\Program Files\Google\Chrome\Application\chrome.exe', (Join-Path $env:LOCALAPPDATA 'Google\Chrome\Application\chrome.exe')) | Where-Object { Test-Path $_ } | Select-Object -First 1
  $r.chrome_installed = [bool]$chrome
  if ($chrome) {
    Start-Process $chrome -ArgumentList (@('--no-first-run', '--no-default-browser-check') + $urls)
    Start-Sleep -Seconds 30
    CloseAll 'chrome'
  }

  Mark 'firefox'
  $firefoxSetup = Join-Path $downloads 'FirefoxSetup.exe'
  Invoke-WebRequest -UseBasicParsing 'https://download.mozilla.org/?product=firefox-latest-ssl&os=win64&lang=en-US' -OutFile $firefoxSetup
  $p = Start-Process $firefoxSetup -ArgumentList '/S' -PassThru
  $null = $p.WaitForExit(900000)
  $firefox = 'C:\Program Files\Mozilla Firefox\firefox.exe'
  $r.firefox_installed = Test-Path $firefox
  if ($r.firefox_installed) {
    Start-Process $firefox -ArgumentList $urls
    Start-Sleep -Seconds 40
    CloseAll 'firefox'
  }
  Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
  $server = Start-Process $python -ArgumentList '-I', ('"' + $serve + '"') -PassThru -WindowStyle Hidden

  Mark 'first start'
  Start-Process $app -ArgumentList '--no-first-run', '--no-default-browser-check' | Out-Null
  Start-Sleep -Seconds 20
  CloseAll 'thoron'
  $r.thoron_profile = Test-Path (Join-Path $thoronProfile 'Preferences')

  Mark 'chrome tabs'
  $chromeProfile = Join-Path $env:LOCALAPPDATA 'Google\Chrome\User Data\Default'
  $t = Tool @('tools\migrate\sessions.py', 'read', '--profile', ('"' + $chromeProfile + '"'))
  $r.chrome_read_exit = $t.exit; $r.chrome_read = $t.text
  $t = Tool @('tools\migrate\sessions.py', 'import', '--from', ('"' + $chromeProfile + '"'), '--to', ('"' + $thoronProfile + '"'), '--set-aside', '--restore-on-next-start')
  $r.chrome_import_exit = $t.exit; $r.chrome_import = ($t.text + $t.errors)
  ThoronOpens 'chrome'

  Mark 'firefox tabs'
  $ffProfile = Get-ChildItem (Join-Path $env:APPDATA 'Mozilla\Firefox\Profiles') -Directory -ErrorAction SilentlyContinue | Where-Object { Test-Path (Join-Path $_.FullName 'sessionstore.jsonlz4') } | Select-Object -First 1
  $r.firefox_session_found = [bool]$ffProfile
  if ($ffProfile) {
    $t = Tool @('tools\migrate\firefox_sessions.py', 'read', '--file', ('"' + (Join-Path $ffProfile.FullName 'sessionstore.jsonlz4') + '"'))
    $r.firefox_read_exit = $t.exit; $r.firefox_read = $t.text
    $t = Tool @('tools\migrate\firefox_sessions.py', 'import', '--from', ('"' + $ffProfile.FullName + '"'), '--to', ('"' + $thoronProfile + '"'), '--set-aside', '--restore-on-next-start')
    $r.firefox_import_exit = $t.exit; $r.firefox_import = ($t.text + $t.errors)
    ThoronOpens 'firefox'
  }
  Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
} catch {
  $r.error = "$_"
}
$r.done = $true
Save
Start-Sleep -Seconds 2
shutdown.exe /s /t 0
"""


def _all_urls(reading: str) -> list[str]:
    urls = tab_urls(reading)
    if urls:
        return urls
    try:                                    # firefox_sessions.py read prints its own reading
        data = json.loads(reading)
    except ValueError:
        return []
    found = []
    for window in (data.get("windows") or data.get("session", {}).get("windows") or []):
        for tab in window.get("tabs", []):
            found += [str(n.get("url", "")) for n in tab.get("navigations", tab.get("entries", []))]
    return found


def problems(found: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {"first start": [], "chrome": [], "firefox": []}
    if found.get("error"):
        out["first start"].append(f"it stopped: {found['error']}")
    if not found.get("thoron_installed") or not found.get("thoron_profile"):
        out["first start"].append("Thoron was not installed, or its first start made no profile")
    for browser in ("chrome", "firefox"):
        steps = out[browser]
        if not found.get(f"{browser}_installed"):
            steps.append(f"{browser} was not installed in the Sandbox")
            continue
        read = _all_urls(found.get(f"{browser}_read") or "")
        if found.get(f"{browser}_read_exit") != 0 or not all(any(m in u for u in read) for m in MARKS):
            steps.append(f"read: exit {found.get(f'{browser}_read_exit')!r}, the pages are not both listed")
        if found.get(f"{browser}_import_exit") != 0:
            steps.append(f"import: exit {found.get(f'{browser}_import_exit')!r}: {str(found.get(f'{browser}_import'))[-300:]}")
        opened = found.get(f"{browser}_opened") or []
        if not all(any(m in str(u) for u in opened) for m in MARKS):
            steps.append(f"Thoron's next start did not open both pages: {opened}")
    return out


def run(installer: Path, work: Path, timeout: float) -> dict:
    if work.exists():
        shutil.rmtree(work)
    for name in ("in/install", "out"):
        (work / name).mkdir(parents=True, exist_ok=True)
    shutil.copy2(installer, work / "in/install" / installer.name)
    shutil.copytree(REPO / "tools", work / "in/thoron-main/tools", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    copy_python(work / "in/python")
    (work / "in/run.ps1").write_text(RUN, encoding="utf-8-sig", newline="\r\n")
    config = work / "thoron-import-chrome-firefox.wsb"
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
    p.add_argument("--installer", type=Path, required=True)
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--timeout", type=float, default=2400)
    a = p.parse_args(argv)
    sys.stdout.reconfigure(errors="backslashreplace")
    found_problems = problems(run(a.installer.resolve(), a.work.resolve(), a.timeout))
    for step, issues in found_problems.items():
        print(f"{'PASS' if not issues else 'FAIL'}  {step}")
        for issue in issues:
            print(f"      {issue}")
    count = sum(len(v) for v in found_problems.values())
    print(f"IMPORT GUIDE, CHROME AND FIREFOX: {'PASSED' if not count else f'FAILED ({count} problem(s))'}")
    return 1 if count else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
