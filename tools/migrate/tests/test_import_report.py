# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""The import report (ROADMAP P3.18): counts per kind of data, made for every import, without a secret value."""
import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tools.migrate import import_profile as ip

# made-up values that must never be in a report
SECRETS = ("s3cret-pass-value", "someone@example.com", "https://bank.example/login", "cookie-value-9f2",
           "Street 7, Town", "Saved bookmark title")


def database(path: Path, sql: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript(sql)
    con.commit()
    con.close()


def make_profile(folder: Path) -> None:
    folder.mkdir(parents=True)
    (folder / "Preferences").write_text("{}", encoding="utf-8")
    (folder / "Bookmarks").write_text(json.dumps({"roots": {
        "bookmark_bar": {"type": "folder", "children": [
            {"type": "url", "name": SECRETS[5], "url": SECRETS[2]},
            {"type": "folder", "children": [{"type": "url", "name": "b", "url": "https://example.org/"}]}]},
        "other": {"type": "folder", "children": [{"type": "url", "name": "c", "url": "https://example.net/"}]}}}),
        encoding="utf-8")
    database(folder / "History", f"CREATE TABLE urls(url TEXT); INSERT INTO urls VALUES('{SECRETS[2]}'),"
                                 "('https://example.org/');")
    database(folder / "Login Data", f"CREATE TABLE logins(origin_url TEXT, username_value TEXT, password_value "
                                    f"BLOB); INSERT INTO logins VALUES('{SECRETS[2]}', '{SECRETS[1]}', "
                                    f"'{SECRETS[0]}');")
    database(folder / "Network" / "Cookies", f"CREATE TABLE cookies(host_key TEXT, value TEXT); INSERT INTO "
                                             f"cookies VALUES('bank.example', '{SECRETS[3]}'), ('example.org', 'x'),"
                                             "('example.net', 'y');")
    database(folder / "Web Data", f"CREATE TABLE autofill(name TEXT, value TEXT); INSERT INTO autofill VALUES"
                                  f"('address', '{SECRETS[4]}');")
    (folder / "Extensions" / "abcdefghijklmnopabcdefghijklmnop" / "1.0").mkdir(parents=True)
    (folder / "Extensions" / "abcdefghijklmnopabcdefghijklmnop" / "1.0" / "manifest.json").write_text("{}")


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.source, self.dest = root / "Thorium" / "User Data", root / "Thoron" / "User Data"
        self.source.mkdir(parents=True)
        (self.source / "Local State").write_text("{}", encoding="utf-8")
        make_profile(self.source / "Default")
        make_profile(self.source / "Profile 1")
        (self.source / "Profile 1" / "Web Data").write_bytes(b"not a database at all")

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = ip.main(["--from", str(self.source), "--to", str(self.dest)])
        return code, out.getvalue()

    def test_every_import_writes_the_report_with_the_counts(self):
        code, printed = self.run_cli()
        self.assertEqual(code, 0, printed)
        report = json.loads((self.dest.parent / ip.REPORT_NAME).read_text(encoding="utf-8"))
        self.assertTrue(report["verified"])
        default = report["profiles"]["Default"]["counts"]
        self.assertEqual(default, {"bookmarks": 3, "history entries": 2, "saved passwords": 1, "cookies": 3,
                                   "autofill entries": 1, "extensions": 1})
        self.assertIn("Default: 3 bookmarks", printed)
        self.assertIn("not brought over: nothing", printed)

    def test_what_could_not_be_counted_is_said(self):
        self.run_cli()
        report = json.loads((self.dest.parent / ip.REPORT_NAME).read_text(encoding="utf-8"))
        self.assertEqual(report["profiles"]["Profile 1"]["not_counted"],
                         ["autofill entries: the database could not be read"])

    def test_the_source_is_unchanged_and_the_databases_are_checked(self):
        self.run_cli()
        report = json.loads((self.dest.parent / ip.REPORT_NAME).read_text(encoding="utf-8"))
        self.assertTrue(report["source_unchanged"])
        self.assertEqual(report["profiles"]["Default"]["databases"], ["all ok"])
        # Profile 1's Web Data is not a database at all
        self.assertEqual(report["profiles"]["Profile 1"]["databases"], ["Web Data: cannot be opened (DatabaseError)"])

    def test_a_source_that_changes_during_the_import_is_refused(self):
        real = ip._sha256
        calls = {"n": 0}

        def changing(path):
            calls["n"] += 1
            digest = real(path)
            # the second look at the source's Bookmarks finds it changed
            if path.name == "Bookmarks" and str(path).startswith(str(self.source)) and calls["n"] > 20:
                return "0" * 64
            return digest

        from unittest import mock
        with mock.patch.object(ip, "_sha256", changing):
            with self.assertRaises(ip.VerificationFailed) as caught:
                ip.import_profile(self.source, self.dest)
        self.assertIn("changed during the import", str(caught.exception))

    def test_the_report_holds_no_secret_value(self):
        code, printed = self.run_cli()
        written = (self.dest.parent / ip.REPORT_NAME).read_text(encoding="utf-8")
        for secret in SECRETS + ("bank.example", "example.org", "abcdefghijklmnop"):
            self.assertNotIn(secret, written, secret)
            self.assertNotIn(secret, printed, secret)

    def test_counting_reads_a_copy_and_leaves_the_profile_alone(self):
        self.run_cli()
        login = self.dest / "Default" / "Login Data"
        before = login.read_bytes()
        ip.profile_report(self.dest / "Default")
        self.assertEqual(login.read_bytes(), before)
        self.assertFalse((self.dest / "Default" / "Login Data-journal").exists())

    def test_no_report_without_an_import(self):
        (self.dest / "Default").mkdir(parents=True)
        (self.dest / "Default" / "Preferences").write_text("{}")
        code, printed = self.run_cli()
        self.assertEqual(code, 1)
        self.assertFalse((self.dest.parent / ip.REPORT_NAME).exists())


if __name__ == "__main__":
    unittest.main()
