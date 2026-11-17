#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""The Windows user guides followed step by step on a clean Windows (ROADMAP D.2). Windows only.

Windows Sandbox (a clean Windows, gone when it closes; networking off) gets the installer, the portable
package and a SHA256SUMS for both. A script in it does what docs/user/INSTALL.md and UPDATES.md tell a
person to do, the clicks included, and writes down what each step showed. Windows names a dialog's buttons
in its own language, so they are pressed by their IDs (the installer's task dialogs) or with Enter (the
default button of the uninstall question), never by their words; UI Automation reads what the dialogs say.

    install, step 3   the installer started from a folder it may not write to stops with a message that
                      names the code 109
    install, steps 3 to 7  copied to Downloads and started: it asks (an Install button), installs, says so
                      (an OK button); then Thoron is in %LOCALAPPDATA%\\Thoron\\Application, in the list of
                      installed apps with its version, and its daily update task is there
    first start       Thoron starts with a window and makes its profile
    updates, section 4  the guide's Set-Content command writes `update-mode`; the daily look then does
                      nothing (ThoronSetup --scheduled ends with 9)
    remove, installed  the profile copied first (step 2), then what Settings' Uninstall runs (the entry's
                      UninstallString): Thoron's own question, its box that deletes browsing data unticked
                      (step 4), Uninstall pressed; the program, its entry and its task gone, the profile kept
    portable, steps 2 to 4  the zip's SHA-256 matches its line in SHA256SUMS; Extract All (the shell's own
                      unzip) into Documents; Thoron.exe starts with a window and makes User Data in the folder
    remove, portable  the folder deleted: nothing of it is left

Not followed here: downloading from GitHub and the minisign check (no network, no published key yet),
and "Windows protected your PC" (the files carry no mark of a download in the Sandbox).

    py -3 -I tools/qa/sandbox_guides_check.py --installer <thoron_AVX2_mini_installer.exe>
        --chrome-bin <Chrome-bin> --launcher <thoron_launcher.exe> --updater <thoron_update.exe> --work <scratch>
"""
from __future__ import annotations

import argparse
import hashlib
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
function Save { $r | ConvertTo-Json -Depth 6 | Set-Content -Encoding utf8 (Join-Path $out 'results.json') }
function Trace($text) { Add-Content -Encoding utf8 -Path (Join-Path $out 'trace.txt') -Value "$(Get-Date -Format HH:mm:ss) $text" }
function Mark($step) { $r.reached = $step; Save; Trace "step: $step" }
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$AE = [System.Windows.Automation.AutomationElement]
$TS = [System.Windows.Automation.TreeScope]
$CT = [System.Windows.Automation.ControlType]
Trace "ui automation: $([bool]$AE) $([bool]$CT)"
# The installer's question and result are Windows task dialogs (mini_installer.cc): its buttons are
# pressed by their IDs with TDM_CLICK_BUTTON, so no button's text (which follows Windows' language) is needed.
Add-Type @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public static class Dialogs {
  public delegate bool EnumProc(IntPtr window, IntPtr data);
  [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc proc, IntPtr data);
  [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr window);
  [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr window, out uint pid);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetClassName(IntPtr window, StringBuilder name, int size);
  [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr window, uint message, IntPtr w, IntPtr l);
  public static IntPtr Find(uint pid) {
    IntPtr found = IntPtr.Zero;
    EnumWindows((window, data) => {
      uint owner; GetWindowThreadProcessId(window, out owner);
      var name = new StringBuilder(64); GetClassName(window, name, 64);
      if (owner == pid && IsWindowVisible(window) && name.ToString() == "#32770") { found = window; return false; }
      return true;
    }, IntPtr.Zero);
    return found;
  }
  // TDM_CLICK_BUTTON (WM_USER + 102)
  public static void Click(IntPtr dialog, int button) { SendMessage(dialog, 0x0400 + 102, (IntPtr)button, IntPtr.Zero); }
}
'@
function WaitDialog($proc, $seconds) {
  $until = (Get-Date).AddSeconds($seconds)
  while ((Get-Date) -lt $until -and -not $proc.HasExited) {
    $d = [Dialogs]::Find([uint32]$proc.Id)
    if ($d -ne [IntPtr]::Zero) { return $d }
    Start-Sleep -Milliseconds 500
  }
  return [IntPtr]::Zero
}
function Inside($hwnd) {
  # everything UI Automation sees in a window: its kind and its name
  try {
    $w = $AE::FromHandle($hwnd)
    @($w.FindAll($TS::Descendants, [System.Windows.Automation.Condition]::TrueCondition) | ForEach-Object {
      "$($_.Current.ControlType.ProgrammaticName -replace 'ControlType\.', ''): $($_.Current.Name)" }) -join ' | '
  } catch { "ui automation error: $_" }
}
function Kind($type) { New-Object System.Windows.Automation.PropertyCondition($AE::ControlTypeProperty, $type) }
function Waited($proc, $seconds) {
  if ($proc.WaitForExit($seconds * 1000)) { return $proc.ExitCode }
  Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue; return 'timeout'
}
function Windows { Get-Process thoron -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } }
function StartAndClose($exe) {
  Start-Process $exe -ArgumentList '--no-first-run', 'about:blank' | Out-Null
  Start-Sleep -Seconds 25
  $shown = [bool](Windows)
  Windows | ForEach-Object { [void]$_.CloseMainWindow() }
  $end = (Get-Date).AddSeconds(30)
  while ((Get-Process thoron -ErrorAction SilentlyContinue) -and (Get-Date) -lt $end) { Start-Sleep -Seconds 1 }
  Get-Process thoron -ErrorAction SilentlyContinue | Stop-Process -Force
  Start-Sleep -Seconds 3
  return $shown
}
function Entry {
  Get-ChildItem 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall' -ErrorAction SilentlyContinue |
    ForEach-Object { Get-ItemProperty $_.PsPath } | Where-Object { $_.DisplayName -like '*Thoron*' } | Select-Object -First 1
}
$task = 'ThoronUpdateTaskUser' + [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
function TaskThere { & schtasks.exe /Query /TN $task *> $null; return ($LASTEXITCODE -eq 0) }
$app = Join-Path $env:LOCALAPPDATA 'Thoron\Application'
$data = Join-Path $env:LOCALAPPDATA 'Thoron\User Data'
$docs = [Environment]::GetFolderPath('MyDocuments')
try {
  $installer = Get-ChildItem 'C:\ThoronTest\in\install' -Filter '*.exe' | Select-Object -First 1

  Mark 'install, step 3: from a read-only folder'
  $p = Start-Process $installer.FullName -PassThru
  $d = WaitDialog $p 90
  $r.readonly_question = Inside $d
  if ($d -ne [IntPtr]::Zero) {
    [Dialogs]::Click($d, 6)                          # IDYES: Install
    Start-Sleep -Seconds 15
    $d = WaitDialog $p 120
    $r.readonly_result = Inside $d
    if ($d -ne [IntPtr]::Zero) { [Dialogs]::Click($d, 1); [Dialogs]::Click($d, 8) }   # IDOK, IDCLOSE
  }
  $r.readonly_exit = Waited $p 60

} catch { $r.error_readonly = "$_" }
try {
  Mark 'install, steps 3 to 7'
  $downloads = Join-Path $env:USERPROFILE 'Downloads'
  New-Item -ItemType Directory -Force $downloads | Out-Null
  $copy = Join-Path $downloads $installer.Name
  Copy-Item $installer.FullName $copy
  $p = Start-Process $copy -PassThru
  $d = WaitDialog $p 90
  $r.install_question = Inside $d
  $r.install_question_found = ($d -ne [IntPtr]::Zero)
  if ($d -ne [IntPtr]::Zero) {
    [Dialogs]::Click($d, 6)                          # IDYES: Install
    # the result page comes when setup has started and ended
    $until = (Get-Date).AddSeconds(90)
    while ((Get-Date) -lt $until -and -not (Get-Process setup -ErrorAction SilentlyContinue)) { Start-Sleep -Milliseconds 500 }
    $until = (Get-Date).AddSeconds(300)
    while ((Get-Date) -lt $until -and (Get-Process setup -ErrorAction SilentlyContinue)) { Start-Sleep -Seconds 2 }
    Start-Sleep -Seconds 5
    $d = WaitDialog $p 60
    $r.install_done = Inside $d
    $r.install_done_found = ($d -ne [IntPtr]::Zero)
    # OK on the result page; a press while it still installs is ignored by the installer
    $until = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $until -and -not $p.HasExited) {
      $d = [Dialogs]::Find([uint32]$p.Id)
      if ($d -ne [IntPtr]::Zero) { [Dialogs]::Click($d, 1) }     # IDOK
      Start-Sleep -Seconds 2
    }
  }
  $r.install_exit = Waited $p 120
  $r.install_folder = Test-Path (Join-Path $app 'thoron.exe')
  $e = Entry
  $r.install_entry = if ($e) { "$($e.DisplayName) $($e.DisplayVersion)" } else { $null }
  $r.install_task = TaskThere

} catch { $r.error_install = "$_" }
try {
  Mark 'first start'
  $r.first_window = StartAndClose (Join-Path $app 'thoron.exe')
  $r.first_profile = Test-Path (Join-Path $data 'Local State')

} catch { $r.error_first_start = "$_" }
try {
  Mark 'updates, section 4: update-mode'
  # the guide's command, as it is written there
  Set-Content -Path "$env:LOCALAPPDATA\Thoron\Application\update-mode" -Value off
  $r.mode_file = "$(Get-Content (Join-Path $app 'update-mode') -ErrorAction SilentlyContinue)".Trim()
  $setup = Get-ChildItem $app -Recurse -Filter 'ThoronSetup.exe' | Select-Object -First 1
  if ($setup) {
    $p = Start-Process $setup.FullName -ArgumentList '--scheduled', '--variant=win-x64-avx2' -PassThru
    $r.mode_scheduled_exit = Waited $p 120
  }

} catch { $r.error_mode = "$_" }
try {
  Mark 'remove, installed'
  $e = Entry
  # step 2: the profile copied somewhere first
  Copy-Item $data (Join-Path $docs 'User Data backup') -Recurse
  $r.remove_backup = Test-Path (Join-Path $docs 'User Data backup\Local State')
  # step 3: what Windows Settings runs for Uninstall
  $s = "$($e.UninstallString)"
  $r.remove_command_found = [bool]$s
  if ($s -match '^"([^"]+)"\s*(.*)$') { $exe = $Matches[1]; $rest = $Matches[2] } else { $exe = $s; $rest = '' }
  $p = Start-Process $exe -ArgumentList $rest -PassThru
  # Thoron's own question (its browser shows it): the window of a thoron process with a check box
  $question = $null
  $until = (Get-Date).AddSeconds(120)
  while ((Get-Date) -lt $until -and -not $question) {
    foreach ($w in @($AE::RootElement.FindAll($TS::Children, [System.Windows.Automation.Condition]::TrueCondition))) {
      try {
        if ((Get-Process -Id $w.Current.ProcessId -ErrorAction SilentlyContinue).Name -eq 'thoron' -and
            $w.FindFirst($TS::Descendants, (Kind $CT::CheckBox))) { $question = $w }
      } catch {}
    }
    if (-not $question) { Start-Sleep -Seconds 1 }
  }
  $r.remove_question = [bool]$question
  if ($question) {
    # step 4: the box that also deletes browsing data, left as it is (its state is read, not its words)
    $boxes = @($question.FindAll($TS::Descendants, (Kind $CT::CheckBox)))
    $r.remove_boxes = @($boxes | ForEach-Object {
      "box = $($_.GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern).Current.ToggleState)" })
    $r.remove_buttons = @($question.FindAll($TS::Descendants, (Kind $CT::Button))).Count
    # Uninstall is the question's default button: Enter presses it
    Add-Type -AssemblyName System.Windows.Forms
    try { $question.SetFocus() } catch {}
    Start-Sleep -Milliseconds 500
    [System.Windows.Forms.SendKeys]::SendWait('{ENTER}')
  }
  $r.remove_exit = Waited $p 300
  $end = (Get-Date).AddSeconds(60)
  while ((Test-Path (Join-Path $app 'thoron.exe')) -and (Get-Date) -lt $end) { Start-Sleep -Seconds 2 }
  $r.remove_program_gone = -not (Test-Path (Join-Path $app 'thoron.exe'))
  $r.remove_entry_gone = -not (Entry)
  $r.remove_task_gone = -not (TaskThere)
  $r.remove_profile_kept = Test-Path (Join-Path $data 'Local State')

} catch { $r.error_remove = "$_" }
try {
  Mark 'portable, steps 2 to 4'
  $zip = Get-ChildItem 'C:\ThoronTest\in\portable' -Filter '*.zip' | Select-Object -First 1
  $line = Get-Content 'C:\ThoronTest\in\SHA256SUMS' | Where-Object { $_ -match [regex]::Escape($zip.Name) } | Select-Object -First 1
  $hash = (Get-FileHash $zip.FullName -Algorithm SHA256).Hash.ToLower()
  $r.portable_hash_matches = [bool]($line -and $line.StartsWith($hash))
  $shell = New-Object -ComObject Shell.Application
  $shell.NameSpace($docs).CopyHere($shell.NameSpace($zip.FullName).Items(), 16 + 4)
  $folder = Join-Path $docs 'ThoronPortable'
  $end = (Get-Date).AddSeconds(120)
  while (-not (Test-Path (Join-Path $folder 'Thoron.exe')) -and (Get-Date) -lt $end) { Start-Sleep -Seconds 2 }
  Start-Sleep -Seconds 5
  $r.portable_extracted = Test-Path (Join-Path $folder 'Thoron.exe')
  $r.portable_window = StartAndClose (Join-Path $folder 'Thoron.exe')
  $r.portable_profile = Test-Path (Join-Path $folder 'User Data\Local State')

  Mark 'remove, portable'
  Remove-Item $folder -Recurse -Force -ErrorAction SilentlyContinue
  $r.portable_gone = -not (Test-Path $folder)
} catch {
  $r.error = "$_"
}
$r.done = $true
Save
Trace 'done'
Stop-Computer -Force
"""


def problems(r: dict) -> dict[str, list[str]]:
    """What each guide step showed that the guide does not say, by step."""
    out: dict[str, list[str]] = {}

    def check(step: str, ok: bool, text: str) -> None:
        out.setdefault(step, [])
        if not ok:
            out[step].append(text)

    for key in sorted(k for k in r if k.startswith("error")):
        check("script", False, f"{key}: {r[key]}")
    check("install, step 3: read-only folder", "109" in str(r.get("readonly_result")),
          f"the message does not name the code 109: {r.get('readonly_result')!r}")
    check("install, step 3: read-only folder", r.get("readonly_exit") not in (0, "timeout"),
          f"from a read-only folder the installer ended with {r.get('readonly_exit')}")
    check("install, step 4", bool(r.get("install_question_found")), "no question before installing")
    check("install, step 4", bool(r.get("install_done_found")), "no message at the end")
    check("install, step 4", r.get("install_exit") == 0, f"the installer ended with {r.get('install_exit')}")
    check("install, step 5", bool(r.get("install_folder")), "no thoron.exe in %LOCALAPPDATA%\\Thoron\\Application")
    check("install, step 6", str(r.get("install_entry") or "").startswith("Thoron "),
          f"the list of installed apps shows {r.get('install_entry')!r}")
    check("install, step 7", bool(r.get("install_task")), "no daily update task")
    check("first start", bool(r.get("first_window")) and bool(r.get("first_profile")),
          "Thoron did not start with a window and make its profile")
    check("updates, section 4", r.get("mode_file") == "off", f"update-mode holds {r.get('mode_file')!r}")
    check("updates, section 4", str(r.get("mode_scheduled_exit")) == "9",
          f"the daily look ended with {r.get('mode_scheduled_exit')} (9: not automatic)")
    check("remove, installed, step 2", bool(r.get("remove_backup")), "the profile was not copied")
    check("remove, installed, step 3", bool(r.get("remove_question")), "no Uninstall question")
    boxes = r.get("remove_boxes") or []
    boxes = [boxes] if isinstance(boxes, str) else boxes
    check("remove, installed, step 4", bool(boxes) and all(b.endswith("= Off") for b in boxes),
          f"the box that deletes browsing data is not unticked: {boxes}")
    for key, text in (("remove_program_gone", "the program is still there"),
                      ("remove_entry_gone", "the entry is still in the list of installed apps"),
                      ("remove_task_gone", "the daily task is still there"),
                      ("remove_profile_kept", "the profile was not kept")):
        check("remove, installed", bool(r.get(key)), text)
    check("portable, step 2", bool(r.get("portable_hash_matches")), "the SHA-256 is not the one in SHA256SUMS")
    check("portable, step 3", bool(r.get("portable_extracted")), "Extract All gave no ThoronPortable\\Thoron.exe")
    check("portable, step 4", bool(r.get("portable_window")) and bool(r.get("portable_profile")),
          "Thoron.exe did not start with a window and make User Data in the folder")
    check("remove, portable", bool(r.get("portable_gone")), "the folder could not be deleted")
    return out


def run(installer: Path, chrome_bin: Path, launcher: Path, updater: Path, work: Path, timeout: float) -> dict:
    if work.exists():
        shutil.rmtree(work)
    for name in ("in/install", "in/portable", "out"):
        (work / name).mkdir(parents=True)
    shutil.copy2(installer, work / "in/install" / installer.name)
    made = subprocess.run([sys.executable, "-I", str(REPO / "tools/release/portable.py"), "build", "--chrome-bin",
                           str(chrome_bin), "--launcher", str(launcher), "--updater", str(updater), "--dist",
                           str(work / "dist"), "--variant", "win-x64-avx2"], capture_output=True, text=True)
    if made.returncode:
        return {"error": f"the portable package could not be made: {made.stdout[-300:]} {made.stderr[-300:]}"}
    package = next((work / "dist").glob("*-portable.zip"))
    shutil.copy2(package, work / "in/portable" / package.name)
    sums = "".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n"
                   for p in (work / "in/install" / installer.name, work / "in/portable" / package.name))
    (work / "in/SHA256SUMS").write_text(sums, encoding="utf-8", newline="\n")
    (work / "in/run.ps1").write_text(RUN, encoding="utf-8-sig", newline="\r\n")
    config = work / "thoron-guides.wsb"
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
    p.add_argument("--chrome-bin", type=Path, required=True)
    p.add_argument("--launcher", type=Path, required=True)
    p.add_argument("--updater", type=Path, required=True)
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--timeout", type=float, default=1500)
    a = p.parse_args(argv)
    found = run(a.installer.resolve(), a.chrome_bin.resolve(), a.launcher.resolve(), a.updater.resolve(),
                a.work.resolve(), a.timeout)
    print(json.dumps(found, indent=1))
    if not found.get("done"):
        print(f"GUIDES CHECK: NOT FINISHED (reached {found.get('reached')}; {found.get('error', '')})")
        return 1
    found_problems = problems(found)
    for step, issues in found_problems.items():
        print(f"{'PASS' if not issues else 'FAIL'}  {step}")
        for issue in issues:
            print(f"      {issue}")
    count = sum(len(v) for v in found_problems.values())
    print(f"GUIDES CHECK: {'PASSED' if not count else f'FAILED ({count} problem(s))'}")
    return 1 if count else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
