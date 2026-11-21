# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""The install guide's SmartScreen step (ROADMAP D.2): the reading of the results."""
import unittest

from tools.qa import sandbox_smartscreen_check as check


class ProblemsTests(unittest.TestCase):
    def test_the_warning_and_run_anyway_pass(self):
        found = {"marked": "[ZoneTransfer]\nZoneId=3", "warning": True, "more_info": True, "run_anyway": True,
                 "installer_started": True}
        self.assertEqual(check.problems(found), [])

    def test_no_warning_but_the_installer_started_passes(self):
        self.assertEqual(check.problems({"marked": "ZoneId=3", "warning": False, "started_without_warning": True}), [])

    def test_each_failure_is_named(self):
        base = {"marked": "ZoneId=3", "warning": True, "more_info": True, "run_anyway": True, "installer_started": True}
        self.assertEqual(len(check.problems({**base, "run_anyway": False})), 1)
        self.assertEqual(len(check.problems({**base, "installer_started": False})), 1)
        self.assertEqual(len(check.problems({"marked": "", "warning": False})), 2)

    def test_the_script_names_the_release_address(self):
        self.assertIn(check.RELEASE_URL, check.RUN)
        self.assertNotIn("__URL__", check.RUN)


if __name__ == "__main__":
    unittest.main()
