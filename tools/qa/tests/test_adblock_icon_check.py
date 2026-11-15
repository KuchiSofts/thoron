# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Thoron adblock, its shield in the address bar and the toolbar: the offline check (ROADMAP P5.52, P5.71,
P5.72)."""
import unittest

from tools.qa import adblock_icon_check as ic


class StepTests(unittest.TestCase):
    def test_icon_and_count(self):
        before = {"name": "Thoron adblock: 0 blocked on this page"}
        after = {"name": "Thoron adblock: 1 blocked on this page"}
        self.assertEqual(ic.icon_problems(before, after), [])
        self.assertIn("icon:", ic.icon_problems({}, after)[0])
        self.assertIn("count:", ic.icon_problems(before, before)[0])
        self.assertIn("count:", ic.icon_problems(before, {"name": "Thoron adblock: off on this site"})[0])

    def test_a_closed_menu_opens_on_every_click(self):
        # in turn: open, closed by the next click, open again
        self.assertEqual(ic.menu_problems([(False, True), (True, False), (False, True)], [True] * 3), [])
        # it closes by itself (lost focus off the screen): every click opens it again
        self.assertEqual(ic.menu_problems([(False, True)] * 6, [True] * 6), [])
        self.assertIn("did not open", ic.menu_problems([(False, False)] * 6, [True] * 6)[0])
        # what the browser did: opened once, then the kept page never showed again
        stuck = ic.menu_problems([(False, True)] + [(False, False)] * 5, [True] * 6)
        self.assertEqual(len(stuck), 1)
        self.assertIn("click(s) [2, 3, 4, 5, 6]", stuck[0])
        self.assertIn("did not answer", ic.menu_problems([(False, True), (True, False)], [True, False])[0])

    def test_the_ad_image(self):
        self.assertIn("http://ads.example/ad.png", ic.ad_image("ads.example"))

    def test_the_two_shields_are_told_apart_by_where_they_are(self):
        # as seen in a test browser: the address bar's (24 px wide), then the toolbar's (34 px)
        address = {"name": "Thoron adblock: 0 blocked on this page", "x": -3383, "w": 24}
        toolbar = {"name": "Thoron adblock: 0 blocked on this page", "x": -3269, "w": 34}
        self.assertTrue(ic.is_toolbar(toolbar, toolbar))
        self.assertFalse(ic.is_toolbar(address, toolbar))
        self.assertFalse(ic.is_toolbar(toolbar, None))
        self.assertEqual(ic.where([address, toolbar], toolbar), (True, True))
        self.assertEqual(ic.where([toolbar], toolbar), (False, True))
        # without the toolbar's, the address bar's moves right, still not where the toolbar's was
        self.assertEqual(ic.where([dict(address, x=-3347)], toolbar), (True, False))
        self.assertEqual(ic.where([], toolbar), (False, False))
        self.assertTrue(toolbar["name"].startswith(ic.ICON))

    def test_where_the_shield_is(self):
        self.assertEqual(ic.place_problems("both", True, True), [])
        self.assertEqual(ic.place_problems("address", True, False), [])
        self.assertEqual(ic.place_problems("toolbar", False, True), [])
        self.assertIn("still has a", ic.place_problems("toolbar", True, True)[0])
        self.assertIn("has no", ic.place_problems("address", False, False)[0])
        self.assertEqual(len(ic.place_problems("both", False, False)), 2)
        # the last place set is the default, both
        self.assertEqual(ic.PLACES[-1], "both")
        self.assertIn("'toolbar'", ic.SET_PLACE % "toolbar")

    def test_a_slow_menu(self):
        self.assertEqual(ic.slow_problems([40, 120, 900]), [])
        self.assertIn("[1400]", ic.slow_problems([40, 1400])[0])
        self.assertEqual(ic.slow_problems([]), [])


if __name__ == "__main__":
    unittest.main()
