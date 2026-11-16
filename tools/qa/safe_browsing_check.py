#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Phishing and malware test pages are blocked, and by what (ROADMAP S.14). ONLINE, unlike the other checks:
run it on purpose.

Starts the browser headless on a throwaway profile and opens Google's Safe Browsing test pages
(testsafebrowsing.appspot.com) one after the other, as a person who follows a bad link would. The tool sends
nothing of its own: the only requests it causes are the browser's visits to those pages. What the browser asks
for by itself in that time (its Safe Browsing list, Thoron adblock's lists) is the build's doing;
`netlog_hosts.py` measures that. For every page it says who stopped it:

    safe-browsing  the browser's Safe Browsing warning is shown instead of the page
    adblock        Thoron adblock's "Thoron blocked this page" is shown instead of the page
    open           the page opened: nothing stopped it
    unreachable    the page did not load for another reason (no network, for one): nothing is learned

A new profile has no Safe Browsing list: the browser fetches its first one 1 to 5 minutes after it starts.
The check therefore opens the first page again every few seconds until something stops it or --wait seconds
have passed, and reports how long after the start that was. The other pages are opened once after that.

    py -3 -I tools/qa/safe_browsing_check.py --browser <out>\\thoron.exe --work <scratch dir>
    ... --safe-browsing off --wait 0     what Thoron adblock stops alone (the profile starts with Safe
                                         Browsing switched off)
    ... --no-google-keys                 what is left without Google's API keys: that one process is started
                                         with Chromium's placeholder in place of the keys (environment
                                         variables GOOGLE_API_KEY, GOOGLE_DEFAULT_CLIENT_ID and
                                         GOOGLE_DEFAULT_CLIENT_SECRET, which a build that is not Google
                                         Chrome reads)
    ... --downloads                      also the test site's download addresses (reported, not counted;
                                         the files are Google's harmless test files, saved inside the
                                         throwaway profile and removed with it, never opened)
    ... --page <address>                 one more address to open (reported, not counted; repeatable)
    ... --switch=--name=value            one more switch for the browser (repeatable)
Exit status 0 only when every phishing and malware test page is blocked. Unwanted software, billing and the
downloads are reported and do not count. The output names the test pages and nothing of the PC.
"""
import argparse
import json
import os
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
from tools.qa.netlog_hosts import seed_prefs  # noqa: E402

TEST_SITE = "https://testsafebrowsing.appspot.com/s/"
# (name, address, counted): the pages a person can land on. The first one is the page that is opened again
# until a list has arrived.
PAGES = (
    ("phishing", TEST_SITE + "phishing.html", True),
    ("malware", TEST_SITE + "malware.html", True),
    ("unwanted-software", TEST_SITE + "unwanted.html", False),
    ("billing", TEST_SITE + "trick_to_bill.html", False),
)
# (name, address): the test site's downloads for Windows, with the warning the site says each should get.
# Its content.exe ("malicious, based on content") is left out: the site sends it as a page, not as a file.
DOWNLOADS = (
    ("download-dangerous-host", TEST_SITE + "badrep.exe"),
    ("download-uncommon", TEST_SITE + "unknown.exe"),
    ("download-unwanted-app", TEST_SITE + "pua.exe"),
)
SAFE_BROWSING, ADBLOCK, OPEN, UNREACHABLE = "safe-browsing", "adblock", "open", "unreachable"
ADBLOCK_TITLE = "Thoron blocked this page"
# Chromium's value for a key that is not set (google_apis/default_api_keys.h, kUnsetApiToken): with it the
# browser is in the state of a build made without keys
PLACEHOLDER = "dummytoken"
KEY_VARIABLES = ("GOOGLE_API_KEY", "GOOGLE_DEFAULT_CLIENT_ID", "GOOGLE_DEFAULT_CLIENT_SECRET")
WAIT_S = 330
POLL_S = 15.0
LOAD_S = 20.0
DOWNLOAD_S = 30.0
DOWNLOADS_URL = "chrome://downloads/"
# What the tab shows: Safe Browsing's warning is one of Chromium's security pages, which carry their kind
# in the page's data; a page that could not be loaded is an error page without one.
LOOK = """(() => { let kind = '';
  try { if (typeof loadTimeData !== 'undefined' && loadTimeData.valueExists('type'))
          kind = String(loadTimeData.getValue('type')); } catch (e) {}
  return JSON.stringify({title: document.title, address: location.href, ready: document.readyState,
                         kind: kind}); })()"""
# chrome://downloads keeps what it shows in its list element: the state and the danger of every download,
# as the numbers of chrome/browser/ui/webui/downloads/downloads.mojom (State, DangerType)
LISTED = """(() => { const list = document.querySelector('downloads-manager');
  const items = (list && (list.items_ || list.items)) || [];
  return JSON.stringify(items.map((d) => ({address: String(d.url || ''), state: d.state,
                                           danger: d.dangerType}))); })()"""
STATE_COMPLETE = 2
DANGER_NONE, DANGER_FILE_TYPE = 0, 1
# the warnings that are a verdict of Safe Browsing's download protection
VERDICTS = {2: "dangerous address", 3: "dangerous content", 4: "cookie theft", 5: "uncommon file",
            6: "dangerous host", 7: "unwanted app"}


def blocked_by(seen: dict) -> str:
    """Who stopped a page, from what the tab shows after the visit."""
    if seen.get("title") == ADBLOCK_TITLE:
        return ADBLOCK
    if str(seen.get("kind", "")).upper() == "SAFEBROWSING":
        return SAFE_BROWSING
    if seen.get("error") or str(seen.get("address", "")).startswith("chrome-error:"):
        return UNREACHABLE
    return OPEN


def is_blocked(by: str) -> bool:
    return by in (SAFE_BROWSING, ADBLOCK)


def problems(results: list[dict]) -> list[str]:
    """Why the check fails: a counted page that nothing stopped, or one that taught nothing."""
    out = []
    for r in results:
        if not r.get("counted") or is_blocked(r["by"]):
            continue
        if r["by"] == UNREACHABLE:
            why = r.get("detail") or "no reason given"
            out.append(f"{r['name']}: the page did not load ({why}): nothing is learned, run it again online")
        else:
            out.append(f"{r['name']}: not blocked")
    if not any(r.get("counted") for r in results):
        out.append("no phishing or malware page was opened")
    return out


def line(result: dict) -> str:
    by = result["by"]
    word = "BLOCKED" if is_blocked(by) else "OPEN" if by == OPEN else "UNKNOWN"
    after = f", {result['after']} s after the start" if result.get("after") is not None else ""
    detail = f" ({result['detail']})" if result.get("detail") else ""
    counted = "" if result.get("counted") else " [not counted]"
    return f"{word:8}{result['name']}: {by}{detail}{after}: {result['address']}{counted}"


def child_environment(base: dict, no_google_keys: bool) -> dict:
    """The environment of the one browser process: with the placeholder in place of Google's keys when asked,
    else the variables are left out so that the build's own keys are the ones measured."""
    env = {k: v for k, v in base.items() if k.upper() not in KEY_VARIABLES}
    if no_google_keys:
        env.update({name: PLACEHOLDER for name in KEY_VARIABLES})
    return env


def download_outcome(saved: bool, listed: dict | None) -> tuple[str, str]:
    """Who stopped a download: (by, detail). `saved` is whether the finished file is in the folder; `listed`
    is the download's entry on chrome://downloads (its state and danger, as numbers)."""
    if saved:
        return OPEN, "the file was saved"
    if not listed:
        return UNREACHABLE, "no download was started"
    danger = listed.get("danger")
    if danger in VERDICTS:
        return SAFE_BROWSING, VERDICTS[danger]
    if danger == DANGER_FILE_TYPE:
        # the browser asks before it keeps a file of this type: its own rule, no verdict of Safe Browsing
        return OPEN, "kept back for its file type only"
    if listed.get("state") == STATE_COMPLETE:
        return OPEN, "the download finished"
    return UNREACHABLE, f"not saved, state {listed.get('state')}, danger {danger}"


def _launch(browser: Path, profile: Path, switches: tuple[str, ...], env: dict) -> subprocess.Popen:
    # no --disable-background-networking and no --disable-component-update: Safe Browsing's list comes that way
    args = [str(browser), "--headless=new", f"--user-data-dir={profile}", "--no-first-run",
            "--no-default-browser-check", "--disable-default-apps", "--mute-audio", "--window-size=1280,800",
            "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0", *switches, "about:blank"]
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)


def _eval(ws: WebSocket, expression: str):
    reply = ws.call("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True)
    return json.loads(reply.get("result", {}).get("value") or "null")


def _visit(tab: WebSocket, address: str) -> dict:
    reply = tab.call("Page.navigate", url=address)
    seen: dict = {}
    for _ in range(int(LOAD_S / 0.5)):
        time.sleep(0.5)
        try:
            seen = _eval(tab, LOOK) or {}
        except (RuntimeError, ValueError):
            continue
        if seen.get("ready") == "complete":
            break
    seen["error"] = str(reply.get("errorText", ""))
    return seen


def _result(name: str, address: str, counted: bool, seen: dict, after: int | None = None) -> dict:
    by = blocked_by(seen)
    return {"name": name, "address": address, "counted": counted, "by": by, "after": after,
            "detail": seen.get("error", "") if by == UNREACHABLE else ""}


def _download(port: int, folder: Path, name: str, address: str) -> dict:
    """One download, in a tab of its own (a tab may start one download without asking)."""
    result = {"name": name, "address": address, "counted": False, "after": None}
    target = _open(port, address)
    time.sleep(2)
    try:
        tab = WebSocket(target["webSocketDebuggerUrl"])
        try:
            by = blocked_by(_eval(tab, LOOK) or {})
        finally:
            tab.close()
        if is_blocked(by):  # the address itself was stopped: a warning page is in the tab
            return {**result, "by": by, "detail": ""}
    except (OSError, RuntimeError, ValueError):
        pass  # a tab that only started a download may be gone already
    listed, saved = None, False
    page = WebSocket(_open(port, DOWNLOADS_URL)["webSocketDebuggerUrl"])
    try:
        deadline = time.monotonic() + DOWNLOAD_S
        while time.monotonic() < deadline:
            time.sleep(2)
            saved = (folder / address.rsplit("/", 1)[-1]).is_file()
            entries = [d for d in (_eval(page, LISTED) or []) if d.get("address") == address]
            listed = entries[0] if entries else listed
            if saved or (listed and listed.get("danger") != DANGER_NONE):
                break
        page.call("Page.close")
    except (RuntimeError, ValueError, OSError):
        pass
    finally:
        page.close()
    by, detail = download_outcome(saved, listed)
    return {**result, "by": by, "detail": detail}


def run(browser: Path, work: Path, wait: float, safe_browsing: bool, no_google_keys: bool, downloads: bool,
        more_pages: tuple[str, ...] = (), switches: tuple[str, ...] = ()) -> tuple[list[dict], list[str]]:
    """Every page's result, and what went wrong with the run itself."""
    profile = Path(tempfile.mkdtemp(prefix="safe-browsing-", dir=work))
    folder = profile / "saved"
    prefs = {"download.default_directory": str(folder), "download.prompt_for_download": False}
    if not safe_browsing:
        prefs["safebrowsing.enabled"] = False
    seed_prefs(profile, prefs)
    results: list[dict] = []
    failures: list[str] = []
    started = time.monotonic()
    proc = _launch(browser, profile, switches, child_environment(dict(os.environ), no_google_keys))
    port = None
    tab = None
    try:
        port = _devtools_port(profile)
        tab = WebSocket(_open(port, "about:blank")["webSocketDebuggerUrl"])
        name, address, counted = PAGES[0]
        while True:
            seen = _visit(tab, address)
            after = round(time.monotonic() - started)
            if blocked_by(seen) != OPEN or after >= wait:
                break
            time.sleep(POLL_S)
        results.append(_result(name, address, counted, seen, after))
        for name, address, counted in PAGES[1:]:
            results.append(_result(name, address, counted, _visit(tab, address)))
        for number, address in enumerate(more_pages, 1):
            results.append(_result(f"page-{number}", address, False, _visit(tab, address)))
        if downloads:
            for name, address in DOWNLOADS:
                results.append(_download(port, folder, name, address))
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as e:
        failures.append(f"the run failed: {type(e).__name__}")
    finally:
        if tab:
            try:
                tab.close()
            except OSError:
                pass
        if port is not None:
            _close_browser(port, proc)
        else:
            bench._stop(proc, profile)
        shutil.rmtree(profile, ignore_errors=True)
    return results, failures


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--browser", required=True, type=Path)
    p.add_argument("--work", required=True, type=Path, help="scratch folder for the throwaway profile")
    p.add_argument("--wait", type=float, default=WAIT_S,
                   help=f"seconds to wait for the first list before the first page counts as open (default {WAIT_S})")
    p.add_argument("--safe-browsing", choices=("on", "off"), default="on",
                   help="off: the profile starts with Safe Browsing switched off")
    p.add_argument("--no-google-keys", action="store_true",
                   help="start the browser with Chromium's placeholder in place of Google's API keys")
    p.add_argument("--downloads", action="store_true", help="also try the test site's downloads")
    p.add_argument("--page", action="append", default=[], help="one more address to open (not counted)")
    p.add_argument("--switch", action="append", default=[], help="one more switch for the browser")
    a = p.parse_args(argv)
    sys.stdout.reconfigure(errors="backslashreplace")
    a.work.mkdir(parents=True, exist_ok=True)
    results, failures = run(a.browser.resolve(), a.work, a.wait, a.safe_browsing == "on", a.no_google_keys,
                            a.downloads, tuple(a.page), tuple(a.switch))
    for result in results:
        print(line(result))
    found = failures + (problems(results) if not failures else [])
    for problem in found:
        print(problem)
    print("SAFE BROWSING CHECK: PASSED" if not found else f"SAFE BROWSING CHECK: FAILED ({len(found)} problem(s))")
    return 0 if not found else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
