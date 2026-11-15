# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Windows Security prompts brought to the front: the offline check (ROADMAP P5.74)."""
import unittest

from tools.qa import windows_security_check as wc


class StepTests(unittest.TestCase):
    def test_brought_to_the_front(self):
        self.assertEqual(wc.zorder_problems({"prompt": 3, "browser": 7, "other": 8}), [])

    def test_left_behind(self):
        found = wc.zorder_problems({"prompt": 8, "browser": 7, "other": 9})
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0].startswith("front:"))

    def test_an_ordinary_window_is_not_raised(self):
        found = wc.zorder_problems({"prompt": 3, "browser": 7, "other": 2})
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0].startswith("others:"))

    def test_windows_not_found(self):
        self.assertIn("not found", wc.zorder_problems({"browser": 1})[0])

    def test_the_window_kind_windows_uses(self):
        self.assertEqual(wc.PROMPT_CLASS, "Credential Dialog Xaml Host")


if __name__ == "__main__":
    unittest.main()
