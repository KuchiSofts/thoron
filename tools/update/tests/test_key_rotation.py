# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Signing-key rotation (ROADMAP P4.7): the old key signs the new key's statement. The drill, end to end, with
keys made for the test only."""
import base64
import hashlib
import tempfile
import unittest
from pathlib import Path

from tools.update import manifest as mf

NOW = mf.parse_time("2026-12-01T13:00:00Z")


def key_pair(phrase: bytes) -> tuple[bytes, bytes]:
    private = hashlib.sha256(b"test key, never a release key: " + phrase).digest()
    return private, mf.public_key_of(private)


OLD, NEW, NEWER, STRANGER = (key_pair(name) for name in (b"old", b"new", b"newer", b"stranger"))


def release(private: bytes, public: bytes) -> tuple[bytes, bytes]:
    """The example manifest of the spec, signed with `private`."""
    raw = mf.example()
    signature = mf.sign(raw, private, public, allowed_hosts=("github.com",), now=NOW)
    return raw, signature


def copy(**more) -> dict:
    out = {"allowed_hosts": ("github.com",), "channel": "stable", "installed": "158.0.8127.3000",
           "updater": "158.0.8127.3000", "variant": "win-x64-avx2", "kind": "installed", "now": NOW}
    out.update(more)
    return out


class StatementTests(unittest.TestCase):
    def test_a_statement_is_the_new_key_and_the_old_key_s_signature(self):
        statement = mf.sign_key_statement(OLD[0], NEW[1])
        self.assertEqual(len(statement), mf.KEY_STATEMENT_BYTES)
        self.assertEqual(statement[:32], NEW[1])
        self.assertEqual(mf.key_from_statement(statement, [OLD[1]]), NEW[1])

    def test_a_statement_another_key_signed_is_ignored(self):
        statement = mf.sign_key_statement(STRANGER[0], NEW[1])
        self.assertIsNone(mf.key_from_statement(statement, [OLD[1]]))

    def test_a_changed_statement_is_ignored(self):
        statement = bytearray(mf.sign_key_statement(OLD[0], NEW[1]))
        for at in (0, 31, 32, 95):
            changed = bytearray(statement)
            changed[at] ^= 1
            self.assertIsNone(mf.key_from_statement(bytes(changed), [OLD[1]]), at)
        self.assertIsNone(mf.key_from_statement(bytes(statement[:95]), [OLD[1]]))

    def test_no_key_is_introduced_as_a_key(self):
        with self.assertRaises(mf.ManifestError):
            mf.sign_key_statement(OLD[0], bytes(32))
        forged = bytes(32) + bytes(64)
        self.assertIsNone(mf.key_from_statement(forged, [OLD[1]]))

    def test_a_statement_is_no_manifest_signature(self):
        # the purposes differ: a statement's signature does not hold for a manifest of the same bytes
        statement = mf.sign_key_statement(OLD[0], NEW[1])
        self.assertFalse(mf.signature_holds(NEW[1], statement[32:], OLD[1]))


class DrillTests(unittest.TestCase):
    """The rotation drill: a copy built with the old key takes a release signed with the new one only through
    the old key's statement, follows a chain, and ignores what it does not trust."""

    def test_the_drill(self):
        manifest, signature = release(*NEW)
        # 1. without the statement the copy cannot verify the release signed with the new key
        self.assertEqual(mf.check_update_with_keys(manifest, signature, [OLD[1]], **copy()).outcome,
                         mf.BAD_SIGNATURE)
        # 2. with the old key's statement it trusts the new key, and the release is an update
        keys = mf.trusted_keys(OLD[1], [mf.sign_key_statement(OLD[0], NEW[1])])
        self.assertEqual(keys, [OLD[1], NEW[1]])
        self.assertEqual(mf.check_update_with_keys(manifest, signature, keys, **copy()).outcome, mf.UPDATE)
        # 3. a release still signed with the old key verifies as before
        old_manifest, old_signature = release(*OLD)
        self.assertEqual(mf.check_update_with_keys(old_manifest, old_signature, keys, **copy()).outcome,
                         mf.UPDATE)
        # 4. a chain: old -> new -> newer, given in any order
        chain = [mf.sign_key_statement(NEW[0], NEWER[1]), mf.sign_key_statement(OLD[0], NEW[1])]
        self.assertEqual(mf.trusted_keys(OLD[1], chain), [OLD[1], NEW[1], NEWER[1]])
        newest, newest_signature = release(*NEWER)
        self.assertEqual(
            mf.check_update_with_keys(newest, newest_signature, mf.trusted_keys(OLD[1], chain), **copy()).outcome,
            mf.UPDATE)
        # 5. a stranger's statement for its own key changes nothing
        sneaky = mf.trusted_keys(OLD[1], [mf.sign_key_statement(STRANGER[0], STRANGER[1])])
        self.assertEqual(sneaky, [OLD[1]])
        forged, forged_signature = release(*STRANGER)
        self.assertEqual(mf.check_update_with_keys(forged, forged_signature, sneaky, **copy()).outcome,
                         mf.BAD_SIGNATURE)

    def test_the_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_file = Path(tmp) / "old.key"
            old_file.write_bytes(base64.b64encode(OLD[0]) + b"\n")
            out = Path(tmp) / "update.key"
            new_text = base64.b64encode(NEW[1]).decode()
            self.assertEqual(mf.main(["key-statement", "--old-key", str(old_file), "--new-public-key", new_text,
                                      "--out", str(out)]), 0)
            self.assertEqual(len(out.read_bytes()), 96)
            self.assertEqual(mf.main(["check-key-statement", str(out), "--public-key",
                                      base64.b64encode(OLD[1]).decode()]), 0)
            self.assertEqual(mf.main(["check-key-statement", str(out), "--public-key",
                                      base64.b64encode(STRANGER[1]).decode()]), 1)


if __name__ == "__main__":
    unittest.main()
