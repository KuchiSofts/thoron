# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Native ad blocking, the filter lists in the blocker's menu: the offline check (ROADMAP P5.71)."""
import unittest

from tools.qa import adblock_menulists_check as mc


class StepTests(unittest.TestCase):
    def test_shown(self):
        rows = [{"name": "EasyList", "box": True, "on": True, "remove": False, "n": "78,126"},
                {"name": "EasyPrivacy", "box": True, "on": True, "remove": False, "n": "56,631"}]
        seen = {"count": "(2 of 2 on)", "rows": rows}
        self.assertEqual(mc.shown_problems(seen), [])
        self.assertEqual(len(mc.shown_problems({"count": "", "rows": [{**rows[0], "box": False, "n": ""}]})), 4)
        self.assertEqual(mc.row(seen, "EasyPrivacy")["n"], "56,631")
        self.assertEqual(mc.row(seen, "nothing"), {})

    def test_the_added_list_is_a_list(self):
        self.assertTrue(mc.EXTRA_TEXT.startswith("! Title: "))
        self.assertIn("||", mc.EXTRA_TEXT)


if __name__ == "__main__":
    unittest.main()
