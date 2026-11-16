#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Thoron M-Notifier's envelope, where it is and what it says, checked end to end and offline (ROADMAP P5.76).
Windows only.

The envelope is next to the address bar (in the toolbar), in the address bar, or in both, where the person
chooses, as Thoron adblock's shield. The toolbar and the address bar are part of the window, which a headless
browser does not draw, so this check runs the browser with a window placed off the screen and finds the
envelopes with Windows UI Automation (their names follow what they say). A local server stands in for Gmail
(as in mail_check.py) with a made-up account; nothing leaves the PC. The M-Notifier's menu is opened as a tab
and its settings are changed there as a person does. Steps:

    place     in the toolbar only (the default), in the address bar only, and in both
    says      the envelope says how much mail there is: unread mail there at the first look is not new; a new
              message is; opening the account's inbox counts the new mail from then
    position  where in the toolbar (right after the address bar, next to the menu, after the extensions) and
              where in the address bar (at the far end, before the other icons, with them); the order of the
              buttons shows it

    py -3 -I tools/qa/mail_place_check.py --browser <out>\\thoron.exe --work <scratch dir>
Exit status 0 when every step passes (or the check does not apply, on another system).
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
from tools.qa.adblock_icon_check import _row, toolbar_buttons  # noqa: E402
from tools.qa.adblock_site_switch_check import _close_browser, _devtools_port, _open  # noqa: E402
from tools.qa.cdp import WebSocket  # noqa: E402
from tools.qa.mail_check import GET_STATE, MENU_URL, Gmail, entry, feed, now_utc  # noqa: E402

# what an envelope says, and so its name ("Thoron M-Notifier: 1 new, 4 unread"); the menu's tab is named
# "Thoron M-Notifier" too, but only buttons count
NAME = "Thoron M-Notifier"
PLACES = ("address", "both", "toolbar")
# where in the toolbar and in the address bar, in the order the check sets them; the last of each is its default
POSITIONS = (("toolbar-position", "address"), ("toolbar-position", "menu"), ("toolbar-position", "extensions"),
             ("address-position", "end"), ("address-position", "start"), ("address-position", "icons"))
SETTLE_S = 1.5
LOOK_S = 4.0


def envelopes(buttons: list[dict]) -> tuple[dict | None, dict | None]:
    """The address bar's envelope (as tall as the address bar's icons) and the toolbar's (as tall as its
    buttons)."""
    found = [b for b in buttons if b["name"].startswith(NAME)]
    return (next((b for b in found if b["h"] < 30), None), next((b for b in found if b["h"] >= 30), None))


def place_problems(place: str, address: dict | None, toolbar: dict | None) -> list[str]:
    want = {"toolbar": (False, True), "address": (True, False), "both": (True, True)}[place]
    if (address is not None, toolbar is not None) != want:
        return [f"place: {place!r}, but there is an envelope in the address bar: {address is not None}, in the "
                f"toolbar: {toolbar is not None}"]
    return []


def says_problems(step: str, name: str, want: str) -> list[str]:
    return [] if name == want else [f"says: {step}: the envelope says {name!r}, not {want!r}"]


def position_problems(setting: str, value: str, buttons: list[dict]) -> list[str]:
    address, toolbar = envelopes(buttons)
    if setting == "toolbar-position":
        if not toolbar:
            return [f"position: no envelope in the toolbar with {setting} {value!r}"]
        # the toolbar's buttons right of the address bar (the window's own buttons are on another line)
        right = [b for b in _row(buttons, toolbar) if b["h"] >= 30 and (not address or b["x"] > address["x"])]
        names = [b["name"][:22] for b in right]
        at = right.index(toolbar)
        if value == "address" and at != 0:
            return [f"position: 'right after the address bar', but the envelope is button {at + 1} ({names})"]
        if value == "menu" and at != len(right) - 2:
            return [f"position: 'next to the menu', but the envelope is not right before it ({names})"]
        if value == "extensions" and at == len(right) - 1:
            return [f"position: 'after the extensions', but the envelope is last ({names})"]
        return []
    if not address:
        return [f"position: no envelope in the address bar with {setting} {value!r}"]
    # the address bar's icons at its end, with the envelope: its security chip (at the other end, past the
    # address) is not one of them
    icons = trailing_icons([b for b in _row(buttons, address) if b["h"] < 30 and b["w"] <= 40], address)
    names = [b["name"][:22] for b in icons]
    at = icons.index(address)
    if value == "end" and at != len(icons) - 1:
        return [f"position: 'at the far end', but the envelope is icon {at + 1} of {len(icons)} ({names})"]
    if value == "start" and at != 0:
        return [f"position: 'before the other icons', but the envelope is icon {at + 1} ({names})"]
    if value == "icons" and len(icons) > 1 and at == len(icons) - 1:
        return [f"position: 'with the other icons', but the envelope is at the far end ({names})"]
    return []


def trailing_icons(icons: list[dict], envelope: dict) -> list[dict]:
    """The icons next to each other (at most 40 px apart) with the envelope among them, left to right."""
    group: list[dict] = []
    groups = [group]
    for icon in sorted(icons, key=lambda b: b["x"]):
        if group and icon["x"] - (group[-1]["x"] + group[-1]["w"]) > 40:
            group = []
            groups.append(group)
        group.append(icon)
    return next((g for g in groups if envelope in g), [envelope])


def _launch(browser: Path, profile: Path, gmail_port: int) -> subprocess.Popen:
    args = [str(browser), f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
            "--disable-default-apps", "--disable-background-networking", "--disable-component-update",
            "--enable-features=ThoronMailNotifier", "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
            f"--thoron-mail-feeds-for-testing=http://127.0.0.1:{gmail_port}/",
            # off the screen: the check needs a real window, not the person's attention
            "--window-position=-4000,-4000", "--window-size=1000,700",
            "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0", "about:blank"]
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run(browser: Path, work: Path) -> list[str]:
    profile = Path(tempfile.mkdtemp(prefix="mail-place-", dir=work))
    problems: list[str] = []
    with Gmail() as gmail:
        old = [entry(1, "Hello"), entry(2, "Lunch")]
        gmail.answers[0] = (200, feed("alice@example.com", 3, old))
        proc = _launch(browser, profile, gmail.port)
        port = None
        ws = None
        try:
            port = _devtools_port(profile)
            ws = WebSocket(_open(port, MENU_URL)["webSocketDebuggerUrl"])
            time.sleep(3)

            def send(name: str, *args) -> None:
                ws.call("Runtime.evaluate", expression=f"chrome.send({json.dumps(name)}, {json.dumps(list(args))}); 1")
                time.sleep(SETTLE_S)

            def state() -> dict:
                reply = ws.call("Runtime.evaluate", expression=GET_STATE, awaitPromise=True, returnByValue=True)
                return json.loads(reply.get("result", {}).get("value") or "{}")

            def report(name: str, found: list[str], detail: str) -> None:
                print(f"{'PASS' if not found else 'FAIL'}  {name}: {detail}")
                problems.extend(found)

            for place in PLACES:
                send("setChoice", "place", place)
                address, toolbar = envelopes(toolbar_buttons(proc.pid))
                report("place", place_problems(place, address, toolbar),
                       f"{place}: address bar {address is not None}, toolbar {toolbar is not None}")

            send("checkNow")
            time.sleep(LOOK_S)

            def name() -> str:
                return (envelopes(toolbar_buttons(proc.pid))[1] or {}).get("name", "")

            report("says", says_problems("first look", name(), f"{NAME}: 3 unread"), name())
            gmail.answers[0] = (200, feed("alice@example.com", 4, [entry(3, "New one", when=now_utc())] + old))
            time.sleep(2.5)  # the new message came after the first look
            send("checkNow")
            time.sleep(LOOK_S)
            report("says", says_problems("a new message", name(), f"{NAME}: 1 new, 4 unread"), name())
            send("openInbox", 0)
            report("says", says_problems("the inbox opened", name(), f"{NAME}: 4 unread"), name())

            send("setChoice", "place", "both")
            for setting, value in POSITIONS:
                send("setChoice", setting, value)
                buttons = toolbar_buttons(proc.pid)
                found = position_problems(setting, value, buttons)
                report("position", found, f"{setting} {value}")
            send("setChoice", "place", "toolbar")
            if state().get("choices", {}).get("place") != "toolbar":
                problems.append("position: the envelope's place was not put back")
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
    if sys.platform != "win32":
        print("MAIL PLACE CHECK: does not apply here (Windows only)")
        return 0
    a.work.mkdir(parents=True, exist_ok=True)
    problems = run(a.browser.resolve(), a.work)
    for problem in problems:
        print(problem)
    print("MAIL PLACE CHECK: PASSED" if not problems else f"MAIL PLACE CHECK: FAILED ({len(problems)} problem(s))")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
