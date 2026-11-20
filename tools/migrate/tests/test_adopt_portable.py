# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Tests of adopt_portable.py with made-up upstream portable folders (no real profile, no browser)."""
import base64
import hashlib
import json
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from tools.migrate import adopt_portable as ap
from tools.migrate import import_profile

KEY = bytes(range(32))


def v10(text: bytes, key: bytes = KEY) -> bytes:
    nonce = os.urandom(12)
    return b"v10" + nonce + AESGCM(key).encrypt(nonce, text, None)


def make_db(path: Path, table: str, column: str, values: list[bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, {column} BLOB)")
    con.executemany(f"INSERT INTO {table} ({column}) VALUES (?)", [(v,) for v in values])
    con.commit()
    con.close()


def make_upstream(root: Path, encrypted_key: str, logins=None, cookies=None) -> Path:
    """An upstream portable folder: BIN, USER_DATA with Local State and one profile; files dated an hour ago."""
    (root / "BIN").mkdir(parents=True)
    user_data = root / "USER_DATA"
    (user_data / "Default").mkdir(parents=True)
    (user_data / "Local State").write_text(json.dumps({"os_crypt": {"encrypted_key": encrypted_key,
                                                                    "audit_enabled": True}}), encoding="utf-8")
    (user_data / "Default" / "Preferences").write_text("{}", encoding="utf-8")
    make_db(user_data / "Default" / "Login Data", "logins", "password_value",
            logins if logins is not None else [v10(b"secret-1"), v10(b"secret-2"), b""])
    make_db(user_data / "Default" / "Network" / "Cookies", "cookies", "encrypted_value",
            cookies if cookies is not None else [v10(b"cookie-1")])
    old = time.time() - 3600
    for path in root.rglob("*"):
        os.utime(path, (old, old))
    return root


def make_thoron(root: Path) -> Path:
    (root / "Application").mkdir(parents=True)
    (root / "Thoron.exe").write_bytes(b"launcher")
    return root


def unprotected(key: bytes = KEY) -> str:
    return base64.b64encode(b"DPAPI" + key).decode()


def tree_hashes(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


class ReadKeyTest(unittest.TestCase):
    def test_unprotected_key(self):
        self.assertEqual(ap.read_key({"os_crypt": {"encrypted_key": unprotected()}}), (KEY, "unprotected"))

    def test_refused_keys(self):
        for state in ({}, {"os_crypt": {}}, {"os_crypt": {"encrypted_key": "not base64!"}},
                      {"os_crypt": {"encrypted_key": base64.b64encode(b"XPAPI" + KEY).decode()}},
                      {"os_crypt": {"encrypted_key": unprotected(), "app_bound_encrypted_key": "x"}},
                      {"os_crypt": {"encrypted_key": base64.b64encode(b"DPAPI" + b"\x01" * 200).decode()}}):
            with self.assertRaises(ap.AdoptRefused, msg=state):
                ap.read_key(state)

    @unittest.skipUnless(os.name == "nt", "DPAPI is Windows'")
    def test_protected_for_this_account(self):
        stored = ap.protected_key(KEY)
        self.assertNotIn(KEY, base64.b64decode(stored))
        self.assertEqual(ap.read_key({"os_crypt": {"encrypted_key": stored}}), (KEY, "this account"))


class DecryptsTest(unittest.TestCase):
    def test_v10_values(self):
        self.assertTrue(ap.decrypts(v10(b"x"), KEY))
        self.assertFalse(ap.decrypts(v10(b"x", bytes(32)), KEY))
        self.assertFalse(ap.decrypts(b"v20" + v10(b"x")[3:], KEY))
        self.assertFalse(ap.decrypts(b"v10short", KEY))


@unittest.skipUnless(os.name == "nt", "DPAPI is Windows'")
class AdoptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_taken_over_with_the_original_unchanged(self):
        upstream = make_upstream(self.root / "Thorium Portable", unprotected())
        thoron = make_thoron(self.root / "ThoronPortable")
        before = tree_hashes(upstream)
        report = ap.adopt(upstream, thoron)
        self.assertEqual(tree_hashes(upstream), before)
        self.assertTrue(report["source_unchanged"])
        self.assertEqual(report["key_was"], "unprotected")
        self.assertEqual(report["secrets"], {"saved passwords": {"found": 2, "readable": 2},
                                             "cookies": {"found": 1, "readable": 1}})
        state = json.loads((thoron / "User Data" / "Local State").read_text(encoding="utf-8"))
        self.assertNotIn(KEY, base64.b64decode(state["os_crypt"]["encrypted_key"]))
        self.assertEqual(ap.read_key(state), (KEY, "this account"))
        self.assertIs(state["thoron_portable"]["locked"], False)
        self.assertFalse((thoron / ap.ADOPTING).exists())
        self.assertFalse(any(p.name.startswith(".thoron-adopt-") for p in (thoron / "User Data").iterdir()))
        # the values in the copy are the original's, byte for byte
        self.assertEqual((thoron / "User Data" / "Default" / "Login Data").read_bytes(),
                         (upstream / "USER_DATA" / "Default" / "Login Data").read_bytes())

    def test_a_value_that_does_not_decrypt_stops_it(self):
        upstream = make_upstream(self.root / "up", unprotected(), cookies=[v10(b"c", bytes(32))])
        thoron = make_thoron(self.root / "ThoronPortable")
        with self.assertRaises(import_profile.VerificationFailed):
            ap.adopt(upstream, thoron)
        self.assertFalse((thoron / "User Data").exists())
        self.assertFalse((thoron / ap.ADOPTING).exists())

    def test_refusals(self):
        upstream = make_upstream(self.root / "up", unprotected())
        with self.assertRaises(ap.AdoptRefused):
            ap.adopt(self.root / "nothing-here", make_thoron(self.root / "T1"))
        with self.assertRaises(ap.AdoptRefused):
            ap.adopt(upstream, self.root / "not-a-thoron-copy")
        busy = make_thoron(self.root / "T2")
        (busy / "User Data").mkdir()
        (busy / "User Data" / "Local State").write_text("{}", encoding="utf-8")
        with self.assertRaises(ap.AdoptRefused):
            ap.adopt(upstream, busy)
        self.assertEqual((busy / "User Data" / "Local State").read_text(encoding="utf-8"), "{}")
        (upstream / "USER_DATA" / "lockfile").write_bytes(b"")
        with self.assertRaises(import_profile.ImportRefused):
            ap.adopt(upstream, make_thoron(self.root / "T3"))


if __name__ == "__main__":
    unittest.main()
