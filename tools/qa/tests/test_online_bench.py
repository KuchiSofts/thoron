# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Tests of the parts of online_bench.py that do not need a browser or the network."""
import unittest

from tools.qa import online_bench as ob


class ScoreTests(unittest.TestCase):
    def test_the_first_number_is_the_score(self):
        self.assertEqual(ob.score_of("23.4"), 23.4)
        self.assertEqual(ob.score_of("1,234.5 ± 2.1"), 1234.5)       # a comma groups thousands
        self.assertEqual(ob.score_of("312.07 ± 1.3"), 312.07)
        self.assertEqual(ob.score_of("Score: 1612"), 1612.0)
        self.assertIsNone(ob.score_of(""))
        self.assertIsNone(ob.score_of("Running..."))

    def test_the_three_suites(self):
        self.assertEqual(sorted(ob.SUITES), ["jetstream2", "motionmark", "speedometer3"])
        for suite in ob.SUITES.values():
            self.assertTrue(suite["url"].startswith("https://browserbench.org/"))

    def test_a_covered_window_is_not_slowed_down(self):
        self.assertIn("--disable-backgrounding-occluded-windows", ob.KEEP_RENDERING)
        self.assertIn("--disable-renderer-backgrounding", ob.KEEP_RENDERING)

    def test_summary(self):
        s = ob.summarise([10.0, 11.0, 12.0])
        self.assertEqual((s["median"], s["runs"]), (11.0, 3))
        self.assertAlmostEqual(s["spread_pct"], 18.2, places=1)


if __name__ == "__main__":
    unittest.main()
