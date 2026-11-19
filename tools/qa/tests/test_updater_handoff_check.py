# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Tests of the parts of updater_handoff_check.py that do not need the updater program."""
import hashlib
import unittest

from tools.qa import updater_handoff_check as hc


class ListingTests(unittest.TestCase):
    def test_the_files_as_the_updater_takes_them(self):
        files = hc.listing({"thoron_update.exe": b"b", "thoron.exe": b"aa"})
        self.assertEqual([f["path"] for f in files], ["thoron.exe", "thoron_update.exe"])
        self.assertEqual(files[0], {"path": "thoron.exe", "size": 2, "sha256": hashlib.sha256(b"aa").hexdigest()})

    def test_a_tampered_program_has_the_same_length_and_another_hash(self):
        for data in (b"\0\0\0\0", b"MZ" + bytes(1000), b"x"):
            with self.subTest(size=len(data)):
                changed = hc.tampered(data)
                self.assertEqual(len(changed), len(data))
                self.assertNotEqual(hashlib.sha256(changed).digest(), hashlib.sha256(data).digest())


if __name__ == "__main__":
    unittest.main()
