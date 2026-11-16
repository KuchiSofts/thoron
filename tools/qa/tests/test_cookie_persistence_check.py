# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Sign-ins survive restarts and updates: the offline check's judge (ROADMAP P5.9)."""
import unittest

from tools.qa import cookie_persistence_check as cc

KEPT = {"cookie": cc.LASTING, "stored": cc.STORED[1]}


class KeptTests(unittest.TestCase):
    def test_after_a_restart(self):
        self.assertEqual(cc.kept_problems("restart", KEPT, cc.LASTING, session_wanted=False), [])

    def test_while_the_session_lasts(self):
        both = f"{cc.LASTING}; {cc.SESSION}"
        self.assertEqual(cc.kept_problems("set", dict(KEPT, cookie=both), both, session_wanted=True), [])
        self.assertEqual(len(cc.kept_problems("set", KEPT, cc.LASTING, session_wanted=True)), 1)

    def test_a_lost_sign_in(self):
        found = cc.kept_problems("update", {"cookie": "", "stored": cc.STORED[1]}, "", session_wanted=False)
        self.assertEqual(len(found), 1)
        self.assertIn("sign-in would be lost", found[0])

    def test_lost_storage(self):
        self.assertEqual(len(cc.kept_problems("update", dict(KEPT, stored=None), cc.LASTING, False)), 1)

    def test_a_session_cookie_that_outlived_its_session(self):
        both = f"{cc.LASTING}; {cc.SESSION}"
        self.assertEqual(len(cc.kept_problems("restart", dict(KEPT, cookie=both), both, False)), 1)

    def test_the_site_is_made_up(self):
        self.assertTrue(cc.HOST.endswith(".test"))
        self.assertIn("made-up", cc.LASTING)


if __name__ == "__main__":
    unittest.main()
