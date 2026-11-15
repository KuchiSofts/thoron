# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Native ad blocking, its own switch for every site: the offline check (ROADMAP P5.70)."""
import unittest

from tools.qa import adblock_power_check as pc


class StepTests(unittest.TestCase):
    def test_page(self):
        self.assertEqual(pc.page_problems("on", {"banner": "none", "asked": 0}, blocking=True), [])
        self.assertEqual(pc.page_problems("off", {"banner": "block", "asked": 1}, blocking=False), [])
        self.assertEqual(len(pc.page_problems("on", {"banner": "block", "asked": 1}, blocking=True)), 2)
        self.assertEqual(len(pc.page_problems("off", {"banner": "none", "asked": 0}, blocking=False)), 2)

    def test_settings(self):
        on = {"blocking": True, "state": "Thoron adblock is on for every site."}
        self.assertEqual(pc.settings_problems("back", on, on=True, state="Thoron adblock is on"), [])
        self.assertEqual(len(pc.settings_problems("off", on, on=False, state="Thoron adblock is off")), 2)
        # a missing answer is not "on"
        self.assertEqual(len(pc.settings_problems("kept", {}, on=True)), 1)

    def test_menu(self):
        on = {"pill": "On", "pressed": "true", "pause": True, "state": ""}
        self.assertEqual(pc.menu_problems("menu", on, on=True), [])
        self.assertEqual(pc.menu_problems("menu", {**on, "pause": False}, on=True, pause=True), [])
        off = {"pill": "Off", "pressed": "false", "pause": True, "state": "Thoron adblock is off for every site."}
        self.assertEqual(pc.menu_problems("menu", off, on=False), [])
        self.assertEqual(len(pc.menu_problems("menu", {**off, "state": "Blocking is on for this site."},
                                              on=False)), 1)
        self.assertEqual(len(pc.menu_problems("menu", off, on=True)), 1)

    def test_while(self):
        self.assertEqual(pc.while_problems(1_000_060_000, 1_000_000_000), [])
        self.assertEqual(len(pc.while_problems(-1, 1_000_000_000)), 1)
        self.assertEqual(len(pc.while_problems(1_000_000_000 + 600_000, 1_000_000_000)), 1)
        self.assertEqual(len(pc.while_problems(None, 1_000_000_000)), 1)

    def test_the_page_has_what_the_rules_name(self):
        self.assertIn(f"http://{pc.AD_HOST}/ad.png", pc.PAGE)
        self.assertIn('class="banner"', pc.PAGE)
        self.assertIn(f"||{pc.AD_HOST}^", pc.FILTERS)
        self.assertTrue(pc.PNG.startswith(b"\x89PNG"))


if __name__ == "__main__":
    unittest.main()
