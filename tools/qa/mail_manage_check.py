#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Thoron M-Notifier's accounts in the person's order, its mailboxes and the accounts of its list edited, and its
backup saved by the browser into a file, checked end to end and offline (ROADMAP P5.81).

A local server stands in for the mail server, with made-up mailboxes, as in `mail_imap_check.py`; nothing leaves
the PC and no real account is used. The M-Notifier's own page is opened as a tab and worked as a person works it,
through its own buttons where a person would press one. Steps:

    order      two mailboxes put in another order: the list follows it at once, the page's arrows and dragging
               change it, and it is the same after a restart
    refused    a mailbox edited with a wrong password: refused, and the mailbox stays as it was
    password   its password changed at the server: the edit with the new one is signed in to and kept; the new
               password is nowhere in the profile's files as it is, and the page is never given it
    renamed    its address changed: its password, its place in the order and whether it is watched go with it
    webmail    only its mail page changed: kept without signing in again
    list       an account of the list edited: its address and name change and its password stays; the address
               of another account of the list is refused; a new app password makes it a mailbox too
    saved      the backup saved by the browser into a file holds the whole backup, with the order; through the
               page's own button, sealed with a passphrase, it holds no password and no address as they are
    unwritable a file that cannot be written is told ("write") and nothing is left there

    py -3 -I tools/qa/mail_manage_check.py --browser <out>\\thoron.exe --work <scratch dir>
Exit status 0 only when every step passes.
"""
import argparse
import json
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
from tools.qa.mail_check import GET_STATE, MENU_URL, Gmail  # noqa: E402
from tools.qa.mail_imap_check import ImapServer, profile_text  # noqa: E402

A, PASSWORD_A = "carol@example.com", "made-up-pass-a1"
B, PASSWORD_B = "dave@example.org", "made-up-pass-b2"
NEW_PASSWORD = "made-up-pass-a3"
RENAMED = "carol.new@example.com"
PASSPHRASE = "correct horse battery"
LIST_PASSWORD = "not an app password"
APP_PASSWORD = "abcd efgh ijkl mnop"
WEBMAIL = "https://mail.example.com/"
# made-up Gmail addresses (Gmail's own rules: no dots, an app password): written as parts
GMAIL = "gmail.com"
ERIN, ERIN_W, ERIN_W_DOTLESS, FAY = (f"{name}@{GMAIL}" for name in ("erin", "erin.w", "erinw", "fay"))
LOOK_S = 4.0


def mailbox_edit(before: str, email: str, password: str = "", webmail: str = "") -> dict:
    return {"before": before, "email": email, "password": password, "host": "imap.example.com", "port": 993,
            "user": "", "webmail": webmail}


def emails(state: dict) -> list[str]:
    return [a.get("email") for a in state.get("accounts", [])]


def account(state: dict, email: str) -> dict:
    return next((a for a in state.get("accounts", []) if a.get("email") == email), {})


def order_problems(after_set: list, after_arrow: list, after_drag: list, after_restart: list) -> list[str]:
    out = []
    for name, got, want in (("set", after_set, [B, A]), ("arrow", after_arrow, [A, B]),
                            ("drag", after_drag, [B, A]), ("restart", after_restart, [B, RENAMED])):
        if got != want:
            out.append(f"order: after the {name} the list is {got}, not {want}")
    return out


def refused_problems(answer: str, state: dict) -> list[str]:
    out = [] if answer == "sign-in" else [f"refused: a wrong password was answered {answer!r}, not 'sign-in'"]
    box = account(state, A)
    if box.get("unread") != 3 or box.get("problem"):
        out.append(f"refused: afterwards the mailbox is {(box.get('unread'), box.get('problem'))}, not (3, '')")
    return out


def password_problems(before: dict, answer: str, after: dict, files: str) -> list[str]:
    out = []
    if account(before, A).get("problem") != "sign-in":
        out.append("password: with its password changed at the server, the mailbox did not say the sign-in failed")
    if answer or account(after, A).get("problem") or account(after, A).get("unread") != 3:
        out.append(f"password: the edit was answered {answer!r} and the mailbox is "
                   f"{(account(after, A).get('unread'), account(after, A).get('problem'))}")
    if NEW_PASSWORD in files:
        out.append("password: the new password is in the profile's files as it is")
    if NEW_PASSWORD in json.dumps(after):
        out.append("password: the page was given the password")
    return out


def renamed_problems(answer: str, state: dict) -> list[str]:
    out = [] if not answer else [f"renamed: the edit was answered {answer!r}"]
    box = account(state, RENAMED)
    if A in emails(state) or not box:
        out.append(f"renamed: the list is {emails(state)}")
    elif box.get("problem") or box.get("unread") != 3:
        out.append(f"renamed: the mailbox's password did not come along: {(box.get('unread'), box.get('problem'))}")
    elif box.get("watched") is not False:
        out.append("renamed: the mailbox was not watched, and is watched under its new address")
    if emails(state) != [B, RENAMED]:
        out.append(f"renamed: its place in the order was lost: {emails(state)}")
    return out


def webmail_problems(answer: str, state: dict) -> list[str]:
    out = [] if not answer else [f"webmail: changing only the mail page was answered {answer!r} (signed in again?)"]
    if account(state, RENAMED).get("server", {}).get("webmail") != WEBMAIL:
        out.append(f"webmail: the mail page is {account(state, RENAMED).get('server')}")
    return out


def list_problems(answers: dict, state: dict, backup: str) -> list[str]:
    out = []
    want = {"imported": 2, "renamed": "", "taken": "exists", "app": ""}
    for name, value in want.items():
        if answers.get(name) != value:
            out.append(f"list: {name} is {answers.get(name)!r}, not {value!r}")
    listed = {a.get("email"): a for a in state.get("wanted", [])}
    erin = listed.get(ERIN_W, {})
    if ERIN in listed or erin.get("alias") != "Erin W" or not erin.get("password"):
        out.append(f"list: after the edit the list is {sorted(listed)}, the account {erin}")
    for secret in (LIST_PASSWORD, APP_PASSWORD, APP_PASSWORD.replace(" ", "")):
        if secret in json.dumps(state):
            out.append("list: the page was given a password")
    try:
        boxes = json.loads(backup).get("accounts", [])
    except ValueError:
        boxes = []
    if not any(b.get("email") == ERIN_W and b.get("host") == "imap.gmail.com" for b in boxes):
        out.append("list: a new app password did not make the account a mailbox")
    return out


def saved_problems(answer: dict, text: str, page_answer: str, sealed: str) -> list[str]:
    out = []
    if answer.get("error") != "" or answer.get("name") != "saved.json":
        out.append(f"saved: the save was answered {answer}")
    try:
        backup = json.loads(text)
    except ValueError:
        return out + [f"saved: the file is not a backup ({len(text)} bytes)"]
    boxes = sorted(b.get("email") for b in backup.get("accounts", []))
    if backup.get("format") != "thoron-m-notifier-backup" or not {B, RENAMED} <= set(boxes):
        out.append(f"saved: the file holds the mailboxes {boxes}")
    if backup.get("settings", {}).get("accountOrder", [])[:2] != [B, RENAMED]:
        out.append(f"saved: the file's order is {backup.get('settings', {}).get('accountOrder')}")
    if "saved.json" not in page_answer:
        out.append(f"saved: through the page's button the page said {page_answer!r}")
    try:
        sealed_file = json.loads(sealed)
    except ValueError:
        return out + ["saved: through the page's button the file is not a backup"]
    if not sealed_file.get("sealed") or NEW_PASSWORD in sealed or RENAMED in sealed:
        out.append("saved: the sealed backup is not sealed, or shows what is in it")
    return out


def unwritable_problems(answer: dict, target: Path) -> list[str]:
    out = []
    if answer.get("error") != "write":
        out.append(f"unwritable: a file that cannot be written was answered {answer}")
    if target.exists():
        out.append("unwritable: something was left where the file could not be written")
    return out


class Page:
    """The M-Notifier's own page (#manage) in one start of the browser."""

    def __init__(self, browser: Path, profile: Path, gmail_port: int, imap_port: int, backup_file: Path,
                 extra_args: tuple[str, ...] = ()):
        (profile / "DevToolsActivePort").unlink(missing_ok=True)
        args = [str(browser), "--headless=new", f"--user-data-dir={profile}", "--no-first-run",
                "--no-default-browser-check", "--disable-background-networking", "--disable-component-update",
                "--enable-features=ThoronMailNotifier", "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
                f"--thoron-mail-feeds-for-testing=http://127.0.0.1:{gmail_port}/",
                f"--thoron-mail-imap-for-testing=127.0.0.1:{imap_port}",
                f"--thoron-mail-backup-file-for-testing={backup_file}", *extra_args,
                "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0", "about:blank"]
        self.profile = profile
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            self.port = _devtools_port(profile)
            self.ws = WebSocket(_open(self.port, MENU_URL + "#manage")["webSocketDebuggerUrl"])
        except (OSError, RuntimeError, ValueError, KeyError):
            bench._stop(self.proc, profile)
            raise
        time.sleep(3)

    def run(self, expression: str):
        reply = self.ws.call("Runtime.evaluate", expression=expression, awaitPromise=True, returnByValue=True)
        return reply.get("result", {}).get("value")

    def ask(self, name: str, *args):
        """A message that is answered (sendWithPromise)."""
        value = self.run("import('chrome://resources/js/cr.js').then((cr) => cr.sendWithPromise("
                         + ", ".join(json.dumps(a) for a in (name, *args)) + ")).then((v) => JSON.stringify(v))")
        return json.loads(value or "null")

    def send(self, name: str, *args) -> None:
        self.run(f"chrome.send({json.dumps(name)}, {json.dumps(list(args))}); 1")
        time.sleep(0.6)

    def state(self) -> dict:
        return json.loads(self.run(GET_STATE) or "{}")

    def look(self) -> dict:
        self.send("checkNow")
        time.sleep(LOOK_S)
        return self.state()

    def wait_for_passwords(self) -> None:
        for _ in range(40):
            if self.state().get("canAddMailbox"):
                return
            time.sleep(0.25)

    def arrow(self, email: str, by: int) -> None:
        """The account opened in the page's list, and its own "Move up" (-1) or "Move down" (1) pressed."""
        item = f"#list .item[data-email={json.dumps(email)}]"
        self.run(f"(() => {{ const open = document.querySelector('{item} button.open'); "
                 "if (open.getAttribute('aria-expanded') !== 'true') { open.click(); } return 1; })()")
        time.sleep(0.5)
        self.run(f"document.querySelector('{item} .details button[data-move=\"{by}\"]').click(); 1")
        time.sleep(0.8)

    def drag(self, moved: str, onto: str) -> None:
        """An account dragged onto the upper half of another, as with the mouse."""
        self.run(f"""(() => {{
            const rows = [...document.querySelectorAll('#list .item')];
            const from = rows.find((r) => r.dataset.email === {json.dumps(moved)});
            const to = rows.find((r) => r.dataset.email === {json.dumps(onto)});
            const data = new DataTransfer();
            const y = to.getBoundingClientRect().top + 2;
            from.dispatchEvent(new DragEvent('dragstart', {{bubbles: true, dataTransfer: data}}));
            to.dispatchEvent(new DragEvent('dragover', {{bubbles: true, cancelable: true, dataTransfer: data,
                                                        clientY: y}}));
            to.dispatchEvent(new DragEvent('drop', {{bubbles: true, cancelable: true, dataTransfer: data,
                                                    clientY: y}}));
            from.dispatchEvent(new DragEvent('dragend', {{bubbles: true, dataTransfer: data}}));
            return 1; }})()""")
        time.sleep(0.8)

    def save_with_button(self, passphrase: str) -> str:
        """The page's own "Save a backup..." pressed with a passphrase typed: what the page says then."""
        self.run(f"document.getElementById('backup-pass').value = {json.dumps(passphrase)}; "
                 "document.getElementById('backup-state').textContent = ''; "
                 "document.getElementById('export').click(); 1")
        said = ""
        for _ in range(60):
            said = self.run("document.getElementById('backup-state').textContent") or ""
            if said:
                break
            time.sleep(0.25)
        self.run("document.getElementById('backup-pass').value = ''; 1")
        return said

    def close(self) -> None:
        try:
            self.ws.close()
        except OSError:
            pass
        _close_browser(self.port, self.proc)


def run(browser: Path, work: Path) -> list[str]:
    profile = Path(tempfile.mkdtemp(prefix="mail-manage-", dir=work))
    files = Path(tempfile.mkdtemp(prefix="mail-manage-files-", dir=work))
    saved, unwritable = files / "saved.json", files / "no-such-folder" / "saved.json"
    problems: list[str] = []

    def report(name: str, found: list[str], detail) -> None:
        print(f"{'PASS' if not found else 'FAIL'}  {name}: {detail}")
        problems.extend(found)

    with Gmail() as gmail, ImapServer(A, PASSWORD_A) as imap:
        imap.users[B] = PASSWORD_B
        page = None
        try:
            page = Page(browser, profile, gmail.port, imap.port, saved)
            page.wait_for_passwords()
            added = [page.ask("addImapAccount", mailbox_edit("", a, p)) for a, p in ((A, PASSWORD_A), (B, PASSWORD_B))]
            if added != ["", ""]:
                raise RuntimeError(f"the two mailboxes were not added: {added}")
            page.look()
            page.send("setOrder", [B, A])
            after_set = emails(page.state())
            page.arrow(A, -1)
            after_arrow = emails(page.state())
            page.drag(B, A)
            after_drag = emails(page.state())

            answer = page.ask("editImapAccount", mailbox_edit(A, A, "not-the-password"))
            report("refused", refused_problems(answer, page.look()), f"answer {answer!r}")

            imap.users[A] = NEW_PASSWORD
            before = page.look()
            answer = page.ask("editImapAccount", mailbox_edit(A, A, NEW_PASSWORD))
            after = page.look()
            time.sleep(1.5)  # the profile writes its settings a moment later
            report("password", password_problems(before, answer, after, profile_text(profile)),
                   f"answer {answer!r}, problem before {account(before, A).get('problem')!r}")

            page.send("setWatched", A, False)
            imap.users[RENAMED] = NEW_PASSWORD
            answer = page.ask("editImapAccount", mailbox_edit(A, RENAMED))
            state = page.look()
            report("renamed", renamed_problems(answer, state), f"answer {answer!r}, list {emails(state)}")

            # the server would refuse a sign-in now: only the mail page changes, so none is made
            imap.users[RENAMED] = "changed-meanwhile"
            answer = page.ask("editImapAccount", mailbox_edit(RENAMED, RENAMED, webmail=WEBMAIL))
            state = page.state()
            imap.users[RENAMED] = NEW_PASSWORD
            report("webmail", webmail_problems(answer, state), f"answer {answer!r}")

            answers = {"imported": page.ask("importGoogleAccounts", [
                {"email": ERIN, "alias": "Erin", "password": LIST_PASSWORD},
                {"email": FAY, "alias": "Fay", "password": ""}]).get("google")}
            answers["renamed"] = page.ask("editGoogleAccount", {"before": ERIN,
                                                                 "email": ERIN_W, "alias": "Erin W",
                                                                 "password": ""})
            answers["taken"] = page.ask("editGoogleAccount", {"before": FAY, "email": ERIN_W_DOTLESS,
                                                               "alias": "Fay", "password": ""})
            answers["app"] = page.ask("editGoogleAccount", {"before": ERIN_W,
                                                             "email": ERIN_W, "alias": "Erin W",
                                                             "password": APP_PASSWORD})
            state = page.state()
            report("list", list_problems(answers, state, page.ask("exportBackup", False, "")), answers)

            answer = page.ask("saveBackup", False, "")
            text = saved.read_text(encoding="utf-8") if saved.exists() else ""
            said = page.save_with_button(PASSPHRASE)
            sealed = saved.read_text(encoding="utf-8") if saved.exists() else ""
            report("saved", saved_problems(answer, text, said, sealed),
                   f"answer {answer}, {len(text)} then {len(sealed)} bytes, the page said {said!r}")
            page.close()

            page = Page(browser, profile, gmail.port, imap.port, unwritable)
            page.wait_for_passwords()
            # the two mailboxes first; the account of the list that became a mailbox comes after them
            after_restart = emails(page.look())[:2]
            report("order", order_problems(after_set, after_arrow, after_drag, after_restart),
                   f"{after_set} -> arrow {after_arrow} -> drag {after_drag}; after a restart {after_restart}")
            answer = page.ask("saveBackup", False, "")
            report("unwritable", unwritable_problems(answer, unwritable), f"answer {answer}")
            page.close()
            page = None
        except (OSError, RuntimeError, ValueError, KeyError, TypeError, AttributeError) as e:
            problems.append(f"the run failed: {e}")
        finally:
            if page is not None:
                try:
                    page.close()
                except (OSError, RuntimeError):
                    bench._stop(page.proc, profile)
            shutil.rmtree(profile, ignore_errors=True)
            shutil.rmtree(files, ignore_errors=True)
    return problems


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--browser", required=True, type=Path)
    p.add_argument("--work", required=True, type=Path, help="scratch folder for the throwaway profile")
    a = p.parse_args(argv)
    sys.stdout.reconfigure(errors="backslashreplace")
    a.work.mkdir(parents=True, exist_ok=True)
    problems = run(a.browser.resolve(), a.work)
    for problem in problems:
        print(problem)
    print("MAIL MANAGE CHECK: PASSED" if not problems else f"MAIL MANAGE CHECK: FAILED ({len(problems)} problem(s))")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
