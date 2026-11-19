#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""What the About page says about updates, and what the updater asks for, in a real build (ROADMAP P3.9, P3.20).

The build starts headless with a fresh profile of its own and every outside name unresolvable, without
--disable-background-networking (so the updater may do what it does on its own), and with a network log.
The About page (chrome://settings/help) is opened, as a person opening it asks for a look.

    without a key (every build until the key ceremony, P2.11): the page shows no update line, and the
    updater asks no host at all, neither on its own nor when the page opens (no name that belongs to
    GitHub in the network log)
    with --expect-key: the page shows a line, and the updater asked github.com (offline here, so the
    line is the error that the manifest could not be fetched)

    py -3 -I tools/qa/about_updater_check.py --browser <Chrome-bin>\\thoron.exe --work <scratch dir> [--expect-key]
Exit status 0 only when every step passes.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.qa import bench  # noqa: E402
from tools.qa.adblock_site_switch_check import _close_browser, _devtools_port, _open  # noqa: E402
from tools.qa.cdp import WebSocket  # noqa: E402

OFFLINE = "MAP * ~NOTFOUND, EXCLUDE 127.0.0.1"
GITHUB = re.compile(r"(?i)\b(?:[a-z0-9-]+\.)*(?:github\.com|githubusercontent\.com)\b")
# The update line of chrome://settings/help, found through the page's shadow roots.
READ_STATUS = r"""
(() => {
  const all = [];
  const walk = (root) => {
    for (const el of root.querySelectorAll('*')) {
      all.push(el);
      if (el.shadowRoot) walk(el.shadowRoot);
    }
  };
  walk(document);
  const line = all.find(el => el.id === 'updateStatusMessage');
  if (!line) return JSON.stringify({found: false});
  const box = line.getBoundingClientRect();
  const shown = !line.hidden && box.width > 0 && box.height > 0 &&
      getComputedStyle(line).display !== 'none' && getComputedStyle(line).visibility !== 'hidden';
  return JSON.stringify({found: true, shown, text: (line.innerText || '').trim().slice(0, 300)});
})()
"""


def github_lines(net_log: str) -> list[str]:
    """The names in a network log that belong to GitHub, each once."""
    return sorted({m.group(0).lower() for m in GITHUB.finditer(net_log)})


def judge(status: dict, asked: list[str], expect_key: bool) -> list[str]:
    problems = []
    if not status.get("found"):
        problems.append("page: the About page's update line was not found")
    elif expect_key:
        if not status.get("shown"):
            problems.append("page: with a key, the update line is not shown")
        if "github.com" not in asked:
            problems.append("network: with a key, github.com was not asked")
    else:
        if status.get("shown"):
            problems.append(f"page: without a key, an update line is shown: {status.get('text')!r}")
        if asked:
            problems.append(f"network: without a key, the updater asked {', '.join(asked)}")
    return problems


def run(browser: Path, work: Path, expect_key: bool, wait: float) -> list[str]:
    work.mkdir(parents=True, exist_ok=True)
    profile = Path(tempfile.mkdtemp(prefix="about-", dir=work))
    net_log = profile.parent / f"{profile.name}.netlog.json"
    proc = subprocess.Popen(
        [str(browser), "--headless=new", f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
         f"--host-resolver-rules={OFFLINE}", f"--log-net-log={net_log}", "--net-log-capture-mode=Default",
         "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    devtools = None
    status: dict = {}
    try:
        devtools = _devtools_port(profile)
        ws = WebSocket(_open(devtools, "about:blank")["webSocketDebuggerUrl"])
        try:
            ws.call("Page.navigate", url="chrome://settings/help")
            time.sleep(wait)
            status = json.loads(ws.call("Runtime.evaluate", expression=READ_STATUS, returnByValue=True)
                                ["result"].get("value") or "{}")
        finally:
            ws.close()
    finally:
        if devtools is not None:
            _close_browser(devtools, proc)
        else:
            bench._stop(proc, profile)
    text = net_log.read_text(encoding="utf-8", errors="replace") if net_log.exists() else ""
    asked = github_lines(text)
    print(f"page: {json.dumps(status)}")
    print(f"network: GitHub names in the log: {asked or 'none'} ({len(text)} characters of log)")
    problems = judge(status, asked, expect_key)
    if not text:
        problems.append("network: no network log was written")
    shutil.rmtree(profile, ignore_errors=True)
    net_log.unlink(missing_ok=True)
    return problems


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--browser", type=Path, required=True)
    p.add_argument("--work", type=Path, required=True, help="a scratch folder; `about-updater` is made in it")
    p.add_argument("--expect-key", action="store_true", help="the build has an update key")
    p.add_argument("--wait", type=float, default=8.0, help="seconds the About page is given (default 8)")
    a = p.parse_args(argv)
    problems = run(a.browser, a.work / "about-updater", a.expect_key, a.wait)
    for problem in problems:
        print(f"FAIL  {problem}")
    print(f"ABOUT UPDATER CHECK: {'PASSED' if not problems else f'FAILED ({len(problems)} problem(s))'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
