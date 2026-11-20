#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""A portable copy locked with a passphrase on this PC, opened on another PC (ROADMAP P4.9, P3.12). Windows only.

P4.9 is done when its round trip passes: encrypt, move to a "new PC" with a fresh system key store, decrypt.
Windows Sandbox is that PC: a clean Windows with its own machine identity and its own DPAPI keys, gone when it
closes, networking off. The steps:

    here      the portable package of the build is made and unpacked; started through its launcher, a page sets a
              cookie (which the profile key encrypts), Settings gets a home page and startup pages (settings
              Chromium protects with a signature), and chrome://thoron-portable locks the copy with "Remember this
              PC" ticked; the browser is closed as a person closes it
    asked     in the Sandbox the copy asks for its passphrase: this PC's remembered lock does not open there
    cookie    after the passphrase, the cookie is sent to a page in the Sandbox: the profile key opened on the
              new PC
    settings  the home page and the startup pages are still the ones set here, and no settings were reset

    py -3 -I tools/qa/sandbox_portable_passphrase_check.py --chrome-bin <release>\\Chrome-bin
        --launcher <out>\\thoron_launcher.exe --updater <out>\\thoron_update.exe --work <scratch>
Exit status 0 only when every step passes.
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
from tools.qa.portable_passphrase_check import PASSPHRASE, CookieServer, Session  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
HOME = "https://example.com/thoron-home"
STARTUP = ["https://example.com/thoron-start-1", "https://example.com/thoron-start-2"]
SANDBOX_PORT = 8123

RUN = r"""$ErrorActionPreference = 'Continue'
$in = 'C:\ThoronTest\in'
$out = 'C:\ThoronTest\out'
$r = [ordered]@{}
function Save { $r | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 (Join-Path $out 'results.json') }
function Trace($text) { $r.reached = $text; Save }
Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public static class Win {
  public delegate bool EnumProc(IntPtr hwnd, IntPtr lparam);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc proc, IntPtr lparam);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint pid);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hwnd);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetClassName(IntPtr hwnd, StringBuilder name, int size);
  [DllImport("user32.dll")] public static extern IntPtr GetDlgItem(IntPtr hwnd, int id);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern IntPtr SendMessage(IntPtr hwnd, uint msg, IntPtr w, string l);
  [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr hwnd, uint msg, IntPtr w, IntPtr l);
  // The unlock window of one of the processes `pids`: a dialog with the passphrase field (102).
  public static IntPtr Unlock(uint[] pids) {
    IntPtr found = IntPtr.Zero;
    EnumWindows((h, l) => {
      uint pid; GetWindowThreadProcessId(h, out pid);
      var name = new StringBuilder(64); GetClassName(h, name, 64);
      if (Array.IndexOf(pids, pid) >= 0 && IsWindowVisible(h) && name.ToString() == "#32770" &&
          GetDlgItem(h, 102) != IntPtr.Zero) { found = h; return false; }
      return true;
    }, IntPtr.Zero);
    return found;
  }
}
'@
try {
  $settings = Get-Content -Raw -Encoding utf8 (Join-Path $in 'expect.json') | ConvertFrom-Json
  $copy = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'ThoronPortable'
  Trace 'copy'
  Copy-Item -Recurse (Join-Path $in 'ThoronPortable') $copy
  $data = Join-Path $copy 'User Data'
  # a port file left by the start on the other PC says nothing about this one
  Remove-Item (Join-Path $data 'DevToolsActivePort') -Force -ErrorAction SilentlyContinue
  # a page here that writes down the cookies it gets
  $listener = Start-Process powershell.exe -PassThru -WindowStyle Hidden -ArgumentList '-NoProfile', '-Command', @"
`$l = [System.Net.HttpListener]::new(); `$l.Prefixes.Add('http://127.0.0.1:$($settings.port)/'); `$l.Start()
while (`$true) { `$c = `$l.GetContext(); Set-Content -Encoding utf8 '$out\cookie.txt' ([string]`$c.Request.Headers['Cookie'])
  `$b = [Text.Encoding]::UTF8.GetBytes('seen'); `$c.Response.OutputStream.Write(`$b, 0, `$b.Length); `$c.Response.Close() }
"@
  Start-Sleep -Seconds 3
  Trace 'start'
  Start-Process (Join-Path $copy 'Thoron.exe') -ArgumentList '--headless=new', '--no-first-run',
      '--no-default-browser-check', '--remote-debugging-address=127.0.0.1', '--remote-debugging-port=0', 'about:blank'
  $window = [IntPtr]::Zero
  $end = (Get-Date).AddSeconds(90)
  while ($window -eq [IntPtr]::Zero -and (Get-Date) -lt $end -and -not (Test-Path (Join-Path $data 'DevToolsActivePort'))) {
    $pids = [uint32[]]@(Get-Process thoron -ErrorAction SilentlyContinue | ForEach-Object { [uint32]$_.Id })
    if ($pids.Count) { $window = [Win]::Unlock($pids) }
    Start-Sleep -Milliseconds 300
  }
  $r.asked = $window -ne [IntPtr]::Zero
  if ($r.asked) {
    Trace 'unlock'
    [void][Win]::SendMessage([Win]::GetDlgItem($window, 102), 0x000C, [IntPtr]::Zero, $settings.passphrase)
    [void][Win]::PostMessage($window, 0x0111, [IntPtr]1, [Win]::GetDlgItem($window, 1))
  }
  $end = (Get-Date).AddSeconds(90)
  while (-not (Test-Path (Join-Path $data 'DevToolsActivePort')) -and (Get-Date) -lt $end) { Start-Sleep -Milliseconds 500 }
  $r.started = Test-Path (Join-Path $data 'DevToolsActivePort')
  if ($r.started) {
    Trace 'cookie'
    Start-Sleep -Seconds 3
    $port = (Get-Content (Join-Path $data 'DevToolsActivePort') | Select-Object -First 1).Trim()
    $page = [uri]::EscapeDataString("http://127.0.0.1:$($settings.port)/get")
    Invoke-WebRequest -UseBasicParsing -Method Put "http://127.0.0.1:$port/json/new?$page" | Out-Null
    $end = (Get-Date).AddSeconds(30)
    while (-not (Test-Path "$out\cookie.txt") -and (Get-Date) -lt $end) { Start-Sleep -Milliseconds 500 }
    $r.cookie = if (Test-Path "$out\cookie.txt") { (Get-Content -Raw -Encoding utf8 "$out\cookie.txt").Trim() } else { '' }
    Trace 'settings'
    # the profile writes its settings a few seconds after a change (a reset is one)
    Start-Sleep -Seconds 20
    foreach ($name in 'Preferences', 'Secure Preferences') {
      $file = Join-Path $data "Default\$name"
      if (Test-Path $file) { Copy-Item $file (Join-Path $out (($name -replace ' ', '-') + '.json')) }
    }
  }
  Get-Process thoron -ErrorAction SilentlyContinue | Stop-Process -Force
  Stop-Process -Id $listener.Id -Force -ErrorAction SilentlyContinue
} catch {
  $r.error = "$_"
}
$r.done = $true
Save
Start-Sleep -Seconds 2
shutdown.exe /s /t 0
"""


def lock_here(package: Path, cookies: CookieServer) -> tuple[list[str], str]:
    """Starts the unpacked package through its launcher, sets the cookie and the settings, locks the copy with
    "Remember this PC", and closes it. Returns its problems and the cookie's value."""
    from tools.qa import portable_passphrase_check as check
    user_data = package / "User Data"
    launcher = package / "Thoron.exe"
    problems: list[str] = []
    (user_data / "DevToolsActivePort").unlink(missing_ok=True)
    proc = subprocess.Popen([str(launcher), "--headless=new", "--no-first-run", "--no-default-browser-check",
                             "--disable-background-networking", "--disable-component-update",
                             "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    session = Session(proc, user_data)
    try:
        session.body(cookies.url("/set"))
        session.go("chrome://settings/", 4)
        set_pref = ("new Promise((ok) => chrome.settingsPrivate.setPref({name}, {value}, '', () => ok(1)))")
        for name, value in (("homepage", HOME), ("homepage_is_newtabpage", False), ("browser.show_home_button", True),
                            ("session.restore_on_startup", 4), ("session.startup_urls", STARTUP)):
            session.run(set_pref.format(name=json.dumps(name), value=json.dumps(value)))
        session.go(check.PAGE_URL, 3)
        session.page(f"""document.getElementById('pass').value = {json.dumps(PASSPHRASE)};
                         document.getElementById('repeat').value = {json.dumps(PASSPHRASE)};
                         document.getElementById('with-recovery').checked = true;
                         document.getElementById('remember').checked = true;
                         document.getElementById('next').click();""")
        time.sleep(1.5)
        recovery = session.run("document.getElementById('recovery-key').textContent") or ""
        session.page(f"""document.getElementById('last-group').value = {json.dumps(recovery[-4:])};
                         document.getElementById('lock').click();""")
        said = session.wait_text("message", "locked with your passphrase")
        if "locked" not in said:
            problems.append(f"here: the page said {said!r}")
    finally:
        session.close()
    if not (user_data / check.KEY_FILE).is_file():
        problems.append("here: no key file")
    return problems, cookies.value


def settings_problems(out: Path) -> list[str]:
    """The home page and startup pages set here are still there in the Sandbox, and nothing was reset."""
    merged: dict = {}
    for name in ("Preferences.json", "Secure-Preferences.json"):
        path = out / name
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            for key, value in data.items():
                if isinstance(value, dict) and isinstance(merged.get(key), dict):
                    merged[key] = {**merged[key], **value}
                else:
                    merged.setdefault(key, value)
    if not merged:
        return ["settings: the profile's settings were not saved in the Sandbox"]
    problems = []
    if merged.get("homepage") != HOME:
        problems.append(f"settings: the home page is {merged.get('homepage')!r}, not the one set")
    if (merged.get("session") or {}).get("startup_urls") != STARTUP:
        problems.append(f"settings: the startup pages are {(merged.get('session') or {}).get('startup_urls')!r}")
    if (merged.get("prefs") or {}).get("preference_reset_time"):
        problems.append("settings: Thoron reset protected settings on the new PC")
    return problems


def run(chrome_bin: Path, launcher: Path, updater: Path, work: Path, timeout: float) -> list[str]:
    if work.exists():
        shutil.rmtree(work)
    (work / "in").mkdir(parents=True)
    (work / "out").mkdir()
    made = subprocess.run([sys.executable, "-I", str(REPO / "tools/release/portable.py"), "build", "--chrome-bin",
                           str(chrome_bin), "--launcher", str(launcher), "--updater", str(updater), "--dist",
                           str(work / "dist"), "--variant", "win-x64-avx2", "--no-zip"], capture_output=True,
                          text=True)
    if made.returncode:
        return [f"the portable package could not be made: {made.stdout[-300:]} {made.stderr[-300:]}"]
    package = work / "dist" / "ThoronPortable"
    cookies = CookieServer()
    try:
        problems, value = lock_here(package, cookies)
    finally:
        cookies.close()
    print(f"{'PASS' if not problems else 'FAIL'}  here: locked with this PC remembered")
    if problems:
        return problems
    shutil.copytree(package, work / "in" / "ThoronPortable",
                    ignore=shutil.ignore_patterns("DevToolsActivePort"))
    (work / "in" / "expect.json").write_text(json.dumps({"passphrase": PASSPHRASE, "port": SANDBOX_PORT}),
                                             encoding="utf-8")
    (work / "in" / "run.ps1").write_text(RUN, encoding="utf-8-sig", newline="\r\n")
    config = work / "thoron-portable-passphrase.wsb"
    config.write_text(sb.wsb(work), encoding="utf-8")
    subprocess.Popen([sb.SANDBOX, str(config)])
    results = work / "out" / "results.json"
    end = time.monotonic() + timeout
    found = sb.read_results(results)
    while time.monotonic() < end and not found.get("done"):
        time.sleep(5)
        found = sb.read_results(results)
    sb.close_sandbox()
    if not found.get("done"):
        return [f"the Sandbox run did not end; it got as far as: {found.get('reached', 'nothing')}"]
    if found.get("error"):
        return [f"the Sandbox run failed: {found['error']}"]
    steps = {
        "asked": [] if found.get("asked") else ["asked: the copy opened on the new PC without its passphrase"],
        "cookie": [] if f"thoronportable={value}" in (found.get("cookie") or "") else
                  [f"cookie: the new PC sent {found.get('cookie')!r}"],
        "settings": settings_problems(work / "out"),
    }
    for name, found_problems in steps.items():
        print(f"{'PASS' if not found_problems else 'FAIL'}  {name}")
        problems.extend(found_problems)
    return problems


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--chrome-bin", type=Path, required=True)
    p.add_argument("--launcher", type=Path, required=True)
    p.add_argument("--updater", type=Path, required=True)
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--timeout", type=float, default=900)
    a = p.parse_args(argv)
    sys.stdout.reconfigure(errors="backslashreplace")
    problems = run(a.chrome_bin.resolve(), a.launcher.resolve(), a.updater.resolve(), a.work.resolve(), a.timeout)
    for problem in problems:
        print(problem)
    print("SANDBOX PORTABLE PASSPHRASE: PASSED" if not problems
          else f"SANDBOX PORTABLE PASSPHRASE: FAILED ({len(problems)} problem(s))")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
