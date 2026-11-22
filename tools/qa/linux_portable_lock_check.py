#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""A Linux portable copy locked with a passphrase, end to end (ROADMAP P4.9 on Linux). Run on Windows.

On a clean Ubuntu test machine of tools/qa/wsl_test_vm.py, the user `tester` unpacks the portable package and starts
it through its own launcher, headless, in a D-Bus session with GNOME's keyring (unlocked with a made-up password).
The launcher's question is answered by a stand-in for zenity that types made-up answers and writes down what it was
asked. Steps:

    seed       an unlocked copy saves a password (GNOME's key, "v11") and a cookie; closed, a second password with
               Chromium's fixed key ("v10") goes into its Login Data, as a browser without a keyring writes it
    lock       chrome://thoron-portable locks the copy: a recovery key shown and confirmed, the key file written, the
               copy marked as locked with its values still to be encrypted again; the values are as they were
    wrong      a wrong passphrase: the browser stops without starting, the launcher asks again, and quitting the
               question ends it; nothing changed
    unlock     the passphrase opens the copy: both passwords and the cookie read back in the browser; then every
               value in the databases is encrypted with the copy's key ("t10"), no checked copy of a database is
               left, nothing is pending, and no value is in a file as it is
    second     a second start while the copy is open asks nothing and is left to Chromium's own singleton (0 when
               the open browser takes it; 21, profile in use, when a headless one does not answer), never a second
               browser on the same profile
    recovery   the recovery key, typed as a person might (small letters, no dashes), opens the copy
    remember   the page remembers this PC in the user's keyring (one item there): the next start asks nothing and the
               passwords read; the page forgets it: the start after asks again, and the keyring's item is gone
    change     the page changes the passphrase: the old one is refused, the new one opens the copy
    tampered   a changed byte in the key file opens nothing (the passphrase is refused, nothing starts); a damaged
               key file stops the browser at once and the launcher shows why
    forged     Local State edited to ask for the lock's removal without the page's proof: the next start (with the
               passphrase) drops the request, the lock stays and the values stay under the copy's key
    remove     the page removes the lock with the passphrase: the next start (with the passphrase once more) puts
               every value back under Chromium's fixed key ("v10", which every Linux build reads), removes the key
               file, keeps the copy's key only for reading (Local State's former key) and no checked copy is left;
               the start after asks nothing, and both passwords and the cookie read
    relock     locked again: the lock takes the former key again (Local State keeps it no longer), and the start
               after it with the passphrase encrypts the values again; both passwords and the cookie read
    taken      the key file taken away and Local State edited to say "not locked": the browser finds the lock's values
               and stops (82), the launcher asks at once with the browser's reason, and "start without them" sets
               the locked databases aside (kept, not deleted) and starts the copy
    missing    locked again, then without its key file: the launcher asks first; "start without them" starts the
               copy unlocked

    py -3 -I tools/qa/linux_portable_lock_check.py --archive <thoron-*-linux-x64-*-portable.tar.xz>
        --deb <thoron-browser_*.deb> --root <test machines folder> --work <scratch> [--machine thoron-test-2604]
(The .deb only brings the libraries the browser needs, as a desktop has them, and is removed again.)
Exit status 0 only when every step passes.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

if __package__ in (None, ""):  # running as a script: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

REPO = Path(__file__).resolve().parents[2]
STEPS = ("seed", "lock", "wrong", "unlock", "second", "recovery", "remember", "change", "tampered", "forged",
         "remove", "relock", "taken", "missing")
PASSPHRASE = "violet harbour lantern seven"
NEW_PASSPHRASE = "quiet orchard copper ninety"
KEY_FILE = "Thoron Portable Key"
BACKUP_SUFFIX = ".thoron-before-lock"
KEYRING_PASSWORD = {"url": "https://example.org/login", "username": "thoron-lock-keyring",
                    "password": "made-up-lock-keyring-secret"}
# the second password (Chromium's fixed key, "v10"), as the settings import check writes it into Login Data
from tools.qa.linux_settings_import_check import FIXED_PASSWORD  # noqa: E402
COOKIE = {"name": "thoron_lock", "value": "made-up-lock-cookie-value", "domain": "example.org"}
ARGS = ["--headless=new", "--no-first-run", "--no-default-browser-check", "--password-store=gnome-libsecret",
        "--disable-background-networking", "--disable-component-update",
        "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0", "about:blank"]
PAGE_URL = "chrome://thoron-portable/"
# where Chromium keeps the encrypted values (components/thoron_portable_key/reencrypt_linux.cc)
VALUES = (("Login Data", "logins", "password_value"), ("Login Data", "password_notes", "value"),
          ("Network/Cookies", "cookies", "encrypted_value"), ("Cookies", "cookies", "encrypted_value"))

SCRIPT = r"""#!/bin/bash
# As root inside a clean test machine: $1 work folder, $2 the portable .tar.xz, $3 the .deb (for its dependencies),
# $4 tools
set -u
W="$1"; ARCHIVE="$2"; DEB="$3"; TOOLS="$4"
out="$W/out"; rm -rf "$out"; mkdir -p "$out"; chmod 777 "$out"
export DEBIAN_FRONTEND=noninteractive
cp "$DEB" /tmp/thoron.deb
apt-get update -qq > /dev/null 2>&1
apt-get install -y -qq /tmp/thoron.deb dbus-x11 gnome-keyring libsecret-tools > "$out/apt-deps.txt" 2>&1
echo $? > "$out/deps_exit"
dpkg -r thoron-browser >> "$out/apt-deps.txt" 2>&1
runuser -u tester -- mkdir -p /home/tester/Downloads/thoron
runuser -u tester -- tar -xf "$ARCHIVE" -C /home/tester/Downloads/thoron
# the user's own runtime folder (root's would be inherited, and GNOME's keyring cannot start in it)
install -d -m 700 -o tester -g tester /tmp/xdg-tester
runuser -u tester -- env HOME=/home/tester XDG_RUNTIME_DIR=/tmp/xdg-tester XDG_CURRENT_DESKTOP=GNOME     dbus-run-session -- bash -c "
    eval \$(printf 'made-up-keyring-password' | gnome-keyring-daemon --unlock --components=secrets)
    export GNOME_KEYRING_CONTROL SSH_AUTH_SOCK
    python3 -I '$TOOLS/qa/linux_portable_lock_check.py' probe --tools '$TOOLS' \
      --package /home/tester/Downloads/thoron/ThoronPortable --out '$out/probe.json' > '$out/probe.txt' 2>&1
  "
echo done > "$out/reached"
"""

# a zenity that types the next line of $TYPED (none left: it is quit) and writes down what it was asked; a question
# ("start without them") is answered yes
FAKE_ZENITY = """#!/bin/sh
printf 'ZENITY' >> "$ZENITY_LOG"; for a in "$@"; do printf ' [%s]' "$a" >> "$ZENITY_LOG"; done; echo >> "$ZENITY_LOG"
case "$*" in *--entry*) ;; *) exit 0 ;; esac
line=$(head -n 1 "$TYPED")
[ -n "$line" ] || exit 1
sed -i 1d "$TYPED"
printf '%s\\n' "$line"
"""


# ----- pure parts, tested on Windows ------------------------------------------------------------------------------

def tag_of(value: bytes) -> str:
    """The three bytes before an encrypted value: "v10", "v11" (Chromium's keys) or "t10" (the copy's own)."""
    return value[:3].decode("ascii", "replace") if len(value) > 3 else ""


def tags_problems(tags: dict[str, list[str]], want: set[str]) -> list[str]:
    """Values whose tag is not one of `want`, by database column."""
    out = []
    for place, found in sorted(tags.items()):
        bad = sorted(set(found) - want)
        if bad:
            out.append(f"{place}: {len(found)} value(s), tags {sorted(set(found))}, not {sorted(want)}")
    return out


def asked(zenity_log: list[str], kind: str) -> int:
    """How many times the stand-in zenity was asked for `kind` (--entry, --error, --question)."""
    return sum(1 for line in zenity_log if f"[{kind}]" in line)


def flipped(data: bytes, at: int = 30) -> bytes:
    """The key file with one bit changed inside the passphrase lock's salt."""
    changed = bytearray(data)
    changed[at] ^= 0x01
    return bytes(changed)


# ----- inside the test machine -------------------------------------------------------------------------------

class Copy:
    """The unpacked portable package and its launcher, started with the stand-in zenity."""

    def __init__(self, package: Path, work: Path):
        self.package, self.data = package, package / "User Data"
        self.bin = work / "fake-bin"
        self.bin.mkdir(parents=True, exist_ok=True)
        (self.bin / "zenity").write_text(FAKE_ZENITY)
        (self.bin / "zenity").chmod(0o755)
        self.typed, self.zenity_log, self.output = work / "typed", work / "zenity.log", work / "launcher.log"
        self.zenity_log.write_text("")
        self.env = dict(os.environ, PATH=f"{self.bin}:/usr/bin:/bin", DISPLAY=":99", TYPED=str(self.typed),
                        ZENITY_LOG=str(self.zenity_log))

    def launch(self, typed: list[str]) -> subprocess.Popen:
        self.typed.write_text("".join(f"{t}\n" for t in typed))
        (self.data / "DevToolsActivePort").unlink(missing_ok=True)
        with open(self.output, "ab") as log:
            return subprocess.Popen([str(self.package / "thoron"), *ARGS], env=self.env, stdout=log,
                                    stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)

    def started(self, proc: subprocess.Popen, timeout: float = 240) -> bool:
        """True once the browser runs (DevTools is up), False when the launcher ended first."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            port = self.data / "DevToolsActivePort"
            if port.is_file() and port.read_text().split():
                return True
            if proc.poll() is not None:
                return False
            time.sleep(0.5)
        raise RuntimeError("the browser neither started nor ended")

    def zenity(self) -> list[str]:
        return self.zenity_log.read_text().splitlines()

    def open(self, typed: list[str]):
        proc = self.launch(typed)
        if not self.started(proc):
            raise RuntimeError(f"the copy did not start (exit {proc.returncode})")
        return Opened(proc, self.data)

    def values(self) -> dict[str, list[bytes]]:
        import sqlite3
        out: dict[str, list[bytes]] = {}
        for file, table, column in VALUES:
            path = self.data / "Default" / file
            if not path.is_file():
                continue
            db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                    out[f"{file}:{table}.{column}"] = [bytes(r[0]) for r in db.execute(
                        f"SELECT {column} FROM {table}") if r[0]]
            finally:
                db.close()
        return out

    def tags(self) -> dict[str, list[str]]:
        return {place: [tag_of(v) for v in found] for place, found in self.values().items()}

    def local_state(self) -> dict:
        return json.loads((self.data / "Local State").read_text(encoding="utf-8")).get("thoron_portable", {})

    def edit_local_state(self, **changes) -> None:
        """What someone holding the drive can do: Local State is plain JSON."""
        path = self.data / "Local State"
        state = json.loads(path.read_text(encoding="utf-8"))
        state.setdefault("thoron_portable", {}).update(changes)
        path.write_text(json.dumps(state), encoding="utf-8")

    def keyring_items(self) -> int:
        """The copy's "remember this PC" items in the user's keyring."""
        # bytes: secret-tool also prints each item's secret, which here is a random key, not text
        found = subprocess.run(["secret-tool", "search", "--all", "application", "thoron-portable"],
                               capture_output=True, timeout=30)
        return sum(1 for line in (found.stdout + found.stderr).splitlines() if line.startswith(b"[/"))

    def leftovers(self) -> list[str]:
        return sorted(str(p.relative_to(self.data)) for p in self.data.rglob(f"*{BACKUP_SUFFIX}"))

    def plain_in_files(self) -> list[str]:
        secrets = [KEYRING_PASSWORD["password"], FIXED_PASSWORD["password"], COOKIE["value"]]
        out = []
        for file, _, _ in VALUES:
            for path in (self.data / "Default").glob(file + "*"):
                if path.is_file() and any(s.encode() in path.read_bytes() for s in secrets):
                    out.append(path.name)
        return sorted(set(out))


def _browser_class():
    from tools.qa.linux_keyring_check import Browser

    class Opened(Browser):
        """A browser the launcher started: DevTools on its password page."""

        def __init__(self, proc, profile: Path):  # noqa: D107 - Browser's start is the launcher's here
            import urllib.request
            self.profile, self.proc = profile, proc
            self.port = int((profile / "DevToolsActivePort").read_text().split()[0])
            time.sleep(3)
            req = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/json/new?chrome://password-manager/passwords", method="PUT")
            self.page = json.loads(urllib.request.urlopen(req, timeout=10).read())
            time.sleep(4)

        def tab(self, url: str) -> dict:
            from tools.qa.linux_settings_import_check import _page
            return _page(self, url)

        def cookies(self) -> list[str]:
            from tools.qa.linux_settings_import_check import _call
            found = _call(self.page, "Network.getAllCookies").get("cookies", [])
            return [c.get("value") for c in found if c.get("name") == COOKIE["name"]]

    return Opened


Opened = None  # made on first use inside the test machine (it needs the keyring check's Browser)


def _wait_text(evaluate, element: str, want: str, timeout: float = 120) -> str:
    end = time.monotonic() + timeout
    text = ""
    while time.monotonic() < end:
        text = evaluate(f"(document.getElementById({json.dumps(element)}) || {{}}).textContent || ''") or ""
        if want in text:
            return text
        time.sleep(0.5)
    return text


def probe(tools: Path, package: Path, out: Path) -> int:
    global Opened
    Opened = _browser_class()
    from tools.qa.linux_keyring_check import _evaluate
    from tools.qa.linux_settings_import_check import _add_fixed_password, _call
    work = out.parent / "lock-work"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    copy = Copy(package, work)
    problems: dict[str, list[str]] = {step: [] for step in STEPS}
    notes: dict[str, str] = {}
    key_file = copy.data / KEY_FILE
    b = None
    try:
        # seed
        b = copy.open([])
        added = b.add(KEYRING_PASSWORD)
        set_cookie = _call(b.page, "Network.setCookie", name=COOKIE["name"], value=COOKIE["value"],
                           domain=COOKIE["domain"], path="/", secure=True, httpOnly=True,
                           expires=time.time() + 30 * 86400).get("success")
        time.sleep(40)  # Chromium writes cookies to disk every 30 seconds
        b.close()
        b = None
        _add_fixed_password(copy.data)
        seeded = copy.tags()
        notes["seed"] = json.dumps(seeded)
        if added != "added" or set_cookie is not True:
            problems["seed"].append(f"password {added!r}, cookie {set_cookie!r}")
        logins = seeded.get("Login Data:logins.password_value", [])
        if sorted(logins) != ["v10", "v11"]:
            problems["seed"].append(f"the passwords are not one v10 and one v11: {logins}")
        if not any(place.endswith("cookies.encrypted_value") and found for place, found in seeded.items()):
            problems["seed"].append("no cookie in the database")

        # lock
        b = copy.open([])
        page = b.tab(PAGE_URL)

        def run(expression):
            return _evaluate(page, expression)

        run(f"""(() => {{ document.getElementById('pass').value = {json.dumps(PASSPHRASE)};
                document.getElementById('repeat').value = {json.dumps(PASSPHRASE)};
                document.getElementById('with-recovery').checked = true;
                document.getElementById('next').click(); }})()""")
        time.sleep(2)
        recovery = run("document.getElementById('recovery-key').textContent") or ""
        run(f"""(() => {{ document.getElementById('last-group').value = {json.dumps(recovery[-4:])};
                document.getElementById('lock').click(); }})()""")
        said = _wait_text(run, "message", "locked with your passphrase")
        b.close()
        b = None
        state = copy.local_state()
        notes["lock"] = said[:200]
        if "locked with your passphrase" not in said:
            problems["lock"].append(f"the page said {said!r}")
        if len(recovery.replace("-", "")) != 32:
            problems["lock"].append(f"no recovery key shown ({recovery!r})")
        if not key_file.is_file():
            problems["lock"].append("no key file")
        if state.get("locked") is not True or state.get("reencrypt_pending") is not True:
            problems["lock"].append(f"Local State: {state}")
        if copy.tags() != seeded:
            problems["lock"].append(f"the values changed before the next start: {copy.tags()}")

        # wrong
        before_key = key_file.read_bytes() if key_file.is_file() else b""
        before_values = copy.values()
        proc = copy.launch(["not the passphrase at all"])
        ran = copy.started(proc)
        code = proc.wait(timeout=120) if not ran else None
        notes["wrong"] = f"exit {code}, asked {asked(copy.zenity(), '--entry')} time(s)"
        if ran:
            problems["wrong"].append("the browser started with a wrong passphrase")
            Opened(proc, copy.data).close()
        if code != 0:
            problems["wrong"].append(f"quitting the question did not end the launcher with 0 (exit {code})")
        if asked(copy.zenity(), "--entry") != 2:
            problems["wrong"].append(f"the launcher did not ask again: {copy.zenity()}")
        if key_file.read_bytes() != before_key or copy.values() != before_values:
            problems["wrong"].append("the key file or a database changed")

        # unlock
        b = copy.open([PASSPHRASE])
        readable = b.readable()
        cookies = b.cookies()

        # second
        entries = asked(copy.zenity(), "--entry")
        lock_link = os.readlink(copy.data / "SingletonLock") if (copy.data / "SingletonLock").is_symlink() else ""
        second = copy.launch([])
        try:
            second_code = second.wait(timeout=120)
        except subprocess.TimeoutExpired:
            second_code = None
            os.killpg(second.pid, signal.SIGKILL)
        notes["second"] = f"exit {second_code}, singleton lock {'there' if lock_link else 'missing'}"
        if asked(copy.zenity(), "--entry") != entries:
            problems["second"].append("the second start asked for the passphrase")
        # Chromium's own answer: 0 when the open browser took the start, 21 (profile in use) when it did not answer
        # it (a headless one opens no window); never a second browser on the same profile
        if second_code not in (0, 21):
            problems["second"].append(f"the second start ended with {second_code}")
        time.sleep(40)
        b.close()
        b = None
        tags = copy.tags()
        notes["unlock"] = json.dumps(tags)
        for entry in (KEYRING_PASSWORD, FIXED_PASSWORD):
            site = entry["url"].split("/")[2]
            if not any(site in s and text == entry["password"] for s, text in readable.items()):
                problems["unlock"].append(f"{site} is not readable: {readable}")
        if COOKIE["value"] not in cookies:
            problems["unlock"].append(f"the cookie is not readable: {cookies}")
        problems["unlock"] += tags_problems(tags, {"t10"})
        if not tags.get("Login Data:logins.password_value"):
            problems["unlock"].append("no password left in Login Data")
        if copy.leftovers():
            problems["unlock"].append(f"checked copies left: {copy.leftovers()}")
        if copy.local_state().get("reencrypt_pending") is not False:
            problems["unlock"].append(f"still pending: {copy.local_state()}")
        if copy.plain_in_files():
            problems["unlock"].append(f"a value is in a file as it is: {copy.plain_in_files()}")

        # recovery
        b = copy.open([recovery.replace("-", "").lower()])
        readable = b.readable()
        b.close()
        b = None
        notes["recovery"] = f"{len(readable)} password(s) listed"
        if not any(KEYRING_PASSWORD["password"] == t for t in readable.values()):
            problems["recovery"].append(f"the password is not readable: {readable}")

        # remember
        b = copy.open([PASSPHRASE])
        page = b.tab(PAGE_URL)
        run("document.getElementById('remember-pc').click()")
        remembered = _wait_text(run, "message", "remembered")
        b.close()
        b = None
        items_remembered = copy.keyring_items()
        entries = asked(copy.zenity(), "--entry")
        b = copy.open([])
        readable = b.readable()
        page = b.tab(PAGE_URL)
        run("document.getElementById('forget-pc').click()")
        forgotten = _wait_text(run, "message", "forgotten")
        b.close()
        b = None
        items_forgotten = copy.keyring_items()
        asked_remembered = asked(copy.zenity(), "--entry") - entries
        entries = asked(copy.zenity(), "--entry")
        b = copy.open([PASSPHRASE])
        b.close()
        b = None
        notes["remember"] = f"{remembered[:90]} / {forgotten[:60]} / keyring items {items_remembered}, then {items_forgotten}"
        if items_remembered != 1 or items_forgotten != 0:
            problems["remember"].append(f"the keyring held {items_remembered} item(s) once remembered and "
                                        f"{items_forgotten} once forgotten (want 1, then 0)")
        if "keyring" not in remembered:
            problems["remember"].append(f"the page said {remembered!r}")
        if asked_remembered:
            problems["remember"].append("a remembered PC was asked for the passphrase")
        if not any(KEYRING_PASSWORD["password"] == t for t in readable.values()):
            problems["remember"].append(f"the password is not readable: {readable}")
        if "forgotten" not in forgotten or asked(copy.zenity(), "--entry") - entries != 1:
            problems["remember"].append(f"after forgetting this PC the copy did not ask again ({forgotten!r})")

        # change
        b = copy.open([PASSPHRASE])
        page = b.tab(PAGE_URL)
        run(f"""(() => {{ document.getElementById('current').value = {json.dumps(PASSPHRASE)};
                document.getElementById('fresh').value = {json.dumps(NEW_PASSPHRASE)};
                document.getElementById('fresh-repeat').value = {json.dumps(NEW_PASSPHRASE)};
                document.getElementById('change').click(); }})()""")
        changed = _wait_text(run, "message", "changed")
        b.close()
        b = None
        entries = asked(copy.zenity(), "--entry")
        b = copy.open([PASSPHRASE, NEW_PASSPHRASE])
        readable = b.readable()
        b.close()
        b = None
        notes["change"] = changed[:200]
        if "changed" not in changed:
            problems["change"].append(f"the page said {changed!r}")
        if asked(copy.zenity(), "--entry") - entries != 2:
            problems["change"].append("the old passphrase was not refused")
        if not any(KEYRING_PASSWORD["password"] == t for t in readable.values()):
            problems["change"].append(f"the password is not readable: {readable}")

        # tampered
        good = key_file.read_bytes()
        key_file.write_bytes(flipped(good))
        entries = asked(copy.zenity(), "--entry")
        proc = copy.launch([NEW_PASSPHRASE])
        ran = copy.started(proc)
        flipped_code = proc.wait(timeout=120) if not ran else None
        if ran:
            Opened(proc, copy.data).close()
            problems["tampered"].append("a changed key file opened the copy")
        if asked(copy.zenity(), "--entry") - entries != 2 or flipped_code != 0:
            problems["tampered"].append(f"a changed key file was not refused (exit {flipped_code})")
        key_file.write_bytes(good[:40])  # cut short: damaged
        proc = copy.launch([NEW_PASSPHRASE])
        ran = copy.started(proc)
        code = proc.wait(timeout=120) if not ran else None
        if ran:
            Opened(proc, copy.data).close()
        key_file.write_bytes(good)
        errors = [line for line in copy.zenity() if "[--error]" in line]
        shown = errors[-1][:160] if errors else "nothing shown"
        notes["tampered"] = f"changed: exit {flipped_code}; damaged: exit {code}, {shown}"
        if ran or code != 82:
            problems["tampered"].append(f"a damaged key file: the browser {'started' if ran else f'ended with {code}'}")
        if not errors or "key file" not in errors[-1]:
            problems["tampered"].append(f"the launcher did not show why: {errors}")
        if (copy.data / "Thoron Unlock Problem").exists():
            problems["tampered"].append("the problem file was left")

        # forged
        locked_tags = copy.tags()
        copy.edit_local_state(remove_pending=True, remove_proof="AAAA")
        b = copy.open([NEW_PASSPHRASE])
        readable = b.readable()
        b.close()
        b = None
        state = copy.local_state()
        notes["forged"] = json.dumps({k: v for k, v in state.items() if k != "former_key"})
        if not key_file.is_file():
            problems["forged"].append("an edited Local State removed the lock")
        if copy.tags() != locked_tags:
            problems["forged"].append(f"the values changed: {copy.tags()}")
        if state.get("remove_pending") is not False or state.get("remove_proof"):
            problems["forged"].append(f"the request was not dropped: {state}")
        if not any(KEYRING_PASSWORD["password"] == t for t in readable.values()):
            problems["forged"].append(f"the password is not readable: {readable}")

        # remove
        b = copy.open([NEW_PASSPHRASE])
        page = b.tab(PAGE_URL)
        run(f"""(() => {{ document.getElementById('check-pass').value = {json.dumps(NEW_PASSPHRASE)};
                document.getElementById('remove').click(); }})()""")
        removed = _wait_text(run, "message", "next start")
        b.close()
        b = None
        pending = copy.local_state()
        b = copy.open([NEW_PASSPHRASE])  # the start that takes the lock away
        b.close()
        b = None
        back = copy.tags()
        state = copy.local_state()
        entries = asked(copy.zenity(), "--entry")
        b = copy.open([])
        readable = b.readable()
        cookies = b.cookies()
        b.close()
        b = None
        notes["remove"] = f"{removed[:90]} / {json.dumps(back)}"
        if "next start" not in removed or pending.get("remove_pending") is not True:
            problems["remove"].append(f"the page said {removed!r}; Local State {pending}")
        # Chromium's fixed key, which every Linux build reads, even with GNOME's keyring there
        problems["remove"] += tags_problems(back, {"v10"})
        if key_file.exists() or state.get("locked") is not False or state.get("remove_pending") is not False:
            problems["remove"].append(f"the lock is still there: key file {key_file.exists()}, Local State {state}")
        if len(state.get("former_key") or "") != 44:  # 32 bytes in base64
            problems["remove"].append("the copy's key was not kept for reading")
        if not pending.get("remove_proof"):
            problems["remove"].append("the page's request carries no proof")
        if asked(copy.zenity(), "--entry") != entries:
            problems["remove"].append("the copy still asks for a passphrase")
        for entry in (KEYRING_PASSWORD, FIXED_PASSWORD):
            site = entry["url"].split("/")[2]
            if not any(site in s and text == entry["password"] for s, text in readable.items()):
                problems["remove"].append(f"{site} is not readable after the removal: {readable}")
        if COOKIE["value"] not in cookies:
            problems["remove"].append(f"the cookie is not readable after the removal: {cookies}")
        if copy.leftovers():
            problems["remove"].append(f"checked copies left: {copy.leftovers()}")

        # relock
        former = copy.local_state().get("former_key")
        b = copy.open([])
        page = b.tab(PAGE_URL)
        run(f"""(() => {{ document.getElementById('pass').value = {json.dumps(PASSPHRASE)};
                document.getElementById('repeat').value = {json.dumps(PASSPHRASE)};
                document.getElementById('with-recovery').checked = false;
                document.getElementById('next').click(); }})()""")
        time.sleep(2)
        run("document.getElementById('lock').click()")
        relocked = _wait_text(run, "message", "locked with your passphrase")
        b.close()
        b = None
        after_lock = copy.local_state()
        b = copy.open([PASSPHRASE])
        readable = b.readable()
        cookies = b.cookies()
        time.sleep(5)
        b.close()
        b = None
        tags = copy.tags()
        notes["relock"] = f"{relocked[:60]} / {json.dumps(tags)}"
        if "locked with your passphrase" not in relocked or not key_file.is_file():
            problems["relock"].append(f"the page said {relocked!r}")
        if not former or after_lock.get("former_key"):
            problems["relock"].append("the former key was not there before, or stayed in Local State beside the lock")
        problems["relock"] += tags_problems(tags, {"t10"})
        for entry in (KEYRING_PASSWORD, FIXED_PASSWORD):
            site = entry["url"].split("/")[2]
            if not any(site in s and text == entry["password"] for s, text in readable.items()):
                problems["relock"].append(f"{site} is not readable after locking again: {readable}")
        if COOKIE["value"] not in cookies:
            problems["relock"].append(f"the cookie is not readable after locking again: {cookies}")

        # taken
        taken = package.parent / (KEY_FILE + ".taken")
        shutil.move(key_file, taken)
        copy.edit_local_state(locked=False)
        questions = len([line for line in copy.zenity() if "[--question]" in line])
        # the browser finds the lock's values and stops (82); the launcher asks at once, with its reason, and the
        # stand-in answers "start without them"
        b = copy.open([])
        b.close()
        b = None
        asked_now = [line for line in copy.zenity() if "[--question]" in line][questions:]
        aside = sorted(p.name for p in (copy.data / "Default").glob("*.thoron-without-key*"))
        notes["taken"] = f"asked: {asked_now[-1][:160] if asked_now else 'nothing'}; set aside {aside}"
        if len(asked_now) != 1 or "key file" not in asked_now[0]:
            problems["taken"].append(f"the launcher did not ask, with the browser's reason: {asked_now}")
        if "Login Data.thoron-without-key" not in aside:
            problems["taken"].append(f"the locked databases were not set aside: {aside}")
        if copy.local_state().get("locked") is not False:
            problems["taken"].append(f"the copy is still marked as locked: {copy.local_state()}")
        taken.unlink(missing_ok=True)

        # missing
        b = copy.open([])
        page = b.tab(PAGE_URL)
        run(f"""(() => {{ document.getElementById('pass').value = {json.dumps(PASSPHRASE)};
                document.getElementById('repeat').value = {json.dumps(PASSPHRASE)};
                document.getElementById('with-recovery').checked = false;
                document.getElementById('next').click(); }})()""")
        time.sleep(2)  # the page's confirm step, here without a recovery key
        run("document.getElementById('lock').click()")
        relocked = _wait_text(run, "message", "locked with your passphrase")
        b.close()
        b = None
        if "locked with your passphrase" not in relocked:
            problems["missing"].append(f"locking again: the page said {relocked!r}")
        shutil.move(key_file, package.parent / KEY_FILE)  # kept beside the package, on the same drive
        questions = asked(copy.zenity(), "--question")
        b = copy.open([])
        b.close()
        b = None
        notes["missing"] = json.dumps(copy.local_state())
        if asked(copy.zenity(), "--question") != questions + 1:
            problems["missing"].append("the launcher did not ask before starting without the key file")
        if copy.local_state().get("locked") is not False:
            problems["missing"].append(f"the copy is still marked as locked: {copy.local_state()}")
    except Exception as exc:  # the reason goes into the results; the host reads it
        problems.setdefault("error", []).append(f"{type(exc).__name__}: {exc}")
        # the steps after the one that stopped never ran
        stopped = next((s for s in STEPS if s not in notes), None)
        for step in STEPS[STEPS.index(stopped) + 1:] if stopped else ():
            problems[step].append("not reached")
    finally:
        if b is not None:
            b.close()
    notes["launcher"] = copy.output.read_text(errors="replace")[-1500:] if copy.output.is_file() else ""
    out.write_text(json.dumps({"problems": problems, "notes": notes}), encoding="utf-8")
    return 0


# ----- on Windows ----------------------------------------------------------------------------------------------

def run_machine(name: str, root: Path, work: Path, archive: Path, deb: Path) -> dict:
    from tools.qa import linux_package_check as lp
    from tools.qa import wsl_test_vm as vm
    vm.restore(root, name)
    folder = work / name

    def writable_again(func, path, _exc):  # files the test machine left read-only
        os.chmod(path, 0o700)
        func(path)

    if folder.exists():
        shutil.rmtree(folder, onexc=writable_again)
    folder.mkdir(parents=True)
    script = folder / "check.sh"
    script.write_bytes(SCRIPT.encode("utf-8"))
    tools = folder / "tools"
    shutil.copytree(REPO / "tools", tools, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    done = subprocess.run(["wsl.exe", "-d", vm.checked_name(name), "-u", "root", "--", "bash", lp.wsl_path(script),
                           lp.wsl_path(folder), lp.wsl_path(archive), lp.wsl_path(deb), lp.wsl_path(tools)],
                          capture_output=True, timeout=3600)
    (folder / "run-output.txt").write_bytes(done.stdout + done.stderr)
    out = folder / "out"
    if lp.read(out, "deps_exit") != "0":
        return {"problems": {"setup": [f"the libraries did not install: {lp.read(out, 'apt-deps.txt')[-400:]}"]}}
    try:
        found = json.loads(lp.read(out, "probe.json") or "{}")
    except ValueError:
        found = {}
    if not found:
        return {"problems": {"probe": [f"the probe wrote nothing: {lp.read(out, 'probe.txt')[-400:]}"]}}
    return found


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command")
    pr = sub.add_parser("probe", help="inside a test machine (used by the check itself)")
    pr.add_argument("--tools", type=Path, required=True)
    pr.add_argument("--package", type=Path, required=True)
    pr.add_argument("--out", type=Path, required=True)
    p.add_argument("--archive", type=Path)
    p.add_argument("--deb", type=Path)
    p.add_argument("--root", type=Path)
    p.add_argument("--work", type=Path)
    p.add_argument("--machine", action="append")
    a = p.parse_args(argv)
    if a.command == "probe":
        return probe(a.tools, a.package, a.out)
    if not (a.archive and a.deb and a.root and a.work):
        p.error("--archive, --deb, --root and --work are needed")
    from tools.qa import wsl_test_vm as vm
    failed = 0
    for name in a.machine or vm.MACHINES:
        print(f"== {name}")
        found = run_machine(name, a.root, a.work.resolve(), a.archive.resolve(), a.deb.resolve())
        notes = found.get("notes", {})
        for step, issues in found.get("problems", {}).items():
            print(f"{'PASS' if not issues else 'FAIL'}  {step}: {notes.get(step, '')[:160]}")
            for issue in issues:
                print(f"      {issue}")
            failed += len(issues)
        if failed and notes.get("launcher"):
            print("launcher output (end):\n" + notes["launcher"])
    print(f"LINUX PORTABLE LOCK CHECK: {'PASSED' if not failed else f'FAILED ({failed} problem(s))'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
