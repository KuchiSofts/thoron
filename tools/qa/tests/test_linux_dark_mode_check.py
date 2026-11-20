# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Thoron on Linux follows the desktop's light and dark style (ROADMAP P2.22): the reading of the probe's
results."""
import unittest

from tools.qa import linux_dark_mode_check as check


def found(dark_seen: dict | None = None) -> dict:
    light = {"page": "light", "settings": "light"}
    dark = {"page": "dark", "settings": "dark"}
    return {"steps": {"starts light": {"want": "light", "seen": light},
                      "goes dark": {"want": "dark", "seen": dark_seen or dark},
                      "back light": {"want": "light", "seen": light}}}


class ProblemsTests(unittest.TestCase):
    def test_a_browser_that_follows_the_style_passes(self):
        self.assertEqual(check.problems(found()), [])

    def test_a_page_or_settings_that_stays_light_is_found(self):
        self.assertEqual(len(check.problems(found({"page": "dark", "settings": "light"}))), 1)
        self.assertEqual(len(check.problems(found({"page": "light", "settings": "light"}))), 1)

    def test_a_missing_step_or_an_error_is_found(self):
        partial = found()
        del partial["steps"]["back light"]
        self.assertEqual(check.problems(partial), ["back light: not reached"])
        self.assertEqual(len(check.problems({"error": "no DevTools port", "steps": {}})), 4)

    def test_the_steps_switch_both_ways(self):
        self.assertEqual([s[1] for s in check.STEPS], ["default", "prefer-dark", "default"])


if __name__ == "__main__":
    unittest.main()
