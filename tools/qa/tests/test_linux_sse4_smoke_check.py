# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Tests for tools/qa/linux_sse4_smoke_check.py: what its results mean."""
import unittest

from tools.qa import linux_sse4_smoke_check as c

GOOD = {"qemu_exit": "0", "sse4_exit": "0", "avx2_exit": "0", "version_exit": "0",
        "version.txt": "Thoron 158.0.8127.65", "dom-first.txt": "<p id=\"x\">sse4 smoke 42</p>",
        "dom-second.txt": "<p id=\"x\">sse4 smoke 42</p>", "first-exit": "0", "second-exit": "0",
        "dom-control.txt": "", "control-exit": "132"}


class ProblemsTest(unittest.TestCase):
    def found(self, **changes) -> dict:
        files = dict(GOOD, **changes)
        return c.problems(lambda name: files.get(name, ""))

    def test_a_good_run_has_none(self):
        self.assertEqual({k: v for k, v in self.found().items() if v}, {})

    def test_each_failure_lands_in_its_step(self):
        for step, change in (("install", {"sse4_exit": "100"}), ("version", {"version_exit": "132"}),
                             ("page", {"dom-first.txt": ""}),
                             ("control", {"dom-control.txt": "<p>sse4 smoke 42</p>"})):
            got = self.found(**change)
            self.assertEqual([s for s, v in got.items() if v], [step], change)


if __name__ == "__main__":
    unittest.main()
