#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Thoron's mail notifier, checked end to end and offline (ROADMAP P5.75).

The notifier reads Gmail's feed of unread mail (mail.google.com/mail/u/N/feed/atom) of every Google account the
profile is signed in to. Here a local server stands in for Gmail (the browser is told so with a switch only a
local server is accepted for), with made-up accounts; nothing leaves the PC and no real account is used. The
notifier's menu is opened as a tab and asked for what it shows. Steps:

    accounts  the two accounts the server has are found, each with its unread count and newest messages, and
              the third address (no account there) ends the look
    new       a message the server adds is found at the next look, and the count goes up
    links     a message whose link leads off Gmail is shown without the link
    out       an answer of 401 for the first account (no sign-in) is told as "signed-out", with no account
    broken    a feed that is not XML leaves the notifier working (no account, no crash), and it reads the next

    py -3 -I tools/qa/mail_check.py --browser <out>\\thoron.exe --work <scratch dir>
Exit status 0 only when every step passes.
"""
import argparse
import http.server
import json
import shutil
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

MENU_URL = "chrome://mail-notifier.top-chrome/"
LOOK_S = 4.0


def entry(n: int, subject: str, link: str = "") -> str:
    link = link or f"http://mail.google.com/mail/u/0?account_id=a&amp;message_id={n}&amp;view=conv&amp;extsrc=atom"
    return (f"<entry><title>{subject}</title><summary>Snippet {n}</summary>"
            f'<link rel="alternate" href="{link}" type="text/html" />'
            f"<modified>2026-11-15T10:0{n}:00Z</modified><issued>2026-11-15T10:0{n}:00Z</issued>"
            f"<id>tag:gmail.google.com,2004:{1000 + n}</id>"
            f"<author><name>Sender {n}</name><email>sender{n}@example.com</email></author></entry>")


def feed(email: str, count: int, entries: list[str]) -> str:
    return ('<?xml version="1.0" encoding="UTF-8"?><feed version="0.3" xmlns="http://purl.org/atom/ns#">'
            f"<title>Gmail - Inbox for {email}</title><tagline>New messages in your Gmail Inbox</tagline>"
            f"<fullcount>{count}</fullcount>" + "".join(entries) + "</feed>")


class Gmail:
    """A stand-in for Gmail's feeds: what each account index answers, changed by the steps."""

    def __init__(self):
        self.answers: dict[int, tuple[int, str]] = {}
        answers = self.answers

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_GET(self):
                status, body = 404, "no"
                parts = self.path.split("/")
                # /mail/u/<index>/feed/atom
                if len(parts) >= 6 and parts[1:3] == ["mail", "u"] and parts[4:6] == ["feed", "atom"]:
                    status, body = answers.get(int(parts[3]) if parts[3].isdigit() else -1, (401, "sign in"))
                data = body.encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/atom+xml" if status == 200 else "text/plain")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self._httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._httpd.daemon_threads = True
        self.port = self._httpd.server_address[1]

    def __enter__(self):
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self._httpd.shutdown()
        self._httpd.server_close()


def accounts_problems(state: dict) -> list[str]:
    got = [(a["email"], a["unread"], len(a["latest"])) for a in state.get("accounts", [])]
    want = [("alice@example.com", 3, 2), ("bob@example.com", 0, 0)]
    out = [] if got == want else [f"accounts: found {got}, not {want}"]
    if state.get("total") != 3:
        out.append(f"accounts: the total is {state.get('total')}, not 3")
    latest = state.get("accounts", [{}])[0].get("latest", []) if state.get("accounts") else []
    if latest and (latest[0].get("from") != "Sender 1" or not latest[0].get("link", "").startswith("https://")):
        out.append(f"accounts: the first message reads {latest[0]}")
    return out


def new_problems(state: dict) -> list[str]:
    accounts = state.get("accounts", [])
    if not accounts or accounts[0]["unread"] != 4 or len(accounts[0]["latest"]) != 3:
        return [f"new: after a new message, {[(a['email'], a['unread'], len(a['latest'])) for a in accounts]}"]
    return []


def links_problems(state: dict) -> list[str]:
    accounts = state.get("accounts", [])
    links = [m.get("link") for m in (accounts[0]["latest"] if accounts else []) if m.get("subject") == "Elsewhere"]
    if links != [""]:
        return [f"links: a link off Gmail is shown as {links}"]
    return []


def out_problems(state: dict) -> list[str]:
    if state.get("accounts") or state.get("problem") != "signed-out":
        return [f"out: without a sign-in: {len(state.get('accounts', []))} account(s), problem "
                f"{state.get('problem')!r}"]
    return []


def broken_problems(broken: dict, after: dict) -> list[str]:
    out = []
    if broken.get("accounts"):
        out.append("broken: a feed that is not XML gave an account")
    if not after.get("accounts"):
        out.append("broken: the notifier did not read a good feed after a broken one")
    return out


GET_STATE = ("import('chrome://resources/js/cr.js').then((cr) => cr.sendWithPromise('getMailState'))"
             ".then((s) => JSON.stringify(s))")


def run(browser: Path, work: Path) -> list[str]:
    profile = Path(tempfile.mkdtemp(prefix="mail-", dir=work))
    problems: list[str] = []
    with Gmail() as gmail:
        args = [str(browser), "--headless=new", f"--user-data-dir={profile}", "--no-first-run",
                "--no-default-browser-check", "--disable-background-networking", "--disable-component-update",
                "--enable-features=ThoronMailNotifier", "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
                f"--thoron-mail-feeds-for-testing=http://127.0.0.1:{gmail.port}/",
                "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0", "about:blank"]
        proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        port = None
        ws = None
        try:
            port = _devtools_port(profile)
            ws = WebSocket(_open(port, MENU_URL)["webSocketDebuggerUrl"])
            time.sleep(3)

            def look() -> dict:
                ws.call("Runtime.evaluate", expression="chrome.send('checkNow'); 1")
                time.sleep(LOOK_S)
                reply = ws.call("Runtime.evaluate", expression=GET_STATE, awaitPromise=True, returnByValue=True)
                return json.loads(reply.get("result", {}).get("value") or "{}")

            def step(name: str, found: list[str], state: dict) -> None:
                print(f"{'PASS' if not found else 'FAIL'}  {name}: "
                      f"{[(a['email'], a['unread']) for a in state.get('accounts', [])]} "
                      f"problem {state.get('problem')!r}")
                problems.extend(found)

            alice = [entry(1, "Hello"), entry(2, "Lunch")]
            gmail.answers[0] = (200, feed("alice@example.com", 3, alice))
            gmail.answers[1] = (200, feed("bob@example.com", 0, []))
            state = look()
            step("accounts", accounts_problems(state), state)

            gmail.answers[0] = (200, feed("alice@example.com", 4, [entry(3, "New one")] + alice))
            state = look()
            step("new", new_problems(state), state)

            gmail.answers[0] = (200, feed("alice@example.com", 1, [entry(4, "Elsewhere", "https://ads.example.test/x")]))
            state = look()
            step("links", links_problems(state), state)

            gmail.answers.pop(0)
            gmail.answers.pop(1)
            state = look()
            step("out", out_problems(state), state)

            gmail.answers[0] = (200, "<feed><title>Gmail - Inbox for broken@example.com<")
            broken = look()
            gmail.answers[0] = (200, feed("alice@example.com", 1, [entry(5, "Back")]))
            after = look()
            step("broken", broken_problems(broken, after), after)
        except (OSError, RuntimeError, ValueError, KeyError, TypeError, IndexError) as e:
            problems.append(f"the run failed: {e}")
        finally:
            if ws:
                try:
                    ws.close()
                except OSError:
                    pass
            if port is not None:
                _close_browser(port, proc)
            else:
                bench._stop(proc, profile)
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
    print("MAIL CHECK: PASSED" if not problems else f"MAIL CHECK: FAILED ({len(problems)} problem(s))")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
