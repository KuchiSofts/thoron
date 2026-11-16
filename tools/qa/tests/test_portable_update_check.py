# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Tests of the parts of portable_update_check.py that do not need a browser."""
import unittest

from tools.qa import portable_update_check as pu


class UpdateOutputTests(unittest.TestCase):
    def test_an_update_says_each_step(self):
        good = "handed off to the updater of 158.0.8127.3010\ndone\n\nlauncher: current\n"
        self.assertEqual(pu.update_problems(0, good, "158.0.8127.3010"), [])

    def test_a_missing_step_or_a_failure_is_found(self):
        self.assertEqual(len(pu.update_problems(0, "done\nlauncher: current\n", "158.0.8127.3010")), 1)
        self.assertEqual(len(pu.update_problems(0, "handed off to the updater of 158.0.8127.3010\ndone\n"
                                                   "launcher: kept\n", "158.0.8127.3010")), 1)
        self.assertGreaterEqual(len(pu.update_problems(12, "bad_files\n", "158.0.8127.3010")), 2)


class RestoreTests(unittest.TestCase):
    def test_a_restored_profile_is_the_snapshot_byte_for_byte(self):
        import hashlib
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            profile = Path(d)
            (profile / "Default").mkdir()
            (profile / "Default" / "Preferences").write_bytes(b"{}")
            held = {"Default/Preferences": hashlib.sha256(b"{}").hexdigest(), "snapshot.json": "x"}
            self.assertEqual(pu.restored_problems(held, profile), [])
            (profile / "Default" / "Preferences").write_bytes(b"{ }")
            self.assertEqual(len(pu.restored_problems(held, profile)), 1)
            self.assertEqual(len(pu.restored_problems({"Default/History": "0" * 64}, profile)), 1)


if __name__ == "__main__":
    unittest.main()
