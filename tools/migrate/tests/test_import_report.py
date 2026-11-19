# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""The import report (ROADMAP P3.18): counts per kind of data, made for every import, without a secret value."""
import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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
        quiet = mock.patch.object(ip, "QUIET_SECONDS", 0)   # written just before; I2 has its own tests
        quiet.start()
        self.addCleanup(quiet.stop)
        self.tmp = tempfile.TemporaryDirectory()
        # resolved, as the tool resolves the folders it is given: a temporary folder named by its short (8.3)
        # name, as on the CI's machines, is then the same path to both
        root = Path(self.tmp.name).resolve()
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

    def test_data_chrome_locks_to_itself_is_named_not_counted_as_brought_over(self):
        # threat model I6: an app-bound key in Local State; Thoron never tries to get around it
        (self.source / "Local State").write_text(json.dumps(
            {"os_crypt": {"encrypted_key": "made-up", "app_bound_encrypted_key": "made-up too"}}), encoding="utf-8")
        code, printed = self.run_cli()
        self.assertEqual(code, 0, printed)
        report = json.loads((self.dest.parent / ip.REPORT_NAME).read_text(encoding="utf-8"))
        self.assertEqual(report["not_brought_over"], [ip.LOCKED_NOTE])
        self.assertEqual(report["profiles"]["Default"]["locked"], ["saved passwords", "cookies"])
        self.assertIn("saved passwords: copied, but locked", printed)
        self.assertIn("app-bound", printed)

    def test_a_thorium_profile_has_nothing_locked(self):
        (self.source / "Local State").write_text(json.dumps({"os_crypt": {"encrypted_key": "made-up"}}),
                                                 encoding="utf-8")
        code, printed = self.run_cli()
        self.assertEqual(code, 0, printed)
        report = json.loads((self.dest.parent / ip.REPORT_NAME).read_text(encoding="utf-8"))
        self.assertEqual(report["not_brought_over"], [])
        self.assertNotIn("locked", report["profiles"]["Default"])
        self.assertIn("not brought over: nothing", printed)
        for broken in ("not json", "[]", '{"os_crypt": "x"}'):
            (self.source / "Local State").write_text(broken, encoding="utf-8")
            self.assertFalse(ip.locked_to_its_browser(self.source))

    def test_the_report_s_temporary_copies_are_deleted_on_success_and_on_failure(self):
        # threat model I8: the copies of the databases the report reads hold secrets; they are made inside the
        # destination, never in the system's temporary folder, and none may stay behind
        temp = Path(self.tmp.name) / "temp"
        temp.mkdir()
        scratch = self.dest / ip.SCRATCH_NAME
        made_in = []
        real = tempfile.TemporaryDirectory

        def watched(*args, **kwargs):
            made_in.append(Path(kwargs.get("dir") or tempfile.gettempdir()))
            return real(*args, **kwargs)

        with mock.patch.object(tempfile, "tempdir", str(temp)), \
                mock.patch.object(ip.tempfile, "TemporaryDirectory", side_effect=watched):
            code, printed = self.run_cli()
            self.assertEqual(code, 0, printed)
            self.assertTrue(made_in)
            self.assertTrue(all(folder == scratch for folder in made_in), made_in)
            self.assertEqual(list(temp.iterdir()), [])
            self.assertFalse(scratch.exists())
            # a failure while a copy is there: it goes all the same
            with mock.patch.object(ip.sqlite3, "connect", side_effect=RuntimeError("stopped")):
                with self.assertRaises(RuntimeError):
                    ip.profile_report(self.dest / "Default")
            self.assertEqual(list(temp.iterdir()), [])
            self.assertFalse(scratch.exists())

    def test_what_a_stopped_report_left_goes_before_the_next_one(self):
        code, printed = self.run_cli()
        self.assertEqual(code, 0, printed)
        left = self.dest / ip.SCRATCH_NAME / "tmp-left" / "db"
        left.parent.mkdir(parents=True)
        left.write_bytes(b"a copy a stopped run left")
        ip.profile_report(self.dest / "Default")
        self.assertFalse((self.dest / ip.SCRATCH_NAME).exists())


def nested_bookmarks(levels: int) -> str:
    """A Bookmarks file with one bookmark at the bottom of `levels` folders, each inside the one before."""
    return ('{"roots": {"bookmark_bar": ' + '{"type": "folder", "children": [' * levels + '{"type": "url"}'
            + "]}" * levels + "}}")


class CraftedBookmarksTests(unittest.TestCase):
    """The Bookmarks file comes from another browser's profile (threat model I3, F1): whatever it holds, the report
    gives a count or says it could not be read, and never fails."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.profile = Path(self.tmp.name) / "Default"
        make_profile(self.profile)
        self.path = self.profile / "Bookmarks"

    def tearDown(self):
        self.tmp.cleanup()

    def count(self, content: str | bytes) -> int | None:
        if isinstance(content, bytes):
            self.path.write_bytes(content)
        else:
            self.path.write_text(content, encoding="utf-8")
        return ip._count_bookmarks(self.path)

    def test_a_file_that_is_not_what_a_browser_writes_is_not_counted(self):
        for content in ("[" * 200_000, nested_bookmarks(5_000), '{"roots": [1, 2]}', "[1]", '"text"', "",
                        b"\xff\xfe not text"):
            with self.subTest(content=content[:40]):
                self.assertIsNone(self.count(content))
                report = ip.profile_report(self.profile)
                self.assertEqual(report["not_counted"], ["bookmarks: the file could not be read"])
                self.assertEqual(report["counts"]["bookmarks"], 0)
                self.assertEqual(report["counts"]["saved passwords"], 1)      # the rest is counted as before

    def test_odd_shapes_and_deep_trees_are_counted_without_an_error(self):
        self.assertEqual(self.count('{"roots": {"a": {"children": 5}, "b": {"children": {"x": 1}}, "c": 7}}'), 0)
        self.assertEqual(self.count('{"roots": null}'), 0)
        # deeper than a recursive walk could go, and still within what the JSON reader takes
        self.assertEqual(self.count(nested_bookmarks(600)), 1)

    def test_a_file_larger_than_a_bookmarks_file_can_be_is_not_read(self):
        with mock.patch.object(ip, "MOST_BOOKMARKS_BYTES", 10):
            self.assertIsNone(self.count(nested_bookmarks(1)))
        self.assertEqual(self.count(nested_bookmarks(1)), 1)


if __name__ == "__main__":
    unittest.main()
