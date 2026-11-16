# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Widevine is not shipped and still works when needed: the online check's decisions (ROADMAP P2.6)."""
import unittest

from tools.qa import widevine_check as wc


class StepTests(unittest.TestCase):
    def test_absent(self):
        self.assertEqual(wc.absent_problems({"version": "0.0.0.0", "status": "new"}), [])
        self.assertTrue(wc.absent_problems(None))
        self.assertTrue(wc.absent_problems({"version": "4.10.2891.0"}))

    def test_fetched(self):
        self.assertEqual(wc.fetched_problems({"version": "4.10.2891.0"}), [])
        self.assertTrue(wc.fetched_problems({"version": "0.0.0.0"}))
        self.assertTrue(wc.fetched_problems(None))

    def test_keys(self):
        self.assertEqual(wc.keys_problems({"access": True, "message": 1234}), [])
        self.assertIn("NotSupportedError", wc.keys_problems({"access": False, "error": "NotSupportedError: x"})[0])
        self.assertTrue(wc.keys_problems({"access": True, "message": 0}))

    def test_plays(self):
        moving = [{"time": 0.0, "error": ""}, None, {"time": 3.2, "error": ""}]
        self.assertEqual(wc.plays_problems(moving), [])
        self.assertTrue(wc.plays_problems([None, None]))
        self.assertTrue(wc.plays_problems([{"time": 0.0, "error": ""}, {"time": 0.4, "error": ""}]))
        self.assertIn("failed", wc.plays_problems([{"time": 0.0, "error": "decode"}])[0])

    def test_the_component_asked_for_is_widevine_s(self):
        self.assertIn(wc.WIDEVINE_ID, wc.ASK)
        self.assertIn(wc.WIDEVINE_ID, wc.VERSION)


if __name__ == "__main__":
    unittest.main()
