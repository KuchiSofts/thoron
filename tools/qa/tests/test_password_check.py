# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Tests of the parts of password_check.py that do not need a browser."""
import unittest

from tools.qa import password_check as pc


class StepTests(unittest.TestCase):
    def test_listed(self):
        entries = [{"user": "a", "where": "[]"}, {"user": "b", "where": "[]"}]
        self.assertEqual(pc.listed_problems("kept", entries, ["a", "b"]), [])
        self.assertIn("c is not in", pc.listed_problems("kept", entries, ["a", "c"])[0])
        self.assertIn("could not be read", pc.listed_problems("kept", None, ["a"])[0])

    def test_stored_encrypted_and_never_in_plain_text(self):
        secret = "made-up-secret-1"
        good = [("http://127.0.0.1:1/login", "a", b"v10" + b"\x8a\x13" * 12)]
        self.assertEqual(pc.stored_problems(good, {"a": secret}), [])
        self.assertEqual(pc.stored_problems([("u", "a", b"v20" + b"\x00" * 30)], {"a": secret}), [])
        plain = [("u", "a", b"v10" + secret.encode())]
        self.assertIn("plain text", " ".join(pc.stored_problems(plain, {"a": secret})))
        wide = [("u", "a", secret.encode("utf-16-le"))]
        found = " ".join(pc.stored_problems(wide, {"a": secret}))
        self.assertIn("plain text", found)
        self.assertIn("not stored the way", found)
        self.assertIn("no row for b", pc.stored_problems(good, {"a": secret, "b": "x"})[0])

    def test_filled(self):
        self.assertEqual(pc.filled_problems({"user": True, "pass": True}), [])
        self.assertTrue(pc.filled_problems({"user": True, "pass": False}))
        self.assertTrue(pc.filled_problems(None))

    def test_the_page_and_the_names_are_made_up(self):
        self.assertTrue(pc.MANUAL_URL.startswith("https://login.example.com"))
        self.assertIn(b'type="password"', pc.LOGIN_PAGE)
        self.assertNotIn(b"http", pc.LOGIN_PAGE)        # the form posts to the local page only


if __name__ == "__main__":
    unittest.main()
