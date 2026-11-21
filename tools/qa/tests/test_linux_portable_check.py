# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""The Linux portable package on a clean Ubuntu machine (ROADMAP P2.9, P3.12): the reading of the results."""
import tempfile
import unittest
from pathlib import Path

from tools.qa import linux_portable_check as check
from tools.qa.tests.test_linux_package_check import SANDBOX


def write(folder: Path, files: dict) -> None:
    for name, text in files.items():
        if text is not None:
            (folder / name).write_text(text, encoding="utf-8")


def good() -> dict:
    return {"reached": "done", "deps_exit": "0", "unpack_exit": "0", "first-ran": "running",
            "first-version.json": '{"Browser": "Chrome/158.0.8127.65"}', "profile-made": "yes",
            "moved-ran": "running", "moved-profile": "yes", "sandbox.txt": SANDBOX}


class ProblemsTests(unittest.TestCase):
    def found(self, changes: dict | None = None) -> dict:
        with tempfile.TemporaryDirectory() as d:
            write(Path(d), {**good(), **(changes or {})})
            return check.problems(Path(d))

    def test_a_good_run_passes(self):
        self.assertEqual({k: v for k, v in self.found().items() if v}, {})

    def test_each_failure_is_named(self):
        self.assertTrue(self.found({"first-ran": None})["starts"])
        self.assertTrue(self.found({"config-thoron": "yes"})["starts"])
        self.assertTrue(self.found({"moved-profile": None})["moved"])
        self.assertTrue(self.found({"sandbox.txt": ""})["sandbox"])

    def test_the_folders_have_spaces_and_other_letters(self):
        for name in (check.FOLDER, check.MOVED):
            self.assertIn(" ", name)
            self.assertTrue(any(ord(c) > 127 for c in name))
        self.assertNotIn("__FOLDER__", check.SCRIPT.replace("__FOLDER__", check.FOLDER))


if __name__ == "__main__":
    unittest.main()
