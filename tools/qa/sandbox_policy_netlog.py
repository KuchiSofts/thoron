#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""What Thoron's policies switch off, measured (ROADMAP S.10). Windows only.

docs/security/NETWORK.md names policies that switch a contact off. Setting a policy needs the machine's
registry, which a test must not touch on this PC, so this check runs in Windows Sandbox (a clean Windows, gone
when it closes). Unlike the installer check, its network is on: the measurement is online, as
`netlog_hosts.py` is, and the browser really reaches the hosts it asks for.

In the Sandbox the build's installer installs Thoron for the user, then Thoron runs twice, each time on a new
profile, headless, with `about:blank` and Chromium's network log, for --seconds:

    without   no policy
    with      the policies below, set in HKLM\\SOFTWARE\\Policies\\Chromium (where a Thoron build reads them)

The two logs are read here with `netlog_hosts.digest` and compared host by host: a host the policies are meant
to switch off must not be asked in the run with them, and one they are meant to reduce asked less; a host
the build does not ask even without the policies is named, as nothing could be shown for it.

    py -3 -I tools/qa/sandbox_policy_netlog.py --installer <out>\\thoron_AVX2_mini_installer.exe --work <scratch>
        [--seconds 240] [--md <report.md>]
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
from tools.qa import netlog_hosts as nh  # noqa: E402
from tools.qa import sandbox_install_check as sb  # noqa: E402

INSIDE = r"C:\ThoronTest"
POLICY_KEY = r"HKLM:\SOFTWARE\Policies\Chromium"
# name: (registry value, the hosts it acts on as docs/security/NETWORK.md names them, and what it does to
# them: "off", no request any more; "fewer", fewer requests: Chromium keeps the components that matter for
# security up to date even with ComponentUpdatesEnabled off)
POLICIES = {
    "AIModeSettings": (1, ["www.google.com"], "off"),
    "BrowserNetworkTimeQueriesEnabled": (0, [], "off"),         # clients2.google.com is shared with extensions
    "ComponentUpdatesEnabled": (0, ["update.googleapis.com"], "fewer"),
    "SafeBrowsingProtectionLevel": (0, ["safebrowsing.googleapis.com"], "off"),
    "BlockExternalExtensions": (1, [], "off"),
}
RUN = r"""$ErrorActionPreference = 'Continue'
$out = 'C:\ThoronTest\out'
$seconds = [int](Get-Content 'C:\ThoronTest\in\seconds.txt' -Raw)
function Trace($text) { Add-Content -Encoding utf8 -Path (Join-Path $out 'trace.txt') -Value "$(Get-Date -Format HH:mm:ss) $text" }
$r = [ordered]@{}
try {
  $shared = Get-ChildItem 'C:\ThoronTest\in' -Filter '*.exe' | Select-Object -First 1
  $installer = Join-Path $env:TEMP $shared.Name
  Copy-Item $shared.FullName $installer
  Trace 'install'
  $p = Start-Process $installer -ArgumentList '--silent', '--do-not-launch-chrome' -PassThru
  if (-not $p.WaitForExit(300000)) { Stop-Process -Id $p.Id -Force }
  $r.install_exit = $p.ExitCode
  $exe = Join-Path $env:LOCALAPPDATA 'Thoron\Application\thoron.exe'
  foreach ($run in @('without', 'with')) {
    if ($run -eq 'with') {
      New-Item -Path 'HKLM:\SOFTWARE\Policies\Chromium' -Force | Out-Null
      foreach ($line in Get-Content 'C:\ThoronTest\in\policies.txt') {
        $name, $value = $line.Split('=')
        New-ItemProperty -Path 'HKLM:\SOFTWARE\Policies\Chromium' -Name $name -Value ([int]$value) -PropertyType DWord -Force | Out-Null
      }
      $r.policies = @(Get-ItemProperty 'HKLM:\SOFTWARE\Policies\Chromium' | Get-Member -MemberType NoteProperty |
                      Where-Object { $_.Name -notmatch '^PS' } | ForEach-Object { $_.Name })
    }
    $profile = Join-Path $env:TEMP "profile-$run"
    $log = Join-Path $out "netlog-$run.json"
    Trace "run $run"
    $r["launched_$run"] = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() / 1000
    $b = Start-Process $exe -ArgumentList '--headless=new', "--user-data-dir=$profile", '--no-first-run',
      '--no-default-browser-check', "--log-net-log=$log", '--net-log-capture-mode=Default', 'about:blank' -PassThru
    Start-Sleep -Seconds $seconds
    Get-Process thoron -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Seconds 5
  }
} catch {
  $r.error = "$_"
}
$r.done = $true
$r | ConvertTo-Json -Depth 4 | Set-Content -Encoding utf8 (Join-Path $out 'results.json')
Trace 'done'
Stop-Computer -Force
"""


def wsb(work: Path) -> str:
    """The Sandbox: networking on (an online measurement), no GPU, the two shared folders, the script at logon."""
    folders = "".join(
        f"<MappedFolder><HostFolder>{escape(str(work / name))}</HostFolder>"
        f"<SandboxFolder>{INSIDE}\\{name}</SandboxFolder><ReadOnly>{'true' if name == 'in' else 'false'}</ReadOnly>"
        "</MappedFolder>" for name in ("in", "out"))
    return ("<Configuration><VGpu>Disable</VGpu><Networking>Default</Networking><MemoryInMB>4096</MemoryInMB>"
            "<ClipboardRedirection>Disable</ClipboardRedirection><PrinterRedirection>Disable</PrinterRedirection>"
            f"<MappedFolders>{folders}</MappedFolders><LogonCommand><Command>powershell.exe -NoProfile "
            f"-ExecutionPolicy Bypass -File {INSIDE}\\in\\run.ps1</Command></LogonCommand></Configuration>")


def hosts_of(log_text: str, launched: float | None) -> dict[str, int]:
    """The hosts a run asked (requests), each with how many requests."""
    found: dict[str, int] = {}
    for request in nh.digest(log_text, launched=launched)["requests"]:
        found[request["host"]] = found.get(request["host"], 0) + 1
    return found


def compare(without: dict[str, int], with_: dict[str, int]) -> tuple[list[str], list[str]]:
    """Where the policies did not do what they are meant to (problems), and what this run could not show
    (notes: a host the build did not ask even without the policy)."""
    problems, notes = [], []
    for name, (_, hosts, effect) in POLICIES.items():
        for host in hosts:
            if host not in without:
                notes.append(f"{name}: {host} was not asked even without the policy; nothing to switch off here")
            elif effect == "off" and host in with_:
                problems.append(f"{name}: {host} was still asked with the policy ({with_[host]} request(s))")
            elif effect == "fewer" and with_.get(host, 0) >= without[host]:
                problems.append(f"{name}: {host} was asked as often with the policy ({with_.get(host, 0)} against "
                                f"{without[host]})")
    return problems, notes


def report(without: dict[str, int], with_: dict[str, int], seconds: float) -> str:
    lines = [f"Two runs of {seconds:g} s in Windows Sandbox, each on a new profile, headless with about:blank:",
             "", "| Host | Without the policies | With them |", "|---|---|---|"]
    for host in sorted(set(without) | set(with_)):
        lines.append(f"| `{host}` | {without.get(host, 0)} | {with_.get(host, 0)} |")
    lines += ["", "Policies (HKLM\\SOFTWARE\\Policies\\Chromium): "
              + ", ".join(f"`{n}` = {v}" for n, (v, _, _) in POLICIES.items()) + "."]
    return "\n".join(lines) + "\n"


def run(installer: Path, work: Path, seconds: float, timeout: float) -> dict:
    if work.exists():
        shutil.rmtree(work)
    (work / "in").mkdir(parents=True)
    (work / "out").mkdir()
    shutil.copy2(installer, work / "in" / installer.name)
    (work / "in" / "seconds.txt").write_text(str(int(seconds)), encoding="utf-8")
    (work / "in" / "policies.txt").write_text("\n".join(f"{n}={v}" for n, (v, _, _) in POLICIES.items()),
                                              encoding="utf-8")
    (work / "in" / "run.ps1").write_text(RUN, encoding="utf-8-sig", newline="\r\n")
    config = work / "thoron-policies.wsb"
    config.write_text(wsb(work), encoding="utf-8")
    subprocess.Popen([sb.SANDBOX, str(config)])
    results = work / "out" / "results.json"
    end = time.monotonic() + timeout
    found = sb.read_results(results)
    while time.monotonic() < end and not found.get("done"):
        time.sleep(5)
        found = sb.read_results(results)
    sb.close_sandbox()
    if not found.get("done"):
        found["error"] = f"no end within {timeout:g} s"
    return found


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--installer", type=Path, required=True)
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--seconds", type=float, default=240)
    p.add_argument("--timeout", type=float, default=1500)
    p.add_argument("--md", type=Path)
    a = p.parse_args(argv)
    found = run(a.installer.resolve(), a.work.resolve(), a.seconds, a.timeout)
    if found.get("error") or found.get("install_exit") != 0:
        print(f"SANDBOX POLICY CHECK: FAILED ({found})")
        return 1
    logs = {}
    for name in ("without", "with"):
        path = a.work / "out" / f"netlog-{name}.json"
        text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
        logs[name] = hosts_of(text, found.get(f"launched_{name}")) if text else {}
    text = report(logs["without"], logs["with"], a.seconds)
    print(text)
    if a.md:
        a.md.write_text(text, encoding="utf-8", newline="\n")
    print(f"policies the browser saw set: {found.get('policies')}")
    problems, notes = compare(logs["without"], logs["with"])
    for note in notes:
        print(f"note  {note}")
    for problem in problems:
        print(f"FAIL  {problem}")
    print(f"SANDBOX POLICY CHECK: {'PASSED' if not problems else f'FAILED ({len(problems)} problem(s))'}")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
