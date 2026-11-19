# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Tests of the parts of site_crash_check.py that do not need a browser."""
import unittest

from tools.qa import site_crash_check as sc


class CrashTests(unittest.TestCase):
    def test_only_a_crash_counts(self):
        self.assertTrue(sc.crashed_in_error("Runtime.evaluate: {'code': -32000, 'message': 'Target crashed'}"))
        self.assertFalse(sc.crashed_in_error("Runtime.evaluate: Execution context was destroyed."))
        self.assertTrue(all(u.startswith("https://discord.com/") for u in sc.DEFAULT_URLS))


if __name__ == "__main__":
    unittest.main()
