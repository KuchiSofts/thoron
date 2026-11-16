# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Guided import of Chrome's passwords (ROADMAP P3.17): the file is checked, then overwritten and deleted."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.migrate import chrome_passwords as cp

CSV = ("name,url,username,password,note\r\n"
       "bank.example,https://bank.example/login,someone@example.com,s3cret-pass-value,\r\n"
       "mail.example,https://mail.example/,me@example.org,another-secret,\r\n")


class FileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel: str, text: str = CSV) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="")
        return path

    def test_chrome_s_file_is_counted_without_reading_values(self):
        self.assertEqual(cp.check_file(self.write("Downloads/Chrome Passwords.csv")), 2)

    def test_another_file_is_refused(self):
        for text in ("a,b,c\r\n1,2,3\r\n", "name,url,username,password\r\n", ""):
            with self.assertRaises(cp.PasswordFileError):
                cp.check_file(self.write("Downloads/x.csv", text))
        with self.assertRaises(cp.PasswordFileError):
            cp.check_file(self.root / "none.csv")

    def test_a_synced_folder_is_refused(self):
        for folder in ("OneDrive", "OneDrive - Company", "Google Drive/My Drive", "Dropbox", "iCloud Drive"):
            path = self.write(f"{folder}/Chrome Passwords.csv")
            with self.assertRaises(cp.PasswordFileError) as caught:
                cp.check_file(path)
            self.assertIn("cloud", str(caught.exception))
        self.assertIsNone(cp.synced_folder(self.root / "Downloads" / "x.csv"))

    def test_the_file_is_overwritten_before_it_is_deleted(self):
        path = self.write("Downloads/Chrome Passwords.csv")
        size = path.stat().st_size
        seen = {}
        real_unlink = Path.unlink

        def unlink(self_path, *args, **kwargs):
            data = self_path.read_bytes()
            seen["size"] = len(data)
            seen["data"] = data
            return real_unlink(self_path, *args, **kwargs)

        with mock.patch.object(Path, "unlink", unlink):
            self.assertTrue(cp.wipe(path))
        self.assertFalse(path.exists())
        # what was on the disk just before the delete: nothing left of the content
        self.assertEqual(seen["size"], 0)
        self.assertGreater(size, 0)

    def test_the_overwrite_replaces_every_byte(self):
        path = self.write("Downloads/Chrome Passwords.csv")
        before = path.read_bytes()
        # the file as it is after the first flush to the disk, before it is cut to nothing
        calls = []
        real_fsync = os.fsync

        def fsync(fd):
            real_fsync(fd)
            if not calls:
                calls.append(path.read_bytes())

        with mock.patch.object(os, "fsync", fsync):
            cp.wipe(path)
        overwritten = calls[0]
        self.assertEqual(len(overwritten), len(before))
        self.assertNotIn(b"s3cret-pass-value", overwritten)
        self.assertNotIn(b"someone@example.com", overwritten)
        self.assertNotEqual(overwritten, before)

    def test_copies_beside_it_go_too(self):
        path = self.write("Downloads/Chrome Passwords.csv")
        copy = self.write("Downloads/Chrome Passwords (1).csv")
        other = self.write("Downloads/Other.csv", "x")
        self.assertEqual(cp.leftovers(path), [copy])
        answers = iter([str(path), ""])
        said = []
        with mock.patch.object(cp, "_open_page"):
            code = cp.guide(Path("chrome.exe"), Path("thoron.exe"), ask=lambda _: next(answers), say=said.append)
        self.assertEqual(code, 0)
        self.assertFalse(path.exists())
        self.assertFalse(copy.exists())
        self.assertTrue(other.exists())
        self.assertTrue(any("2 saved password(s)" in s for s in said))
        self.assertFalse(any("s3cret" in s or "@example" in s for s in said))

    def test_a_refused_file_is_left_for_the_person(self):
        path = self.write("OneDrive/Chrome Passwords.csv")
        answers = iter([str(path)])
        with mock.patch.object(cp, "_open_page"):
            self.assertEqual(cp.guide(Path("c"), Path("t"), ask=lambda _: next(answers), say=lambda _: None), 1)
        self.assertTrue(path.exists())

    def test_wipe_from_the_command_line(self):
        path = self.write("Downloads/p.csv")
        self.assertEqual(cp.main(["--wipe", str(path)]), 0)
        self.assertFalse(path.exists())
        self.assertTrue(cp.wipe(path))


if __name__ == "__main__":
    unittest.main()
