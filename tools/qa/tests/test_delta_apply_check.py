# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Tests of the parts of delta_apply_check.py that do not need the updater."""
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools.qa import delta_apply_check as dc


class HelperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_tree_hashes_and_links(self):
        src = self.tmp / "src"
        (src / "a").mkdir(parents=True)
        (src / "a" / "x.bin").write_bytes(b"x")
        (src / "y.bin").write_bytes(b"y")
        dc.link_tree(src, self.tmp / "dst")
        self.assertEqual(dc.tree_hashes(src), dc.tree_hashes(self.tmp / "dst"))
        self.assertEqual(sorted(dc.tree_hashes(src)), ["a/x.bin", "y.bin"])

    def test_a_damaged_copy_changes_only_what_it_is_told(self):
        delta = self.tmp / "d.delta"
        with zipfile.ZipFile(delta, "w") as z:
            z.writestr("delta.json", "{}")
            z.writestr("patch/1", b"abc")
        out = dc.damaged(delta, self.tmp / "e.delta", lambda name, data: b"zzz" if name == "patch/1" else data)
        with zipfile.ZipFile(out) as z:
            self.assertEqual(z.read("delta.json"), b"{}")
            self.assertEqual(z.read("patch/1"), b"zzz")


if __name__ == "__main__":
    unittest.main()
