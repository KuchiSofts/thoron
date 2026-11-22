#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Settings' import from another browser of the Chromium family, on Linux (ROADMAP P3.14). Run on Windows.

On a clean Ubuntu test machine of tools/qa/wsl_test_vm.py, Thoron and upstream's thorium-browser are installed
with GNOME's keyring; in a D-Bus session of the user `tester` (the keyring unlocked with a made-up password),
headless, through DevTools on 127.0.0.1:

    source      Thorium saves a made-up password on its password page (encrypted with the keyring's key,
                "v11") and gets a persistent cookie for example.org (secure, HTTP only); then, closed, its
                profile gets a bookmark, a history entry and a second password encrypted with Chromium's fixed
                key ("v10", what a browser without a keyring writes), all made up
    listed      Thoron's Settings import (chrome://settings/importData, its own messages) lists "Thorium" and
                not Thoron itself
    import      the import of bookmarks, history, passwords and cookies from Thorium ends with success
    passwords   after a restart Thoron shows both passwords, readable, on its own password page
    cookie      the cookie is in Thoron's cookie jar with its value, right after the import and after a restart
    the data    Thoron's profile holds the bookmark (on its empty bookmarks bar, as Chromium puts it) and the
                history entry
    the report  the profile holds `Thoron import report.json`: from Thorium, the bookmark, the history entry,
                both passwords and the cookie counted, and no address or other value
    untouched   Thorium's files are as they were before the import

--desktop kde does the same with KDE's KWallet in place of GNOME's keyring, set up as linux_keyring_check.py
--desktop kde sets it up (the wallet opened as at sign-in, the browsers choosing KWallet by themselves): Thoron's
import then reads Thorium's key from the open wallet.

    py -3 -I tools/qa/linux_settings_import_check.py --deb <thoron-browser_*.deb> --upstream <thorium-browser_*.deb>
        --root <test machines folder> --work <scratch> [--machine thoron-test-2604] [--desktop kde]
Exit status 0 only when every step passes on every machine.
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

if __package__ in (None, ""):  # running as a script: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

REPO = Path(__file__).resolve().parents[2]
KEYRING_PASSWORD = {"url": "https://example.org/login", "username": "thoron-import-keyring",
                    "password": "made-up-keyring-secret"}
FIXED_PASSWORD = {"url": "https://example.net/login", "username": "thoron-import-fixed",
                  "password": "made-up-fixed-secret"}
COOKIE = {"name": "thoron_import", "value": "made-up-cookie-value", "domain": "example.org"}
BOOKMARK = "https://example.org/thoron-import-bookmark"
HISTORY = "https://example.org/thoron-import-history"
# Chromium's fixed key on Linux (components/os_crypt/async/browser/posix_key_provider.cc, kV10Key)
V10_KEY = "fd621fe5a2b402539dfa147ca9272778"
STEPS = ("source", "listed", "import", "passwords", "cookie", "the data", "the report", "untouched")
WATCHED = ("Default/Bookmarks", "Default/History", "Default/Login Data", "Default/Cookies", "Local State")

SCRIPT = r"""#!/bin/bash
# Other work may share this WSL machine: if memory runs out, the kernel ends this check's processes first.
echo 1000 > /proc/self/oom_score_adj 2>/dev/null
# As root inside a clean test machine: $1 work folder, $2 Thoron's .deb, $3 upstream's .deb, $4 tools
set -u
W="$1"; DEB="$2"; UP="$3"; TOOLS="$4"
out="$W/out"; rm -rf "$out"; mkdir -p "$out"; chmod 777 "$out"
export DEBIAN_FRONTEND=noninteractive
cp "$DEB" /tmp/thoron.deb; cp "$UP" /tmp/upstream.deb
apt-get update -qq > "$out/apt-update.txt" 2>&1
apt-get install -y -qq /tmp/thoron.deb /tmp/upstream.deb dbus-x11 gnome-keyring libsecret-tools sqlite3 openssl \
  > "$out/apt-install.txt" 2>&1
echo $? > "$out/install_exit"
runuser -u tester -- env HOME=/home/tester XDG_CURRENT_DESKTOP=GNOME dbus-run-session -- bash -c "
    eval \$(printf 'made-up-keyring-password' | gnome-keyring-daemon --unlock --components=secrets)
    export GNOME_KEYRING_CONTROL SSH_AUTH_SOCK
    python3 -I '$TOOLS/qa/linux_settings_import_check.py' probe --tools '$TOOLS' --out '$out/probe.json' \
      > '$out/probe.txt' 2>&1
  "
echo done > "$out/reached"
"""


# ----- inside the test machine -------------------------------------------------------------------------------

def _chromium_now() -> int:
    """Now, as Chromium stores times: microseconds since 1601-01-01."""
    return int((time.time() + 11644473600) * 1_000_000)


def _v10(plaintext: str) -> bytes:
    done = subprocess.run(["openssl", "enc", "-aes-128-cbc", "-K", V10_KEY, "-iv", "20" * 16],
                          input=plaintext.encode(), capture_output=True, check=True)
    return b"v10" + done.stdout


def _add_fixed_password(profile: Path) -> None:
    """A second saved password, as a browser without a keyring writes it: a copy of the first row with another
    site, user and value."""
    import sqlite3
    db = sqlite3.connect(profile / "Default" / "Login Data")
    try:
        columns = [row[1] for row in db.execute("PRAGMA table_info(logins)") if row[1] != "id"]
        row = dict(zip(columns, db.execute(f"SELECT {', '.join(columns)} FROM logins LIMIT 1").fetchone()))
        row.update(origin_url=FIXED_PASSWORD["url"], action_url=FIXED_PASSWORD["url"],
                   signon_realm="https://example.net/", username_value=FIXED_PASSWORD["username"],
                   password_value=_v10(FIXED_PASSWORD["password"]))
        db.execute(f"INSERT INTO logins ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                   [row[c] for c in columns])
        db.commit()
    finally:
        db.close()


def _add_bookmark_and_history(profile: Path) -> None:
    import sqlite3
    now = _chromium_now()
    node = {"date_added": str(now), "guid": "6f1e2d3c-4b5a-4968-8776-655443322110", "id": "5",
            "name": "Thoron import bookmark", "type": "url", "url": BOOKMARK}
    roots = {name: {"children": [], "date_added": str(now), "date_modified": "0", "guid": guid, "id": str(i),
                    "name": title, "type": "folder"}
             for i, (name, guid, title) in enumerate((
                 ("bookmark_bar", "0bc5d13f-2cba-5d74-951f-3f233fe6c908", "Bookmarks bar"),
                 ("other", "82b081ec-3dd3-529c-8475-ab6c344590dd", "Other bookmarks"),
                 ("synced", "4cf2e351-0e85-532b-bb37-df045d8f8d0f", "Mobile bookmarks")), start=1)}
    roots["bookmark_bar"]["children"].append(node)
    (profile / "Default" / "Bookmarks").write_text(json.dumps({"roots": roots, "version": 1}), encoding="utf-8")
    db = sqlite3.connect(profile / "Default" / "History")
    try:
        db.execute("INSERT INTO urls (url, title, visit_count, typed_count, last_visit_time, hidden) "
                   "VALUES (?, ?, 1, 1, ?, 0)", (HISTORY, "Thoron import history", now))
        db.commit()
    finally:
        db.close()


def _hashes(profile: Path) -> dict[str, str]:
    return {name: hashlib.sha256((profile / name).read_bytes()).hexdigest()
            for name in WATCHED if (profile / name).is_file()}


def _page(browser, url: str) -> dict:
    import urllib.request
    req = urllib.request.Request(f"http://127.0.0.1:{browser.port}/json/new?{url}", method="PUT")
    target = json.loads(urllib.request.urlopen(req, timeout=10).read())
    time.sleep(4)
    return target


def _call(target: dict, method: str, wait: float = 30, **params):
    from tools.qa import cdp
    ws = cdp.WebSocket(target["webSocketDebuggerUrl"], timeout=wait)
    try:
        return ws.call(method, **params)
    finally:
        ws.close()


def _cookies(browser) -> list[dict]:
    cookies = _call(browser.page, "Network.getAllCookies").get("cookies", [])
    return [{k: c.get(k) for k in ("name", "value", "domain", "secure", "httpOnly")}
            for c in cookies if c.get("name") == COOKIE["name"]]


IMPORT_JS = r"""
(async () => {
  const cr = await import('chrome://resources/js/cr.js');
  const browsers = await cr.sendWithPromise('initializeImportDialog');
  const names = browsers.map(b => b.name);
  const thorium = browsers.find(b => b.name === 'Thorium');
  if (!thorium) return JSON.stringify({names, status: 'no Thorium'});
  const status = new Promise(resolve => cr.addWebUiListener('import-data-status-changed', s => {
    if (s !== 'inProgress') resolve(s);
  }));
  chrome.send('importData', [thorium.index, {
    import_dialog_bookmarks: true, import_dialog_history: true, import_dialog_saved_passwords: true,
    import_dialog_search_engine: false, import_dialog_autofill_form_data: false, import_dialog_cookies: true,
    import_dialog_startup: false, import_dialog_extensions: false, import_dialog_open_tabs: false}]);
  const timeout = new Promise(resolve => setTimeout(() => resolve('timed out'), 240000));
  return JSON.stringify({names, status: await Promise.race([status, timeout])});
})()
"""


def probe(tools: Path, out: Path, store: str = "gnome-libsecret") -> int:
    from tools.qa.linux_keyring_check import Browser
    home = Path.home()
    thorium, thoron = home / ".config/thorium", home / ".config/thoron"
    found: dict = {}
    try:
        b = Browser("/usr/bin/thorium-browser", thorium, store)
        found["source_added"] = b.add(KEYRING_PASSWORD)
        found["source_cookie"] = _call(b.page, "Network.setCookie", name=COOKIE["name"], value=COOKIE["value"],
                                       domain=COOKIE["domain"], path="/", secure=True, httpOnly=True,
                                       expires=time.time() + 30 * 86400).get("success")
        time.sleep(40)        # Chromium writes cookies to disk every 30 seconds
        b.close()
        time.sleep(10)
        _add_fixed_password(thorium)
        _add_bookmark_and_history(thorium)
        time.sleep(30)        # the import refuses a profile written a moment ago
        found["before"] = _hashes(thorium)
        b = Browser("/usr/bin/thoron-browser", thoron, store)
        settings = _page(b, "chrome://settings/importData")
        value = _call(settings, "Runtime.evaluate", wait=300, expression=IMPORT_JS, returnByValue=True,
                      awaitPromise=True)
        found["import"] = json.loads(value.get("result", {}).get("value") or "{}")
        time.sleep(5)
        found["cookies_now"] = _cookies(b)
        time.sleep(40)        # Chromium writes cookies to disk every 30 seconds
        b.close()
        time.sleep(5)
        found["after"] = _hashes(thorium)
        b = Browser("/usr/bin/thoron-browser", thoron, store)
        found["readable"] = b.readable()
        found["cookies"] = _cookies(b)
        b.close()
        found["bookmarks"] = (thoron / "Default" / "Bookmarks").read_text(encoding="utf-8") \
            if (thoron / "Default" / "Bookmarks").is_file() else ""
        import sqlite3
        db = sqlite3.connect(f"file:{thoron / 'Default' / 'History'}?mode=ro", uri=True)
        try:
            found["history"] = [r[0] for r in db.execute("SELECT url FROM urls WHERE url = ?", (HISTORY,))]
        finally:
            db.close()
        report = thoron / "Default" / "Thoron import report.json"
        found["report"] = report.read_text(encoding="utf-8") if report.is_file() else ""
    except Exception as exc:  # the reason goes into the results; the host reads it
        found["error"] = f"{type(exc).__name__}: {exc}"
    out.write_text(json.dumps(found), encoding="utf-8")
    return 0


# ----- on Windows ----------------------------------------------------------------------------------------------

def problems(found: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {step: [] for step in STEPS}
    if found.get("error"):
        out["source"].append(f"the probe stopped: {found['error']}")
    if found.get("source_added") != "added" or found.get("source_cookie") is not True:
        out["source"].append(f"Thorium: password {found.get('source_added')!r}, cookie {found.get('source_cookie')!r}")
    names = (found.get("import") or {}).get("names") or []
    if "Thorium" not in names or any("Thoron" in n for n in names):
        out["listed"].append(f"the dialog lists {names}")
    status = (found.get("import") or {}).get("status")
    if status != "succeeded":
        out["import"].append(f"the import ended with {status!r}")
    readable = found.get("readable") or {}
    for entry in (KEYRING_PASSWORD, FIXED_PASSWORD):
        site = entry["url"].split("/")[2]
        if not any(site in s and text == entry["password"] for s, text in readable.items()):
            out["passwords"].append(f"{site} is not readable in Thoron: {readable}")
    for when, key in (("right after the import", "cookies_now"), ("after a restart", "cookies")):
        if not any(c.get("value") == COOKIE["value"] and c.get("secure") and c.get("httpOnly")
                   for c in found.get(key) or []):
            out["cookie"].append(f"{when} the cookie is not in Thoron's jar as it was: {found.get(key)}")
    # Chromium puts imported bookmarks straight onto an empty bookmarks bar, into a folder of their own otherwise
    if BOOKMARK not in (found.get("bookmarks") or ""):
        out["the data"].append("the bookmark is not in Thoron's bookmarks")
    if found.get("history") != [HISTORY]:
        out["the data"].append(f"the history entry is not in Thoron's history: {found.get('history')}")
    text = found.get("report") or ""
    if not text:
        out["the report"].append("there is no import report")
    else:
        for secret in ("example.org", "example.net", KEYRING_PASSWORD["password"], FIXED_PASSWORD["password"],
                       COOKIE["value"], KEYRING_PASSWORD["username"]):
            if secret in text:
                out["the report"].append(f"the report holds a value ({secret[:12]}...)")
        if "Thorium" not in text:
            out["the report"].append("the report does not name Thorium")
    if not found.get("before") or found.get("before") != found.get("after"):
        changed = sorted(k for k in set(found.get("before") or {}) | set(found.get("after") or {})
                         if (found.get("before") or {}).get(k) != (found.get("after") or {}).get(k))
        out["untouched"].append(f"Thorium's files changed: {changed}")
    return out


def run_machine(name: str, root: Path, work: Path, deb: Path, upstream: Path,
                desktop: str = "gnome") -> tuple[dict[str, list[str]], dict]:
    from tools.qa import linux_keyring_check as keyring
    from tools.qa import linux_package_check as lp
    from tools.qa import wsl_test_vm as vm
    vm.restore(root, name)
    folder = work / name
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    script = folder / "check.sh"
    extra = []
    if desktop == "kde":      # KDE's KWallet, made and opened as at sign-in (linux_keyring_check.py --desktop kde)
        script.write_bytes(keyring.KDE_SCRIPT.encode("utf-8"))
        (folder / "kde-session.sh").write_bytes(keyring.KDE_SESSION.encode("utf-8"))
        extra = [Path(__file__).name]
    else:
        script.write_bytes(SCRIPT.encode("utf-8"))
    tools = folder / "tools"
    shutil.copytree(REPO / "tools", tools, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    done = subprocess.run(["wsl.exe", "-d", vm.checked_name(name), "-u", "root", "--", "bash", lp.wsl_path(script),
                           lp.wsl_path(folder), lp.wsl_path(deb), lp.wsl_path(upstream), lp.wsl_path(tools), *extra],
                          capture_output=True, timeout=2400)
    (folder / "run-output.txt").write_bytes(done.stdout + done.stderr)
    out = folder / "out"
    if lp.read(out, "install_exit") != "0":
        return {"install": [f"the packages did not install: {lp.read(out, 'apt-install.txt')[-400:]}"]}, {}
    try:
        found = json.loads(lp.read(out, "probe.json") or "{}")
    except ValueError:
        found = {}
    if not found:
        return {"probe": [f"the probe wrote nothing: {lp.read(out, 'probe.txt')[-400:]}"]}, {}
    return problems(found), found


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command")
    pr = sub.add_parser("probe", help="inside a test machine (used by the check itself)")
    pr.add_argument("--tools", type=Path, required=True)
    pr.add_argument("--out", type=Path, required=True)
    pr.add_argument("--store", default="gnome-libsecret", help='"desktop": the browser chooses (no --password-store)')
    p.add_argument("--deb", type=Path)
    p.add_argument("--upstream", type=Path)
    p.add_argument("--root", type=Path)
    p.add_argument("--work", type=Path)
    p.add_argument("--machine", action="append")
    p.add_argument("--desktop", choices=("gnome", "kde"), default="gnome")
    a = p.parse_args(argv)
    if a.command == "probe":
        return probe(a.tools, a.out, a.store)
    if not (a.deb and a.upstream and a.root and a.work):
        p.error("--deb, --upstream, --root and --work are needed")
    from tools.qa import wsl_test_vm as vm
    failed = 0
    for name in a.machine or vm.MACHINES:
        print(f"== {name} ({'KDE, KWallet' if a.desktop == 'kde' else 'GNOME, its keyring'})")
        issues_by_step, _ = run_machine(name, a.root, a.work.resolve(), a.deb.resolve(), a.upstream.resolve(),
                                        a.desktop)
        for step, issues in issues_by_step.items():
            print(f"{'PASS' if not issues else 'FAIL'}  {step}")
            for issue in issues:
                print(f"      {issue}")
            failed += len(issues)
    print(f"LINUX SETTINGS IMPORT CHECK: {'PASSED' if not failed else f'FAILED ({failed} problem(s))'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
