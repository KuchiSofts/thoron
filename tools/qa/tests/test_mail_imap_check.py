# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Thoron M-Notifier's mailboxes by address and password: the offline check (ROADMAP P5.77)."""
import base64
import json
import socket
import unittest

from tools.qa import mail_imap_check as mi


def box(unread=3, new=0, problem="", latest=None):
    return {"imap": True, "email": mi.EMAIL, "unread": unread, "new": new, "problem": problem,
            "latest": latest if latest is not None else [
                {"from": "Dana ✓", "fromEmail": "dana@example.com", "subject": "Café plans"},
                {"from": "Eli", "fromEmail": "eli@example.org", "subject": "Présentation"},
                {"from": "", "fromEmail": "frank@example.net", "subject": "Plain subject"}]}


class StepTests(unittest.TestCase):
    def test_the_date_is_english_whatever_the_language(self):
        self.assertEqual(mi.imap_date(0), "01-Jan-1970 00:00:00 +0000")
        self.assertEqual(mi.imap_date(1794823200), "16-Nov-2026 10:00:00 +0000")

    def test_refused(self):
        self.assertEqual(mi.refused_problems("sign-in", {"accounts": []}), [])
        self.assertTrue(mi.refused_problems("", {"accounts": []}))
        self.assertTrue(mi.refused_problems("sign-in", {"accounts": [box()]}))

    def test_added(self):
        self.assertEqual(mi.added_problems("", {"accounts": [box()], "problem": ""}), [])
        self.assertTrue(mi.added_problems("offline", {"accounts": []}))
        self.assertTrue(mi.added_problems("", {"accounts": [box(unread=2)], "problem": ""}))
        self.assertTrue(mi.added_problems("", {"accounts": [box(latest=[])], "problem": ""}))
        self.assertTrue(mi.added_problems("", {"accounts": [box(new=3)], "problem": ""}))

    def test_secret(self):
        self.assertEqual(mi.secret_problems("{}", "{}"), [])
        self.assertEqual(len(mi.secret_problems(mi.PASSWORD, mi.PASSWORD)), 2)

    def test_new_seen_restart(self):
        self.assertEqual(mi.new_problems({"sounds": 0}, {"sounds": 1, "accounts": [box(4, 1)]}), [])
        self.assertEqual(len(mi.new_problems({"sounds": 0}, {"sounds": 0, "accounts": [box(3, 0)]})), 2)
        self.assertEqual(mi.seen_problems({"accounts": [box(4, 0)]}), [])
        self.assertTrue(mi.seen_problems({"accounts": [box(4, 1)]}))
        self.assertEqual(mi.restart_problems({"accounts": [box(4)]}), [])
        self.assertTrue(mi.restart_problems({"accounts": []}))
        self.assertTrue(mi.restart_problems({"accounts": [box(4, problem="sign-in")]}))

    def test_backup(self):
        sealed = json.dumps({"sealed": True, "data": "AAAA"})
        bare = json.dumps({"sealed": False, "accounts": [{"email": mi.EMAIL}]})
        plain = json.dumps({"sealed": False, "accounts": [{"email": mi.EMAIL, "password": mi.PASSWORD}]})
        answers = {"removed": False, "wrong": "wrong", "none": "passphrase", "changed": "wrong", "bare": "",
                   "bare_boxes": 0, "right": "", "right_boxes": 1}
        back = {"accounts": [box(4)]}
        self.assertEqual(mi.backup_problems(sealed, bare, plain, answers, back), [])
        self.assertTrue(mi.backup_problems(plain, bare, plain, answers, back))
        self.assertTrue(mi.backup_problems(sealed, plain, plain, answers, back))
        self.assertTrue(mi.backup_problems(sealed, bare, bare, answers, back))
        self.assertTrue(mi.backup_problems(sealed, bare, plain, dict(answers, wrong=""), back))
        self.assertTrue(mi.backup_problems(sealed, bare, plain, answers, {"accounts": []}))
        self.assertTrue(mi.backup_problems("not json", bare, plain, answers, back))


class ServerTests(unittest.TestCase):
    """The stand-in mail server answers a look the way a mail server does."""

    def talk(self, server, lines):
        with socket.create_connection(("127.0.0.1", server.port), timeout=5) as s:
            f = s.makefile("rwb")
            out = [f.readline().decode()]
            for line in lines:
                f.write(line.encode() + b"\r\n")
                f.flush()
                while True:
                    got = f.readline().decode()
                    out.append(got)
                    # an answer ends with its tagged line, or asks for more ("+")
                    if not got or got.startswith("+") or (got[:1] == "a" and got[1:2].isdigit()):
                        break
            return "".join(out)

    def test_a_look(self):
        with mi.ImapServer("u@example.com", "pw") as server:
            auth = base64.b64encode(b"\0u@example.com\0pw").decode()
            said = self.talk(server, ["a1 CAPABILITY", "a2 AUTHENTICATE PLAIN", auth])
            self.assertIn("AUTH=PLAIN", said)
            said = self.talk(server, ["a1 AUTHENTICATE PLAIN " + auth, "a3 EXAMINE INBOX", "a4 UID SEARCH UNSEEN",
                                      "a5 UID FETCH 11,15 (UID)", "a6 LOGOUT"])
            self.assertIn("a1 OK", said)
            self.assertIn("* SEARCH 11 12 15", said)
            self.assertIn("UID 11 INTERNALDATE", said)
            self.assertNotIn("UID 12 INTERNALDATE", said)
            self.assertIn("a6 OK", said)
            self.assertEqual(server.logins[-1], ("u@example.com", True))

    def test_a_wrong_password_and_no_sign_in(self):
        with mi.ImapServer("u@example.com", "pw") as server:
            wrong = base64.b64encode(b"\0u@example.com\0nope").decode()
            said = self.talk(server, ["a1 AUTHENTICATE PLAIN " + wrong, "a2 EXAMINE INBOX"])
            self.assertIn("a1 NO", said)
            self.assertIn("a2 BAD", said)


if __name__ == "__main__":
    unittest.main()
