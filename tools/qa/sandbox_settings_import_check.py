#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Settings' import from another browser of the Chromium family, on a clean Windows (ROADMAP P3.13, P3.14).
Windows only.

In Windows Sandbox (a clean Windows, gone when it closes; networking off) Thoron is installed for the user.
There is no other browser of the family in it, so the script makes a Thorium profile the way Thorium would:
Thoron's own program started on `%LOCALAPPDATA%\\Thorium\\User Data`, then closed; a bookmark and a history
entry, both made up, are written into that profile with Python's standard library (handed in from the PC,
as in sandbox_import_guide_check.py). Thoron is then started on a profile of its own with its DevTools port
open on 127.0.0.1, and through it the script uses Settings' import dialog as a person would, reading and
pressing it by its element ids, never by its words:

    listed           the dialog lists "Thorium" among the browsers it found, and not Thoron itself
    running          with Thorium running, Import shows Thoron's request to close it (a dialog of its own):
                     nothing is imported, and Thorium keeps running
    import           Thorium closed and the request's default button (Try again) pressed: the import ends
                     with success
    the data         after Thoron is closed, its profile holds the bookmark (in a folder of its own) and the
                     history entry; Thorium's profile still holds both, unchanged

    py -3 -I tools/qa/sandbox_settings_import_check.py --installer <thoron_AVX2_mini_installer.exe> --work <scratch>
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
from tools.qa import sandbox_import_guide_check as ig  # noqa: E402
from tools.qa import sandbox_install_check as sb  # noqa: E402

BOOKMARK = "https://example.org/thoron-import-bookmark"
HISTORY = "https://example.org/thoron-import-history"
# Made-up data for the Thorium profile, and the look into both profiles afterwards (run with Python's own
# standard library in the Sandbox).
DATA = r'''import json, sqlite3, sys, time
from pathlib import Path

BOOKMARK, HISTORY = "%s", "%s"
mode, folder = sys.argv[1], Path(sys.argv[2]) / "Default"
if mode == "write":
    folder_of = lambda name, i, children: {"children": children, "date_added": "13380000000000000",
                                           "date_modified": "0", "id": str(i), "name": name, "type": "folder"}
    marks = {"checksum": "", "version": 1, "roots": {
        "bookmark_bar": folder_of("Bookmarks bar", 1, [{"date_added": "13380000000000000", "id": "4",
                                                       "name": "Thoron import test", "type": "url",
                                                       "url": BOOKMARK}]),
        "other": folder_of("Other bookmarks", 2, []), "synced": folder_of("Mobile bookmarks", 3, [])}}
    (folder / "Bookmarks").write_text(json.dumps(marks), encoding="utf-8")
    db = sqlite3.connect(folder / "History")
    # an hour ago, in Chromium's time (microseconds since 1601): history keeps visits of the last 90 days only
    visit = int((time.time() - 3600 + 11644473600) * 1000000)
    db.execute("INSERT INTO urls (url, title, visit_count, typed_count, last_visit_time, hidden) "
               "VALUES (?, 'Thoron import test', 3, 1, ?, 0)", (HISTORY, visit))
    db.commit()
    db.close()
    print("written")
else:
    marks = (folder / "Bookmarks").read_text(encoding="utf-8") if (folder / "Bookmarks").is_file() else ""
    rows = []
    if (folder / "History").is_file():
        db = sqlite3.connect(f"file:{folder / 'History'}?mode=ro", uri=True)
        rows = [r[0] for r in db.execute("SELECT url FROM urls WHERE url = ?", (HISTORY,))]
        db.close()
    print(json.dumps({"bookmark": BOOKMARK in marks, "history": HISTORY in rows}))
''' % (BOOKMARK, HISTORY)

RUN = r"""$ErrorActionPreference = 'Continue'
$out = 'C:\ThoronTest\out'
$r = [ordered]@{}
function Save { $r | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 (Join-Path $out 'results.json') }
function Trace($text) { Add-Content -Encoding utf8 -Path (Join-Path $out 'trace.txt') -Value "$(Get-Date -Format HH:mm:ss) $text" }
function Mark($step) { $r.reached = $step; Save; Trace "step: $step" }
$python = 'C:\ThoronTest\in\python\python.exe'
$port = 9334
function Tabs { try { @((Invoke-RestMethod "http://127.0.0.1:$port/json/list" -TimeoutSec 10) | Where-Object { $_.type -eq 'page' }) } catch { @() } }
function Evaluate($tab, $expression) {
  $ws = New-Object System.Net.WebSockets.ClientWebSocket
  $none = [Threading.CancellationToken]::None
  [void]$ws.ConnectAsync([Uri]$tab.webSocketDebuggerUrl, $none).Wait(10000)
  $msg = @{ id = 1; method = 'Runtime.evaluate'; params = @{ expression = $expression; returnByValue = $true } } | ConvertTo-Json -Compress -Depth 5
  $bytes = [Text.Encoding]::UTF8.GetBytes($msg)
  [void]$ws.SendAsync((New-Object 'ArraySegment[byte]' (,$bytes)), 'Text', $true, $none).Wait(10000)
  $buffer = New-Object byte[] 262144
  $got = $ws.ReceiveAsync((New-Object 'ArraySegment[byte]' (,$buffer)), $none)
  [void]$got.Wait(15000)
  $text = [Text.Encoding]::UTF8.GetString($buffer, 0, $got.Result.Count)
  $ws.Dispose()
  # the value the expression gave, which the page makes JSON itself
  try { return (($text | ConvertFrom-Json).result.result.value) } catch { return $text }
}
# finds the import dialog through the shadow roots of Settings
$dialog = "const deep = (root, s) => { const f = root.querySelector(s); if (f) return f; for (const e of root.querySelectorAll('*')) if (e.shadowRoot) { const g = deep(e.shadowRoot, s); if (g) return g; } return null; }; const d = deep(document, 'settings-import-data-dialog');"
function Python($arguments) { (& $python -I @arguments 2>&1 | Out-String).Trim() }
function Thoriums { @(Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'thoron.exe' -and $_.CommandLine -like '*Thorium\User Data*' }) }
function TopWindows($ids) {
  # the visible top-level windows of these processes
  Add-Type -AssemblyName UIAutomationClient
  $all = [System.Windows.Automation.AutomationElement]::RootElement.FindAll([System.Windows.Automation.TreeScope]::Children, [System.Windows.Automation.Condition]::TrueCondition)
  @($all | Where-Object { $ids -contains $_.Current.ProcessId })
}
$app = Join-Path $env:LOCALAPPDATA 'Thoron\Application'
$thorium = "$env:LOCALAPPDATA\Thorium\User Data"
$thoron = Join-Path $env:LOCALAPPDATA 'Thoron\Import test'
try {
  Mark 'install'
  $copy = Join-Path $env:TEMP 'installer.exe'
  Copy-Item (Get-ChildItem 'C:\ThoronTest\in\install' -Filter '*.exe' | Select-Object -First 1).FullName $copy
  $p = Start-Process $copy -ArgumentList '--silent', '--do-not-launch-chrome' -PassThru
  $null = $p.WaitForExit(300000)
  $r.installed = Test-Path (Join-Path $app 'thoron.exe')

  Mark 'a Thorium profile with a bookmark and a history entry'
  Start-Process (Join-Path $app 'thoron.exe') -ArgumentList "--user-data-dir=`"$thorium`"", '--no-first-run', 'about:blank' | Out-Null
  Start-Sleep -Seconds 20
  Thoriums | ForEach-Object { $q = Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue; if ($q -and $q.MainWindowHandle -ne 0) { try { [void]$q.CloseMainWindow() } catch {} } }
  $end = (Get-Date).AddSeconds(30); while ((Thoriums) -and (Get-Date) -lt $end) { Start-Sleep -Seconds 1 }
  Start-Sleep -Seconds 3
  $r.data_written = Python @('C:\ThoronTest\in\data.py', 'write', "`"$thorium`"")
  $r.thorium_before = Python @('C:\ThoronTest\in\data.py', 'read', "`"$thorium`"")

  Mark 'Thorium runs; Settings import'
  Start-Process (Join-Path $app 'thoron.exe') -ArgumentList "--user-data-dir=`"$thorium`"", '--no-first-run', 'about:blank' | Out-Null
  Start-Sleep -Seconds 15
  Start-Process (Join-Path $app 'thoron.exe') -ArgumentList "--user-data-dir=`"$thoron`"", '--no-first-run', "--remote-debugging-port=$port" | Out-Null
  Start-Sleep -Seconds 25
  # an address on the command line opens no chrome:// page: the first tab goes there, as when a person types it
  $first = Tabs | Select-Object -First 1
  if ($first) { [void](Evaluate $first "location.href = 'chrome://settings/importData'; 'going'") }
  Start-Sleep -Seconds 8
  $r.tabs_seen = @(Tabs | ForEach-Object { $_.url })
  $tab = Tabs | Where-Object { $_.url -like 'chrome://settings*' } | Select-Object -First 1
  $r.settings_open = [bool]$tab
  if ($tab) {
    $r.listed = Evaluate $tab "(() => { $dialog if (!d) return 'no dialog'; const s = d.shadowRoot.getElementById('browserSelect'); return JSON.stringify(Array.from(s.options).map(o => o.textContent.trim())); })()"
    $r.chosen = Evaluate $tab "(() => { $dialog const s = d.shadowRoot.getElementById('browserSelect'); const i = Array.from(s.options).findIndex(o => o.textContent.trim().startsWith('Thorium')); if (i < 0) return -1; s.selectedIndex = i; s.dispatchEvent(new Event('change')); return i; })()"
    Start-Sleep -Seconds 2
    $ours = @(Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'thoron.exe' -and $_.CommandLine -like '*Import test*' } | ForEach-Object { [int]$_.ProcessId })
    $r.windows_before = @(TopWindows $ours).Count
    $r.import_pressed = Evaluate $tab "(() => { $dialog d.shadowRoot.getElementById('import').click(); return 'pressed'; })()"
    Start-Sleep -Seconds 6
    $windows = @(TopWindows $ours)
    $r.windows_with_request = $windows.Count
    $r.status_while_running = Evaluate $tab "(() => { $dialog return String(d.importStatus_); })()"
    $r.thorium_still_runs = [bool](Thoriums)

    Mark 'Thorium closed; Try again'
    Thoriums | ForEach-Object { $q = Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue; if ($q -and $q.MainWindowHandle -ne 0) { try { [void]$q.CloseMainWindow() } catch {} } }
    $end = (Get-Date).AddSeconds(30); while ((Thoriums) -and (Get-Date) -lt $end) { Start-Sleep -Seconds 1 }
    Start-Sleep -Seconds 3
    $r.thorium_closed = -not (Thoriums)
    # the request is the newest window: Enter presses its default button, Try again
    $request = $windows | Where-Object { $_.Current.Name -ne ($windows | Select-Object -First 1).Current.Name } | Select-Object -Last 1
    if (-not $request) { $request = $windows | Select-Object -Last 1 }
    Add-Type -AssemblyName System.Windows.Forms
    try { $request.SetFocus() } catch {}
    Start-Sleep -Milliseconds 500
    [System.Windows.Forms.SendKeys]::SendWait('{ENTER}')
    $end = (Get-Date).AddSeconds(90)
    do { Start-Sleep -Seconds 3; $status = Evaluate $tab "(() => { $dialog return String(d.importStatus_); })()" } while ($status -notmatch 'succeeded|failed' -and (Get-Date) -lt $end)
    $r.status = $status
  }
  Mark 'the data'
  Get-Process thoron -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | ForEach-Object { try { [void]$_.CloseMainWindow() } catch {} }
  $end = (Get-Date).AddSeconds(30); while ((Get-Process thoron -ErrorAction SilentlyContinue) -and (Get-Date) -lt $end) { Start-Sleep -Seconds 1 }
  Get-Process thoron -ErrorAction SilentlyContinue | Stop-Process -Force
  Start-Sleep -Seconds 3
  $r.thoron_after = Python @('C:\ThoronTest\in\data.py', 'read', "`"$thoron`"")
  $r.thorium_after = Python @('C:\ThoronTest\in\data.py', 'read', "`"$thorium`"")
} catch {
  $r.error = "$_"
}
$r.done = $true
Save
Trace 'done'
Stop-Computer -Force
"""


def _list(value) -> list[str]:
    import json
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return [value]
    return list(value or [])


def _flags(value) -> dict:
    import json
    try:
        return json.loads(value) if isinstance(value, str) else dict(value or {})
    except ValueError:
        return {}


def problems(r: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}

    def check(step: str, ok: bool, text: str) -> None:
        out.setdefault(step, [])
        if not ok:
            out[step].append(text)

    if r.get("error"):
        check("script", False, f"it stopped: {r['error']}")
    check("setup", bool(r.get("installed")) and _flags(r.get("thorium_before")) == {"bookmark": True, "history": True},
          f"Thoron was not installed, or the Thorium profile has not the made-up data: {r.get('thorium_before')!r}")
    names = _list(r.get("listed"))
    check("listed", any(n.startswith("Thorium") for n in names), f"Thorium is not listed: {names}")
    check("listed", not any(n.startswith("Thoron") for n in names), f"Thoron lists itself: {names}")
    check("running", (r.get("windows_with_request") or 0) > (r.get("windows_before") or 0),
          "no request to close Thorium came up")
    check("running", "succeeded" not in str(r.get("status_while_running")),
          f"it imported while Thorium ran ({r.get('status_while_running')})")
    check("running", bool(r.get("thorium_still_runs")), "Thorium did not keep running (Thoron must never close it)")
    check("import", bool(r.get("thorium_closed")) and "succeeded" in str(r.get("status")),
          f"after Thorium closed and Try again, the import ended with {r.get('status')!r}")
    check("the data", _flags(r.get("thoron_after")) == {"bookmark": True, "history": True},
          f"Thoron's profile does not hold the bookmark and the history entry: {r.get('thoron_after')!r}")
    check("the data", _flags(r.get("thorium_after")) == {"bookmark": True, "history": True},
          f"Thorium's profile lost the data: {r.get('thorium_after')!r}")
    return out


def run(installer: Path, work: Path, timeout: float) -> dict:
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    for name in ("in/install", "out"):
        (work / name).mkdir(parents=True, exist_ok=True)
    shutil.copy2(installer, work / "in/install" / installer.name)
    ig.copy_python(work / "in/python")
    (work / "in/data.py").write_text(DATA, encoding="utf-8")
    (work / "in/run.ps1").write_text(RUN, encoding="utf-8-sig", newline="\r\n")
    config = work / "thoron-settings-import.wsb"
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
        print(f"SETTINGS IMPORT CHECK: NOT FINISHED (reached {found.get('reached')}; {found.get('error', '')})")
        return 1
    found_problems = problems(found)
    for step, issues in found_problems.items():
        print(f"{'PASS' if not issues else 'FAIL'}  {step}")
        for issue in issues:
            print(f"      {issue}")
    count = sum(len(v) for v in found_problems.values())
    print(f"SETTINGS IMPORT CHECK: {'PASSED' if not count else f'FAILED ({count} problem(s))'}")
    return 1 if count else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
