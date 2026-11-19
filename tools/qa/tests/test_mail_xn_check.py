# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Thoron M-Notifier reads X-notifier's file of accounts: the offline check (ROADMAP P5.80)."""
import json
import unittest

from tools.qa import mail_xn_check as mx
from tools.qa import xn_file

BARE = f"{mx.BARE_USER}@{mx.GMAIL}"
SAID = "Read from X-notifier. Google accounts: 3; as mailboxes by app password: 1; left out (not mail): 2"


def listed(counted=(), password=True, alias=mx.LISTED_NAME):
    return [{"email": mx.LISTED, "alias": alias, "counted": mx.LISTED in counted, "password": password},
            {"email": BARE, "alias": "", "counted": BARE in counted, "password": password},
            {"email": mx.BOX, "alias": "", "counted": mx.BOX in counted, "password": password}]


def state(wanted=None, boxes=((mx.BOX, ""),), google=0):
    accounts = [{"email": f"user{i}@example.com", "imap": False} for i in range(google)]
    accounts += [{"email": email, "imap": True, "problem": problem} for email, problem in boxes]
    return {"wanted": listed() if wanted is None else wanted, "accounts": accounts}


class FileTests(unittest.TestCase):
    def test_the_file_is_made_up_and_opens(self):
        got = xn_file.read(mx.the_file(), mx.PASSPHRASE)
        self.assertEqual(got["accounts"], mx.ACCOUNTS)
        self.assertEqual(len([a for a in mx.ACCOUNTS if a[0] == "gmail"]), 3)
        for _, user, _ in mx.ACCOUNTS:
            self.assertTrue("@" not in user or user.endswith("@example.com"))
        self.assertIsNone(xn_file.read(mx.the_file(), "not the passphrase"))
        self.assertEqual(len(mx.APP_PASSWORD.replace(" ", "")), 16)


class StepTests(unittest.TestCase):
    def test_wrong(self):
        said = "The passphrase does not open this file of X-notifier."
        self.assertEqual(mx.wrong_problems(said, {"wanted": []}), [])
        self.assertEqual(len(mx.wrong_problems("", {"wanted": []})), 1)
        self.assertEqual(len(mx.wrong_problems(said, state())), 1)

    def test_read(self):
        self.assertEqual(mx.read_problems(SAID, state()), [])
        self.assertEqual(len(mx.read_problems(SAID.replace(": 3;", ": 2;"), state())), 1)
        self.assertEqual(len(mx.read_problems(SAID, state(wanted=listed()[:1]))), 1)
        self.assertEqual(len(mx.read_problems(SAID, state(wanted=listed(alias="")))), 1)
        self.assertEqual(len(mx.read_problems(SAID, state(wanted=listed(password=False)))), 1)
        self.assertEqual(len(mx.read_problems(SAID, state(boxes=()))), 1)
        self.assertEqual(len(mx.read_problems(SAID, state(boxes=((mx.BOX, "sign-in"),)))), 1)

    def test_secret(self):
        self.assertEqual(mx.secret_problems("{}", json.dumps(state())), [])
        self.assertEqual(len(mx.secret_problems("x " + mx.PASSWORDS[0], "{}")), 1)
        self.assertEqual(len(mx.secret_problems("{}", "abcdefghijklmnop")), 1)

    def test_counted(self):
        self.assertEqual(mx.counted_problems(state(wanted=listed(counted=(mx.LISTED, mx.BOX)))), [])
        self.assertEqual(len(mx.counted_problems(state())), 2)
        self.assertEqual(len(mx.counted_problems(state(wanted=listed(counted=(mx.LISTED,))))), 1)
        self.assertEqual(len(mx.counted_problems(state(wanted=listed(counted=(mx.LISTED, mx.BOX, BARE))))), 1)

    def test_many(self):
        self.assertEqual(mx.many_problems(state(google=mx.MANY)), [])
        self.assertEqual(len(mx.many_problems(state(google=10))), 1)
        self.assertGreater(mx.MANY, 10)

    def test_sign_in(self):
        before = ["chrome://mail-notifier.top-chrome/#manage"]
        page = "https://accounts.google.com/AddSession?service=mail&continue=x&Email=alice%40example.com"
        self.assertEqual(mx.signin_problems(before, before, before + [page]), [])
        self.assertEqual(len(mx.signin_problems(before, before, before)), 1)
        self.assertEqual(len(mx.signin_problems(before, before + ["https://accounts.google.com/x"], before + [page])), 1)
        self.assertEqual(len(mx.signin_problems(before, before, before + [page.replace("alice", "eve")])), 1)

    def test_kept(self):
        self.assertEqual(mx.kept_problems(state()), [])
        self.assertEqual(len(mx.kept_problems(state(wanted=listed(password=False)))), 1)
        self.assertEqual(len(mx.kept_problems(state(wanted=[]))), 1)

    def test_backup(self):
        bare = json.dumps({"google": [{"email": mx.LISTED, "alias": "Work"}]})
        plain = json.dumps({"google": [{"email": mx.LISTED, "alias": "Work", "password": mx.PASSWORDS[0]}]})
        gone = state(wanted=listed()[1:])  # the first one removed
        ok = (bare, plain, "c2VhbGVk", gone, {"error": "", "accounts": 1}, state())
        self.assertEqual(mx.backup_problems(*ok), [])
        self.assertEqual(len(mx.backup_problems(plain, plain, "c2VhbGVk", gone, {"error": ""}, state())), 1)
        self.assertEqual(len(mx.backup_problems(bare, bare, "c2VhbGVk", gone, {"error": ""}, state())), 1)
        self.assertEqual(len(mx.backup_problems(bare, plain, plain, gone, {"error": ""}, state())), 1)
        self.assertEqual(len(mx.backup_problems(bare, plain, "c2VhbGVk", state(), {"error": ""}, state())), 1)
        self.assertEqual(len(mx.backup_problems(bare, plain, "c2VhbGVk", gone, {"error": "bad"}, state())), 1)
        self.assertEqual(len(mx.backup_problems(bare, plain, "c2VhbGVk", gone, {"error": ""}, gone)), 1)
        self.assertEqual(len(mx.backup_problems("no", plain, "c2VhbGVk", gone, {"error": ""}, state())), 1)


if __name__ == "__main__":
    unittest.main()
