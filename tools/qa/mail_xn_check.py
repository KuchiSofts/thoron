#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Thoron M-Notifier reads X-notifier's file of accounts, checked end to end and offline (ROADMAP P5.80).

X-notifier exports its accounts to a file sealed with a passphrase ("chrome.xn"). The M-Notifier's page reads
such a file: its Google accounts go into a list the M-Notifier keeps (address, the name the person gave it, the
password encrypted by the system), one whose password is an app password becomes a mailbox, and what is not
mail is left out. Here the file is written by `xn_file.py` with made-up accounts, local servers stand in for
Gmail and for a mail server, and no outside name can be resolved: nothing leaves the PC. Steps:

    wrong     a wrong passphrase: the page says so and nothing is taken
    read      the right one: its three Google accounts are in the list (one written without "@", so it is a
              Gmail address; one with the name it had), the one with an app password is a mailbox as well, two
              entries that are not mail are left out
    secret    no password of the file is in the profile's settings as text, and none in what the page is told
    counted   an account of the list that Gmail answers for (written another way) is shown as counted, and
              so is the one that is read as a mailbox; the one nobody is signed in to is not
    many      twelve Google accounts are all found (the M-Notifier stopped after ten)
    sign-in   "Sign in" opens Google's page with the address filled in, and only for an address of the list
    kept      after the browser starts again the list is there, with its passwords kept
    backup    the M-Notifier's own backup holds the list: without passwords, with them, and sealed; a removed
              account comes back from it

    py -3 -I tools/qa/mail_xn_check.py --browser <out>\\thoron.exe --work <scratch dir>
Exit status 0 only when every step passes.
"""
import argparse
import json
import re
import shutil
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.qa import xn_file  # noqa: E402
from tools.qa.mail_check import MENU_URL, Gmail, feed  # noqa: E402
from tools.qa.mail_imap_check import ImapServer, Page, profile_text  # noqa: E402

PASSPHRASE = "made-up passphrase"
GMAIL = "gmail.com"
LISTED = "alice@example.com"
LISTED_NAME = "Work"
BARE_USER = "thoronchecknosuchuser"  # written without "@": a Gmail address
BOX = "carol@example.com"
APP_PASSWORD = "abcd efgh ijkl mnop"  # the shape of an app password: 16 letters
PASSWORDS = ("made-up-password-1", "made-up-password-2")
ACCOUNTS = [("gmail", LISTED, PASSWORDS[0]), ("gmail", BARE_USER, PASSWORDS[1]), ("gmail", BOX, APP_PASSWORD),
            ("app_forums", "bob", "made-up-password-3"), ("scripts", "dave", "made-up-password-4")]
PREFERENCES = [("soundUrl", 0, ""), (f"accounts.[gmail#{LISTED}].alias", 0, LISTED_NAME),
               (f"accounts.[gmail#{LISTED}].enabled", 2, "true")]
MANY = 12
STATE_TEXT = "document.getElementById('backup-state').textContent"


def the_file() -> str:
    return xn_file.write(ACCOUNTS, PASSPHRASE, preferences=PREFERENCES)


def wanted(state: dict) -> dict:
    return {w["email"]: w for w in state.get("wanted", [])}


def wrong_problems(said: str, state: dict) -> list[str]:
    out = []
    if "passphrase" not in said.lower():
        out.append(f"wrong: with a wrong passphrase the page says {said!r}")
    if state.get("wanted"):
        out.append(f"wrong: accounts were taken all the same: {sorted(wanted(state))}")
    return out


def read_problems(said: str, state: dict) -> list[str]:
    out = []
    numbers = [int(n) for n in re.findall(r"\d+", said)]
    if numbers != [3, 1, 2]:
        out.append(f"read: the page says {said!r}, not 3 Google accounts, 1 mailbox and 2 left out")
    listed = wanted(state)
    bare = f"{BARE_USER}@{GMAIL}"
    if sorted(listed) != sorted([LISTED, bare, BOX]):
        out.append(f"read: the list holds {sorted(listed)}, not {sorted([LISTED, bare, BOX])}")
    else:
        if listed[LISTED].get("alias") != LISTED_NAME:
            out.append(f"read: {LISTED} has the name {listed[LISTED].get('alias')!r}, not {LISTED_NAME!r}")
        if not all(w.get("password") for w in listed.values()):
            out.append("read: an account of the list has no password kept")
    boxes = [a for a in state.get("accounts", []) if a.get("imap")]
    if [a["email"] for a in boxes] != [BOX]:
        out.append(f"read: the mailboxes are {[a['email'] for a in boxes]}, not [{BOX!r}]")
    elif boxes[0].get("problem"):
        out.append(f"read: the mailbox by app password was not read: {boxes[0]['problem']!r}")
    return out


def secret_problems(kept_text: str, state_text: str) -> list[str]:
    out = []
    for secret in (*PASSWORDS, APP_PASSWORD, APP_PASSWORD.replace(" ", "")):
        if secret in kept_text:
            out.append("secret: a password of the file is in the profile's settings as text")
        if secret in state_text:
            out.append("secret: a password of the file is in what the page is told")
    return out


def counted_problems(state: dict) -> list[str]:
    listed = wanted(state)
    bare = f"{BARE_USER}@{GMAIL}"
    out = []
    if not listed.get(LISTED, {}).get("counted"):
        out.append(f"counted: {LISTED} is signed in at the stand-in for Gmail and is not shown as counted")
    if not listed.get(BOX, {}).get("counted"):
        out.append(f"counted: {BOX} is read as a mailbox and is not shown as counted")
    if listed.get(bare, {}).get("counted", True):
        out.append(f"counted: {bare} is not signed in anywhere and is shown as counted")
    return out


def many_problems(state: dict) -> list[str]:
    found = [a["email"] for a in state.get("accounts", []) if not a.get("imap")]
    return [] if len(found) == MANY else [f"many: {len(found)} of {MANY} Google accounts were found"]


def signin_problems(before: list[str], other: list[str], after: list[str]) -> list[str]:
    out = []
    opened = [u for u in after if u not in before]
    if [u for u in other if u not in before]:
        out.append("sign-in: a page was opened for an address that is not in the list")
    wanted_page = [u for u in opened if u.startswith("https://accounts.google.com/AddSession")
                   and "Email=" + urllib.request.quote(LISTED, safe="") in u]
    if len(wanted_page) != 1:
        out.append(f"sign-in: Google's page with the address was not opened: {opened}")
    return out


def kept_problems(state: dict) -> list[str]:
    listed = wanted(state)
    if len(listed) != 3 or not all(w.get("password") for w in listed.values()):
        return [f"kept: after a restart the list is {[(e, w.get('password')) for e, w in listed.items()]}"]
    return []


def backup_problems(bare: str, plain: str, sealed: str, after_remove: dict, answer: dict, back: dict) -> list[str]:
    out = []
    try:
        without = {g["email"]: g for g in json.loads(bare).get("google", [])}
        with_them = {g["email"]: g for g in json.loads(plain).get("google", [])}
    except (ValueError, AttributeError, KeyError, TypeError):
        return ["backup: a backup is not JSON with the list of Google accounts"]
    if LISTED not in without or any("password" in g for g in without.values()):
        out.append("backup: the backup without passwords lacks the list, or holds a password")
    if with_them.get(LISTED, {}).get("password") != PASSWORDS[0]:
        out.append("backup: the backup with passwords lacks the list's password")
    if any(secret in sealed for secret in PASSWORDS) or LISTED in sealed:
        out.append("backup: the sealed backup shows an address or a password")
    if LISTED in wanted(after_remove):
        out.append("backup: the account was not removed")
    if answer.get("error"):
        out.append(f"backup: reading the backup said {answer.get('error')!r}")
    if not wanted(back).get(LISTED, {}).get("password"):
        out.append("backup: the removed account did not come back with its password")
    return out


def _pages(port: int) -> list[str]:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=10) as reply:
        return [t.get("url", "") for t in json.loads(reply.read())]


def _read_file(page: Page, path: Path, passphrase: str) -> str:
    """Has the page read `path` as a person would: the passphrase typed, the file chosen. What the page says."""
    page.ws.call("Runtime.evaluate", expression="document.getElementById('backup-state').textContent = '';"
                 f"document.getElementById('backup-pass').value = {json.dumps(passphrase)}; 1")
    root = page.ws.call("DOM.getDocument")["root"]["nodeId"]
    node = page.ws.call("DOM.querySelector", nodeId=root, selector="#import-file")["nodeId"]
    page.ws.call("DOM.setFileInputFiles", files=[str(path)], nodeId=node)
    said = ""
    for attempt in range(12):
        time.sleep(0.5)
        said = page.ws.call("Runtime.evaluate", expression=STATE_TEXT, returnByValue=True)["result"].get("value", "")
        if said:
            break
        if attempt == 3:  # the browser did not tell the page that a file was chosen
            page.ws.call("Runtime.evaluate", expression="document.getElementById('import-file')"
                         ".dispatchEvent(new Event('change')); 1")
    return said


def run(browser: Path, work: Path) -> list[str]:
    profile = Path(tempfile.mkdtemp(prefix="mail-xn-", dir=work))
    file = profile.parent / (profile.name + ".xn")
    file.write_text(the_file(), encoding="utf-8", newline="")
    problems: list[str] = []

    def report(name: str, found: list[str], detail) -> None:
        print(f"{'PASS' if not found else 'FAIL'}  {name}: {detail}")
        problems.extend(found)

    with Gmail() as gmail, ImapServer(BOX, APP_PASSWORD.replace(" ", "")) as imap:
        page = None
        try:
            page = Page(browser, profile, gmail.port, imap.port)
            page.ws.call("Page.navigate", url=MENU_URL + "#manage")
            time.sleep(2.5)
            page.wait_for_passwords()
            said = _read_file(page, file, "not the passphrase")
            state = page.state()
            report("wrong", wrong_problems(said, state), f"the page says {said!r}")

            said = _read_file(page, file, PASSPHRASE)
            state = page.look()
            report("read", read_problems(said, state),
                   f"{said!r}; list {sorted(wanted(state))}; sign-ins at the mail server {imap.logins}")
            report("secret", secret_problems(profile_text(profile), json.dumps(state)), "the profile and the page's state")

            gmail.answers[0] = (200, feed("Alice@Example.com", 2, []))
            state = page.look()
            report("counted", counted_problems(state), {e: w.get("counted") for e, w in wanted(state).items()})

            for index in range(MANY):
                gmail.answers[index] = (200, feed(f"user{index}@example.com", index, []))
            time.sleep(0.5)
            page.send("checkNow")
            time.sleep(8)
            state = page.state()
            report("many", many_problems(state), f"{len([a for a in state.get('accounts', []) if not a.get('imap')])} found")
            for index in range(1, MANY):
                del gmail.answers[index]
            gmail.answers[0] = (200, feed(LISTED, 2, []))

            before = _pages(page.port)
            page.send("signInGoogle", "eve@example.com")
            time.sleep(1.5)
            other = _pages(page.port)
            page.send("signInGoogle", LISTED)
            time.sleep(2.5)
            after = _pages(page.port)
            report("sign-in", signin_problems(before, other, after), [u[:90] for u in after if u not in before])

            page.close()
            page = Page(browser, profile, gmail.port, imap.port)
            page.wait_for_passwords()
            state = page.look()
            report("kept", kept_problems(state), sorted(wanted(state)))

            bare = page.ask("exportBackup", False, "")
            plain = page.ask("exportBackup", True, "")
            sealed = page.ask("exportBackup", False, PASSPHRASE)
            page.send("removeGoogleAccount", LISTED)
            after_remove = page.state()
            answer = page.ask("importBackup", plain, "")
            back = page.state()
            report("backup", backup_problems(bare, plain, sealed, after_remove, answer, back),
                   f"answer {answer}, list {sorted(wanted(back))}")
        except (OSError, RuntimeError, ValueError, KeyError, TypeError) as e:
            problems.append(f"the run failed: {e}")
        finally:
            if page:
                page.close()
            file.unlink(missing_ok=True)
            shutil.rmtree(profile, ignore_errors=True)
    return problems


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--browser", required=True, type=Path)
    p.add_argument("--work", required=True, type=Path, help="scratch folder for the throwaway profile")
    a = p.parse_args(argv)
    a.work.mkdir(parents=True, exist_ok=True)
    problems = run(a.browser.resolve(), a.work)
    for problem in problems:
        print(problem)
    print("MAIL XN CHECK: PASSED" if not problems else f"MAIL XN CHECK: FAILED ({len(problems)} problem(s))")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
