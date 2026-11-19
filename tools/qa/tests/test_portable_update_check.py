# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Tests of the parts of portable_update_check.py that do not need a browser."""
import tempfile
import unittest
import zipfile
from pathlib import Path

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


class PreviousReleaseTests(unittest.TestCase):
    def test_the_last_release_s_package_is_unpacked_and_its_version_read(self):
        with tempfile.TemporaryDirectory() as d:
            package = Path(d) / "thoron-158.0.8127.3010-win-x64-avx2-portable.zip"
            with zipfile.ZipFile(package, "w") as z:
                z.writestr("ThoronPortable/Application/current", "158.0.8127.3010\n")
                z.writestr("ThoronPortable/Application/158.0.8127.3010/thoron.exe", b"MZ")
                z.writestr("../outside.txt", b"never outside")
            place = Path(d) / "place"
            self.assertEqual(pu.unpack_previous(package, place), "158.0.8127.3010")
            self.assertTrue((place / "ThoronPortable/Application/158.0.8127.3010/thoron.exe").is_file())
            self.assertFalse((Path(d) / "outside.txt").exists())

    def test_a_package_that_names_no_version_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            package = Path(d) / "bad.zip"
            with zipfile.ZipFile(package, "w") as z:
                z.writestr("ThoronPortable/Application/current", "../../x\n")
            with self.assertRaises(ValueError):
                pu.unpack_previous(package, Path(d) / "place")

    def test_the_report_release_py_reads(self):
        text = pu.report_text([], "158.0.8127.3020", "158.0.8127.3010", Path("thoron-158.0.8127.3010-p.zip"))
        self.assertIn("Build: 158.0.8127.3020\nFrom: 158.0.8127.3010\n", text)
        self.assertIn("Previous package: thoron-158.0.8127.3010-p.zip\n", text)
        self.assertTrue(text.endswith("PORTABLE UPDATE CHECK: PASSED\n"))
        self.assertIn("FAILED", pu.report_text(["x"], "1.2.3.4", "1.2.3.3", None))


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
