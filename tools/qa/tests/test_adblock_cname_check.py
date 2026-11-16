# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Thoron adblock's CNAME uncloaking: the offline check (ROADMAP P5.18)."""
import json
import unittest

from tools.qa import adblock_cname_check as cc

SITE = cc.SITE


class StepTests(unittest.TestCase):
    def test_the_hosts_and_their_names(self):
        self.assertEqual(cc.ALIASES[f"metrics.{SITE}"], cc.TRACKER)
        self.assertIn(f"||{cc.TRACKER}^", cc.MY_FILTERS)
        self.assertIn(f"@@||spared.{SITE}^", cc.MY_FILTERS)
        self.assertTrue(cc.PNG.startswith(b"\x89PNG"))

    def test_the_page_s_script(self):
        script = cc.load_images({"a": "http://x.test/a.png"})
        self.assertIn(json.dumps({"a": "http://x.test/a.png"}), script)
        self.assertIn("'blocked'", script)

    def test_hidden(self):
        seen = [f"metrics.{SITE}/p1.png"]
        self.assertEqual(cc.hidden_problems({"metrics": "blocked"}, seen), [])
        self.assertTrue(cc.hidden_problems({"metrics": "loaded"}, seen))
        self.assertTrue(cc.hidden_problems({"metrics": "blocked"}, []))

    def test_learned(self):
        self.assertEqual(cc.learned_problems({"again": "blocked"}, [f"metrics.{SITE}/p1.png"]), [])
        self.assertTrue(cc.learned_problems({"again": "blocked"}, [f"metrics.{SITE}/p2.png"]))
        self.assertTrue(cc.learned_problems({"again": "loaded"}, []))

    def test_kept(self):
        self.assertEqual(cc.kept_problems({"static": "loaded", "img": "loaded", "spared": "loaded"}), [])
        self.assertEqual(len(cc.kept_problems({"static": "loaded", "img": "blocked"})), 2)

    def test_cost(self):
        self.assertEqual(cc.middle([3.0, 1.0, 2.0]), 2.0)
        self.assertEqual(cc.middle([1.0, 2.0, 3.0, 4.0]), 2.5)
        self.assertEqual(cc.cost_problems({"named": [5.0, 6.0], "plain": [4.0, 5.0]}), [])
        self.assertTrue(cc.cost_problems({"named": [40.0, 50.0], "plain": [4.0, 5.0]}))
        self.assertTrue(cc.cost_problems({"named": [], "plain": [4.0]}))
        self.assertIn("plain.example.com", cc.timed_images("static.example.com", "plain.example.com", 3))

    def test_off(self):
        self.assertEqual(cc.off_problems({"metrics": "loaded"}, {"metrics": "blocked"}), [])
        self.assertEqual(len(cc.off_problems({"metrics": "blocked"}, {"metrics": "loaded"})), 2)


if __name__ == "__main__":
    unittest.main()
