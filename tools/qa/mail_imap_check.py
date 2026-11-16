#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Thoron M-Notifier's mailboxes by address and password, and its backup, checked end to end and offline
(ROADMAP P5.77).

A mailbox a person adds with its address and password is looked at over IMAP. Here a local server stands in
for the mail server (the browser is told so with a switch that only takes a loopback address, and talks to it
in plain text; a real server is always reached over TLS), with a made-up mailbox; nothing leaves the PC and no
real account is used. The M-Notifier's page is opened as a tab and worked as a person works it. Steps:

    refused   a wrong password: the mailbox is not added, and the answer says the sign-in was refused
    added     the right password: it is added, its unread mail is counted and the newest messages are read,
              their words decoded from the form mail carries them in (UTF-8 and another charset)
    secret    the password is nowhere in the profile's files as it is, and the page is never given it
    new       a message that comes later is new, and makes the M-Notifier's sound
    seen      the mailbox opened from the menu: its new mail is counted from then
    restart   the browser closed and started again: the mailbox is there and is looked at
    backup    a backup sealed with a passphrase holds no password as it is; one without a passphrase holds
              none at all unless asked; the mailbox removed and the sealed backup read brings it back; the
              wrong passphrase, no passphrase and a changed file are refused

    py -3 -I tools/qa/mail_imap_check.py --browser <out>\\thoron.exe --work <scratch dir>
Exit status 0 only when every step passes.
"""
import argparse
import base64
import json
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.qa import bench  # noqa: E402
from tools.qa.adblock_site_switch_check import _close_browser, _devtools_port, _open  # noqa: E402
from tools.qa.cdp import WebSocket  # noqa: E402
from tools.qa.mail_check import GET_STATE, MENU_URL, Gmail  # noqa: E402

EMAIL = "carol@example.com"
PASSWORD = "made-up-app-pass-7"
PASSPHRASE = "correct horse battery"
LOOK_S = 4.0
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def imap_date(seconds: float) -> str:
    """A time as IMAP writes it (English month names, whatever the PC's language)."""
    t = time.gmtime(seconds)
    return f"{t.tm_mday:02d}-{MONTHS[t.tm_mon - 1]}-{t.tm_year} {t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d} +0000"


def headers(sender: str, subject: str) -> bytes:
    return f"From: {sender}\r\nSubject: {subject}\r\n\r\n".encode("ascii")


# Three unread messages there from the start (a day old): mail writes words outside ASCII as encoded words.
OLD = [
    (11, headers("=?UTF-8?B?RGFuYSDinJM=?= <dana@example.com>", "=?utf-8?Q?Caf=C3=A9_plans?=")),
    (12, headers('"Eli" <eli@example.org>', "=?iso-8859-1?Q?Pr=E9sentation?=")),
    (15, headers("frank@example.net", "Plain subject")),
]


class ImapServer:
    """A stand-in for a mail server: IMAP in plain text on 127.0.0.1, one made-up mailbox."""

    def __init__(self, user: str, password: str):
        self.user, self.password = user, password
        day_ago = time.time() - 86400
        self.messages: list[tuple[int, str, bytes]] = [(uid, imap_date(day_ago + uid), data) for uid, data in OLD]
        self.logins: list[tuple[str, bool]] = []
        server = self

        class Handler(socketserver.StreamRequestHandler):
            def say(self, text: str) -> None:
                self.wfile.write(text.encode("ascii"))
                self.wfile.flush()

            def handle(self):
                self.say("* OK [CAPABILITY IMAP4rev1 AUTH=PLAIN] ready\r\n")
                signed_in = False
                while True:
                    line = self.rfile.readline()
                    if not line:
                        return
                    tag, _, rest = line.decode("utf-8", "replace").rstrip("\r\n").partition(" ")
                    command = rest.upper()
                    if command == "CAPABILITY":
                        self.say(f"* CAPABILITY IMAP4rev1 AUTH=PLAIN\r\n{tag} OK\r\n")
                    elif command.startswith("AUTHENTICATE PLAIN"):
                        given = rest[len("AUTHENTICATE PLAIN"):].strip()
                        if not given:
                            self.say("+ \r\n")
                            given = self.rfile.readline().decode("ascii", "replace").strip()
                        try:
                            _, user, password = base64.b64decode(given).decode("utf-8").split("\0")
                        except (ValueError, UnicodeDecodeError):
                            user = password = ""
                        signed_in = user == server.user and password == server.password
                        server.logins.append((user, signed_in))
                        self.say(f"{tag} OK signed in\r\n" if signed_in else
                                 f"{tag} NO [AUTHENTICATIONFAILED] Invalid credentials\r\n")
                    elif command == "LOGOUT":
                        self.say(f"* BYE\r\n{tag} OK\r\n")
                        return
                    elif not signed_in:
                        self.say(f"{tag} BAD sign in first\r\n")
                    elif command.startswith("EXAMINE"):
                        self.say(f"* {len(server.messages)} EXISTS\r\n* OK [UIDVALIDITY 7] ok\r\n"
                                 f"{tag} OK [READ-ONLY] done\r\n")
                    elif command == "UID SEARCH UNSEEN":
                        self.say("* SEARCH " + " ".join(str(m[0]) for m in server.messages) + f"\r\n{tag} OK\r\n")
                    elif command.startswith("UID FETCH"):
                        wanted = {int(n) for n in rest.split()[2].split(",") if n.isdigit()}
                        for seq, (uid, date, data) in enumerate(server.messages, 1):
                            if uid in wanted:
                                self.wfile.write(
                                    f'* {seq} FETCH (UID {uid} INTERNALDATE "{date}" '
                                    f"BODY[HEADER.FIELDS (FROM SUBJECT)] {{{len(data)}}}\r\n".encode("ascii")
                                    + data + b")\r\n")
                        self.say(f"{tag} OK\r\n")
                    else:
                        self.say(f"{tag} BAD\r\n")

        class Server(socketserver.ThreadingTCPServer):
            daemon_threads = True
            allow_reuse_address = True

        self._server = Server(("127.0.0.1", 0), Handler)
        self.port = self._server.server_address[1]

    def __enter__(self):
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()


def mailbox(state: dict) -> dict | None:
    return next((a for a in state.get("accounts", []) if a.get("imap")), None)


def refused_problems(answer: str, state: dict) -> list[str]:
    out = [] if answer == "sign-in" else [f"refused: a wrong password was answered {answer!r}, not 'sign-in'"]
    if mailbox(state):
        out.append("refused: the mailbox was added with a wrong password")
    return out


def added_problems(answer: str, state: dict) -> list[str]:
    box = mailbox(state)
    if answer or not box:
        return [f"added: the answer was {answer!r} and the mailbox is {'there' if box else 'not there'}"]
    out = []
    if (box["email"], box["unread"], box.get("problem")) != (EMAIL, 3, ""):
        out.append(f"added: the mailbox is {(box['email'], box['unread'], box.get('problem'))}, not ({EMAIL!r}, 3, '')")
    read = sorted((m.get("from"), m.get("fromEmail"), m.get("subject")) for m in box.get("latest", []))
    want = sorted([("Dana ✓", "dana@example.com", "Café plans"),
                   ("Eli", "eli@example.org", "Présentation"),
                   ("", "frank@example.net", "Plain subject")])
    if read != want:
        out.append(f"added: its messages read {read}, not {want}")
    if box.get("new") != 0 or state.get("problem"):
        out.append(f"added: {box.get('new')} new at the first look, problem {state.get('problem')!r}")
    return out


def secret_problems(profile_text: str, state_text: str) -> list[str]:
    out = []
    if PASSWORD in profile_text:
        out.append("secret: the password is in the profile's files as it is")
    if PASSWORD in state_text:
        out.append("secret: the page was given the password")
    return out


def new_problems(before: dict, after: dict) -> list[str]:
    box = mailbox(after) or {}
    out = []
    if (box.get("unread"), box.get("new")) != (4, 1):
        out.append(f"new: (unread, new) is {(box.get('unread'), box.get('new'))}, not (4, 1)")
    if after.get("sounds", 0) - before.get("sounds", 0) != 1:
        out.append(f"new: the sound was made {after.get('sounds', 0) - before.get('sounds', 0)} time(s), not once")
    return out


def seen_problems(state: dict) -> list[str]:
    box = mailbox(state) or {}
    if (box.get("unread"), box.get("new")) != (4, 0):
        return [f"seen: after the mailbox was opened, (unread, new) is {(box.get('unread'), box.get('new'))}"]
    return []


def restart_problems(state: dict) -> list[str]:
    box = mailbox(state)
    if not box or box.get("unread") != 4 or box.get("problem"):
        return [f"restart: after a restart the mailbox is {box and (box.get('unread'), box.get('problem'))}"]
    return []


def backup_problems(sealed: str, bare: str, plain: str, answers: dict, back: dict) -> list[str]:
    out = []
    try:
        sealed_file, bare_file, plain_file = json.loads(sealed), json.loads(bare), json.loads(plain)
    except ValueError:
        return ["backup: an export is not JSON"]
    if not sealed_file.get("sealed") or PASSWORD in sealed or EMAIL in sealed:
        out.append("backup: the sealed backup is not sealed, or shows what is in it")
    if bare_file.get("sealed") or PASSWORD in bare or bare_file.get("accounts", [{}])[0].get("email") != EMAIL:
        out.append("backup: the backup without a passphrase holds a password, or not the mailbox")
    if plain_file.get("accounts", [{}])[0].get("password") != PASSWORD:
        out.append("backup: asked to, the backup does not hold the password")
    want = {"removed": False, "wrong": "wrong", "none": "passphrase", "changed": "wrong", "bare": "",
            "bare_boxes": 0, "right": "", "right_boxes": 1}
    for name, value in want.items():
        if answers.get(name) != value:
            out.append(f"backup: {name} is {answers.get(name)!r}, not {value!r}")
    box = mailbox(back)
    if not box or box.get("unread") != 4 or box.get("problem"):
        out.append(f"backup: read back, the mailbox is {box and (box.get('unread'), box.get('problem'))}")
    return out


def _launch(browser: Path, profile: Path, gmail_port: int, imap_port: int) -> subprocess.Popen:
    args = [str(browser), "--headless=new", f"--user-data-dir={profile}", "--no-first-run",
            "--no-default-browser-check", "--disable-background-networking", "--disable-component-update",
            "--enable-features=ThoronMailNotifier", "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
            f"--thoron-mail-feeds-for-testing=http://127.0.0.1:{gmail_port}/",
            f"--thoron-mail-imap-for-testing=127.0.0.1:{imap_port}",
            "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0", "about:blank"]
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def profile_text(profile: Path) -> str:
    """What the profile keeps as text: its settings files."""
    out = []
    for path in profile.rglob("*"):
        if path.is_file() and path.name in ("Preferences", "Secure Preferences", "Local State"):
            out.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(out)


class Page:
    """The M-Notifier's page in one start of the browser."""

    def __init__(self, browser: Path, profile: Path, gmail_port: int, imap_port: int):
        (profile / "DevToolsActivePort").unlink(missing_ok=True)
        self.proc = _launch(browser, profile, gmail_port, imap_port)
        try:
            self.port = _devtools_port(profile)
            self.ws = WebSocket(_open(self.port, MENU_URL)["webSocketDebuggerUrl"])
        except (OSError, RuntimeError, ValueError, KeyError):
            bench._stop(self.proc, profile)
            raise
        time.sleep(3)

    def ask(self, name: str, *args):
        """A message that is answered (sendWithPromise)."""
        reply = self.ws.call(
            "Runtime.evaluate", awaitPromise=True, returnByValue=True,
            expression="import('chrome://resources/js/cr.js').then((cr) => cr.sendWithPromise("
                       + ", ".join(json.dumps(a) for a in (name, *args)) + ")).then((v) => JSON.stringify(v))")
        return json.loads(reply.get("result", {}).get("value") or "null")

    def send(self, name: str, *args) -> None:
        self.ws.call("Runtime.evaluate", expression=f"chrome.send({json.dumps(name)}, {json.dumps(list(args))}); 1")
        time.sleep(0.6)

    def state(self) -> dict:
        reply = self.ws.call("Runtime.evaluate", expression=GET_STATE, awaitPromise=True, returnByValue=True)
        return json.loads(reply.get("result", {}).get("value") or "{}")

    def look(self) -> dict:
        self.send("checkNow")
        time.sleep(LOOK_S)
        return self.state()

    def wait_for_passwords(self) -> None:
        for _ in range(40):
            if self.state().get("canAddMailbox"):
                return
            time.sleep(0.25)

    def close(self) -> None:
        try:
            self.ws.close()
        except OSError:
            pass
        _close_browser(self.port, self.proc)


def run(browser: Path, work: Path) -> list[str]:
    profile = Path(tempfile.mkdtemp(prefix="mail-imap-", dir=work))
    problems: list[str] = []

    def report(name: str, found: list[str], detail) -> None:
        print(f"{'PASS' if not found else 'FAIL'}  {name}: {detail}")
        problems.extend(found)

    account = {"email": EMAIL, "password": PASSWORD, "host": "imap.example.com", "port": 993, "user": "", "webmail": ""}
    with Gmail() as gmail, ImapServer(EMAIL, PASSWORD) as imap:
        page = None
        try:
            page = Page(browser, profile, gmail.port, imap.port)
            page.wait_for_passwords()
            answer = page.ask("addImapAccount", dict(account, password="not-the-password"))
            state = page.look()
            report("refused", refused_problems(answer, state), f"answer {answer!r}, sign-ins {imap.logins}")

            answer = page.ask("addImapAccount", account)
            state = page.look()
            box = mailbox(state) or {}
            report("added", added_problems(answer, state),
                   f"answer {answer!r}, unread {box.get('unread')}, {len(box.get('latest', []))} messages read")

            time.sleep(1.5)  # the profile writes its settings a moment later
            report("secret", secret_problems(profile_text(profile), json.dumps(state)), "looked in the profile's files")

            imap.messages.append((16, imap_date(time.time() + 2), headers("gina@example.com", "Just in")))
            time.sleep(2.5)
            after = page.look()
            report("new", new_problems(state, after), f"sounds {state.get('sounds')} -> {after.get('sounds')}")

            page.send("openInbox", box.get("index", -1))
            report("seen", seen_problems(page.state()), "opened from the menu")
            page.close()

            page = Page(browser, profile, gmail.port, imap.port)
            page.wait_for_passwords()
            state = page.look()
            report("restart", restart_problems(state), f"the mailbox after a restart: {(mailbox(state) or {}).get('unread')} unread")

            sealed = page.ask("exportBackup", False, PASSPHRASE)
            bare = page.ask("exportBackup", False, "")
            plain = page.ask("exportBackup", True, "")
            page.send("removeImapAccount", EMAIL)
            time.sleep(1)
            answers = {"removed": mailbox(page.look()) is not None}
            answers["wrong"] = page.ask("importBackup", sealed, "not the passphrase")["error"]
            answers["none"] = page.ask("importBackup", sealed, "")["error"]
            changed = json.loads(sealed)
            changed["data"] = changed["data"][:-6] + ("AAAAAA" if not changed["data"].endswith("AAAAAA") else "BBBBBB")
            answers["changed"] = page.ask("importBackup", json.dumps(changed), PASSPHRASE)["error"]
            # a backup without passwords brings no mailbox back (it has no password for it here)
            got = page.ask("importBackup", bare, "")
            answers["bare"], answers["bare_boxes"] = got["error"], got["accounts"]
            got = page.ask("importBackup", sealed, PASSPHRASE)
            answers["right"], answers["right_boxes"] = got["error"], got["accounts"]
            back = page.look()
            report("backup", backup_problems(sealed, bare, plain, answers, back), answers)
            page.close()
            page = None
        except (OSError, RuntimeError, ValueError, KeyError, TypeError, IndexError) as e:
            problems.append(f"the run failed: {e}")
        finally:
            if page is not None:
                try:
                    page.close()
                except (OSError, RuntimeError):
                    bench._stop(page.proc, profile)
            shutil.rmtree(profile, ignore_errors=True)
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
    print("MAIL IMAP CHECK: PASSED" if not problems else f"MAIL IMAP CHECK: FAILED ({len(problems)} problem(s))")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
