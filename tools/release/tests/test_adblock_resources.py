# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Signed updates of Thoron adblock's scriptlets (ROADMAP P5.23): the release tool."""
import base64
import json
import unittest

from tools.release import adblock_resources as ar

RESOURCES = json.dumps([{"name": "noop.js", "aliases": [], "kind": {"mime": "application/javascript"},
                         "content": base64.b64encode(b"(function() {})();").decode("ascii")}])


class SignTests(unittest.TestCase):
    def setUp(self):
        self.private, self.public = ar.keygen()

    def test_a_signed_file_verifies_with_its_key(self):
        text = ar.sign(RESOURCES, "2026120100", self.private)
        self.assertTrue(text.startswith("thoron-adblock-resources 1\nserial: 2026120100\nsignature: "))
        self.assertTrue(text.endswith("\n\n" + RESOURCES))
        self.assertEqual(ar.verify(text, self.public), "2026120100")

    def test_a_change_anywhere_or_another_key_is_refused(self):
        text = ar.sign(RESOURCES, "2026120100", self.private)
        self.assertIsNone(ar.verify(text.replace("2026120100", "2026120199"), self.public))
        self.assertIsNone(ar.verify(text.replace("noop.js", "nooq.js"), self.public))
        self.assertIsNone(ar.verify(text, ar.keygen()[1]))
        self.assertIsNone(ar.verify("thoron-adblock-resources 1\nserial: 1\n\n[]", self.public))

    def test_only_resource_lists_and_ten_digit_serials_are_signed(self):
        with self.assertRaises(ValueError):
            ar.sign(RESOURCES, "20261201", self.private)
        with self.assertRaises(ValueError):
            ar.sign("{}", "2026120100", self.private)
        with self.assertRaises(ValueError):
            ar.sign(json.dumps([{"name": "x"}]), "2026120100", self.private)

    def test_the_public_key_as_cpp(self):
        self.assertEqual(ar.cpp_array(bytes([0, 255])), "{0x00, 0xff}")
        self.assertEqual(len(self.public), 32)


if __name__ == "__main__":
    unittest.main()
