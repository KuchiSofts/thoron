# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Tests for tools/qa/linux_arm64_smoke_check.py: what its results mean."""
import unittest

from tools.qa import linux_arm64_smoke_check as c

GOOD = {"qemu_exit": "0", "install_exit": "0", "file.txt": "ELF 64-bit LSB pie executable, ARM aarch64",
        "version_exit": "0", "version.txt": "Thoron 158.0.8127.65", "dom-first.txt": "<p id=\"x\">arm64 smoke 42</p>",
        "dom-second.txt": "<p id=\"x\">arm64 smoke 42</p>", "first-exit": "0", "second-exit": "0"}


class ProblemsTest(unittest.TestCase):
    def found(self, **changes) -> dict:
        files = dict(GOOD, **changes)
        return c.problems(lambda name: files.get(name, ""))

    def test_a_good_run_has_none(self):
        self.assertEqual({k: v for k, v in self.found().items() if v}, {})

    def test_each_failure_lands_in_its_step(self):
        for step, change in (("install", {"install_exit": "100"}), ("install", {"file.txt": "ELF x86-64"}),
                             ("version", {"version_exit": "133"}), ("page", {"dom-second.txt": ""})):
            got = self.found(**change)
            self.assertEqual([s for s, v in got.items() if v], [step], change)


if __name__ == "__main__":
    unittest.main()
