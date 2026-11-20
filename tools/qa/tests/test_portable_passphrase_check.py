# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Tests of the parts of portable_passphrase_check.py that need no browser."""
import sqlite3
import tempfile
import unittest
import urllib.request
from pathlib import Path

from tools.qa import portable_passphrase_check as check


def make_cookies(folder: Path, rows: list[tuple[str, bytes]]) -> Path:
    db = folder / "Default" / "Network" / "Cookies"
    db.parent.mkdir(parents=True)
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE cookies (name TEXT, value TEXT, encrypted_value BLOB)")
    con.executemany("INSERT INTO cookies VALUES ('thoronportable', ?, ?)", rows)
    con.commit()
    con.close()
    return db


class CookieServerTest(unittest.TestCase):
    def test_sets_and_shows_the_cookie(self):
        server = check.CookieServer()
        try:
            with urllib.request.urlopen(server.url("/set"), timeout=10) as reply:
                self.assertIn(f"thoronportable={server.value}", reply.headers.get("Set-Cookie"))
            request = urllib.request.Request(server.url("/get"), headers={"Cookie": "a=b"})
            with urllib.request.urlopen(request, timeout=10) as reply:
                self.assertEqual(reply.read(), b"a=b")
        finally:
            server.close()


class CookieEncryptedTest(unittest.TestCase):
    def test_only_an_encrypted_cookie_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            make_cookies(folder, [("", b"v10" + b"\x01" * 40)])
            self.assertTrue(check.cookie_encrypted(folder, "secretvalue"))
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            make_cookies(folder, [("secretvalue", b"")])
            self.assertFalse(check.cookie_encrypted(folder, "secretvalue"))
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            make_cookies(folder, [("", b"v10secretvalue")])
            self.assertFalse(check.cookie_encrypted(folder, "secretvalue"))
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            make_cookies(folder, [])
            self.assertFalse(check.cookie_encrypted(folder, "secretvalue"))


if __name__ == "__main__":
    unittest.main()
