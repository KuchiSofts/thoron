#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Thoron M-Notifier, Thoron's mail notifier, checked end to end and offline (ROADMAP P5.75, P5.76).

The notifier reads Gmail's feed of unread mail (mail.google.com/mail/u/N/feed/atom) of every Google account the
profile is signed in to. Here a local server stands in for Gmail (the browser is told so with a switch only a
local server is accepted for), with made-up accounts; nothing leaves the PC and no real account is used. The
notifier's menu is opened as a tab and asked for what it shows. Steps:

    accounts  the two accounts the server has are found, each with its unread count and newest messages, and
              the third address (no account there) ends the look; what was there at the first look is not new,
              and the settings have their defaults
    new       a message the server adds is found at the next look: the unread count goes up and it is new
    seen      the account's inbox opened from the menu: its new mail is counted from then (0 new, still unread)
    settings  a setting changes (and a value it does not know is refused), and an account not watched is not
              counted
    alerts    (P5.78) as it comes, the M-Notifier only counts: new mail made a sound and no notice; with the
              notice switched on and the sound off, the next new mail makes a notice and no sound
    which     (P5.77) what of Gmail is counted: only the Primary tab (its own feed), the inbox and spam (the
              spam's feed added, its messages marked), and the whole inbox again; where Gmail does not know
              the Primary tab's feed, the inbox is counted
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
import urllib.parse
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.qa import bench  # noqa: E402
from tools.qa.adblock_site_switch_check import _close_browser, _devtools_port, _open  # noqa: E402
from tools.qa.cdp import WebSocket  # noqa: E402

MENU_URL = "chrome://mail-notifier.top-chrome/"
LOOK_S = 4.0
DEFAULT_CHOICES = {"sound": "on", "count": "new", "open": "reuse", "messages": "off", "which": "inbox",
                   "place": "toolbar", "toolbar-position": "extensions", "address-position": "icons"}
# Gmail's label of the inbox's Primary tab, as its feed's address names it
PRIMARY = "^sq_ig_i_personal"


def now_utc() -> str:
    """A time a moment from now, as Gmail's feed writes it: mail that came after the first look."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 2))


def entry(n: int, subject: str, link: str = "", when: str = "") -> str:
    link = link or f"http://mail.google.com/mail/u/0?account_id=a&amp;message_id={n}&amp;view=conv&amp;extsrc=atom"
    when = when or f"2026-11-15T10:0{n}:00Z"
    return (f"<entry><title>{subject}</title><summary>Snippet {n}</summary>"
            f'<link rel="alternate" href="{link}" type="text/html" />'
            f"<modified>{when}</modified><issued>{when}</issued>"
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
        # the feeds of one label of an account: (index, label) -> answer; a label not here is not known (404)
        self.labels: dict[tuple[int, str], tuple[int, str]] = {}
        answers, labels = self.answers, self.labels

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_GET(self):
                status, body = 404, "no"
                parts = self.path.split("/")
                # /mail/u/<index>/feed/atom
                if len(parts) >= 6 and parts[1:3] == ["mail", "u"] and parts[4:6] == ["feed", "atom"]:
                    index = int(parts[3]) if parts[3].isdigit() else -1
                    if len(parts) > 6 and parts[6]:
                        status, body = labels.get((index, urllib.parse.unquote(parts[6])), (404, "no such label"))
                    else:
                        status, body = answers.get(index, (401, "sign in"))
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
    if state.get("totalNew") != 0 or any(a.get("new") for a in state.get("accounts", [])):
        out.append(f"accounts: mail there at the first look counts as new ({state.get('totalNew')})")
    if state.get("choices") != DEFAULT_CHOICES:
        out.append(f"accounts: the settings are {state.get('choices')}, not {DEFAULT_CHOICES}")
    if state.get("notify") is not False:
        out.append(f"accounts: notices are {state.get('notify')} before anyone asked for them")
    return out


def alerts_problems(first: dict, quiet: dict, loud: dict) -> list[str]:
    """`first`: after the first new mail, as the M-Notifier comes; `quiet`: before, `loud`: after new mail with
    the notice on and the sound off."""
    out = []
    if first.get("sounds") != 1 or first.get("notices") != 0:
        out.append(f"alerts: as it comes, new mail made {first.get('sounds')} sound(s) and "
                   f"{first.get('notices')} notice(s), not 1 and 0")
    if loud.get("sounds") != quiet.get("sounds") or loud.get("notices", 0) - quiet.get("notices", 0) != 1:
        out.append(f"alerts: with the notice on and the sound off, sounds went from {quiet.get('sounds')} to "
                   f"{loud.get('sounds')} and notices from {quiet.get('notices')} to {loud.get('notices')}")
    return out


def new_problems(state: dict) -> list[str]:
    accounts = state.get("accounts", [])
    if not accounts or accounts[0]["unread"] != 4 or len(accounts[0]["latest"]) != 3:
        return [f"new: after a new message, {[(a['email'], a['unread'], len(a['latest'])) for a in accounts]}"]
    marks = [bool(m.get("isNew")) for m in accounts[0]["latest"]]
    if accounts[0].get("new") != 1 or state.get("totalNew") != 1 or marks != [True, False, False]:
        return [f"new: {accounts[0].get('new')} new ({state.get('totalNew')} in all), marked {marks}, not 1 and "
                "[True, False, False]"]
    return []


def seen_problems(state: dict) -> list[str]:
    accounts = state.get("accounts", [])
    if not accounts or accounts[0].get("new") != 0 or state.get("totalNew") != 0 or accounts[0]["unread"] != 4:
        found = [(a["email"], a.get("new"), a["unread"]) for a in accounts]
        return [f"seen: after the inbox was opened, (address, new, unread) {found}, not 0 new and 4 unread"]
    return []


def settings_problems(changed: dict, refused: dict, unwatched: dict, back: dict) -> list[str]:
    out = []
    want = dict(DEFAULT_CHOICES, place="address", count="unread")
    if changed.get("choices") != want:
        out.append(f"settings: after a change they are {changed.get('choices')}, not {want}")
    if refused.get("choices") != want:
        out.append(f"settings: a value not known changed them to {refused.get('choices')}")
    first = (unwatched.get("accounts") or [{}])[0]
    if first.get("watched") is not False or unwatched.get("total") != 0 or unwatched.get("totalNew") != 0:
        out.append(f"settings: an account not watched: watched {first.get('watched')}, total "
                   f"{unwatched.get('total')}, not False and 0")
    if back.get("choices") != DEFAULT_CHOICES or back.get("total") != 4:
        out.append(f"settings: put back, they are {back.get('choices')} with {back.get('total')} unread")
    return out


def which_problems(primary: dict, everything: dict, unknown: dict, inbox: dict) -> list[str]:
    """Alice's inbox has 5 unread, its Primary tab 1, her spam 2."""
    def alice(state: dict) -> dict:
        return next((a for a in state.get("accounts", []) if a["email"] == "alice@example.com"), {})
    out = []
    if alice(primary).get("unread") != 1:
        out.append(f"which: only the Primary tab: {alice(primary).get('unread')} unread, not 1")
    spam = [m.get("subject") for m in alice(everything).get("latest", []) if m.get("spam")]
    if alice(everything).get("unread") != 7 or sorted(spam) != ["Prize", "Winner"]:
        out.append(f"which: the inbox and spam: {alice(everything).get('unread')} unread with spam {spam}, not 7 "
                   "with ['Prize', 'Winner']")
    if alice(unknown).get("unread") != 5:
        out.append(f"which: the Primary tab's feed not known: {alice(unknown).get('unread')} unread, not the "
                   "inbox's 5")
    if alice(inbox).get("unread") != 5 or any(m.get("spam") for m in alice(inbox).get("latest", [])):
        out.append(f"which: the whole inbox again: {alice(inbox).get('unread')} unread, not 5 without spam")
    return out


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

            def read() -> dict:
                reply = ws.call("Runtime.evaluate", expression=GET_STATE, awaitPromise=True, returnByValue=True)
                return json.loads(reply.get("result", {}).get("value") or "{}")

            def look() -> dict:
                ws.call("Runtime.evaluate", expression="chrome.send('checkNow'); 1")
                time.sleep(LOOK_S)
                return read()

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

            gmail.answers[0] = (200, feed("alice@example.com", 4, [entry(3, "New one", when=now_utc())] + alice))
            time.sleep(2.5)  # the new message came after the first look
            state = look()
            step("new", new_problems(state), state)
            first_new = state

            # the address pressed in the menu: its inbox opens (a tab that goes nowhere here: no network)
            ws.call("Runtime.evaluate", expression="chrome.send('openInbox', [0]); 1")
            time.sleep(1)
            state = read()
            step("seen", seen_problems(state), state)

            def send(name: str, *args) -> dict:
                ws.call("Runtime.evaluate", expression=f"chrome.send({json.dumps(name)}, {json.dumps(list(args))}); 1")
                time.sleep(0.5)
                return read()

            send("setChoice", "place", "address")
            changed = send("setChoice", "count", "unread")
            refused = send("setChoice", "place", "nowhere")
            unwatched = send("setWatched", "alice@example.com", False)
            send("setWatched", "alice@example.com", True)
            send("setChoice", "place", "toolbar")
            back = send("setChoice", "count", "new")
            step("settings", settings_problems(changed, refused, unwatched, back), back)

            send("setNotify", True)
            quiet = send("setChoice", "sound", "off")
            gmail.answers[0] = (200, feed("alice@example.com", 5, [entry(6, "Another", when=now_utc()),
                                                                   entry(3, "New one")] + alice))
            time.sleep(2.5)
            loud = look()
            send("setNotify", False)
            send("setChoice", "sound", "on")
            step("alerts", alerts_problems(first_new, quiet, loud), loud)

            def look_with(which: str) -> dict:
                send("setChoice", "which", which)
                return look()

            gmail.labels[(0, PRIMARY)] = (200, feed("alice@example.com", 1, [entry(6, "Another")]))
            gmail.labels[(1, PRIMARY)] = (200, feed("bob@example.com", 0, []))
            gmail.labels[(0, "spam")] = (200, feed("alice@example.com", 2, [entry(7, "Winner"), entry(8, "Prize")]))
            primary = look_with("primary")
            everything = look_with("all")
            gmail.labels.pop((0, PRIMARY))
            unknown = look_with("primary")
            inbox = look_with("inbox")
            step("which", which_problems(primary, everything, unknown, inbox), inbox)

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
