# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Native ad blocking, HTML filtering, response headers and $replace: the offline check (ROADMAP P5.66)."""
import unittest

from tools.qa import adblock_htmlfilter_check as hc


class StepTests(unittest.TestCase):
    def test_html(self):
        self.assertEqual(hc.html_problems({"detector": None, "inPage": False, "kept": "x"}), [])
        self.assertEqual(len(hc.html_problems({"detector": "thoron-detector", "inPage": True, "kept": None})), 2)

    def test_stay_and_replace(self):
        self.assertEqual(hc.stay_problems("meta", "/meta.html", "/meta.html"), [])
        self.assertEqual(len(hc.stay_problems("meta", "/gone.html", "/meta.html")), 1)
        new = {"kept": "thoronNewWord", "word": "thoronNewWord", "lib": "thoronNewWord"}
        self.assertEqual(hc.replace_problems(new), [])
        self.assertEqual(len(hc.replace_problems({**new, "lib": "thoronOldWord"})), 1)

    def test_logger_and_others(self):
        rows = ["##^script:has-text(thoron-detector)", "$replace=/thoronOldWord/"]
        self.assertEqual(hc.logger_problems(rows), [])
        self.assertEqual(len(hc.logger_problems([])), 2)
        self.assertEqual(hc.other_problems("other", {"detector": "thoron-detector", "kept": "thoronOldWord"}), [])
        self.assertEqual(len(hc.other_problems("other", {"detector": None, "kept": "thoronOldWord"})), 1)

    def test_structure(self):
        gone = {"structured": None, "gtm": None}
        ran = {"structured": "thoron-structure", "gtm": "thoron-gtm"}
        self.assertEqual(hc.structure_problems(gone, ran), [])
        self.assertEqual(len(hc.structure_problems(ran, gone)), 4)
        self.assertIn('href="/recipes/1"', hc.RECIPES)

    def test_the_rules_and_pages(self):
        self.assertIn(f"{hc.SPARED}#@#^script:has-text(thoron-detector)", hc.MY_FILTERS)
        self.assertIn("thoron-detector", hc.PAGE)
        self.assertIn('http-equiv="refresh"', hc.META_PAGE)


if __name__ == "__main__":
    unittest.main()
