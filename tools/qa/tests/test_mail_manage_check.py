# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Tests of mail_manage_check.py's verdicts (ROADMAP P5.81); the browser itself is driven only by the check."""
import json
import tempfile
import unittest
from pathlib import Path

from tools.qa import mail_manage_check as mm

A, B, RENAMED = mm.A, mm.B, mm.RENAMED


def state(*accounts, wanted=()):
    return {"accounts": list(accounts), "wanted": list(wanted)}


def box(email, unread=3, problem="", watched=True, **more):
    return {"email": email, "unread": unread, "problem": problem, "watched": watched, "imap": True, **more}


class OrderTests(unittest.TestCase):
    def test_the_order_that_is_asked_for(self):
        self.assertEqual(mm.order_problems([B, A], [A, B], [B, A], [B, RENAMED]), [])

    def test_an_order_that_did_not_change(self):
        found = mm.order_problems([A, B], [A, B], [B, A], [RENAMED, B])
        self.assertEqual(len(found), 2)
        self.assertIn("after the set", found[0])
        self.assertIn("after the restart", found[1])


class EditTests(unittest.TestCase):
    def test_a_wrong_password_is_refused_and_changes_nothing(self):
        self.assertEqual(mm.refused_problems("sign-in", state(box(A))), [])
        self.assertTrue(mm.refused_problems("", state(box(A))))
        self.assertTrue(mm.refused_problems("sign-in", state(box(A, problem="sign-in"))))

    def test_a_new_password(self):
        before, after = state(box(A, problem="sign-in")), state(box(A))
        self.assertEqual(mm.password_problems(before, "", after, "no secret here"), [])
        self.assertTrue(mm.password_problems(state(box(A)), "", after, ""))
        self.assertTrue(mm.password_problems(before, "", after, f"... {mm.NEW_PASSWORD} ..."))
        self.assertTrue(mm.password_problems(before, "", state(box(A, note=mm.NEW_PASSWORD)), ""))

    def test_a_new_address_takes_the_rest_along(self):
        good = state(box(B), box(RENAMED, watched=False))
        self.assertEqual(mm.renamed_problems("", good), [])
        self.assertTrue(mm.renamed_problems("", state(box(B), box(RENAMED))))                # watched again
        self.assertTrue(mm.renamed_problems("", state(box(RENAMED, watched=False), box(B))))  # place lost
        self.assertTrue(mm.renamed_problems("", state(box(B), box(RENAMED, problem="sign-in", watched=False))))
        self.assertTrue(mm.renamed_problems("", state(box(B), box(A), box(RENAMED, watched=False))))

    def test_only_the_mail_page(self):
        good = state(box(RENAMED, server={"webmail": mm.WEBMAIL}))
        self.assertEqual(mm.webmail_problems("", good), [])
        self.assertTrue(mm.webmail_problems("sign-in", good))
        self.assertTrue(mm.webmail_problems("", state(box(RENAMED, server={"webmail": ""}))))


class ListTests(unittest.TestCase):
    ANSWERS = {"imported": 2, "renamed": "", "taken": "exists", "app": ""}
    BACKUP = json.dumps({"accounts": [{"email": mm.ERIN_W, "host": "imap.gmail.com"}]})

    def wanted(self, **erin):
        return state(wanted=[{"email": mm.ERIN_W, "alias": "Erin W", "password": True, **erin},
                             {"email": mm.FAY, "alias": "Fay", "password": False}])

    def test_an_edited_account_of_the_list(self):
        self.assertEqual(mm.list_problems(self.ANSWERS, self.wanted(), self.BACKUP), [])

    def test_what_is_wrong(self):
        self.assertTrue(mm.list_problems(dict(self.ANSWERS, taken=""), self.wanted(), self.BACKUP))
        self.assertTrue(mm.list_problems(self.ANSWERS, self.wanted(password=False), self.BACKUP))
        self.assertTrue(mm.list_problems(self.ANSWERS, self.wanted(alias="Erin"), self.BACKUP))
        self.assertTrue(mm.list_problems(self.ANSWERS, self.wanted(), json.dumps({"accounts": []})))
        self.assertTrue(mm.list_problems(self.ANSWERS, self.wanted(note=mm.LIST_PASSWORD), self.BACKUP))


class SavedTests(unittest.TestCase):
    TEXT = json.dumps({"format": "thoron-m-notifier-backup", "accounts": [{"email": B}, {"email": RENAMED}],
                       "settings": {"accountOrder": [B, RENAMED, mm.ERIN_W_DOTLESS]}})
    SEALED = json.dumps({"format": "thoron-m-notifier-backup", "sealed": True, "data": "AAAA"})
    ANSWER = {"error": "", "name": "saved.json"}

    def test_a_whole_backup(self):
        said = "Saved, with the passwords sealed. File: saved.json. Mailboxes: 3; Google accounts: 2."
        self.assertEqual(mm.saved_problems(self.ANSWER, self.TEXT, said, self.SEALED), [])

    def test_an_empty_file_or_a_wrong_one(self):
        self.assertTrue(mm.saved_problems(self.ANSWER, "", "saved.json", self.SEALED))
        self.assertTrue(mm.saved_problems({"error": "write", "name": ""}, self.TEXT, "saved.json", self.SEALED))
        reordered = json.loads(self.TEXT)
        reordered["settings"]["accountOrder"] = [RENAMED, B]
        self.assertTrue(mm.saved_problems(self.ANSWER, json.dumps(reordered), "saved.json", self.SEALED))
        self.assertTrue(mm.saved_problems(self.ANSWER, self.TEXT, "", self.SEALED))
        self.assertTrue(mm.saved_problems(self.ANSWER, self.TEXT, "saved.json", self.TEXT))   # not sealed

    def test_a_file_that_cannot_be_written(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "no-such-folder" / "saved.json"
            self.assertEqual(mm.unwritable_problems({"error": "write", "name": "saved.json"}, target), [])
            self.assertTrue(mm.unwritable_problems({"error": "", "name": "saved.json"}, target))
            target.parent.mkdir()
            target.write_text("", encoding="utf-8")
            self.assertTrue(mm.unwritable_problems({"error": "write", "name": "saved.json"}, target))


if __name__ == "__main__":
    unittest.main()
