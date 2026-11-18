#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Thoron's first start on a clean Windows (ROADMAP P3.21): the offer shows once, each choice does what it
says, and declining changes nothing. Windows only.

In Windows Sandbox (a clean Windows, gone when it closes; networking off) Thoron is installed for the user and
started on a new profile with its DevTools port open on 127.0.0.1 (Chromium opens that port only for a
profile folder that is not the default one, so the check uses one of its own; for the browser it is a first
start all the same). Through the port the script reads the open tabs and presses the page's buttons, so
nothing depends on the words on the screen:

    first start      after Chromium's own first-run screens (the sign-in offer, declined; a default-browser
                     step, skipped, when Windows allows it), the first tab is chrome://thoron-welcome/
    import           its Import button opens chrome://settings/importData, Settings' own import dialog
    default          its button opens Windows' own settings page for the default browser (the Settings app
                     starts); nothing is confirmed there, and the browser for web links stays as it was
    declined         the browser closed with the tab, started again: no welcome page, and the browser for
                     web links (http, https) and .html is still the one Windows had before Thoron

    py -3 -I tools/qa/sandbox_first_run_check.py --installer <thoron_AVX2_mini_installer.exe> --work <scratch>
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.qa import sandbox_install_check as sb  # noqa: E402

WELCOME = "chrome://thoron-welcome/"
IMPORT = "chrome://settings/importData"
RUN = r"""$ErrorActionPreference = 'Continue'
$out = 'C:\ThoronTest\out'
$r = [ordered]@{}
function Save { $r | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 (Join-Path $out 'results.json') }
function Trace($text) { Add-Content -Encoding utf8 -Path (Join-Path $out 'trace.txt') -Value "$(Get-Date -Format HH:mm:ss) $text" }
function Mark($step) { $r.reached = $step; Save; Trace "step: $step" }
$port = 9333
function Tabs {
  try { @((Invoke-RestMethod "http://127.0.0.1:$port/json/list" -TimeoutSec 10) | Where-Object { $_.type -eq 'page' }) } catch { @() }
}
function Evaluate($tab, $expression) {
  # Runtime.evaluate in a tab, through its DevTools socket
  $ws = New-Object System.Net.WebSockets.ClientWebSocket
  $none = [Threading.CancellationToken]::None
  [void]$ws.ConnectAsync([Uri]$tab.webSocketDebuggerUrl, $none).Wait(10000)
  $msg = @{ id = 1; method = 'Runtime.evaluate'; params = @{ expression = $expression; returnByValue = $true } } | ConvertTo-Json -Compress -Depth 5
  $bytes = [Text.Encoding]::UTF8.GetBytes($msg)
  [void]$ws.SendAsync((New-Object 'ArraySegment[byte]' (,$bytes)), 'Text', $true, $none).Wait(10000)
  $buffer = New-Object byte[] 65536
  $got = $ws.ReceiveAsync((New-Object 'ArraySegment[byte]' (,$buffer)), $none)
  [void]$got.Wait(10000)
  $text = [Text.Encoding]::UTF8.GetString($buffer, 0, $got.Result.Count)
  $ws.Dispose()
  return $text
}
function Choice($what) {
  # the program Windows opens for links or a file type, as the person chose it (empty: none chosen)
  $key = if ($what -like '.*') { "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\$what\UserChoice" } else { "HKCU:\Software\Microsoft\Windows\Shell\Associations\UrlAssociations\$what\UserChoice" }
  "$((Get-ItemProperty $key -ErrorAction SilentlyContinue).ProgId)"
}
function Choices { [ordered]@{ http = (Choice 'http'); https = (Choice 'https'); html = (Choice '.html') } }
function Close {
  Get-Process thoron -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | ForEach-Object { [void]$_.CloseMainWindow() }
  $end = (Get-Date).AddSeconds(30)
  while ((Get-Process thoron -ErrorAction SilentlyContinue) -and (Get-Date) -lt $end) { Start-Sleep -Seconds 1 }
  Get-Process thoron -ErrorAction SilentlyContinue | Stop-Process -Force
  Start-Sleep -Seconds 3
}
$app = Join-Path $env:LOCALAPPDATA 'Thoron\Application'
$testData = Join-Path $env:LOCALAPPDATA 'Thoron\First run test'
try {
  Mark 'install'
  $copy = Join-Path $env:TEMP 'installer.exe'
  Copy-Item (Get-ChildItem 'C:\ThoronTest\in\install' -Filter '*.exe' | Select-Object -First 1).FullName $copy
  $p = Start-Process $copy -ArgumentList '--silent', '--do-not-launch-chrome' -PassThru
  $null = $p.WaitForExit(300000)
  $r.installed = Test-Path (Join-Path $app 'thoron.exe')
  $r.choices_before = Choices

  Mark 'first start'
  Start-Process (Join-Path $app 'thoron.exe') -ArgumentList "--user-data-dir=`"$testData`"", "--remote-debugging-port=$port" | Out-Null
  Start-Sleep -Seconds 20
  # Chromium's own first-run screens come first (chrome://intro): the sign-in offer, where the person says
  # no (Google sign-in does not work in Thoron), and, when Windows allows it, a default-browser step,
  # skipped here so that the welcome page's own offer is tried
  $deep = "const deep = (root, s) => { const f = root.querySelector(s); if (f) return f; for (const e of root.querySelectorAll('*')) if (e.shadowRoot) { const g = deep(e.shadowRoot, s); if (g) return g; } return null; };"
  $r.intro = @()
  $end = (Get-Date).AddSeconds(90)
  do {
    $tabs = @(Tabs)
    $intro = $tabs | Where-Object { $_.url -like 'chrome://intro*' } | Select-Object -First 1
    if ($intro) {
      $r.intro += "$($intro.url)"
      [void](Evaluate $intro "(() => { $deep const b = deep(document, '#declineSignInButton') || deep(document, '#skip-button'); if (b) { b.click(); return 'pressed'; } return 'none'; })()")
      Start-Sleep -Seconds 5
    }
  } while ($intro -and (Get-Date) -lt $end)
  Start-Sleep -Seconds 5
  $tabs = @(Tabs)
  $r.first_tabs = @($tabs | ForEach-Object { $_.url })
  $welcome = $tabs | Where-Object { $_.url -like 'chrome://thoron-welcome*' } | Select-Object -First 1

  if ($welcome) {
    Mark 'default'
    $r.default_state = Evaluate $welcome "JSON.stringify({button: !document.getElementById('make-default').hidden, already: !document.getElementById('already').hidden})"
    $before = @(Get-Process SystemSettings -ErrorAction SilentlyContinue).Count
    $r.default_click = Evaluate $welcome "document.getElementById('make-default').click(); 'clicked'"
    $end = (Get-Date).AddSeconds(30)
    while (@(Get-Process SystemSettings -ErrorAction SilentlyContinue).Count -le $before -and (Get-Date) -lt $end) { Start-Sleep -Seconds 1 }
    $r.default_settings_opened = @(Get-Process SystemSettings -ErrorAction SilentlyContinue).Count -gt $before
    Start-Sleep -Seconds 5
    Get-Process SystemSettings -ErrorAction SilentlyContinue | Stop-Process -Force
    $r.choices_after_default = Choices

    Mark 'import'
    $r.import_click = Evaluate $welcome "document.getElementById('import').click(); 'clicked'"
    Start-Sleep -Seconds 5
    $r.import_tabs = @(Tabs | ForEach-Object { $_.url })
  }

  Mark 'declined: closed and started again'
  Close
  Start-Process (Join-Path $app 'thoron.exe') -ArgumentList "--user-data-dir=`"$testData`"", "--remote-debugging-port=$port" | Out-Null
  Start-Sleep -Seconds 20
  $r.second_tabs = @(Tabs | ForEach-Object { $_.url })
  Close
  $r.choices_after = Choices
} catch {
  $r.error = "$_"
}
$r.done = $true
Save
Trace 'done'
Stop-Computer -Force
"""


def _list(value) -> list[str]:
    return [value] if isinstance(value, str) else list(value or [])


def problems(r: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}

    def check(step: str, ok: bool, text: str) -> None:
        out.setdefault(step, [])
        if not ok:
            out[step].append(text)

    if r.get("error"):
        check("script", False, f"it stopped: {r['error']}")
    check("install", bool(r.get("installed")), "Thoron was not installed")
    first = _list(r.get("first_tabs"))
    check("first start", bool(first) and first[0].startswith(WELCOME),
          f"the first tab is not the welcome page: {first}")
    check("default", '"button":true' in str(r.get("default_state", "")).replace(" ", "").replace('\\"', '"'),
          f"the page does not offer to make Thoron the default: {r.get('default_state')!r}")
    check("default", bool(r.get("default_settings_opened")), "Windows' settings page did not open")
    check("default", r.get("choices_after_default") == r.get("choices_before"),
          f"the browser for links changed without the person: {r.get('choices_before')} -> "
          f"{r.get('choices_after_default')}")
    tabs = _list(r.get("import_tabs"))
    check("import", any(t.startswith(IMPORT) for t in tabs), f"Settings' import dialog did not open: {tabs}")
    second = _list(r.get("second_tabs"))
    check("declined", bool(second) and not any(t.startswith(WELCOME) for t in second),
          f"the welcome page came again, or the browser did not start: {second}")
    check("declined", r.get("choices_after") == r.get("choices_before"),
          f"the browser for links or .html changed: {r.get('choices_before')} -> {r.get('choices_after')}")
    return out


def run(installer: Path, work: Path, timeout: float) -> dict:
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    for name in ("in/install", "out"):
        (work / name).mkdir(parents=True, exist_ok=True)
    shutil.copy2(installer, work / "in/install" / installer.name)
    (work / "in/run.ps1").write_text(RUN, encoding="utf-8-sig", newline="\r\n")
    config = work / "thoron-first-run.wsb"
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
    p.add_argument("--timeout", type=float, default=1200)
    a = p.parse_args(argv)
    found = run(a.installer.resolve(), a.work.resolve(), a.timeout)
    if not found.get("done"):
        print(f"FIRST RUN CHECK: NOT FINISHED (reached {found.get('reached')}; {found.get('error', '')})")
        return 1
    found_problems = problems(found)
    for step, issues in found_problems.items():
        print(f"{'PASS' if not issues else 'FAIL'}  {step}")
        for issue in issues:
            print(f"      {issue}")
    count = sum(len(v) for v in found_problems.values())
    print(f"FIRST RUN CHECK: {'PASSED' if not count else f'FAILED ({count} problem(s))'}")
    return 1 if count else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
