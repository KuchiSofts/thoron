# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Tests of the parts of sandbox_vivaldi_opera_check.py that need no Sandbox."""
import json
import unittest

from tools.qa import sandbox_vivaldi_opera_check as check


def reading(*urls):
    return json.dumps({"session": {"windows": [{"tabs": [{"navigations": [{"url": u}]} for u in urls]}]}})


class ProblemsTest(unittest.TestCase):
    def test_both_found_and_read(self):
        found = {"vivaldi_installed": True, "opera_installed": True,
                 "detect": json.dumps([{"browser": "Vivaldi"}, {"browser": "Opera"}]),
                 "vivaldi_tabs": reading("http://127.0.0.1:47640/p/thoron-tab-one", "http://127.0.0.1:47640/p/thoron-tab-two"),
                 "opera_tabs": reading("http://127.0.0.1:47640/p/thoron-tab-two", "http://127.0.0.1:47640/p/thoron-tab-one")}
        self.assertEqual(check.problems(found), {"Vivaldi": [], "Opera": []})

    def test_missing_pieces_are_named(self):
        found = {"vivaldi_installed": True, "detect": json.dumps([{"browser": "Vivaldi"}]),
                 "vivaldi_tabs": reading("http://127.0.0.1:47640/p/thoron-tab-one"), "opera_tabs": "not json"}
        result = check.problems(found)
        self.assertEqual(len(result["Vivaldi"]), 1)
        self.assertEqual(len(result["Opera"]), 3)

    def test_tab_urls(self):
        self.assertEqual(check.tab_urls(reading("a", "b")), ["a", "b"])
        self.assertEqual(check.tab_urls("{}"), [])
        self.assertEqual(check.tab_urls("x"), [])


if __name__ == "__main__":
    unittest.main()
