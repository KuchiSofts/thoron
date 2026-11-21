# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""The pure parts of the Linux portable lock check (ROADMAP P4.9 on Linux)."""
import unittest

from tools.qa import linux_portable_lock_check as lc


class LockCheckTests(unittest.TestCase):
    def test_a_values_tag_is_its_first_three_bytes(self):
        self.assertEqual(lc.tag_of(b"t10" + b"x" * 30), "t10")
        self.assertEqual(lc.tag_of(b"v11abc"), "v11")
        self.assertEqual(lc.tag_of(b"v1"), "")

    def test_values_with_another_tag_are_named_by_place(self):
        found = lc.tags_problems({"Login Data:logins.password_value": ["t10", "v10"],
                                  "Cookies:cookies.encrypted_value": ["t10"]}, {"t10"})
        self.assertEqual(len(found), 1)
        self.assertIn("Login Data:logins.password_value", found[0])
        self.assertEqual(lc.tags_problems({"Cookies:cookies.encrypted_value": ["t10", "t10"]}, {"t10"}), [])

    def test_questions_are_counted_by_kind(self):
        log = ["ZENITY [--entry] [--hide-text]", "ZENITY [--error] [--text=x]", "ZENITY [--entry]"]
        self.assertEqual(lc.asked(log, "--entry"), 2)
        self.assertEqual(lc.asked(log, "--question"), 0)

    def test_one_bit_changes(self):
        data = bytes(64)
        changed = lc.flipped(data)
        self.assertEqual(sum(a != b for a, b in zip(data, changed)), 1)
        self.assertEqual(len(changed), len(data))

    def test_the_stand_in_zenity_types_one_line_and_never_the_command_line(self):
        self.assertIn('head -n 1 "$TYPED"', lc.FAKE_ZENITY)
        self.assertIn("printf '%s\\n' \"$line\"", lc.FAKE_ZENITY)
        self.assertNotIn(lc.PASSPHRASE, lc.SCRIPT)

    def test_every_step_is_reported(self):
        self.assertEqual(len(set(lc.STEPS)), len(lc.STEPS))
        self.assertIn("unlock", lc.STEPS)
        self.assertNotIn("--no-sandbox", " ".join(lc.ARGS))


if __name__ == "__main__":
    unittest.main()
