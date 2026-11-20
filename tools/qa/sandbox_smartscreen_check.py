#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""The install guide's step for the "Windows protected your PC" warning, on a clean Windows (ROADMAP D.2, S.8).
Windows only.

Thoron's programs are not signed yet (S.8), so Windows' SmartScreen may stop an installer downloaded from the
web. docs/user/INSTALL.md step 5 says to choose **More info**, then **Run anyway**. In Windows Sandbox (a clean
Windows; networking on, since SmartScreen asks Microsoft about the file) the installer is put into Downloads
marked the way a browser marks a download from the web (the Zone.Identifier stream: the Internet zone and
the release's address) and opened the way Explorer opens it. Then, by UI Automation and never by the words of
the PC's language:

    warning      SmartScreen's window comes up for the installer (or Windows lets it start without one: then
                 the step is not needed on this Windows, which is reported as such)
    run anyway   its link (More info) shows a second button; pressing it starts Thoron's installer, which
                 shows its own question

    py -3 -I tools/qa/sandbox_smartscreen_check.py --installer <thoron_AVX2_mini_installer.exe> --work <scratch>
Exit status 0 when the warning came and Run anyway started the installer, or when no warning came and the
installer started at once (reported). Nothing is installed on the PC itself.
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
from tools.qa.sandbox_vivaldi_opera_check import wsb  # noqa: E402

RELEASE_URL = "https://github.com/KuchiSofts/thoron/releases/download/v0.1.1/thoron_AVX2_mini_installer.exe"

RUN = r"""$ErrorActionPreference = 'Continue'
$out = 'C:\ThoronTest\out'
$r = [ordered]@{}
function Save { $r | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 (Join-Path $out 'results.json') }
function Mark($step) { $r.reached = $step; Save }
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$A = [System.Windows.Automation.AutomationElement]
$T = [System.Windows.Automation.TreeScope]
$C = [System.Windows.Automation.Condition]
function WindowsOf($names) {
  $ids = @(Get-Process -Name $names -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
  @($A::RootElement.FindAll($T::Children, $C::TrueCondition) | Where-Object { $ids -contains $_.Current.ProcessId })
}
function OfType($root, $type) {
  $cond = New-Object System.Windows.Automation.PropertyCondition($A::ControlTypeProperty, $type)
  @($root.FindAll($T::Descendants, $cond))
}
function Press($element) {
  try { $element.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke(); return $true } catch { return $false }
}
try {
  Mark 'network'
  for ($i = 0; $i -lt 90; $i++) { try { [void][System.Net.Dns]::GetHostAddresses('www.microsoft.com'); break } catch { Start-Sleep -Seconds 2 } }
  Mark 'download'
  $downloads = Join-Path $env:USERPROFILE 'Downloads'
  New-Item -ItemType Directory -Force $downloads | Out-Null
  $file = Join-Path $downloads 'thoron_AVX2_mini_installer.exe'
  Copy-Item (Get-ChildItem 'C:\ThoronTest\in\install' -Filter '*.exe' | Select-Object -First 1).FullName $file
  # what a browser writes beside a file it downloaded from the web
  Set-Content -Path $file -Stream 'Zone.Identifier' -Value "[ZoneTransfer]`r`nZoneId=3`r`nReferrerUrl=https://github.com/KuchiSofts/thoron/releases`r`nHostUrl=__URL__"
  $r.marked = "$(Get-Content -Path $file -Stream 'Zone.Identifier' -Raw)"
  Mark 'open'
  # as a person opens it: Explorer opens the file through the shell, which applies the download's zone (the shell's
  # own ShellExecute call returns "cancelled" to its caller at once when SmartScreen steps in)
  try { Start-Process explorer.exe -ArgumentList ('"' + $file + '"') } catch { $r.open_error = "$_" }
  $end = (Get-Date).AddSeconds(60)
  $warning = $null
  do {
    Start-Sleep -Seconds 1
    $warning = WindowsOf @('smartscreen') | Select-Object -First 1
    $installer = [bool](Get-Process -Name 'thoron_AVX2_mini_installer', 'setup' -ErrorAction SilentlyContinue)
  } while (-not $warning -and -not $installer -and (Get-Date) -lt $end)
  $r.warning = [bool]$warning
  $r.started_without_warning = (-not $warning) -and $installer
  if ($warning) {
    Mark 'run anyway'
    $before = @(OfType $warning ([System.Windows.Automation.ControlType]::Button) | ForEach-Object { $_.Current.AutomationId + '|' + $_.Current.Name })
    $r.buttons_before = $before.Count
    $link = OfType $warning ([System.Windows.Automation.ControlType]::Hyperlink) | Select-Object -First 1
    $r.more_info = if ($link) { Press $link } else { $false }
    Start-Sleep -Seconds 2
    $after = @(OfType $warning ([System.Windows.Automation.ControlType]::Button))
    $r.buttons_after = $after.Count
    # the button More info added: Run anyway
    $new = $after | Where-Object { $before -notcontains ($_.Current.AutomationId + '|' + $_.Current.Name) } | Select-Object -First 1
    $r.run_anyway = if ($new) { Press $new } else { $false }
    $end = (Get-Date).AddSeconds(60)
    do { Start-Sleep -Seconds 1; $installer = [bool](Get-Process -Name 'thoron_AVX2_mini_installer', 'setup' -ErrorAction SilentlyContinue) } while (-not $installer -and (Get-Date) -lt $end)
  }
  $r.installer_started = $installer
  Start-Sleep -Seconds 5
  $r.installer_windows = @(WindowsOf @('thoron_AVX2_mini_installer', 'setup')).Count
  Get-Process -Name 'thoron_AVX2_mini_installer', 'setup' -ErrorAction SilentlyContinue | Stop-Process -Force
} catch {
  $r.error = "$_"
}
$r.done = $true
Save
Start-Sleep -Seconds 2
shutdown.exe /s /t 0
""".replace("__URL__", RELEASE_URL)


def problems(found: dict) -> list[str]:
    out = []
    if found.get("error"):
        out.append(f"it stopped: {found['error']}")
    if "ZoneId=3" not in str(found.get("marked")):
        out.append("the installer could not be marked as a download from the web")
    if found.get("warning"):
        if not found.get("more_info"):
            out.append("More info could not be pressed")
        if not found.get("run_anyway"):
            out.append(f"no Run anyway button came ({found.get('buttons_before')} buttons, then {found.get('buttons_after')})")
        if not found.get("installer_started"):
            out.append("Run anyway did not start the installer")
    elif not found.get("started_without_warning"):
        out.append("neither the warning nor the installer came up")
    return out


def run(installer: Path, work: Path, timeout: float) -> dict:
    if work.exists():
        shutil.rmtree(work)
    for name in ("in/install", "out"):
        (work / name).mkdir(parents=True, exist_ok=True)
    shutil.copy2(installer, work / "in/install" / installer.name)
    (work / "in/run.ps1").write_text(RUN, encoding="utf-8-sig", newline="\r\n")
    config = work / "thoron-smartscreen.wsb"
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
    p.add_argument("--timeout", type=float, default=900)
    a = p.parse_args(argv)
    found = run(a.installer.resolve(), a.work.resolve(), a.timeout)
    issues = problems(found)
    if found.get("warning"):
        print("the warning came up for the installer")
    elif found.get("started_without_warning"):
        print("no warning on this Windows: the installer started at once (the guide's step 5 was not needed)")
    for issue in issues:
        print(f"      {issue}")
    print(f"SMARTSCREEN STEP: {'PASSED' if not issues else f'FAILED ({len(issues)} problem(s))'}")
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
