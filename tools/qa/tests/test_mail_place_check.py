# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Thoron M-Notifier's envelope: where it is and what it says (ROADMAP P5.76)."""
import unittest

from tools.qa import mail_place_check as mp


def button(name, x, y=10, w=34, h=34):
    return {"name": name, "x": x, "y": y, "w": w, "h": h}


ADDRESS = button("Thoron M-Notifier: 3 unread", 500, y=14, w=24, h=24)
TOOLBAR = button("Thoron M-Notifier: 3 unread", 700)


class StepTests(unittest.TestCase):
    def test_envelopes_are_told_apart_by_height(self):
        self.assertEqual(mp.envelopes([ADDRESS, TOOLBAR, button("Back", 10)]), (ADDRESS, TOOLBAR))
        self.assertEqual(mp.envelopes([button("Thoron adblock: on", 600)]), (None, None))

    def test_place(self):
        self.assertEqual(mp.place_problems("toolbar", None, TOOLBAR), [])
        self.assertEqual(mp.place_problems("address", ADDRESS, None), [])
        self.assertEqual(mp.place_problems("both", ADDRESS, TOOLBAR), [])
        self.assertTrue(mp.place_problems("toolbar", ADDRESS, TOOLBAR))
        self.assertTrue(mp.place_problems("both", None, TOOLBAR))

    def test_says(self):
        self.assertEqual(mp.says_problems("x", "Thoron M-Notifier: 3 unread", "Thoron M-Notifier: 3 unread"), [])
        self.assertTrue(mp.says_problems("x", "Thoron M-Notifier: 1 new, 3 unread", "Thoron M-Notifier: 3 unread"))

    def test_toolbar_position(self):
        menu = button("Thoron", 820)
        ext = button("Extensions", 740)
        after_address = [ADDRESS, button("Thoron M-Notifier: 3 unread", 660), ext, menu]
        self.assertEqual(mp.position_problems("toolbar-position", "address", after_address), [])
        self.assertTrue(mp.position_problems("toolbar-position", "menu", after_address))
        next_to_menu = [ADDRESS, ext, button("Thoron M-Notifier: 3 unread", 780), menu]
        self.assertEqual(mp.position_problems("toolbar-position", "menu", next_to_menu), [])
        self.assertEqual(mp.position_problems("toolbar-position", "extensions", next_to_menu), [])
        last = [ADDRESS, ext, menu, button("Thoron M-Notifier: 3 unread", 900)]
        self.assertTrue(mp.position_problems("toolbar-position", "extensions", last))
        self.assertTrue(mp.position_problems("toolbar-position", "address", [ADDRESS]))

    def test_address_position(self):
        star = button("Bookmark this tab", 540, y=14, w=24, h=24)
        at_end = [star, button("Thoron M-Notifier: 3 unread", 570, y=14, w=24, h=24), TOOLBAR]
        self.assertEqual(mp.position_problems("address-position", "end", at_end), [])
        self.assertTrue(mp.position_problems("address-position", "start", at_end))
        self.assertTrue(mp.position_problems("address-position", "icons", at_end))
        first = [ADDRESS, star, TOOLBAR]
        self.assertEqual(mp.position_problems("address-position", "start", first), [])
        self.assertEqual(mp.position_problems("address-position", "icons", first), [])
        self.assertTrue(mp.position_problems("address-position", "end", [TOOLBAR]))

    def test_the_security_chip_is_not_one_of_the_icons(self):
        chip = button("View site information", 120, y=14, w=24, h=24)
        star = button("Bookmark this tab", 530, y=14, w=24, h=24)
        self.assertEqual(mp.trailing_icons([chip, ADDRESS, star], ADDRESS), [ADDRESS, star])
        self.assertEqual(mp.position_problems("address-position", "start", [chip, ADDRESS, star, TOOLBAR]), [])


if __name__ == "__main__":
    unittest.main()
