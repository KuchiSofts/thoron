# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Native ad blocking, the theme of its pages: the offline check (ROADMAP P5.59)."""
import unittest

from tools.qa import adblock_theme_check as tc


class ColourTests(unittest.TestCase):
    LIGHT_TEXT, DARK_TEXT = "rgb(230, 230, 234)", "rgb(31, 31, 36)"

    def test_a_page_is_told_by_its_text(self):
        self.assertEqual(tc.kind_of(self.LIGHT_TEXT), tc.DARK)
        self.assertEqual(tc.kind_of(self.DARK_TEXT), tc.LIGHT)
        self.assertEqual(tc.kind_of("rgba(255, 255, 255, 0.87)"), tc.DARK)
        self.assertEqual(tc.kind_of("color(srgb 0.12 0.12 0.14)"), tc.LIGHT)
        self.assertEqual(tc.kind_of("canvastext"), "")

    def test_as_wanted(self):
        self.assertEqual(tc.colour_problems("dark", "menu", {"theme": "dark", "text": self.LIGHT_TEXT}, tc.DARK,
                                            "dark"), [])
        self.assertEqual(tc.colour_problems("auto", "menu", {"theme": "", "text": self.DARK_TEXT}, tc.LIGHT, ""), [])

    def test_what_differs_is_named(self):
        found = tc.colour_problems("dark", "settings", {"theme": "", "text": self.DARK_TEXT}, tc.DARK, "dark")
        self.assertEqual(len(found), 2)
        self.assertIn("is light, not dark", found[0])

    def test_the_pages(self):
        self.assertEqual(set(tc.PAGES), {"settings", "menu"})
        self.assertIn("data-theme", tc.READ)


if __name__ == "__main__":
    unittest.main()
