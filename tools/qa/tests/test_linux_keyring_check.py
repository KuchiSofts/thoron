# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Saved passwords on Linux with GNOME's keyring (ROADMAP P3.16, P5.8): the reading of the probe's results."""
import unittest

from tools.qa import linux_keyring_check as check

KEYRING = """[/org/freedesktop/secrets/collection/login/1]
label = Chromium Safe Storage
secret = made-up
attribute.application = chromium
"""


def good() -> dict:
    return {
        "thorium_added": "added", "thorium_stored": ["v11"], "thorium_plain": False, "import_exit": 0,
        "imported_readable": {"https://example.org": check.FIRST["password"]},
        "thoron_added": "added",
        "after_restart": {"https://example.org": check.FIRST["password"],
                          "https://example.com": check.SECOND["password"]},
        "thoron_stored": ["v11", "v11"], "thoron_plain": False,
    }


class ProblemsTests(unittest.TestCase):
    def test_a_good_run_passes(self):
        self.assertEqual({k: v for k, v in check.problems(good(), {"chromium": KEYRING}).items() if v}, {})

    def test_each_failure_is_named_in_its_step(self):
        cases = {
            "thorium saves": {"thorium_stored": ["v10"]},
            "imported": {"imported_readable": {"https://example.org": "error: no"}},
            "thoron saves": {"after_restart": {"https://example.org": check.FIRST["password"]}},
        }
        for step, change in cases.items():
            with self.subTest(step):
                self.assertTrue(check.problems({**good(), **change}, {"chromium": KEYRING})[step], step)
        self.assertTrue(check.problems({**good(), "thoron_plain": True}, {"chromium": KEYRING})["thoron saves"])

    def test_the_key_is_one_entry_shared_by_both(self):
        self.assertTrue(check.problems(good(), {"chromium": ""})["one key"])
        self.assertTrue(check.problems(good(), {"chromium": KEYRING + KEYRING})["one key"])
        own = KEYRING.replace("chromium", "thoron")
        self.assertTrue(check.problems(good(), {"chromium": KEYRING, "thoron": own})["one key"])


if __name__ == "__main__":
    unittest.main()
