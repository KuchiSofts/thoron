# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Saved passwords on Linux with GNOME's keyring or KDE's KWallet (ROADMAP P3.16, P5.8): the reading of the probe's results."""
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


class WalletTests(unittest.TestCase):
    """KDE's KWallet: gdbus's replies of folderList and entryList."""
    FOLDERS = "(['Chromium Keys'],)\n"
    KEYS = "(['Chromium Safe Storage'],)\n"

    def test_a_good_wallet_passes(self):
        self.assertEqual(check.wallet_problems(self.FOLDERS, self.KEYS), [])
        found = check.problems(good(), wallet=check.wallet_problems(self.FOLDERS, self.KEYS))
        self.assertEqual({k: v for k, v in found.items() if v}, {})

    def test_a_missing_or_doubled_key_and_a_folder_of_its_own_fail(self):
        self.assertTrue(check.wallet_problems("(@as [],)", self.KEYS))
        self.assertTrue(check.wallet_problems(self.FOLDERS, "(@as [],)"))
        self.assertTrue(check.wallet_problems(self.FOLDERS, "(['Chromium Safe Storage', 'Other'],)"))
        self.assertTrue(check.wallet_problems("(['Chromium Keys', 'Thoron Keys'],)", self.KEYS))
        self.assertTrue(check.wallet_problems("(['Chromium Keys', 'Thorium Keys'],)", self.KEYS))
        self.assertTrue(check.problems(good(), wallet=["x"])["one key"])

    def test_the_desktop_store_gives_no_switch(self):
        self.assertIn("--store desktop", check.KDE_SESSION)
        self.assertIn("pamOpen", check.KDE_SESSION)
        self.assertIn("Prompt on Open=false", check.KDE_SESSION)


if __name__ == "__main__":
    unittest.main()
