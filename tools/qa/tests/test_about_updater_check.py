# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Tests of the parts of about_updater_check.py that do not need a browser."""
import unittest

from tools.qa import about_updater_check as au


class GithubTests(unittest.TestCase):
    def test_github_names_are_found_once_and_others_are_not(self):
        log = ('{"host":"github.com"} "url":"https://github.com/KuchiSofts/thoron/releases/latest/download/update.json" '
               '"objects.githubusercontent.com" "release-assets.githubusercontent.com" "example.com" "notgithub.company"')
        self.assertEqual(au.github_lines(log), ["github.com", "objects.githubusercontent.com",
                                                "release-assets.githubusercontent.com"])
        self.assertEqual(au.github_lines('{"host":"ublockorigin.github.io"}'), [])


class JudgeTests(unittest.TestCase):
    def test_without_a_key_nothing_is_shown_or_asked(self):
        self.assertEqual(au.judge({"found": True, "shown": False}, [], False), [])
        self.assertEqual(len(au.judge({"found": True, "shown": True, "text": "x"}, [], False)), 1)
        self.assertEqual(len(au.judge({"found": True, "shown": False}, ["github.com"], False)), 1)
        self.assertEqual(len(au.judge({"found": False}, [], False)), 1)

    def test_with_a_key_a_line_is_shown_and_github_is_asked(self):
        self.assertEqual(au.judge({"found": True, "shown": True}, ["github.com"], True), [])
        self.assertEqual(len(au.judge({"found": True, "shown": False}, [], True)), 2)


if __name__ == "__main__":
    unittest.main()
