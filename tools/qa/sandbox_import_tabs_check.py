#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Open tabs and extensions in Settings' import from the Chromium family, on a clean Windows (ROADMAP P3.22,
P3.14). Windows only.

In Windows Sandbox (a clean Windows, gone when it closes; networking on, so that an extension can come from the
Chrome Web Store) Thoron is installed for the user. Thorium, Chrome, Edge, Brave, Vivaldi and Opera are made the
way each keeps its profile, each with the golden session file of tools/migrate/tests/data/sessions (written by
that browser itself: windows, tabs with their back and forward history, pinned tabs, tab groups with names,
colours and collapsed or not), and the made-up pages they show are served again on 127.0.0.1 by
tools/qa/session_golden.py's server. Chrome's profile also lists one extension from the Chrome Web Store (uBlock
Origin Lite) and one unpacked. Thoron is then started with its DevTools port open on 127.0.0.1, and through it
Settings' import dialog is used as a person would, by its element ids: for each browser only **Open tabs and tab
groups** is ticked (for Chrome, **Extensions** too) and Import pressed. Then Thoron exits as from its menu
(DevTools' Browser.close), which writes every open window to its own session file, and the steps are checked:

    imported     every import ends with success
    the tabs     Thoron's session holds each source window: the same tabs in the same order, each with the same
                 pages of its history and the same current page, pinned as before, in groups with the same name,
                 colour and collapsed state, and the same selected tab
    extensions   the store extension is installed in Thoron from the store, switched off until its access is
                 accepted (or on, when it asks for none); the unpacked one is not installed
    the report   the last import's report counts the open tabs, the extension to install and the one left out,
                 and names no address

    py -3 -I tools/qa/sandbox_import_tabs_check.py --installer <thoron_AVX2_mini_installer.exe> --work <scratch>
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
from tools.qa.sandbox_vivaldi_opera_check import wsb  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
GOLDEN = REPO / "tools/migrate/tests/data/sessions"
# (the name Settings lists, the golden folder, where the browser keeps its profiles, whether its only profile is
# the folder itself); Chrome last, so that the report on record is the one with the extensions
SOURCES = (
    ("Thorium", "thorium", r"%LOCALAPPDATA%\Thorium\User Data", False),
    ("Edge", "edge", r"%LOCALAPPDATA%\Microsoft\Edge\User Data", False),
    ("Brave", "brave", r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\User Data", False),
    ("Vivaldi", "vivaldi", r"%LOCALAPPDATA%\Vivaldi\User Data", False),
    ("Opera", "opera", r"%APPDATA%\Opera Software\Opera Stable", True),
    ("Chrome", "chrome", r"%LOCALAPPDATA%\Google\Chrome\User Data", False),
)
STORE_EXTENSION = "ddkjiahejlhfcafbddmgiahcphecmpfh"     # uBlock Origin Lite, from the Chrome Web Store
UNPACKED_EXTENSION = "abcdefghijklmnopabcdefghijklmnop"  # made up
PORTS = (47615, 47640)

RUN = r"""$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
$out = 'C:\ThoronTest\out'
$r = [ordered]@{}
function Save { $r | ConvertTo-Json -Depth 6 | Set-Content -Encoding utf8 (Join-Path $out 'results.json') }
function Trace($text) { Add-Content -Encoding utf8 -Path (Join-Path $out 'trace.txt') -Value "$(Get-Date -Format HH:mm:ss) $text" }
function Mark($step) { $r.reached = $step; Save; Trace "step: $step" }
$python = 'C:\ThoronTest\in\python\python.exe'
$tools = 'C:\ThoronTest\in\thoron-main'
$port = 9334
function Tabs { try { @((Invoke-RestMethod "http://127.0.0.1:$port/json/list" -TimeoutSec 10) | Where-Object { $_.type -eq 'page' }) } catch { @() } }
function Cdp($tab, $method, $params) {
  $ws = New-Object System.Net.WebSockets.ClientWebSocket
  $none = [Threading.CancellationToken]::None
  [void]$ws.ConnectAsync([Uri]$tab.webSocketDebuggerUrl, $none).Wait(10000)
  $msg = @{ id = 1; method = $method; params = $params } | ConvertTo-Json -Compress -Depth 6
  $bytes = [Text.Encoding]::UTF8.GetBytes($msg)
  [void]$ws.SendAsync((New-Object 'ArraySegment[byte]' (,$bytes)), 'Text', $true, $none).Wait(10000)
  $buffer = New-Object byte[] 4194304
  $got = $ws.ReceiveAsync((New-Object 'ArraySegment[byte]' (,$buffer)), $none)
  [void]$got.Wait(30000)
  $text = [Text.Encoding]::UTF8.GetString($buffer, 0, $got.Result.Count)
  $ws.Dispose()
  return $text
}
function Evaluate($tab, $expression) {
  $text = Cdp $tab 'Runtime.evaluate' @{ expression = $expression; returnByValue = $true; awaitPromise = $true }
  try { return (($text | ConvertFrom-Json).result.result.value) } catch { return $text }
}
function Tool($arguments) {
  $o = Join-Path $env:TEMP 'tool-out.txt'; $e = Join-Path $env:TEMP 'tool-err.txt'
  $p = Start-Process $python -ArgumentList (@('-I') + $arguments) -RedirectStandardOutput $o -RedirectStandardError $e `
         -NoNewWindow -PassThru -WorkingDirectory $tools
  $null = $p.Handle
  if (-not $p.WaitForExit(300000)) { Stop-Process -Id $p.Id -Force; return @{ exit = 'timeout'; text = '' } }
  # the tools write UTF-8; the Sandbox's own code page is the PC's, so it is named
  return @{ exit = $p.ExitCode; text = ("$(Get-Content $o -Raw -Encoding utf8 -ErrorAction SilentlyContinue)");
           errors = ("$(Get-Content $e -Raw -Encoding utf8 -ErrorAction SilentlyContinue)") }
}
# finds the import dialog through the shadow roots of Settings
$dialog = "const deep = (root, s) => { const f = root.querySelector(s); if (f) return f; for (const e of root.querySelectorAll('*')) if (e.shadowRoot) { const g = deep(e.shadowRoot, s); if (g) return g; } return null; }; const d = deep(document, 'settings-import-data-dialog');"
$app = Join-Path $env:LOCALAPPDATA 'Thoron\Application'
$thoron = Join-Path $env:LOCALAPPDATA 'Thoron\Import tabs test'
try {
  Mark 'install'
  $copy = Join-Path $env:TEMP 'installer.exe'
  Copy-Item (Get-ChildItem 'C:\ThoronTest\in\install' -Filter '*.exe' | Select-Object -First 1).FullName $copy
  $p = Start-Process $copy -ArgumentList '--silent', '--do-not-launch-chrome' -PassThru
  $null = $p.WaitForExit(300000)
  $r.installed = Test-Path (Join-Path $app 'thoron.exe')

  Mark 'the pages'
  $serve = Join-Path $env:TEMP 'serve.py'
  Set-Content -Encoding ascii $serve @'
import sys, time
sys.path.insert(0, r"C:\ThoronTest\in\thoron-main")
from tools.qa.session_golden import PageServer
servers = [PageServer(port) for port in (47615, 47640)]
for server in servers:
    server.__enter__()
time.sleep(7200)
'@
  $server = Start-Process $python -ArgumentList '-I', ('"' + $serve + '"') -PassThru -WindowStyle Hidden
  Start-Sleep -Seconds 3

  Mark 'the browsers'
  $sources = Get-Content 'C:\ThoronTest\in\sources.json' -Raw | ConvertFrom-Json
  foreach ($s in $sources) {
    $root = [Environment]::ExpandEnvironmentVariables($s.user_data)
    Copy-Item -Recurse -Force (Join-Path 'C:\ThoronTest\in\sources' $s.folder) $root
  }
  $r.made = @($sources | ForEach-Object { Test-Path ([Environment]::ExpandEnvironmentVariables($_.user_data)) })
  for ($i = 0; $i -lt 60; $i++) { try { [void][System.Net.Dns]::GetHostAddresses('clients2.google.com'); break } catch { Start-Sleep -Seconds 2 } }

  Mark 'Settings import'
  Start-Process (Join-Path $app 'thoron.exe') -ArgumentList "--user-data-dir=`"$thoron`"", '--no-first-run', "--remote-debugging-port=$port" | Out-Null
  Start-Sleep -Seconds 25
  $r.imports = [ordered]@{}
  foreach ($s in $sources) {
    $first = Tabs | Where-Object { $_.url -like 'chrome://settings*' } | Select-Object -First 1
    if (-not $first) { $first = Tabs | Select-Object -First 1 }
    [void](Cdp $first 'Page.navigate' @{ url = 'chrome://settings/importData' })
    Start-Sleep -Seconds 6
    $tab = Tabs | Where-Object { $_.url -like 'chrome://settings*' } | Select-Object -First 1
    $one = [ordered]@{}
    if ($tab) {
      $one.chosen = Evaluate $tab "(() => { $dialog if (!d) return -2; const s = d.shadowRoot.getElementById('browserSelect'); const i = Array.from(s.options).findIndex(o => o.textContent.trim().startsWith('$($s.name)')); if (i < 0) return -1; s.selectedIndex = i; s.dispatchEvent(new Event('change')); return i; })()"
      Start-Sleep -Seconds 2
      $wanted = if ($s.name -eq 'Chrome') { "['importDialogOpenTabs', 'importDialogExtensions']" } else { "['importDialogOpenTabs']" }
      $one.boxes = Evaluate $tab "(() => { $dialog const want = $wanted; const boxes = Array.from(d.shadowRoot.querySelectorAll('settings-checkbox')).filter(c => !c.hidden); boxes.forEach(c => c.checked = want.includes(c.id)); return JSON.stringify(boxes.filter(c => c.checked).map(c => c.id)); })()"
      $one.pressed = Evaluate $tab "(() => { $dialog d.shadowRoot.getElementById('import').click(); return 'pressed'; })()"
      $end = (Get-Date).AddSeconds(90)
      do { Start-Sleep -Seconds 3; $status = Evaluate $tab "(() => { $dialog return d ? String(d.importStatus_) : 'no dialog'; })()" } while ($status -notmatch 'succeeded|failed' -and (Get-Date) -lt $end)
      $one.status = $status
      $one.pages_after = @(Tabs).Count
    }
    $r.imports[$s.name] = $one
    Save
  }

  Mark 'extensions'
  Start-Sleep -Seconds 60
  $tab = Tabs | Where-Object { $_.url -like 'chrome://settings*' } | Select-Object -First 1
  if ($tab) {
    [void](Cdp $tab 'Page.navigate' @{ url = 'chrome://extensions/' })
    Start-Sleep -Seconds 6
    $ext = Tabs | Where-Object { $_.url -like 'chrome://extensions*' } | Select-Object -First 1
    if ($ext) {
      $r.extensions = Evaluate $ext "chrome.developerPrivate.getExtensionsInfo({includeDisabled: true}).then(list => JSON.stringify(list.map(e => ({id: e.id, state: e.state, location: e.location, reasons: e.disableReasons}))))"
    }
  }

  Mark 'exit'
  # a normal exit of the whole browser through DevTools, as from its menu: every window stays in its session
  try { $browser = Invoke-RestMethod "http://127.0.0.1:$port/json/version" -TimeoutSec 10; [void](Cdp $browser 'Browser.close' @{}) } catch {}
  $end = (Get-Date).AddSeconds(60); while ((Get-Process thoron -ErrorAction SilentlyContinue) -and (Get-Date) -lt $end) { Start-Sleep -Seconds 1 }
  $r.thoron_left_running = [bool](Get-Process thoron -ErrorAction SilentlyContinue)
  Get-Process thoron -ErrorAction SilentlyContinue | Stop-Process -Force
  Start-Sleep -Seconds 3
  Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue

  Mark 'the tabs'
  $t = Tool @('tools\migrate\sessions.py', 'read', '--profile', ('"' + (Join-Path $thoron 'Default') + '"'))
  $r.session_exit = $t.exit
  $r.session = $t.text
  $r.session_errors = $t.errors
  $r.report = "$(Get-Content (Join-Path $thoron 'Default\Thoron import report.json') -Raw -ErrorAction SilentlyContinue)"
} catch {
  $r.error = "$_"
}
$r.done = $true
Save
Start-Sleep -Seconds 2
shutdown.exe /s /t 0
"""


def make_sources(folder: Path) -> list[dict]:
    """Each browser's user data folder the way the browser keeps it: `Local State` listing the profile, the
    profile's `Preferences` and its golden session file in `Sessions`."""
    listed = []
    for name, golden, user_data, single in SOURCES:
        root = folder / golden
        profile = root if single else root / "Default"
        (profile / "Sessions").mkdir(parents=True, exist_ok=True)
        state = {} if single else {"profile": {"info_cache": {"Default": {"name": "Person 1"}}}}
        (root / "Local State").write_text(json.dumps(state), encoding="utf-8")
        prefs: dict = {}
        if name == "Chrome":
            prefs = {"extensions": {"settings": {
                STORE_EXTENSION: {"location": 1, "from_webstore": True, "state": 1},
                UNPACKED_EXTENSION: {"location": 4, "path": "C:\\made-up\\extension", "state": 1}}}}
        (profile / "Preferences").write_text(json.dumps(prefs), encoding="utf-8")
        for session in (GOLDEN / golden).glob("Session_*"):
            shutil.copy2(session, profile / "Sessions" / session.name)
        listed.append({"name": name, "folder": golden, "user_data": user_data})
    return listed


def _group(window: dict, group_id) -> tuple | None:
    for g in window.get("groups", []):
        if g.get("id") == group_id:
            return (g.get("title"), g.get("color"), bool(g.get("collapsed")))
    return None


def shape(window: dict) -> tuple:
    """What must come over of a window: its tabs in order (pinned, group by its name, colour and collapsed state,
    the current page, every page of the history) and its selected tab. Ids, bounds and titles are not compared:
    a restore makes new ids, and a page's title is the page's own once loaded."""
    tabs = tuple((bool(t.get("pinned")), _group(window, t.get("group")), t.get("current"),
                  tuple(n.get("url") for n in t.get("navigations", []))) for t in window.get("tabs", []))
    return (window.get("selected_tab"), tabs)


def is_source_window(window: dict) -> bool:
    return all(n.get("url", "").startswith("http://127.0.0.1:") for t in window.get("tabs", [])
               for n in t.get("navigations", []))


def expected_windows() -> list[tuple]:
    out = []
    for _name, golden, _user_data, _single in SOURCES:
        reading = json.loads((GOLDEN / golden / "expected.json").read_text(encoding="utf-8"))
        out += [shape(w) for w in reading["session"]["windows"] if w.get("type", "normal") == "normal"]
    return out


def compare_tabs(expected: list[tuple], session_reading: str) -> list[str]:
    """Each expected window must be one of Thoron's windows (each of Thoron's used once)."""
    try:
        reading = json.loads(session_reading)
    except ValueError:
        return [f"Thoron's session could not be read: {session_reading[:200]!r}"]
    windows = [shape(w) for w in ((reading.get("session") or {}).get("windows") or []) if is_source_window(w)]
    problems, left = [], list(windows)
    for want in expected:
        if want in left:
            left.remove(want)
        else:
            problems.append(f"a source window is not in Thoron's session as it was: {str(want)[:300]}")
    if left:
        problems.append(f"{len(left)} window(s) of the test pages in Thoron's session that no source had")
    return problems


def _json(value, default):
    try:
        return json.loads(value) if isinstance(value, str) else (value if value is not None else default)
    except ValueError:
        return default


def problems(found: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {"imported": [], "the tabs": [], "extensions": [], "the report": []}
    if found.get("error"):
        out["imported"].append(f"it stopped: {found['error']}")
    if not found.get("installed"):
        out["imported"].append("Thoron was not installed")
    imports = found.get("imports") or {}
    for name, *_ in SOURCES:
        one = imports.get(name) or {}
        if "succeeded" not in str(one.get("status")):
            out["imported"].append(f"{name}: the import ended with {one.get('status')!r} (chosen {one.get('chosen')!r}, "
                                   f"boxes {one.get('boxes')!r})")
    if found.get("thoron_left_running"):
        out["the tabs"].append("Thoron did not exit through DevTools' Browser.close, so its session may hold less")
    out["the tabs"] += compare_tabs(expected_windows(), found.get("session") or "")
    listed = _json(found.get("extensions"), [])
    by_id = {e.get("id"): e for e in listed if isinstance(e, dict)}
    store = by_id.get(STORE_EXTENSION)
    if not store:
        out["extensions"].append(f"the store extension is not installed ({sorted(by_id)})")
    elif store.get("location") != "FROM_STORE" or store.get("state") not in ("DISABLED", "ENABLED"):
        out["extensions"].append(f"the store extension is {store.get('state')!r}, from {store.get('location')!r}")
    elif store.get("state") == "DISABLED" and any((store.get("reasons") or {}).values()):
        # off until its access is accepted: none of the other reasons (a suspicious or damaged install, a policy)
        out["extensions"].append(f"the store extension is off for another reason: {store.get('reasons')!r}")
    if UNPACKED_EXTENSION in by_id:
        out["extensions"].append("the unpacked extension was installed")
    report = _json(found.get("report"), {})
    imported, left_out = report.get("imported") or {}, report.get("left_out") or {}
    want_tabs = sum(len(w["tabs"]) for w in json.loads((GOLDEN / "chrome/expected.json").read_text(encoding="utf-8"))
                    ["session"]["windows"])
    if imported.get("open_tabs") != want_tabs:
        out["the report"].append(f"open tabs counted {imported.get('open_tabs')!r}, not {want_tabs}")
    if imported.get("extensions_to_install_from_the_store") != 1:
        out["the report"].append(f"extensions to install counted {imported.get('extensions_to_install_from_the_store')!r}")
    if left_out.get("extensions_not_from_the_store") != 1:
        out["the report"].append(f"extensions left out counted {left_out.get('extensions_not_from_the_store')!r}")
    if "127.0.0.1" in str(found.get("report")) or STORE_EXTENSION in str(found.get("report")):
        out["the report"].append("the report names an address or an extension")
    return out


def run(installer: Path, work: Path, timeout: float) -> dict:
    if work.exists():
        shutil.rmtree(work)
    for name in ("in/install", "out"):
        (work / name).mkdir(parents=True, exist_ok=True)
    shutil.copy2(installer, work / "in/install" / installer.name)
    shutil.copytree(REPO / "tools", work / "in/thoron-main/tools", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    copy_python(work / "in/python")
    listed = make_sources(work / "in/sources")
    (work / "in/sources.json").write_text(json.dumps(listed), encoding="utf-8")
    (work / "in/run.ps1").write_text(RUN, encoding="utf-8-sig", newline="\r\n")
    config = work / "thoron-import-tabs.wsb"
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
    p.add_argument("--timeout", type=float, default=1800)
    a = p.parse_args(argv)
    sys.stdout.reconfigure(errors="backslashreplace")
    found = run(a.installer.resolve(), a.work.resolve(), a.timeout)
    found_problems = problems(found)
    for step, issues in found_problems.items():
        print(f"{'PASS' if not issues else 'FAIL'}  {step}")
        for issue in issues:
            print(f"      {issue}")
    count = sum(len(v) for v in found_problems.values())
    print(f"IMPORT TABS CHECK: {'PASSED' if not count else f'FAILED ({count} problem(s))'}")
    return 1 if count else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
