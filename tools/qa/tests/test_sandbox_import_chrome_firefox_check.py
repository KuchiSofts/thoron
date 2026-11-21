# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""The Import guide's Chrome and Firefox sections on a clean Windows (ROADMAP D.2): the reading of the results."""
import json
import unittest

from tools.qa import sandbox_import_chrome_firefox_check as check

PAGES = [f"http://127.0.0.1:47640/p/{m}" for m in check.MARKS]


def chrome_reading() -> str:
    tabs = [{"navigations": [{"url": u}]} for u in PAGES]
    return json.dumps({"session": {"windows": [{"tabs": tabs}]}})


def firefox_reading() -> str:
    tabs = [{"navigations": [{"url": u}]} for u in PAGES]
    return json.dumps({"format": 1, "source": "firefox", "windows": [{"tabs": tabs}]})


def good() -> dict:
    return {"thoron_installed": True, "thoron_profile": True,
            "chrome_installed": True, "chrome_read_exit": 0, "chrome_read": chrome_reading(),
            "chrome_import_exit": 0, "chrome_opened": PAGES + ["chrome://newtab/"],
            "firefox_installed": True, "firefox_read_exit": 0, "firefox_read": firefox_reading(),
            "firefox_import_exit": 0, "firefox_opened": PAGES}


class ProblemsTests(unittest.TestCase):
    def test_a_good_run_passes(self):
        self.assertEqual({k: v for k, v in check.problems(good()).items() if v}, {})

    def test_each_failure_is_named_for_its_browser(self):
        cases = {
            "chrome": {"chrome_opened": PAGES[:1]},
            "firefox": {"firefox_import_exit": 1},
        }
        for step, change in cases.items():
            with self.subTest(step):
                self.assertTrue(check.problems({**good(), **change})[step])
        self.assertTrue(check.problems({**good(), "firefox_read": "{}"})["firefox"])
        self.assertEqual(check.problems({**good(), "chrome_installed": False})["chrome"],
                         ["chrome was not installed in the Sandbox"])
        self.assertTrue(check.problems({**good(), "thoron_profile": False})["first start"])

    def test_both_readings_give_their_addresses(self):
        self.assertEqual(check._all_urls(chrome_reading()), PAGES)
        self.assertEqual(check._all_urls(firefox_reading()), PAGES)
        self.assertEqual(check._all_urls("not json"), [])


if __name__ == "__main__":
    unittest.main()
