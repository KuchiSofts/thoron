# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Thoron's mail notifier: the offline check (ROADMAP P5.75)."""
import unittest

from tools.qa import mail_check as mc


def account(email, unread, latest):
    return {"email": email, "unread": unread, "latest": latest}


GOOD = {"accounts": [account("alice@example.com", 3, [{"from": "Sender 1", "link": "https://mail.google.com/x"},
                                                       {"from": "Sender 2", "link": "https://mail.google.com/y"}]),
                     account("bob@example.com", 0, [])], "total": 3, "problem": ""}


class StepTests(unittest.TestCase):
    def test_the_feed_made_up(self):
        text = mc.feed("a@example.com", 2, [mc.entry(1, "Hi")])
        self.assertIn("Inbox for a@example.com", text)
        self.assertIn("<fullcount>2</fullcount>", text)
        self.assertIn("message_id=1", mc.entry(1, "Hi"))
        self.assertIn('href="https://elsewhere"', mc.entry(1, "Hi", "https://elsewhere"))

    def test_accounts(self):
        self.assertEqual(mc.accounts_problems(GOOD), [])
        self.assertIn("found", mc.accounts_problems(dict(GOOD, accounts=GOOD["accounts"][:1]))[0])
        self.assertTrue(mc.accounts_problems(dict(GOOD, total=5)))

    def test_new(self):
        state = {"accounts": [account("alice@example.com", 4, [{}, {}, {}])]}
        self.assertEqual(mc.new_problems(state), [])
        self.assertTrue(mc.new_problems(GOOD))

    def test_links(self):
        state = {"accounts": [account("alice@example.com", 1, [{"subject": "Elsewhere", "link": ""}])]}
        self.assertEqual(mc.links_problems(state), [])
        state["accounts"][0]["latest"][0]["link"] = "https://ads.example.test/x"
        self.assertTrue(mc.links_problems(state))

    def test_out_and_broken(self):
        self.assertEqual(mc.out_problems({"accounts": [], "problem": "signed-out"}), [])
        self.assertTrue(mc.out_problems(GOOD))
        self.assertEqual(mc.broken_problems({"accounts": []}, GOOD), [])
        self.assertEqual(len(mc.broken_problems(GOOD, {"accounts": []})), 2)


if __name__ == "__main__":
    unittest.main()
