# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Tests of mail_bridge_check.py (ROADMAP P5.77): its verdicts, and its stand-in for Proton Mail Bridge spoken to
over STARTTLS and over TLS from the start, as the browser speaks to it."""
import json
import socket
import ssl
import tempfile
import unittest
from pathlib import Path

from tools.qa import mail_bridge_check as mb
from tools.qa.mail_imap_check import ImapServer

PIN = "AB" * 32


def state(**boxes):
    return {"accounts": [{"email": email, **values} for email, values in boxes.items()]}


class VerdictTests(unittest.TestCase):
    def test_the_form(self):
        good = {"host": "127.0.0.1", "port": "1143", "hint": "use the password Bridge shows", "blocked": False}
        self.assertEqual(mb.form_problems(good), [])
        self.assertTrue(mb.form_problems({**good, "port": "993"}))
        self.assertTrue(mb.form_problems({**good, "blocked": True}))

    def test_counted(self):
        self.assertEqual(mb.counted_problems("x", "", state(**{mb.CAROL: {"unread": 3, "problem": ""}}),
                                             mb.CAROL, 1), [])
        self.assertTrue(mb.counted_problems("x", "", state(**{mb.CAROL: {"unread": 3, "problem": ""}}), mb.CAROL, 0))
        self.assertTrue(mb.counted_problems("x", "sign-in", state(), mb.CAROL, 1))

    def test_pins(self):
        backup = json.dumps({"accounts": [{"email": mb.CAROL, "pin": PIN}]})
        self.assertEqual(mb.pin_of(backup, mb.CAROL), PIN)
        self.assertEqual(mb.pin_of("not json", mb.CAROL), "")
        self.assertEqual(mb.pinned_problems("x", PIN, PIN), [])
        self.assertTrue(mb.pinned_problems("x", "", PIN))

    def test_changed(self):
        self.assertEqual(mb.changed_problems(state(**{mb.CAROL: {"problem": "certificate"}}), 2, 2), [])
        self.assertTrue(mb.changed_problems(state(**{mb.CAROL: {"problem": ""}}), 2, 2))
        self.assertTrue(mb.changed_problems(state(**{mb.CAROL: {"problem": "certificate"}}), 2, 3))


class StandInTests(unittest.TestCase):
    """The stand-in speaks as Bridge does: TLS before any password, with its own certificate."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.context, self.pin = mb.make_context(Path(self.folder.name), "test")
        self.client = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.client.check_hostname = False
        self.client.verify_mode = ssl.CERT_NONE

    def tearDown(self):
        self.folder.cleanup()

    def test_starttls_then_a_sign_in(self):
        with ImapServer("a@example.com", "pw", tls="starttls", context=self.context) as server:
            with socket.create_connection(("127.0.0.1", server.port), timeout=5) as raw:
                plain = raw.makefile("rwb", 0)
                self.assertIn(b"STARTTLS", plain.readline())
                plain.write(b"a LOGIN a@example.com pw\r\n")
                self.assertTrue(plain.readline().startswith(b"a BAD"))
                plain.write(b"s0 STARTTLS\r\n")
                self.assertTrue(plain.readline().startswith(b"s0 OK"))
                plain.close()
                with self.client.wrap_socket(raw) as secure:
                    der = secure.getpeercert(binary_form=True)
                    secure.sendall(b"a1 CAPABILITY\r\n")
                    self.assertIn(b"AUTH=PLAIN", secure.recv(4096))
            self.assertEqual(server.secured, 1)
            self.assertEqual(server.logins, [])
        import hashlib
        self.assertEqual(hashlib.sha256(der).hexdigest().upper(), self.pin)

    def test_tls_from_the_start(self):
        with ImapServer("a@example.com", "pw", tls="ssl", context=self.context) as server:
            with socket.create_connection(("127.0.0.1", server.port), timeout=5) as raw:
                with self.client.wrap_socket(raw) as secure:
                    self.assertTrue(secure.recv(4096).startswith(b"* OK"))
            self.assertEqual(server.secured, 1)


if __name__ == "__main__":
    unittest.main()
