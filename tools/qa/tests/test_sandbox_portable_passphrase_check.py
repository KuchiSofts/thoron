# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Tests of the parts of sandbox_portable_passphrase_check.py that need no Sandbox."""
import json
import tempfile
import unittest
from pathlib import Path

from tools.qa import sandbox_portable_passphrase_check as check


def write(folder: Path, name: str, data: dict) -> None:
    (folder / name).write_text(json.dumps(data), encoding="utf-8")


class SettingsProblemsTest(unittest.TestCase):
    def test_kept_settings_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write(out, "Preferences.json", {"session": {"restore_on_startup": 4}})
            write(out, "Secure-Preferences.json", {"homepage": check.HOME,
                                                   "session": {"startup_urls": check.STARTUP}})
            self.assertEqual(check.settings_problems(out), [])

    def test_a_reset_is_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write(out, "Preferences.json", {"prefs": {"preference_reset_time": "13400000000000000"}})
            write(out, "Secure-Preferences.json", {"session": {"startup_urls": []}})
            found = check.settings_problems(out)
            self.assertEqual(len(found), 3, found)

    def test_nothing_saved_is_a_problem(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(len(check.settings_problems(Path(tmp))), 1)


if __name__ == "__main__":
    unittest.main()
