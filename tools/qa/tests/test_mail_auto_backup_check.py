# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Tests of mail_auto_backup_check.py's verdicts (ROADMAP P5.77); the browser itself is driven only by the check."""
import json
import tempfile
import unittest
from pathlib import Path

from tools.qa import mail_auto_backup_check as ab

A, B = ab.A, ab.B
FIRST = "thoron-m-notifier-auto-2026-11-19-101500.json"
SECOND = "thoron-m-notifier-auto-2026-11-19-101503.json"
THIRD = "thoron-m-notifier-auto-2026-11-19-101506.thoron"


def backup(order=(A, B), passwords=False, sealed=False):
    boxes = [{"email": e, "host": "imap.example.com", **({"password": "x"} if passwords else {})} for e in (A, B)]
    return json.dumps({"format": "thoron-m-notifier-backup", "version": 1, "sealed": sealed, "accounts": boxes,
                       "settings": {"accountOrder": list(order)}})


def told(name=FIRST, **more):
    return {"autoBackup": {"on": True, "name": name, "error": "", "last": 1.0, **more}}


class NamesTests(unittest.TestCase):
    def test_only_its_own_names(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            for name in (FIRST, THIRD, *ab.OTHERS, "thoron-m-notifier-auto-2026-11-19-1015.json"):
                (root / name).write_text("x", encoding="utf-8")
            self.assertEqual(ab.own_files(root), [THIRD, FIRST])

    def test_a_folder_that_is_not_there(self):
        self.assertEqual(ab.own_files(Path(tempfile.gettempdir()) / "no-such-folder-of-the-check"), [])


class PlainTests(unittest.TestCase):
    def test_a_backup_without_passwords(self):
        self.assertEqual(ab.plain_problems(FIRST, backup(), told()), [])

    def test_no_file_came(self):
        self.assertTrue(ab.plain_problems("", "", told()))

    def test_a_password_in_a_plain_file(self):
        self.assertTrue(ab.plain_problems(FIRST, backup(passwords=True), told()))
        self.assertTrue(ab.plain_problems(FIRST, backup() + ab.PASSWORD_A, told()))

    def test_the_page_is_told_another_file(self):
        self.assertTrue(ab.plain_problems(FIRST, backup(), told(SECOND)))
        self.assertTrue(ab.plain_problems(FIRST, backup(), told(error="write")))


class ChangedTests(unittest.TestCase):
    def test_one_new_file_with_the_new_order(self):
        self.assertEqual(ab.changed_problems([FIRST], [SECOND, FIRST], backup((B, A))), [])

    def test_no_new_file_or_the_old_order(self):
        self.assertTrue(ab.changed_problems([FIRST], [FIRST], backup((B, A))))
        self.assertTrue(ab.changed_problems([FIRST], [SECOND, FIRST], backup((A, B))))


class SealedTests(unittest.TestCase):
    GOOD = {"short": "short", "kept": "", "opened": "", "wrong": "wrong"}
    SEALED = json.dumps({"format": "thoron-m-notifier-backup", "sealed": True, "data": "c2VhbGVk"})

    def test_a_sealed_file(self):
        self.assertEqual(ab.sealed_problems(self.GOOD, THIRD, self.SEALED, "{}", "{}"), [])

    def test_what_a_sealed_file_must_not_show(self):
        self.assertTrue(ab.sealed_problems(self.GOOD, THIRD, self.SEALED + A, "{}", "{}"))
        self.assertTrue(ab.sealed_problems(self.GOOD, THIRD, self.SEALED, ab.PASSPHRASE, "{}"))
        self.assertTrue(ab.sealed_problems(self.GOOD, THIRD, self.SEALED, "{}", ab.PASSPHRASE))
        self.assertTrue(ab.sealed_problems(self.GOOD, FIRST, backup(), "{}", "{}"))

    def test_a_wrong_passphrase_that_opens_it(self):
        self.assertTrue(ab.sealed_problems({**self.GOOD, "wrong": ""}, THIRD, self.SEALED, "{}", "{}"))


class KeptRestartGoneNowTests(unittest.TestCase):
    def test_kept(self):
        others = {name: True for name in ab.OTHERS}
        self.assertEqual(ab.kept_problems([THIRD, SECOND, FIRST], others), [])
        self.assertTrue(ab.kept_problems([THIRD, SECOND], others))
        self.assertTrue(ab.kept_problems([THIRD, SECOND, FIRST], {**others, "notes.txt": False}))

    def test_restart(self):
        self.assertEqual(ab.restart_problems([SECOND, FIRST], [SECOND, FIRST], [THIRD, FIRST]), [])
        self.assertTrue(ab.restart_problems([SECOND, FIRST], [THIRD, SECOND, FIRST], [THIRD, FIRST]))
        self.assertTrue(ab.restart_problems([SECOND, FIRST], [SECOND, FIRST], [FIRST]))

    def test_gone(self):
        state = {"autoBackup": {"error": "folder", "name": FIRST}}
        self.assertEqual(ab.gone_problems(state, "The folder is not there any more", "folder"), [])
        self.assertTrue(ab.gone_problems({"autoBackup": {"error": ""}}, "x", "folder"))
        self.assertTrue(ab.gone_problems(state, "", "folder"))
        self.assertTrue(ab.gone_problems(state, "x", ""))

    def test_now(self):
        self.assertEqual(ab.now_problems("", [SECOND, FIRST], [THIRD, SECOND, FIRST], "Saved."), [])
        self.assertEqual(ab.now_problems("", [THIRD, SECOND, FIRST], ["thoron-m-notifier-auto-2026-11-19-101509.json",
                                                                     THIRD, SECOND], "Saved."), [])
        self.assertTrue(ab.now_problems("folder", [FIRST], [FIRST], "x"))
        self.assertTrue(ab.now_problems("", [FIRST], [FIRST], ""))


if __name__ == "__main__":
    unittest.main()
