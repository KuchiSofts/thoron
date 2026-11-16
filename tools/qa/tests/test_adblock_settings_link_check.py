# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Thoron adblock in the side menu of chrome://settings: the offline check (ROADMAP P5.30)."""
import unittest

from tools.qa import adblock_settings_link_check as sl

GOOD = {"shown": True, "text": "Thoron adblock", "href": "chrome://adblock", "target": "_blank", "icon": True}


class StepTests(unittest.TestCase):
    def test_shown(self):
        self.assertEqual(sl.shown_problems(GOOD), [])
        self.assertTrue(sl.shown_problems(None))
        self.assertTrue(sl.shown_problems(dict(GOOD, shown=False)))
        self.assertTrue(sl.shown_problems(dict(GOOD, text="Ads")))
        self.assertTrue(sl.shown_problems(dict(GOOD, target=None)))
        self.assertTrue(sl.shown_problems(dict(GOOD, icon=False)))

    def test_opens(self):
        self.assertEqual(sl.opens_problems(["chrome://settings/", "chrome://adblock/"]), [])
        self.assertTrue(sl.opens_problems(["chrome://settings/"]))

    def test_hidden(self):
        self.assertEqual(sl.hidden_problems(None), [])
        self.assertEqual(sl.hidden_problems(dict(GOOD, shown=False)), [])
        self.assertTrue(sl.hidden_problems(GOOD))

    def test_the_entry_s_middle_is_found_for_the_click(self):
        self.assertIn("getBoundingClientRect", sl.FIND)
        self.assertNotIn("link.click()", sl.FIND)


if __name__ == "__main__":
    unittest.main()
