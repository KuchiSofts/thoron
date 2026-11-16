# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Thoron M-Notifier: the offline check (ROADMAP P5.75, P5.76)."""
import time
import unittest

from tools.qa import mail_check as mc


def account(email, unread, latest, new=0, watched=True):
    return {"email": email, "unread": unread, "latest": latest, "new": new, "watched": watched}


GOOD = {"accounts": [account("alice@example.com", 3, [{"from": "Sender 1", "link": "https://mail.google.com/x"},
                                                       {"from": "Sender 2", "link": "https://mail.google.com/y"}]),
                     account("bob@example.com", 0, [])], "total": 3, "totalNew": 0, "problem": "",
        "choices": dict(mc.DEFAULT_CHOICES)}


class StepTests(unittest.TestCase):
    def test_the_feed_made_up(self):
        text = mc.feed("a@example.com", 2, [mc.entry(1, "Hi")])
        self.assertIn("Inbox for a@example.com", text)
        self.assertIn("<fullcount>2</fullcount>", text)
        self.assertIn("message_id=1", mc.entry(1, "Hi"))
        self.assertIn('href="https://elsewhere"', mc.entry(1, "Hi", "https://elsewhere"))
        self.assertIn("<issued>2026-01-02T03:04:05Z</issued>", mc.entry(1, "Hi", when="2026-01-02T03:04:05Z"))
        self.assertTrue(time.strptime(mc.now_utc(), "%Y-%m-%dT%H:%M:%SZ"))

    def test_accounts(self):
        self.assertEqual(mc.accounts_problems(GOOD), [])
        self.assertIn("found", mc.accounts_problems(dict(GOOD, accounts=GOOD["accounts"][:1]))[0])
        self.assertTrue(mc.accounts_problems(dict(GOOD, total=5)))
        self.assertIn("first look", mc.accounts_problems(dict(GOOD, totalNew=2))[0])
        self.assertIn("settings", mc.accounts_problems(dict(GOOD, choices=dict(mc.DEFAULT_CHOICES, place="both")))[0])

    def test_new(self):
        state = {"accounts": [account("alice@example.com", 4, [{"isNew": True}, {}, {}], new=1)], "totalNew": 1}
        self.assertEqual(mc.new_problems(state), [])
        self.assertTrue(mc.new_problems(GOOD))
        self.assertTrue(mc.new_problems(dict(state, totalNew=0)))
        state["accounts"][0]["latest"][1]["isNew"] = True
        self.assertTrue(mc.new_problems(state))

    def test_seen(self):
        seen = {"accounts": [account("alice@example.com", 4, [{}, {}, {}], new=0)], "totalNew": 0}
        self.assertEqual(mc.seen_problems(seen), [])
        self.assertTrue(mc.seen_problems(dict(seen, totalNew=1)))
        self.assertTrue(mc.seen_problems({"accounts": [account("alice@example.com", 3, [], new=0)], "totalNew": 0}))

    def test_settings(self):
        changed = {"choices": dict(mc.DEFAULT_CHOICES, place="address", count="unread")}
        unwatched = {"accounts": [account("alice@example.com", 4, [], watched=False)], "total": 0, "totalNew": 0}
        back = {"choices": dict(mc.DEFAULT_CHOICES), "total": 4}
        self.assertEqual(mc.settings_problems(changed, changed, unwatched, back), [])
        self.assertTrue(mc.settings_problems({"choices": dict(mc.DEFAULT_CHOICES)}, changed, unwatched, back))
        self.assertTrue(mc.settings_problems(changed, {"choices": dict(changed["choices"], place="nowhere")},
                                             unwatched, back))
        self.assertTrue(mc.settings_problems(changed, changed, dict(unwatched, total=4), back))
        self.assertTrue(mc.settings_problems(changed, changed, unwatched, dict(back, total=0)))

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
