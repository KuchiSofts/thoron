# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Tests for tools/qa/linux_settings_import_check.py: what its results mean."""
import copy
import unittest

from tools.qa import linux_settings_import_check as c


def good() -> dict:
    return {
        "source_added": "added", "source_cookie": True,
        "import": {"names": ["Thorium", "Bookmarks HTML File"], "status": "succeeded"},
        "readable": {"https://example.org/": c.KEYRING_PASSWORD["password"],
                     "https://example.net/": c.FIXED_PASSWORD["password"]},
        "cookies": [{"name": c.COOKIE["name"], "value": c.COOKIE["value"], "domain": ".example.org",
                     "secure": True, "httpOnly": True}],
        "cookies_now": [{"name": c.COOKIE["name"], "value": c.COOKIE["value"], "domain": ".example.org",
                         "secure": True, "httpOnly": True}],
        "bookmarks": '{"name": "Thoron import bookmark", "url": "%s"}' % c.BOOKMARK,
        "history": [c.HISTORY],
        "report": '{"source": "Thorium", "imported": {"bookmarks": 1, "history": 1, "passwords": 2, "cookies": 1}}',
        "before": {"Default/Login Data": "a"}, "after": {"Default/Login Data": "a"},
    }


class ProblemsTest(unittest.TestCase):
    def test_a_good_run_has_none(self):
        self.assertEqual({k: v for k, v in c.problems(good()).items() if v}, {})

    def test_each_failure_lands_in_its_step(self):
        cases = {
            "listed": lambda f: f["import"].update(names=["Thorium", "Thoron"]),
            "import": lambda f: f["import"].update(status="failed"),
            "passwords": lambda f: f["readable"].pop("https://example.net/"),
            "cookie": lambda f: f["cookies"][0].update(httpOnly=False),
            "the data": lambda f: f.update(history=[]),
            "the report": lambda f: f.update(report=f["report"] + c.COOKIE["value"]),
            "untouched": lambda f: f.update(after={"Default/Login Data": "b"}),
            "source": lambda f: f.update(source_cookie=False),
        }
        for step, spoil in cases.items():
            found = copy.deepcopy(good())
            spoil(found)
            got = c.problems(found)
            self.assertTrue(got[step], step)
            self.assertEqual([s for s, v in got.items() if v], [step], step)

    def test_no_report_or_no_hashes_is_a_problem(self):
        found = good()
        found["report"] = ""
        found["before"] = {}
        got = c.problems(found)
        self.assertTrue(got["the report"])
        self.assertTrue(got["untouched"])


if __name__ == "__main__":
    unittest.main()
