#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Taking over an upstream Thorium portable folder, end to end on test copies (ROADMAP P4.10). Windows only.

An upstream-style portable folder is made with the given build started the way upstream's THORIUM.BAT starts
Thorium (`BIN\\thoron.exe --user-data-dir=USER_DATA --disable-encryption --disable-machine-id`, folder junctions,
nothing copied): a page sets a cookie and Settings gets a home page. Then:

    adopt     tools/migrate/adopt_portable.py takes it over into a Thoron portable layout: the original is hash-identical
              afterwards, and the copy's key is protected
    opens     the Thoron copy starts without a question and sends the cookie: every value is readable in Thoron
    settings  the home page set in the upstream folder is still the home page (no settings were reset)
    lock      the copy is locked on chrome://thoron-portable; after a restart and the passphrase the cookie is there

    py -3 -I tools/qa/portable_adopt_check.py --browser <out>\\thoron.exe --work <scratch dir>
Exit status 0 only when every step passes.
"""
import argparse
import hashlib
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
from tools.migrate import adopt_portable  # noqa: E402
from tools.qa import portable_passphrase_check as pp  # noqa: E402

HOME = "https://example.com/thoron-adopted-home"


def junction(link: Path, target: Path) -> None:
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)


def unlink_junction(link: Path) -> None:
    subprocess.run(["cmd", "/c", "rmdir", str(link)], capture_output=True)


def hashes(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


def start(exe: Path, user_data: Path, *extra: str) -> subprocess.Popen:
    (user_data / "DevToolsActivePort").unlink(missing_ok=True)
    return subprocess.Popen([str(exe), "--headless=new", f"--user-data-dir={user_data}", "--no-first-run",
                             "--no-default-browser-check", "--disable-background-networking",
                             "--disable-component-update", "--remote-debugging-address=127.0.0.1",
                             "--remote-debugging-port=0", *extra, "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def home_page(session: pp.Session) -> str:
    session.go("chrome://settings/", 4)
    return session.run("new Promise((ok) => chrome.settingsPrivate.getPref('homepage', (p) => ok(p.value)))") or ""


def run(browser: Path, work: Path) -> list[str]:
    if os.name != "nt":
        return ["this check runs on Windows only"]
    problems: list[str] = []
    root = Path(tempfile.mkdtemp(prefix="portable-adopt-", dir=work))
    upstream, thoron = root / "Thorium Portable", root / "ThoronPortable"
    cookies = pp.CookieServer()
    win = pp.Win32()
    session = None

    def report(name: str, found: list[str], detail) -> None:
        print(f"{'PASS' if not found else 'FAIL'}  {name}: {detail}")
        problems.extend(found)

    try:
        # the upstream folder, made the way upstream's launcher starts Thorium
        upstream.mkdir()
        junction(upstream / "BIN", browser.parent)
        session = pp.Session(start(upstream / "BIN" / browser.name, upstream / "USER_DATA", "--disable-encryption",
                                   "--disable-machine-id"), upstream / "USER_DATA")
        session.body(cookies.url("/set"))
        session.go("chrome://settings/", 4)
        for name, value in (("homepage", HOME), ("homepage_is_newtabpage", False)):
            session.run(f"new Promise((ok) => chrome.settingsPrivate.setPref({json.dumps(name)}, "
                        f"{json.dumps(value)}, '', () => ok(1)))")
        session.close()
        session = None
        time.sleep(2)
        unlink_junction(upstream / "BIN")
        (upstream / "BIN").mkdir()  # the layout without the build in it, as the tool sees it
        # files are dated a minute ago, so the copy does not take the folder for one still being written
        old = time.time() - 120
        for path in (upstream / "USER_DATA").rglob("*"):
            os.utime(path, (old, old))
        before = hashes(upstream)

        # adopt
        (thoron / "Application").mkdir(parents=True)
        (thoron / "Thoron.exe").write_bytes(b"launcher stand-in")
        (thoron / "Application" / "current").write_text("v\n", encoding="utf-8")
        taken = adopt_portable.adopt(upstream, thoron)
        state = json.loads((thoron / "User Data" / "Local State").read_text(encoding="utf-8"))
        found = [] if hashes(upstream) == before else ["adopt: the original changed"]
        if taken["key_was"] != "unprotected":
            found.append(f"adopt: the upstream key was {taken['key_was']!r}, not unprotected")
        if adopt_portable.read_key(state)[1] != "this account":
            found.append("adopt: the copy's key is not protected")
        if taken["secrets"]["cookies"]["found"] < 1:
            found.append("adopt: the cookie was not in the copy")
        report("adopt", found, taken["secrets"])

        # opens
        junction(thoron / "Application" / "v", browser.parent)
        exe = thoron / "Application" / "v" / browser.name
        proc = start(exe, thoron / "User Data")
        asked = False
        end = time.time() + 30
        while time.time() < end and not (thoron / "User Data" / "DevToolsActivePort").exists():
            if any(win.user32.GetDlgItem(h, pp.EDIT) for h in win.dialogs(proc.pid)):
                asked = True
                break
            time.sleep(0.2)
        if asked:
            proc.kill()
            report("opens", ["opens: the taken-over copy asked for a passphrase"], "asked")
            return problems
        session = pp.Session(proc, thoron / "User Data")
        seen = f"thoronportable={cookies.value}" in session.body(cookies.url("/get"))
        report("opens", [] if seen else ["opens: the cookie is not readable in Thoron"], "cookie sent" if seen else "")

        # settings
        home = home_page(session)
        report("settings", [] if home == HOME else [f"settings: the home page is {home!r}"], home)

        # lock
        session.go(pp.PAGE_URL, 3)
        session.page(f"""document.getElementById('pass').value = {json.dumps(pp.PASSPHRASE)};
                         document.getElementById('repeat').value = {json.dumps(pp.PASSPHRASE)};
                         document.getElementById('with-recovery').checked = false;
                         document.getElementById('next').click();""")
        time.sleep(1.5)
        session.page("document.getElementById('lock').click();")
        said = session.wait_text("message", "locked with your passphrase")
        session.close()
        session = None
        proc = start(exe, thoron / "User Data")
        dialog = win.wait_dialog(proc.pid, pp.EDIT)
        win.set_text(dialog, pp.EDIT, pp.PASSPHRASE)
        win.press(dialog, pp.IDOK)
        session = pp.Session(proc, thoron / "User Data")
        seen = f"thoronportable={cookies.value}" in session.body(cookies.url("/get"))
        found = [] if "locked" in said else [f"lock: the page said {said!r}"]
        if not seen:
            found.append("lock: the cookie is not readable after the passphrase")
        report("lock", found, said)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, subprocess.SubprocessError,
            adopt_portable.AdoptRefused) as e:
        problems.append(f"the run failed: {e}")
    finally:
        if session is not None:
            try:
                session.close()
            except (OSError, RuntimeError):
                session.proc.kill()
        cookies.close()
        for link in (upstream / "BIN", thoron / "Application" / "v"):
            if link.is_junction() if hasattr(link, "is_junction") else link.exists():
                unlink_junction(link)
        shutil.rmtree(root, ignore_errors=True)
    return problems


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--browser", required=True, type=Path)
    p.add_argument("--work", required=True, type=Path, help="scratch folder for the test copies")
    a = p.parse_args(argv)
    sys.stdout.reconfigure(errors="backslashreplace")
    a.work.mkdir(parents=True, exist_ok=True)
    problems = run(a.browser.resolve(), a.work.resolve())
    for problem in problems:
        print(problem)
    print("PORTABLE ADOPT CHECK: PASSED" if not problems else f"PORTABLE ADOPT CHECK: FAILED ({len(problems)} problem(s))")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
