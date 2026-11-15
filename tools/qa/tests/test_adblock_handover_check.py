# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Native ad blocking on by default and the hand-over from uBlock Origin: the offline check (ROADMAP P5.24)."""
import tempfile
import unittest
from pathlib import Path

from tools.qa import adblock_handover_check as hc


class StepTests(unittest.TestCase):
    def test_default(self):
        self.assertEqual(hc.default_problems(0, False, True), [])
        self.assertEqual(len(hc.default_problems(2, True, False)), 3)
        self.assertEqual(len(hc.default_problems(0, False, None)), 1)

    def test_both(self):
        self.assertEqual(hc.both_problems({"shown": True}, {"shown": False}, {"shown": False}), [])
        self.assertEqual(len(hc.both_problems({"shown": False}, {"shown": True}, {"shown": True})), 3)

    def test_installed_means_unpacked_into_the_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp)
            self.assertFalse(hc.installed(profile))
            folder = profile / "Default" / "Extensions" / hc.UBO_ID
            folder.mkdir(parents=True)
            self.assertFalse(hc.installed(profile))          # an empty folder is not an extension
            (folder / "1.75.0_0").mkdir()
            self.assertTrue(hc.installed(profile))


if __name__ == "__main__":
    unittest.main()
