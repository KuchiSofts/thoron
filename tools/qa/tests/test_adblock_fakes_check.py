# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Thoron adblock, a blocked request the page's own scriptlet would answer: the offline check (ROADMAP P5.72)."""
import unittest

from tools.qa import adblock_fakes_check as fc

GOOD = {"page": {"status": 200, "text": ""}, "worker": {"status": 200, "text": ""},
        "plain": {"status": 0, "text": ""}}


class StepTests(unittest.TestCase):
    def test_every_step_as_it_should_be(self):
        self.assertEqual(fc.step_problems(GOOD, ["/page.html", "/worker.js"]), [])

    def test_the_worker_met_the_network_s_refusal(self):
        # what Google Docs met: the call failed instead of being answered
        seen = dict(GOOD, worker={"status": 0, "text": ""})
        found = fc.step_problems(seen, [])
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0].startswith("worker:"))

    def test_an_answer_that_is_not_empty_or_a_request_that_got_out(self):
        self.assertIn("page:", fc.step_problems(dict(GOOD, page={"status": 200, "text": "real"}), [])[0])
        self.assertIn("reached the server", fc.step_problems(GOOD, ["/api/plain?from=worker"])[0])

    def test_the_rules(self):
        self.assertIn("no-xhr-if, method:POST url:/api/log", fc.MY_FILTERS)
        self.assertIn(f"||{fc.PAGE_HOST}/api/plain^", fc.MY_FILTERS)
        self.assertEqual(set(fc.WANT), {"page", "worker", "plain"})


if __name__ == "__main__":
    unittest.main()
