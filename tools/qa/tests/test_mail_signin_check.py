# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Thoron M-Notifier asks Gmail only with a Google sign-in: the offline check (ROADMAP S.15)."""
import base64
import unittest

from tools.qa import mail_signin_check as ms


class ListTests(unittest.TestCase):
    def test_one_account(self):
        raw = base64.b64decode(ms.listed_accounts(["a@example.com"]))
        # field 1 (an account) of 23 bytes: field 3 the address (13 bytes), field 10 the id (6 bytes)
        self.assertEqual(raw, b"\x0a\x17" + b"\x1a\x0d" + b"a@example.com" + b"\x52\x06" + b"100000")

    def test_several_and_none(self):
        raw = base64.b64decode(ms.listed_accounts(["a@example.com", "b@example.org"]))
        self.assertEqual(raw.count(b"@example."), 2)
        self.assertIn(b"100001", raw)
        self.assertEqual(ms.listed_accounts([]), "")

    def test_a_long_field(self):
        long = "x" * 200 + "@example.com"
        raw = base64.b64decode(ms.listed_accounts([long]))
        # lengths above 127 take two bytes
        self.assertEqual(raw[:3], b"\x0a" + bytes([(len(long) + 11) & 0x7F | 0x80, (len(long) + 11) >> 7]))

    def test_into_the_preferences(self):
        before = {"gaia_cookie": {"other": 1}, "profile": {"name": "x"}}
        after = ms.with_list(before, ["a@example.com"])
        self.assertEqual(after["gaia_cookie"]["other"], 1)
        self.assertEqual(after["gaia_cookie"]["last_list_accounts_binary_data"], ms.listed_accounts(["a@example.com"]))
        self.assertEqual(after["profile"], {"name": "x"})
        self.assertNotIn("last_list_accounts_binary_data", before["gaia_cookie"])
        self.assertIn("gaia_cookie", ms.with_list({}, ["a@example.com"]))


class StepTests(unittest.TestCase):
    def test_quiet(self):
        self.assertEqual(ms.quiet_problems({"problem": "signed-out", "accounts": []}), [])
        self.assertEqual(len(ms.quiet_problems({"problem": "offline", "accounts": []})), 1)
        self.assertEqual(len(ms.quiet_problems({"problem": "", "accounts": [{"email": "a@example.com"}]})), 1)

    def test_asked(self):
        self.assertEqual(ms.asked_problems({"problem": "offline"}), [])
        self.assertEqual(len(ms.asked_problems({"problem": "signed-out"})), 1)
        self.assertEqual(len(ms.asked_problems({})), 1)

    def test_the_stand_ins_are_made_up(self):
        self.assertTrue(ms.ACCOUNT.endswith("@example.com"))
        self.assertEqual(ms.SET_COOKIE["value"], "stand-in")


if __name__ == "__main__":
    unittest.main()
