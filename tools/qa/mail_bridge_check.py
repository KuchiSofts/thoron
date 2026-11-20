#!/usr/bin/env python3
# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Thoron M-Notifier reading Proton Mail through Proton Mail Bridge, checked end to end and offline (ROADMAP P5.77).

Proton Mail Bridge is Proton's own app on the person's computer: it serves the mailbox over IMAP on 127.0.0.1
with a certificate it makes itself, which no authority signs. Thoron trusts that certificate by its SHA-256,
pinned when the mailbox is added. Here local servers stand in for Bridge (`ImapServer` with TLS, certificates
made for the run), with made-up mailboxes; nothing leaves the PC and no real account is used. Steps:

    form       a Proton address in the page's form fills in Bridge's address and port, and says to use the
               password Bridge shows
    starttls   a mailbox on a Bridge that greets in plain text (its default): added over STARTTLS, counted, and
               its certificate pinned (the one the server has)
    ssl        a mailbox on a Bridge that waits for TLS at once: added and counted
    refused    a wrong Bridge password: not added
    plain      a server on this computer without TLS: not added, and no password was sent to it
    changed    Bridge with another certificate: the look says so, and the password is not sent to it
    retrust    the mailbox edited with its password typed again: the new certificate is pinned, and it is counted
    kept       the mailbox edited without its password (only its mail page): the pin stays, nothing signed in
    restart    after a restart the mailbox is counted with its pin; its password is in no file as it is

    py -3 -I tools/qa/mail_bridge_check.py --browser <out>\\thoron.exe --work <scratch dir>
Exit status 0 only when every step passes.
"""
import argparse
import datetime
import ipaddress
import json
import shutil
import ssl
import sys
import tempfile
import time
from pathlib import Path

if __package__ in (None, ""):  # running as a script under `py -3 -I`: make `tools` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.qa import bench  # noqa: E402
from tools.qa.mail_check import Gmail  # noqa: E402
from tools.qa.mail_imap_check import ImapServer, profile_text  # noqa: E402
from tools.qa.mail_manage_check import Page  # noqa: E402

# made-up Proton addresses (Proton's own domains): written as parts
PROTON = "proton.me"
CAROL, DAVE, ERIN = (f"{name}@{PROTON}" for name in ("carol", "dave", "erin"))
BRIDGE_PASSWORD = "made-up-bridge-pass-1"
WEBMAIL = "https://mail.proton.me/"
LOOK_S = 4.0


def make_context(folder: Path, name: str) -> tuple[ssl.SSLContext, str]:
    """A certificate made for the run, as Bridge makes its own: its TLS side and its SHA-256 (hex)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(hours=1)).not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
                           critical=False)
            .sign(key, hashes.SHA256()))
    cert_path, key_path = folder / f"{name}.pem", folder / f"{name}.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    return context, cert.fingerprint(hashes.SHA256()).hex().upper()


def bridge_box(email: str, port: int, password: str = BRIDGE_PASSWORD, before: str = "", webmail: str = WEBMAIL):
    return {"before": before, "email": email, "password": password, "host": "127.0.0.1", "port": port,
            "user": "", "webmail": webmail}


def box(state: dict, email: str) -> dict:
    return next((a for a in state.get("accounts", []) if a.get("email") == email), {})


def pin_of(backup: str, email: str) -> str:
    try:
        entries = json.loads(backup).get("accounts", [])
    except ValueError:
        return ""
    return next((e.get("pin", "") for e in entries if e.get("email") == email), "")


def form_problems(filled: dict) -> list[str]:
    out = []
    if (filled.get("host"), filled.get("port")) != ("127.0.0.1", "1143"):
        out.append(f"form: a Proton address filled in {filled.get('host')!r}:{filled.get('port')!r}")
    if "Bridge" not in filled.get("hint", "") or filled.get("blocked"):
        out.append(f"form: the hint is {filled.get('hint')!r}, the Add button blocked: {filled.get('blocked')}")
    return out


def counted_problems(name: str, answer: str, state: dict, email: str, secured: int) -> list[str]:
    out = [] if answer == "" else [f"{name}: adding was answered {answer!r}"]
    found = box(state, email)
    if found.get("unread") != 3 or found.get("problem"):
        out.append(f"{name}: the mailbox is {(found.get('unread'), found.get('problem'))}, not (3, '')")
    if secured < 1:
        out.append(f"{name}: no session reached TLS")
    return out


def pinned_problems(name: str, pin: str, want: str) -> list[str]:
    return [] if pin == want else [f"{name}: the pin is {pin[:12]!r}..., not the server's certificate {want[:12]!r}..."]


def changed_problems(state: dict, logins_before: int, logins_after: int) -> list[str]:
    out = []
    if box(state, CAROL).get("problem") != "certificate":
        out.append(f"changed: the look says {box(state, CAROL).get('problem')!r}, not 'certificate'")
    if logins_after != logins_before:
        out.append("changed: the password was sent to a server with another certificate")
    return out


def run(browser: Path, work: Path) -> list[str]:
    profile = Path(tempfile.mkdtemp(prefix="mail-bridge-", dir=work))
    certs = Path(tempfile.mkdtemp(prefix="mail-bridge-certs-", dir=work))
    problems: list[str] = []

    def report(name: str, found: list[str], detail) -> None:
        print(f"{'PASS' if not found else 'FAIL'}  {name}: {detail}")
        problems.extend(found)

    first, first_pin = make_context(certs, "first")
    second, second_pin = make_context(certs, "second")
    other, _ = make_context(certs, "other")
    with Gmail() as gmail, ImapServer(CAROL, BRIDGE_PASSWORD, tls="starttls", context=first) as bridge, \
            ImapServer(DAVE, BRIDGE_PASSWORD, tls="ssl", context=other) as ssl_bridge, \
            ImapServer(ERIN, BRIDGE_PASSWORD) as plain:
        page = None
        try:
            page = Page(browser, profile, gmail.port, plain.port, work / "unused.json")
            page.wait_for_passwords()

            # the form, as a person fills it in (the menu's form is on the page)
            filled = json.loads(page.run(f"""(() => {{
                const email = document.getElementById('imap-email');
                email.value = {json.dumps(CAROL)};
                email.dispatchEvent(new Event('input'));
                return JSON.stringify({{host: document.getElementById('imap-host').value,
                                       port: document.getElementById('imap-port').value,
                                       hint: document.getElementById('imap-hint').textContent,
                                       blocked: document.getElementById('imap-add').disabled}}); }})()""") or "{}")
            report("form", form_problems(filled), filled)

            answer = page.ask("addImapAccount", bridge_box(CAROL, bridge.port))
            state = page.look()
            report("starttls", counted_problems("starttls", answer, state, CAROL, bridge.secured) +
                   pinned_problems("starttls", pin_of(page.ask("exportBackup", False, ""), CAROL), first_pin),
                   f"answer {answer!r}, TLS sessions {bridge.secured}")

            answer = page.ask("addImapAccount", bridge_box(DAVE, ssl_bridge.port))
            state = page.look()
            report("ssl", counted_problems("ssl", answer, state, DAVE, ssl_bridge.secured),
                   f"answer {answer!r}, TLS sessions {ssl_bridge.secured}")

            bridge.users[ERIN] = BRIDGE_PASSWORD
            answer = page.ask("addImapAccount", bridge_box(ERIN, bridge.port, "not-the-bridge-password"))
            report("refused", [] if answer == "sign-in" else [f"refused: answered {answer!r}, not 'sign-in'"],
                   f"answer {answer!r}")

            answer = page.ask("addImapAccount", bridge_box(ERIN, plain.port))
            report("plain", ([] if answer == "protocol" else [f"plain: answered {answer!r}, not 'protocol'"]) +
                   ([] if not plain.logins else ["plain: a password was sent to a server without TLS"]),
                   f"answer {answer!r}, sign-ins it saw {len(plain.logins)}")

            before = len(bridge.logins)
            bridge.context = second
            state = page.look()
            report("changed", changed_problems(state, before, len(bridge.logins)),
                   f"problem {box(state, CAROL).get('problem')!r}")

            answer = page.ask("editImapAccount", bridge_box(CAROL, bridge.port, before=CAROL))
            state = page.look()
            report("retrust", counted_problems("retrust", answer, state, CAROL, bridge.secured) +
                   pinned_problems("retrust", pin_of(page.ask("exportBackup", False, ""), CAROL), second_pin),
                   f"answer {answer!r}")

            before = len(bridge.logins)
            answer = page.ask("editImapAccount", bridge_box(CAROL, bridge.port, password="", before=CAROL,
                                                            webmail="https://mail.proton.me/u/0/"))
            pin = pin_of(page.ask("exportBackup", False, ""), CAROL)
            report("kept", ([] if answer == "" else [f"kept: answered {answer!r}"]) +
                   pinned_problems("kept", pin, second_pin) +
                   ([] if len(bridge.logins) == before else ["kept: signed in again for a new mail page"]),
                   f"answer {answer!r}")
            page.close()

            page = Page(browser, profile, gmail.port, plain.port, work / "unused.json")
            page.wait_for_passwords()
            state = page.look()
            time.sleep(1.5)  # the profile writes its settings a moment later
            found = counted_problems("restart", "", state, CAROL, bridge.secured)
            found += pinned_problems("restart", pin_of(page.ask("exportBackup", False, ""), CAROL), second_pin)
            if BRIDGE_PASSWORD in profile_text(profile):
                found.append("restart: the Bridge password is in the profile's files as it is")
            if BRIDGE_PASSWORD in json.dumps(state):
                found.append("restart: the page was given the password")
            report("restart", found, f"mailbox {(box(state, CAROL).get('unread'), box(state, CAROL).get('problem'))}")
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
            shutil.rmtree(certs, ignore_errors=True)
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
    print("MAIL BRIDGE CHECK: PASSED" if not problems else f"MAIL BRIDGE CHECK: FAILED ({len(problems)} problem(s))")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
