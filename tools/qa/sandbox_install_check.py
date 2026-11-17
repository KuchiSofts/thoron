#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Thoron's installer on a clean Windows, in Windows Sandbox (ROADMAP P2.8, Q.6): install, first start, uninstall.

Nothing runs on this PC itself. A Windows Sandbox starts (a clean Windows every time, gone when it closes) with
networking off, the installer in a folder it may only read and an empty folder it writes its findings to. A
script inside it:

    install    runs the installer for the user (`--silent --do-not-launch-chrome`, from the Sandbox's own disk):
               Thoron's program, its version folder and its entry among the installed programs are there
    start      starts Thoron once with its window and closes the window as a person would: Thoron ends by
               itself within 30 s and has made its profile (`User Data`)
    update     (with --update) starts Thoron again and, while it runs, installs the newer build over it
               (Chromium's in-use update, status 30): new_thoron.exe waits beside thoron.exe; after the window
               is closed and Thoron started again it runs from the newer version folder, new_thoron.exe is
               gone and the profile is kept. For every user of the PC the installer ends the running browser
               and updates in place instead (status 2; Thorium's installer patch)
    uninstall  runs Thoron's own uninstaller (`--uninstall --force-uninstall`, no question asked): the program
               and its entry are gone, and the profile, with a file put into it, is kept, as it is by default

With --system-level every step is the one for all users of the PC: the installer and uninstaller get
`--system-level`, the program goes to Program Files and its entry to the PC's list; the profile stays the
user's own. Then the script shuts the Sandbox down. Windows Sandbox must be on (Windows 11 Pro; it opens a
window for a few minutes).
    py -3 -I tools/qa/sandbox_install_check.py --installer <out>\\thoron_AVX2_mini_installer.exe --work <scratch>
        [--update <newer build>\\thoron_AVX2_mini_installer.exe] [--system-level] [--timeout 900]
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from xml.sax.saxutils import escape

INSIDE = r"C:\ThoronTest"
SANDBOX = r"C:\Windows\System32\WindowsSandbox.exe"
# Setup turns every successful install (first, repair, update, in-use update) into exit 0
# (InstallUtil::GetInstallReturnCode) and keeps the status itself in the registry as InstallerError
# (chrome/installer/util/util_constants.h); the uninstaller ends with the status.
INSTALL_OK = {0}
UNINSTALL_SUCCESSFUL = 19
IN_USE_UPDATED = 30
NEW_VERSION_UPDATED = 2
RUN = r"""$ErrorActionPreference = 'Continue'
$r = [ordered]@{}
$out = 'C:\ThoronTest\out'
# for every user of the PC (needs an administrator; the Sandbox's own account is one) or for this user
$system = Test-Path 'C:\ThoronTest\in\system-level'
$level = @(); if ($system) { $level = @('--system-level') }
$r.system_level = $system
$app = if ($system) { Join-Path $env:ProgramFiles 'Thoron\Application' } else { Join-Path $env:LOCALAPPDATA 'Thoron\Application' }
$uninstallKey = if ($system) { 'HKLM:' } else { 'HKCU:' }
$exe = Join-Path $app 'thoron.exe'
$data = Join-Path $env:LOCALAPPDATA 'Thoron\User Data'
$marker = Join-Path $data 'Default\sandbox-marker.txt'
function Save { $r | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 (Join-Path $out 'results.json') }
# the findings so far are saved before each step, so a run that hangs still says how far it got
function Mark($step) { $r.reached = $step; Save; Trace "step: $step" }
function Trace($text) {
  # what the script does, line by line with the time, so a step that hangs shows where
  Add-Content -Encoding utf8 -Path (Join-Path $out 'trace.txt') -Value "$(Get-Date -Format HH:mm:ss) $text"
}
function Busy {
  # the installer's and the browser's processes that are running, with their command lines
  @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match 'setup|installer|thoron' } |
    ForEach-Object { "$($_.ProcessId) $($_.Name) $($_.CommandLine)" }) -join ' | '
}
function Timed($file, $arguments, $seconds) {
  # a program that shows a dialog would wait for ever: it gets $seconds, then it is stopped
  Trace "run $file $($arguments -join ' ')"
  $proc = Start-Process $file -ArgumentList $arguments -PassThru
  $until = (Get-Date).AddSeconds($seconds)
  $next = (Get-Date).AddSeconds(30)
  while (-not $proc.HasExited -and (Get-Date) -lt $until) {
    Start-Sleep -Seconds 2
    if ((Get-Date) -ge $next) { Trace "still running: $(Busy)"; $next = (Get-Date).AddSeconds(30) }
  }
  if (-not $proc.HasExited) {
    Trace "stopped after $seconds s: $(Busy)"
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    return 'timeout'
  }
  Trace "ended with $($proc.ExitCode)"
  return $proc.ExitCode
}
function Install($folder) {
  # from the Sandbox's own disk: the installer unpacks into a folder next to itself, and the shared folder is
  # read-only (it ends with 109, UNABLE_TO_GET_WORK_DIRECTORY, there); --silent: without it the installer
  # waits for its Install and OK buttons
  $shared = Get-ChildItem (Join-Path 'C:\ThoronTest\in' $folder) -Filter '*.exe' | Select-Object -First 1
  $copy = Join-Path $env:TEMP ($folder + '-' + $shared.Name)
  Trace "copy $($shared.Name) to the Sandbox's disk"
  Copy-Item $shared.FullName $copy
  return Timed $copy (@('--silent', '--do-not-launch-chrome', '--verbose-logging') + $level) 300
}
function Entry {
  # Chromium writes a system install's entry in the 32-bit view of the registry (WOW6432Node)
  @("$($uninstallKey)\Software\Microsoft\Windows\CurrentVersion\Uninstall",
    "$($uninstallKey)\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall") |
    ForEach-Object { Get-ChildItem $_ -ErrorAction SilentlyContinue } |
    ForEach-Object { Get-ItemProperty $_.PsPath } | Where-Object { $_.DisplayName -like '*Thoron*' } |
    Select-Object -First 1
}
function InstallerStatus {
  # the status the installer kept for its last run, wherever the build's registry key is
  # read with reg.exe and a time limit: PowerShell's own registry reader hung on HKLM\Software\Thoron
  # after an update of an install for every user
  $hive = if ($system) { 'HKLM' } else { 'HKCU' }
  foreach ($view in @('/reg:64', '/reg:32')) {
    $file = Join-Path $env:TEMP "status$($view -replace '\W', '').txt"
    Trace "status: reg query $hive\Software\Thoron $view"
    $q = Start-Process reg.exe -ArgumentList @('query', "$hive\Software\Thoron", '/s', '/v', 'InstallerError', $view) `
           -RedirectStandardOutput $file -NoNewWindow -PassThru
    if (-not $q.WaitForExit(30000)) { Stop-Process -Id $q.Id -Force -ErrorAction SilentlyContinue; Trace "status: reg.exe hung"; continue }
    $line = Get-Content $file -ErrorAction SilentlyContinue | Where-Object { $_ -match 'InstallerError' } | Select-Object -First 1
    if ($line -and ($line -match 'InstallerError\s+REG_DWORD\s+0x([0-9a-fA-F]+)')) {
      Trace "status: $($line.Trim())"
      return [Convert]::ToInt32($Matches[1], 16)
    }
  }
  Trace "status: none kept"
  return $null
}
function Versions {
  @(Get-ChildItem $app -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match '^\d+\.\d+\.\d+\.\d+$' } | ForEach-Object { $_.Name })
}
function Windows { Get-Process thoron -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } }
function Started {
  # a normal start with a window (headless would use a throwaway profile in TEMP)
  $b = Start-Process $exe -ArgumentList '--no-first-run', 'about:blank' -PassThru
  Start-Sleep -Seconds 25
  return [bool](Windows)
}
function Loaded {
  # the version folder the browser window's process runs from
  foreach ($w in @(Windows)) {
    foreach ($m in @($w.Modules)) {
      if ($m.FileName -match '\\Application\\(\d+\.\d+\.\d+\.\d+)\\') { return $Matches[1] }
    }
  }
  return ''
}
function Close {
  # the way a person closes it, so Thoron writes its profile as it does for them
  Windows | ForEach-Object { [void]$_.CloseMainWindow() }
  $closing = (Get-Date).AddSeconds(30)
  while ((Get-Process thoron -ErrorAction SilentlyContinue) -and (Get-Date) -lt $closing) { Start-Sleep -Seconds 1 }
  $byItself = -not (Get-Process thoron -ErrorAction SilentlyContinue)
  Get-Process thoron -ErrorAction SilentlyContinue | Stop-Process -Force
  Start-Sleep -Seconds 3
  return $byItself
}
try {
  Mark 'install'
  $r.install_exit = Install 'install'
  $r.program = Test-Path $exe
  $r.version_folders = @(Versions)
  $e = Entry
  $r.entry = [bool]$e
  if ($e) { $r.entry_name = "$($e.DisplayName)"; $r.entry_version = "$($e.DisplayVersion)" }
  Mark 'start'
  $r.started = Started
  $r.window = $r.started
  Mark 'close'
  $r.closed_by_itself = Close
  $r.profile = Test-Path (Join-Path $data 'Local State')
  New-Item -ItemType Directory -Force (Join-Path $data 'Default') | Out-Null
  Set-Content -Path $marker -Value 'kept'
  if (Test-Path 'C:\ThoronTest\in\update') {
    # the newer build installed while the older one runs: Chromium leaves new_thoron.exe beside thoron.exe
    # and swaps them when the browser closes (or at its next start)
    Mark 'update: start the older version'
    $r.update_started = Started
    $r.update_from = Loaded
    $r.update_browser_before = @(Get-Process thoron -ErrorAction SilentlyContinue).Count
    Trace "before the update: $(Busy)"
    Mark 'update: install the newer version'
    $r.update_exit = Install 'update'
    $r.update_browser_after = @(Get-Process thoron -ErrorAction SilentlyContinue).Count
    Trace "after the update: $(Busy)"
    $r.update_status = InstallerStatus
    Trace "look for new_thoron.exe"
    $r.update_new_exe_while_running = Test-Path (Join-Path $app 'new_thoron.exe')
    Trace "list the version folders"
    $r.update_folders_while_running = @(Versions)
    Mark 'update: close the older version'
    $r.update_closed_by_itself = Close
    $r.update_new_exe_after_close = Test-Path (Join-Path $app 'new_thoron.exe')
    Mark 'update: start again'
    $r.update_restarted = Started
    $r.update_to = Loaded
    Mark 'update: close again'
    [void](Close)
    $r.update_new_exe_after = Test-Path (Join-Path $app 'new_thoron.exe')
    $r.update_folders_after = @(Versions)
    $r.update_marker_kept = Test-Path $marker
    $r.update_local_state = Test-Path (Join-Path $data 'Local State')
  }
  $setup = Get-ChildItem $app -Recurse -Filter 'setup.exe' -ErrorAction SilentlyContinue | Select-Object -First 1
  $r.setup_found = [bool]$setup
  Mark 'uninstall'
  if ($setup) {
    $r.uninstall_exit = Timed $setup.FullName (@('--uninstall', '--force-uninstall', '--verbose-logging') + $level) 300
  }
  Start-Sleep -Seconds 5
  $r.program_after = Test-Path $exe
  $r.entry_after = [bool](Entry)
  $r.profile_after = Test-Path $marker
  $r.local_state_after = Test-Path (Join-Path $data 'Local State')
} catch {
  $r.error = "$_"
}
# the installer's logs, wherever it wrote them, and what the temporary folder holds, for a failure
foreach ($dir in @($env:TEMP, (Join-Path $env:WINDIR 'Temp'), (Join-Path $env:WINDIR 'SystemTemp'),
                   (Join-Path $env:LOCALAPPDATA 'Thoron'), (Join-Path $env:ProgramFiles 'Thoron'))) {
  Get-ChildItem $dir -Recurse -Filter '*.log' -ErrorAction SilentlyContinue | Select-Object -First 20 |
    ForEach-Object { Copy-Item $_.FullName (Join-Path $out ("log-" + $_.Name)) -ErrorAction SilentlyContinue }
}
$r.temp_listing = @(Get-ChildItem $env:TEMP -ErrorAction SilentlyContinue | Select-Object -First 40 |
                    ForEach-Object { "$($_.Name) $($_.Length)" })
$r.done = $true
Save
Stop-Computer -Force
"""


def wsb(work: Path) -> str:
    """The Sandbox's configuration: no network, no GPU, the two shared folders, the script at logon."""
    folders = "".join(
        f"<MappedFolder><HostFolder>{escape(str(work / name))}</HostFolder>"
        f"<SandboxFolder>{INSIDE}\\{name}</SandboxFolder><ReadOnly>{'true' if name == 'in' else 'false'}</ReadOnly>"
        "</MappedFolder>" for name in ("in", "out"))
    return ("<Configuration><VGpu>Disable</VGpu><Networking>Disable</Networking><MemoryInMB>4096</MemoryInMB>"
            "<ClipboardRedirection>Disable</ClipboardRedirection><PrinterRedirection>Disable</PrinterRedirection>"
            f"<MappedFolders>{folders}</MappedFolders><LogonCommand><Command>powershell.exe -NoProfile "
            f"-ExecutionPolicy Bypass -File {INSIDE}\\in\\run.ps1</Command></LogonCommand></Configuration>")


def _folders(value) -> list[str]:
    """A list of folder names as the script saved it (PowerShell can turn a list of one into a string)."""
    return [value] if isinstance(value, str) else list(value or [])


def problems(r: dict) -> dict[str, list[str]]:
    """What each step found wrong, by step."""
    out: dict[str, list[str]] = {"install": [], "start": []}       # in the order the steps run
    if r.get("error"):
        out["install"].append(f"the script stopped: {r['error']}")
    if r.get("install_exit") not in INSTALL_OK:
        out["install"].append(f"the installer ended with {r.get('install_exit')}")
    if not r.get("program"):
        out["install"].append("no thoron.exe was installed")
    if len(_folders(r.get("version_folders"))) != 1:
        out["install"].append(f"version folders: {r.get('version_folders')}")
    if not r.get("entry"):
        out["install"].append("no entry among the installed programs")
    if not r.get("started"):
        out["start"].append("Thoron did not start")
    elif not r.get("window"):
        out["start"].append("Thoron started without a window")
    elif not r.get("closed_by_itself"):
        out["start"].append("Thoron did not close within 30 s of closing its window")
    if not r.get("profile"):
        out["start"].append("no profile was made")
    if any(k.startswith("update_") for k in r):
        out["update"] = update_problems(r)
    out["uninstall"] = []
    if not r.get("setup_found"):
        out["uninstall"].append("no uninstaller (setup.exe) next to the program")
    elif r.get("uninstall_exit") != UNINSTALL_SUCCESSFUL:
        out["uninstall"].append(f"the uninstaller ended with {r.get('uninstall_exit')}")
    if r.get("program_after"):
        out["uninstall"].append("thoron.exe is still there")
    if r.get("entry_after"):
        out["uninstall"].append("the entry among the installed programs is still there")
    if not r.get("profile_after") or not r.get("local_state_after"):
        out["uninstall"].append("the profile was not kept")
    return out


def _version(folder: str) -> tuple[int, ...]:
    return tuple(int(n) for n in folder.split(".")) if folder else ()


def update_problems(r: dict) -> list[str]:
    """The newer build installed over the running older one (ROADMAP P3.6).

    For one user, Chromium's in-use update: the running browser is left alone, new_thoron.exe waits beside
    thoron.exe (status 30) and is swapped in when the browser closes. For every user of the PC
    (--system-level), Thorium's installer patch (other/mini_installer.patch) ends the running browser and
    updates in place (status 2): such an install has no Google Update to finish the swap later. Either way
    Thoron must start again on the newer version with the profile kept."""
    system = bool(r.get("system_level"))
    found = []
    if not r.get("update_started") or not r.get("update_from"):
        found.append("the older version did not start before the update")
    if r.get("update_exit") not in INSTALL_OK:
        found.append(f"the update ended with {r.get('update_exit')}")
    status = NEW_VERSION_UPDATED if system else IN_USE_UPDATED
    if r.get("update_status") is not None and r.get("update_status") != status:
        found.append(f"the installer kept status {r.get('update_status')}, not {status}")
    if system:
        if r.get("update_browser_before") and r.get("update_browser_after"):
            found.append("the update of an install for every user left the older browser running")
        if r.get("update_new_exe_while_running"):
            found.append("new_thoron.exe after the update of an install for every user")
    else:
        if r.get("update_browser_before") and r.get("update_browser_after") == 0:
            found.append("the update ended the running browser instead of leaving it to be swapped on its next start")
        if not r.get("update_new_exe_while_running"):
            found.append("no new_thoron.exe while the older version ran")
    newest = max(_folders(r.get("update_folders_while_running")), key=_version, default="")
    if not newest or _version(newest) <= _version(r.get("update_from") or ""):
        found.append(f"the update brought no newer version folder: {r.get('update_folders_while_running')}")
    if not r.get("update_closed_by_itself"):
        found.append("the older version did not close within 30 s of closing its window")
    if not r.get("update_restarted"):
        found.append("Thoron did not start again after the update")
    elif r.get("update_to") != newest:
        found.append(f"after the restart Thoron runs {r.get('update_to') or 'no version'}, not {newest}")
    if r.get("update_new_exe_after"):
        found.append("new_thoron.exe is still there after the restart")
    if not r.get("update_marker_kept") or not r.get("update_local_state"):
        found.append("the profile was not kept through the update")
    return found


def run(installer: Path, work: Path, timeout: float, update: Path | None = None, system_level: bool = False) -> dict:
    if work.exists():
        shutil.rmtree(work)
    (work / "out").mkdir(parents=True)
    for folder, file in (("install", installer), ("update", update)):
        if file:
            (work / "in" / folder).mkdir(parents=True)
            shutil.copy2(file, work / "in" / folder / file.name)
    if system_level:
        (work / "in" / "system-level").write_text("", encoding="utf-8")
    (work / "in" / "run.ps1").write_text(RUN, encoding="utf-8-sig", newline="\r\n")
    config = work / "thoron-test.wsb"
    config.write_text(wsb(work), encoding="utf-8")
    subprocess.Popen([SANDBOX, str(config)])
    results = work / "out" / "results.json"
    end = time.monotonic() + timeout
    found = read_results(results)
    while time.monotonic() < end and not found.get("done"):
        time.sleep(5)
        found = read_results(results)
    if not found.get("done"):
        found["error"] = f"no end within {timeout:g} s; it got as far as: {found.get('reached', 'nothing')}"
    close_sandbox()
    return found


def read_results(path: Path) -> dict:
    """The findings the script saved so far ({} before the first save or while it is being written)."""
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


def close_sandbox(grace: float = 60) -> None:
    """The script shuts its Sandbox down; one that is still there after `grace` seconds is closed (only one
    Sandbox can run at a time, so it is this one)."""
    end = time.monotonic() + grace
    while time.monotonic() < end and _sandbox_running():
        time.sleep(3)
    if _sandbox_running():
        subprocess.run(["taskkill", "/IM", "WindowsSandboxClient.exe", "/F"], capture_output=True)
        subprocess.run(["taskkill", "/IM", "WindowsSandbox.exe", "/F"], capture_output=True)


def _sandbox_running() -> bool:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq WindowsSandboxClient.exe"], capture_output=True,
                         text=True).stdout
    return "WindowsSandboxClient.exe" in out


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--installer", type=Path, required=True)
    p.add_argument("--work", type=Path, required=True, help="a scratch folder; shared with the Sandbox")
    p.add_argument("--update", type=Path, help="a newer build's installer, installed while the first one runs")
    p.add_argument("--system-level", action="store_true",
                   help="install for every user of the PC (Program Files), not for the user who runs it")
    p.add_argument("--timeout", type=float, default=900)
    a = p.parse_args(argv)
    if not Path(SANDBOX).is_file():
        print("SANDBOX INSTALL CHECK: FAILED (Windows Sandbox is not on)")
        return 1
    found = run(a.installer.resolve(), a.work.resolve(), a.timeout, a.update.resolve() if a.update else None,
                a.system_level)
    print(json.dumps(found, indent=1))
    by_step = problems(found)
    for step, found_problems in by_step.items():
        print(f"{'PASS' if not found_problems else 'FAIL'}  {step}")
        for f in found_problems:
            print(f"      {f}")
    bad = sum(len(v) for v in by_step.values())
    print(f"SANDBOX INSTALL CHECK: {'PASSED' if not bad else f'FAILED ({bad} problem(s))'}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
