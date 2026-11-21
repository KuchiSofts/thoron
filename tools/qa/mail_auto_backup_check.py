#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Thoron M-Notifier's backup written by itself into a chosen folder, checked end to end and offline (ROADMAP
P5.77).

A local server stands in for the mail server, with made-up mailboxes, as in `mail_imap_check.py`; nothing leaves
the PC and no real account is used. The M-Notifier's own page is opened as a tab and its Backup tab is worked
through its own switch, buttons and fields. The browser is told to look every few seconds instead of every two
minutes, and is given the folder instead of the system's dialog. Steps:

    off        while it is off nothing is written, and "Save one now" says so
    plain      turned on: a backup comes into the folder by itself; without a passphrase it holds the mailboxes and
               not one password
    unchanged  nothing changed: no new file
    changed    the order changed: a new file, with the new order
    sealed     a passphrase kept: the next one is sealed, shows no password or address, and opens with that
               passphrase only; a short one is refused; the passphrase is in neither the profile nor the page
    kept       with 3 kept, only its own 3 newest files stay; the person's other files there are untouched
    restart    after a restart nothing new is written while nothing changed; its newest file deleted, it is
               written again
    gone       the folder taken away: the page says so, "Save one now" answers "folder", nothing crashes
    now        the folder back: "Save one now" writes one at once, even with nothing changed

    py -3 -I tools/qa/mail_auto_backup_check.py --browser <out>\\thoron.exe --work <scratch dir>
Exit status 0 only when every step passes.
"""
import argparse
import json
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.qa import bench  # noqa: E402
from tools.qa.mail_check import Gmail  # noqa: E402
from tools.qa.mail_imap_check import ImapServer, profile_text  # noqa: E402
from tools.qa.mail_manage_check import A, B, PASSWORD_A, PASSWORD_B, Page, mailbox_edit  # noqa: E402

PASSPHRASE = "a long made-up passphrase"
# how often the browser is told to look, and how long a step waits for a file
LOOK_S = 3
WAIT_S = 20.0
# its own files, as the browser names them
OWN = re.compile(r"^thoron-m-notifier-auto-\d{4}-\d{2}-\d{2}-\d{6}\.(thoron|json)$")
# the person's files in the same folder, which it must never touch
OTHERS = ("thoron-m-notifier-backup-2026-01-01.json", "notes.txt", "thoron-m-notifier-auto-notes.json")


def own_files(folder: Path) -> list[str]:
    """Its own files in `folder`, the newest first."""
    if not folder.is_dir():
        return []
    return sorted((p.name for p in folder.iterdir() if p.is_file() and OWN.match(p.name)), reverse=True)


def plain_problems(name: str, text: str, state: dict) -> list[str]:
    out = []
    if not name.endswith(".json"):
        return [f"plain: no backup came into the folder by itself ({name!r})"]
    try:
        backup = json.loads(text)
    except ValueError:
        return [f"plain: {name} is not a backup ({len(text)} bytes)"]
    boxes = sorted(b.get("email") for b in backup.get("accounts", []))
    if backup.get("format") != "thoron-m-notifier-backup" or backup.get("sealed") or boxes != sorted([A, B]):
        out.append(f"plain: {name} holds the mailboxes {boxes}")
    if PASSWORD_A in text or PASSWORD_B in text or any("password" in b for b in backup.get("accounts", [])):
        out.append(f"plain: {name} holds a password, without a passphrase")
    auto = state.get("autoBackup", {})
    if not auto.get("on") or auto.get("name") != name or auto.get("error") or not auto.get("last"):
        out.append(f"plain: the page is told {auto}")
    return out


def changed_problems(before: list[str], after: list[str], text: str) -> list[str]:
    if len(after) != len(before) + 1 or after[1:] != before:
        return [f"changed: the files went from {before} to {after}"]
    try:
        order = json.loads(text).get("settings", {}).get("accountOrder", [])
    except ValueError:
        return ["changed: the new file is not a backup"]
    return [] if order[:2] == [B, A] else [f"changed: the new file's order is {order}"]


def sealed_problems(answers: dict, name: str, text: str, profile: str, state: str) -> list[str]:
    out = []
    want = {"short": "short", "kept": "", "opened": "", "wrong": "wrong"}
    for key, value in want.items():
        if answers.get(key) != value:
            out.append(f"sealed: {key} was answered {answers.get(key)!r}, not {value!r}")
    try:
        sealed = json.loads(text).get("sealed")
    except ValueError:
        sealed = False
    if not name.endswith(".thoron") or not sealed:
        out.append(f"sealed: the next file, {name!r}, is not sealed")
    for secret in (PASSWORD_A, PASSWORD_B, A, B, PASSPHRASE):
        if secret in text:
            out.append("sealed: the sealed file shows what is in it, or its passphrase")
            break
    if PASSPHRASE in profile:
        out.append("sealed: the passphrase is in the profile's files as it is")
    if PASSPHRASE in state:
        out.append("sealed: the page was given the passphrase")
    return out


def kept_problems(own: list[str], others: dict[str, bool]) -> list[str]:
    out = [] if len(own) == 3 else [f"kept: with 3 kept, the folder has {len(own)} of its own files: {own}"]
    out += [f"kept: the person's file {name} was touched" for name, there in others.items() if not there]
    return out


def restart_problems(before: list[str], after_restart: list[str], after_delete: list[str]) -> list[str]:
    out = []
    if after_restart != before:
        out.append(f"restart: with nothing changed the files went from {before} to {after_restart}")
    if not after_delete or after_delete[0] in before or len(after_delete) != len(before):
        out.append(f"restart: its newest file deleted, the files are {after_delete} (were {before})")
    return out


def gone_problems(state: dict, said: str, answer: str) -> list[str]:
    out = []
    if state.get("autoBackup", {}).get("error") != "folder":
        out.append(f"gone: the page is told {state.get('autoBackup')}")
    if not said or said == state.get("autoBackup", {}).get("name"):
        out.append(f"gone: the page says {said!r}")
    if answer != "folder":
        out.append(f"gone: \"Save one now\" was answered {answer!r}")
    return out


def now_problems(answer: str, before: list[str], after: list[str], said: str) -> list[str]:
    out = [] if answer == "" else [f"now: \"Save one now\" was answered {answer!r}"]
    if len(after) != len(before) + 1 and not (len(after) == len(before) and after[0] not in before):
        out.append(f"now: the files went from {before} to {after}")
    if not said:
        out.append("now: the page said nothing")
    return out


class AutoPage(Page):
    """The M-Notifier's page with the backup written by itself looking every few seconds, into `folder`."""

    def __init__(self, browser: Path, profile: Path, gmail_port: int, imap_port: int, folder: Path):
        super().__init__(browser, profile, gmail_port, imap_port, folder / "unused.json",
                         (f"--thoron-mail-auto-backup-seconds-for-testing={LOOK_S}",
                          f"--thoron-mail-auto-backup-folder-for-testing={folder}"))
        self.run("location.hash = '#manage/backup'; 1")
        time.sleep(0.5)

    def text(self, element: str) -> str:
        return self.run(f"document.getElementById({json.dumps(element)}).textContent") or ""

    def click(self, element: str) -> None:
        self.run(f"document.getElementById({json.dumps(element)}).click(); 1")
        time.sleep(0.8)

    def note_after(self, element: str) -> str:
        """`element` pressed: what the page says then (its note)."""
        self.run("document.getElementById('auto-note').textContent = ''; 1")
        self.click(element)
        for _ in range(40):
            said = self.text("auto-note")
            if said:
                return said
            time.sleep(0.25)
        return ""

    def keep_passphrase(self, passphrase: str) -> str:
        self.run(f"document.getElementById('auto-pass').value = {json.dumps(passphrase)}; 1")
        return self.note_after("auto-pass-keep")

    def set_keep(self, keep: int) -> None:
        self.run(f"(() => {{ const s = document.getElementById('auto-keep'); s.value = '{keep}'; "
                 "s.dispatchEvent(new Event('change')); return 1; })()")
        time.sleep(0.8)


def wait_for_new(folder: Path, before: list[str], seconds: float = WAIT_S) -> list[str]:
    """Its files once one that was not there `before` came, or as they are after `seconds`."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        now = own_files(folder)
        if any(name not in before for name in now):
            time.sleep(1.0)  # its older files are taken away just after a new one is written
            return own_files(folder)
        time.sleep(0.5)
    return own_files(folder)


def run(browser: Path, work: Path) -> list[str]:
    profile = Path(tempfile.mkdtemp(prefix="mail-auto-", dir=work))
    files = Path(tempfile.mkdtemp(prefix="mail-auto-files-", dir=work))
    folder = files / "backups"
    folder.mkdir()
    problems: list[str] = []

    def report(name: str, found: list[str], detail) -> None:
        print(f"{'PASS' if not found else 'FAIL'}  {name}: {detail}")
        problems.extend(found)

    def read(name: str) -> str:
        path = folder / name
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    with Gmail() as gmail, ImapServer(A, PASSWORD_A) as imap:
        imap.users[B] = PASSWORD_B
        page = None
        try:
            page = AutoPage(browser, profile, gmail.port, imap.port, folder)
            page.wait_for_passwords()
            added = [page.ask("addImapAccount", mailbox_edit("", a, p)) for a, p in ((A, PASSWORD_A), (B, PASSWORD_B))]
            if added != ["", ""]:
                raise RuntimeError(f"the two mailboxes were not added: {added}")
            page.send("setOrder", [A, B])

            time.sleep(LOOK_S * 2.5)
            answer = page.ask("saveAutoBackupNow")
            report("off", [] if not own_files(folder) and answer == "off" else
                   [f"off: {own_files(folder)} written, \"Save one now\" answered {answer!r}"],
                   f"files {own_files(folder)}, answer {answer!r}")

            page.click("auto-on")
            now = wait_for_new(folder, [])
            name = now[0] if now else ""
            report("plain", plain_problems(name, read(name), page.state()), f"files {now}")

            time.sleep(LOOK_S * 3.5)
            report("unchanged", [] if own_files(folder) == now else
                   [f"unchanged: with nothing changed the files went from {now} to {own_files(folder)}"],
                   f"files {own_files(folder)}")

            before = own_files(folder)
            page.send("setOrder", [B, A])
            after = wait_for_new(folder, before)
            report("changed", changed_problems(before, after, read(after[0]) if after else ""), f"files {after}")

            answers = {"short": page.ask("setAutoBackupPassphrase", "short1")}
            before = own_files(folder)
            said = page.keep_passphrase(PASSPHRASE)
            # kept: the page says so and is told it is kept (the words are in the browser's language)
            answers["kept"] = "" if said and page.state().get("autoBackup", {}).get("sealed") else said
            after = wait_for_new(folder, before)
            name = after[0] if after else ""
            answers["opened"] = page.ask("importBackup", read(name), PASSPHRASE).get("error")
            answers["wrong"] = page.ask("importBackup", read(name), "not the passphrase").get("error")
            time.sleep(1.5)  # the profile writes its settings a moment later
            report("sealed", sealed_problems(answers, name, read(name), profile_text(profile),
                                             json.dumps(page.state())), f"answers {answers}, file {name!r}")

            for other in OTHERS:
                (folder / other).write_text("the person's own file\n", encoding="utf-8")
            page.set_keep(3)
            order = [A, B]
            for _ in range(4):
                before = own_files(folder)
                page.send("setOrder", order)
                order.reverse()
                wait_for_new(folder, before)
            report("kept", kept_problems(own_files(folder), {o: (folder / o).is_file() for o in OTHERS}),
                   f"files {own_files(folder)}")
            page.close()

            page = AutoPage(browser, profile, gmail.port, imap.port, folder)
            page.wait_for_passwords()
            before = own_files(folder)
            time.sleep(LOOK_S * 3.5)
            after_restart = own_files(folder)
            if after_restart:
                (folder / after_restart[0]).unlink()
            after_delete = wait_for_new(folder, own_files(folder))
            report("restart", restart_problems(before, after_restart, after_delete),
                   f"{before} -> {after_restart} -> {after_delete}")

            aside = files / "taken-away"
            folder.rename(aside)
            page.send("setOrder", [B, A])
            time.sleep(LOOK_S * 2.5)
            # a look at the mail has the page show the state again, as it does every few minutes
            state = page.look()
            said = page.text("auto-state")
            answer = page.ask("saveAutoBackupNow")
            report("gone", gone_problems(state, said, answer), f"error {state.get('autoBackup', {}).get('error')!r}, "
                   f"the page says {said!r}, answer {answer!r}")

            aside.rename(folder)
            time.sleep(LOOK_S * 2.5)
            before = own_files(folder)
            said = page.note_after("auto-now")
            after = wait_for_new(folder, before, 5.0)
            answer = "" if after and after[0] not in before else said
            report("now", now_problems(answer, before, after, said), f"{before} -> {after}, the page said {said!r}")
            page.close()
            page = None
        except (OSError, RuntimeError, ValueError, KeyError, TypeError, AttributeError, IndexError) as e:
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
    print("MAIL AUTO BACKUP CHECK: PASSED" if not problems else
          f"MAIL AUTO BACKUP CHECK: FAILED ({len(problems)} problem(s))")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
