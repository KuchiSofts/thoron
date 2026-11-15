# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Native ad blocking, filter list updates from the real list servers: the online check (ROADMAP P5.70)."""
import unittest

from tools.qa import adblock_live_update_check as lc

LISTS = [{"id": "easylist", "enabled": True, "note": "updated", "rules": 78000},
         {"id": "urlhaus-1", "enabled": True, "note": "unchanged", "rules": 109000},
         {"id": "off-list", "enabled": False, "note": "", "rules": 0}]


class StepTests(unittest.TestCase):
    def test_update(self):
        self.assertEqual(lc.update_problems("", LISTS), [])
        failed = [{**LISTS[0], "note": "kept: download failed"}, LISTS[1]]
        self.assertEqual(len(lc.update_problems("", failed)), 1)
        self.assertEqual(len(lc.update_problems("No list could be downloaded.", LISTS)), 1)
        self.assertEqual(len(lc.update_problems("", [LISTS[2]])), 1)

    def test_rules(self):
        self.assertEqual(lc.rules_problems(LISTS), [])
        few = [{**LISTS[0], "rules": 12}, {**LISTS[1], "rules": 50}]
        self.assertEqual(len(lc.rules_problems(few)), 3)


if __name__ == "__main__":
    unittest.main()
