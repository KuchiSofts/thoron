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

    # the buttons of a test browser's window as seen with the defaults (P5.73)
    ROW = [{"name": "Not secure", "x": -3838, "y": -3949, "w": 91, "h": 24},
           {"name": "Thoron adblock: 0 blocked on this page", "x": -3395, "y": -3949, "w": 24, "h": 24},
           {"name": "Share", "x": -3363, "y": -3949, "w": 24, "h": 24},
           {"name": "Bookmark this tab", "x": -3331, "y": -3949, "w": 24, "h": 24},
           {"name": "Thoron adblock: 0 blocked on this page", "x": -3286, "y": -3954, "w": 34, "h": 34},
           {"name": "Thoron Labs - pinned", "x": -3250, "y": -3954, "w": 34, "h": 34},
           {"name": "Sign in to Thoron?", "x": -3193, "y": -3954, "w": 146, "h": 34},
           {"name": "Thoron", "x": -3042, "y": -3955, "w": 36, "h": 36},
           {"name": "Minimize", "x": -3137, "y": -3999, "w": 45, "h": 39}]

    def moved(self, index, x):
        row = [dict(b) for b in self.ROW]
        row[index]["x"] = x
        return row

    def test_where_in_the_toolbar(self):
        self.assertEqual(ic.position_problems("toolbar-position", "address", self.ROW), [])
        self.assertEqual(ic.position_problems("toolbar-position", "extensions", self.ROW), [])
        self.assertIn("next to the menu", ic.position_problems("toolbar-position", "menu", self.ROW)[0])
        # moved next to the menu: last but one
        self.assertEqual(ic.position_problems("toolbar-position", "menu", self.moved(4, -3080)), [])
        self.assertIn("button 2", ic.position_problems("toolbar-position", "address", self.moved(4, -3220))[0])

    def test_where_in_the_address_bar(self):
        self.assertEqual(ic.position_problems("address-position", "start", self.ROW), [])
        self.assertEqual(ic.position_problems("address-position", "icons", self.ROW), [])
        self.assertIn("far end", ic.position_problems("address-position", "end", self.ROW)[0])
        at_end = self.moved(1, -3300)
        self.assertEqual(ic.position_problems("address-position", "end", at_end), [])
        self.assertIn("far end", ic.position_problems("address-position", "icons", at_end)[0])
        self.assertIn("no shield", ic.position_problems("address-position", "end", self.ROW[2:4])[0])

    @staticmethod
    def capture(boxes, width=150, height=40):
        """A picture of `width` x `height` px, grey, with white boxes (x, y, w, h) drawn on it."""
        data = bytearray(bytes((60, 60, 60, 255)) * width * height)
        for x0, y0, w, h in boxes:
            for y in range(y0, y0 + h):
                for x in range(x0, x0 + w):
                    data[(y * width + x) * 4:(y * width + x) * 4 + 3] = b"\xff\xff\xff"
        return {"left": 0, "top": 0, "w": width, "h": height, "data": bytes(data)}

    def test_the_size_and_the_line(self):
        shield = {"name": "Thoron adblock: 2 blocked on this page", "x": 4, "y": 8, "w": 24, "h": 24}
        star = {"name": "Bookmark this tab", "x": 36, "y": 8, "w": 24, "h": 24}
        tool = {"name": "Thoron adblock: 2 blocked on this page", "x": 66, "y": 3, "w": 34, "h": 34}
        pin = {"name": "Thoron Labs - pinned", "x": 104, "y": 3, "w": 34, "h": 34}
        row = [shield, star, tool, pin]
        toolbar_ink = [(76, 12, 14, 16), (113, 12, 16, 16)]
        # all of them about 16 px tall, in the middle of their place
        good = self.capture([(9, 12, 14, 16), (42, 12, 12, 16), *toolbar_ink])
        self.assertEqual(ic.size_problems(row, good), [])
        # what Thoron did before P5.73: 2 px right of and below its place
        low = self.capture([(11, 14, 14, 16), (42, 12, 12, 16), *toolbar_ink])
        found = ic.size_problems(row, low)
        self.assertTrue(any("address bar's shield is drawn +2.0 px off the line" in f for f in found), found)
        self.assertTrue(any("sideways" in f for f in found), found)
        self.assertFalse(any("toolbar" in f for f in found), found)
        # smaller than the icon next to it
        small = self.capture([(11, 15, 10, 10), (42, 12, 12, 16), *toolbar_ink])
        self.assertTrue(any("10 px tall" in f for f in ic.size_problems(row, small)))
        self.assertEqual(ic.ink(good, shield)[2:], (14, 16))
        self.assertIn("address bar 14x16 px", ic.size_summary(row, good))
        self.assertIn("no shield in the toolbar", ic.size_problems([shield, star], good)[0])

    def test_a_slow_menu(self):
        self.assertEqual(ic.slow_problems([40, 120, 900]), [])
        self.assertIn("[1400]", ic.slow_problems([40, 1400])[0])
        self.assertEqual(ic.slow_problems([]), [])


if __name__ == "__main__":
    unittest.main()
