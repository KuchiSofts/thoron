# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Tests of the parts of thoron_setup_check.py that do not need ThoronSetup."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tools.qa import thoron_setup_check as ts
from tools.update import manifest as mf


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_a_release_the_reference_tool_accepts(self):
        ts.release(self.tmp, b"MZ a stand-in")
        data = (self.tmp / "update.json").read_bytes()
        signature = (self.tmp / "update.json.sig").read_bytes()
        public = mf.public_key_of(__import__("hashlib").sha256(ts.TEST_KEY_PHRASE).digest())
        self.assertTrue(mf.signature_holds(data, signature, public))
        packages = json.loads(data)["packages"]
        self.assertEqual(packages["win-x64-avx2"]["installed"]["full"]["size"], len(b"MZ a stand-in"))
        ts.release(self.tmp / "f", b"x", forge=True)
        self.assertFalse(mf.signature_holds((self.tmp / "f" / "update.json").read_bytes(),
                                            (self.tmp / "f" / "update.json.sig").read_bytes(), public))

    def test_judge(self):
        self.assertTrue(ts.judge(0, "Thoron 0.1.2 is installed.", 0, "is installed"))
        self.assertFalse(ts.judge(5, "Thoron 0.1.2 is installed.", 0, "is installed"))
        self.assertFalse(ts.judge(0, "", 0, "is installed"))


if __name__ == "__main__":
    unittest.main()
