#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Thoron M-Notifier's settings page and its sounds, checked end to end and offline (ROADMAP P5.82).

A local server stands in for the mail server, with made-up mailboxes (`mail_imap_check.py`); nothing leaves the
PC and no real account is used. The sound is counted, not heard (the offline checks' switch), so what was
played and what was held back are read from the page's state. Steps:

    tabs       the page has its five tabs; each shows its own part and the address keeps it (#manage/alerts)
    settings   the menu's Settings button opens the page in a tab
    one list   every account is listed once on the page: two mailboxes and an account of the list, one of
               them in the list and a mailbox at once; no address shows twice
    sounds     Windows' own sound and ten made ones; each can be heard (played on asking); the sound and its
               volume chosen are kept
    own sound  an account with no sound of its own takes the one for all; one set to "no sound" stays quiet
               when its mail comes, the others play theirs
    quiet      in quiet hours no sound plays and no notice shows; without them it plays again
    backup     the backup holds the sound, the volume, the quiet rules and each account's own sound

    py -3 -I tools/qa/mail_settings_check.py --browser <out>\\thoron.exe --work <scratch dir>
Exit status 0 only when every step passes.
"""
import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.qa import bench  # noqa: E402
from tools.qa.mail_check import MENU_URL, Gmail  # noqa: E402
from tools.qa.mail_imap_check import ImapServer, headers, imap_date  # noqa: E402
from tools.qa.mail_manage_check import Page, mailbox_edit  # noqa: E402

A, PASSWORD_A = "carol@example.com", "made-up-pass-a1"
B, PASSWORD_B = "dave@example.org", "made-up-pass-b2"
LISTED = "erin@example.net"
MADE = ["chime", "bell", "marimba", "pop", "drops", "bright", "soft", "knock", "ding", "beeps"]
TABS = ["accounts", "alerts", "counting", "display", "backup"]


def tabs_problems(seen: dict) -> list[str]:
    out = []
    if seen.get("tabs") != TABS:
        out.append(f"tabs: the page's tabs are {seen.get('tabs')}, not {TABS}")
    for name in TABS:
        if seen.get(name) != [f"tab-{name}"]:
            out.append(f"tabs: with {name} chosen, the parts shown are {seen.get(name)}")
    if seen.get("address") != "#manage/backup":
        out.append(f"tabs: the address does not keep the tab: {seen.get('address')!r}")
    if seen.get("reloaded") != ["tab-alerts"]:
        out.append(f"tabs: #manage/alerts opened {seen.get('reloaded')}")
    return out


def settings_problems(urls_before: list, urls_after: list) -> list[str]:
    opened = [u for u in urls_after if u not in urls_before and "#manage" in u]
    return [] if opened else [f"settings: the menu's Settings button opened no page (tabs: {urls_after})"]


def list_problems(rows: list, text: str) -> list[str]:
    out = []
    if sorted(rows) != sorted([A, B, LISTED]):
        out.append(f"one list: the list holds {rows}, not each of {[A, B, LISTED]} once")
    for email in (A, B, LISTED):
        if text.count(email) != 1:
            out.append(f"one list: {email} shows {text.count(email)} times on the page, not once")
    return out


def sounds_problems(state: dict, heard: dict, kept: dict) -> list[str]:
    out = []
    names = state.get("sound", {}).get("names", [])
    if names != MADE:
        out.append(f"sounds: the made sounds are {names}, not {MADE}")
    for name in ["system", *MADE]:
        if heard.get(name) != name:
            out.append(f"sounds: asked to play {name}, the last sound was {heard.get(name)!r}")
    if (kept.get("name"), kept.get("volume")) != ("bell", 40):
        out.append(f"sounds: the sound chosen is kept as {(kept.get('name'), kept.get('volume'))}, not ('bell', 40)")
    return out


def own_problems(before: dict, after: dict) -> list[str]:
    b, a = before.get("sound", {}), after.get("sound", {})
    out = []
    if a.get("accounts") != {A: "off", B: "pop"}:
        out.append(f"own sound: the accounts' own sounds are {a.get('accounts')}")
    if after.get("sounds", 0) - before.get("sounds", 0) != 1 or a.get("last") != "pop":
        out.append(f"own sound: new mail at both made {after.get('sounds', 0) - before.get('sounds', 0)} sound(s), "
                   f"the last {a.get('last')!r}; not one, 'pop'")
    if a.get("held", 0) - b.get("held", 0) != 1 or a.get("lastQuiet") != "account":
        out.append(f"own sound: {a.get('held', 0) - b.get('held', 0)} sound(s) held, for {a.get('lastQuiet')!r}; "
                   "not one, for the account")
    return out


def quiet_problems(before: dict, during: dict, after: dict) -> list[str]:
    out = []
    held = during.get("sound", {}).get("held", 0) - before.get("sound", {}).get("held", 0)
    if during.get("sounds") != before.get("sounds") or held != 2 or during.get("sound", {}).get("lastQuiet") != "hours":
        out.append(f"quiet: in quiet hours {during.get('sounds', 0) - before.get('sounds', 0)} sound(s) played and "
                   f"{held} were held ({during.get('sound', {}).get('lastQuiet')!r}); not 0 and 2, for the hours")
    if during.get("notices") != before.get("notices"):
        out.append("quiet: in quiet hours a notice was shown")
    if after.get("sounds", 0) - during.get("sounds", 0) != 2:
        out.append(f"quiet: without quiet hours {after.get('sounds', 0) - during.get('sounds', 0)} sound(s), not 2")
    return out


def backup_problems(backup: str) -> list[str]:
    try:
        sound = json.loads(backup).get("settings", {}).get("sound", {})
    except ValueError:
        return ["backup: the backup is not JSON"]
    want = {"name": "bell", "volume": 40, "accounts": {A: "off", B: "pop"}}
    got = {k: sound.get(k) for k in want}
    out = [] if got == want else [f"backup: its sound is {got}, not {want}"]
    if not {"quietFullscreen", "quietInFront", "quietFrom", "quietTo"} <= set(sound):
        out.append(f"backup: the quiet rules are not in it ({sorted(sound)})")
    return out


TAB_SCRIPT = """(async () => {
  const shown = () => [...document.querySelectorAll('#page .panel')].filter((p) => !p.hidden).map((p) => p.id);
  const tabs = [...document.querySelectorAll('#tabs [role=tab]')];
  const out = {tabs: tabs.map((tab) => tab.dataset.tab)};
  for (const tab of tabs) {
    tab.click();
    await new Promise((done) => setTimeout(done, 150));
    out[tab.dataset.tab] = shown();
  }
  out.address = location.hash;
  return JSON.stringify(out);
})()"""


def run(browser: Path, work: Path) -> list[str]:
    profile = Path(tempfile.mkdtemp(prefix="mail-settings-", dir=work))
    problems: list[str] = []

    def report(name: str, found: list[str], detail) -> None:
        print(f"{'PASS' if not found else 'FAIL'}  {name}: {detail}")
        problems.extend(found)

    uid = [20]

    def new_mail(imap) -> None:
        uid[0] += 1
        imap.messages.append((uid[0], imap_date(time.time() + 2), headers("gina@example.com", f"Note {uid[0]}")))
        time.sleep(2.5)

    with Gmail() as gmail, ImapServer(A, PASSWORD_A) as imap:
        imap.users[B] = PASSWORD_B
        page = None
        try:
            page = Page(browser, profile, gmail.port, imap.port, work / "unused.json")
            page.wait_for_passwords()
            for email, password in ((A, PASSWORD_A), (B, PASSWORD_B)):
                if page.ask("addImapAccount", mailbox_edit("", email, password)):
                    raise RuntimeError(f"the mailbox {email} was not added")
            # an account of the list, and one of the mailboxes in the list as well
            page.ask("importGoogleAccounts", [{"email": LISTED, "alias": "", "password": ""},
                                              {"email": A, "alias": "", "password": ""}])
            page.look()
            page.send("setNotify", True)

            seen = json.loads(page.run(TAB_SCRIPT) or "{}")
            page.run("location.hash = '#manage/alerts'; location.reload(); 1")
            time.sleep(2.5)
            seen["reloaded"] = page.run("JSON.stringify([...document.querySelectorAll('#page .panel')]"
                                        ".filter((p) => !p.hidden).map((p) => p.id))")
            seen["reloaded"] = json.loads(seen["reloaded"] or "[]")
            report("tabs", tabs_problems(seen), seen)

            page.run("location.hash = '#manage/accounts'; 1")
            time.sleep(0.8)
            rows = json.loads(page.run("JSON.stringify([...document.querySelectorAll('#list .item')]"
                                       ".map((item) => item.dataset.email))") or "[]")
            text = page.run("document.body.innerText") or ""
            report("one list", list_problems(rows, text), rows)

            before = [t.get("url", "") for t in json.loads(open_pages(page.port))]
            page.run(f"location.href = {json.dumps(MENU_URL)}; 1")
            time.sleep(2.5)
            page.run("document.getElementById('gear').click(); 1")
            time.sleep(2.0)
            after = [t.get("url", "") for t in json.loads(open_pages(page.port))]
            report("settings", settings_problems(before, after), [u for u in after if "mail-notifier" in u])
            # back to the page (a change of the part after # alone would not load it again)
            page.run(f"location.replace({json.dumps(MENU_URL + '#manage')}); location.reload(); 1")
            time.sleep(2.5)

            heard = {}
            for name in ["system", *MADE]:
                page.send("previewSound", name, 50)
                heard[name] = page.state().get("sound", {}).get("last")
            page.send("setSound", "bell", 40)
            state = page.state()
            report("sounds", sounds_problems(state, heard, state.get("sound", {})),
                   f"{len(state.get('sound', {}).get('names', []))} made sounds, kept {state.get('sound', {}).get('name')}")

            page.send("setAccountSound", A, "off")
            page.send("setAccountSound", B, "pop")
            before_state = page.state()
            new_mail(imap)
            after_state = page.look()
            report("own sound", own_problems(before_state, after_state),
                   f"sounds {before_state.get('sounds')} -> {after_state.get('sounds')}, "
                   f"last {after_state.get('sound', {}).get('last')!r}")

            page.send("setAccountSound", A, "")
            now = time.localtime()
            minute = now.tm_hour * 60 + now.tm_min
            page.send("setQuiet", {"fullscreen": True, "front": True, "from": (minute - 30) % 1440,
                                   "to": (minute + 30) % 1440})
            before_state = page.state()
            new_mail(imap)
            during = page.look()
            page.send("setQuiet", {"fullscreen": True, "front": True, "from": -1, "to": -1})
            new_mail(imap)
            after_state = page.look()
            report("quiet", quiet_problems(before_state, during, after_state),
                   f"held {before_state.get('sound', {}).get('held')} -> {during.get('sound', {}).get('held')}, "
                   f"sounds after {after_state.get('sounds')}")

            page.send("setAccountSound", A, "off")
            report("backup", backup_problems(page.ask("exportBackup", False, "")), "the sound settings in the backup")
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
    return problems


def open_pages(port: int) -> str:
    """The browser's open pages, from its DevTools endpoint (127.0.0.1)."""
    import urllib.request
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=10) as reply:
        return reply.read().decode("utf-8")


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
    print("MAIL SETTINGS CHECK: PASSED" if not problems else
          f"MAIL SETTINGS CHECK: FAILED ({len(problems)} problem(s))")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
