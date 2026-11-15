# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Native ad blocking, the blocker's shield in the address bar: the offline check (ROADMAP P5.52, P5.71)."""
import unittest

from tools.qa import adblock_icon_check as ic


class StepTests(unittest.TestCase):
    def test_icon_and_count(self):
        before = {"name": "Ad blocking: 0 blocked on this page"}
        after = {"name": "Ad blocking: 1 blocked on this page"}
        self.assertEqual(ic.icon_problems(before, after), [])
        self.assertIn("icon:", ic.icon_problems({}, after)[0])
        self.assertIn("count:", ic.icon_problems(before, before)[0])
        self.assertIn("count:", ic.icon_problems(before, {"name": "Ad blocking: off on this site"})[0])

    def test_menu_opens_and_closes_in_turn(self):
        self.assertEqual(ic.menu_problems([True, False, True, False, True, False], [True] * 6), [])
        self.assertIn("did not open", ic.menu_problems([False] * 6, [True] * 6)[0])
        # what the browser did before the fix: opened once, then never again
        stuck = ic.menu_problems([True, False, False, False, False, False], [True] * 6)
        self.assertEqual(len(stuck), 1)
        self.assertIn("again:", stuck[0])
        self.assertIn("did not answer", ic.menu_problems([True, False], [True, False])[0])

    def test_the_ad_image(self):
        self.assertIn("http://ads.example/ad.png", ic.ad_image("ads.example"))

    def test_the_toolbar_shield_is_not_taken_for_the_address_bar_s(self):
        # the toolbar's is named "Ad blocking", with no colon
        self.assertFalse("Ad blocking".startswith(ic.ICON))
        self.assertTrue("Ad blocking: 2 blocked on this page".startswith(ic.ICON))


if __name__ == "__main__":
    unittest.main()
