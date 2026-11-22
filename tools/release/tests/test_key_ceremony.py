# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""The key ceremony (ROADMAP P2.11): minisign's formats, the offline check, the encrypted backup, the restore test
and unlock. GnuPG runs for real on Linux; elsewhere a stand-in plays the APT key."""
import base64
import io
import json
import os
import shutil
import socket
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from tools.release import key_ceremony as kc
from tools.update import manifest as mf

PASSPHRASE = "correct horse battery staple again"
FAST = {"n": 2 ** 14, "r": 8, "p": 1}
REAL_GPG = os.name != "nt" and shutil.which("gpg") is not None


def fake_apt(test: unittest.TestCase):
    """A stand-in APT key where GnuPG is not run: a fixed keyring, its 'secret' a file in the home."""
    def make_apt(home, public, when):
        home.mkdir()
        (home / "secret").write_bytes(os.urandom(16))
        (public / kc.KEYRING).write_bytes(b"keyring of " + (home / "secret").read_bytes())
        return "A" * 40

    def check_apt(home, keyring, fingerprint, root_needed):
        if keyring.read_bytes() != b"keyring of " + (home / "secret").read_bytes():
            raise kc.CeremonyError("the APT key's signature does not verify under the published keyring")
        return f"APT key {fingerprint}: stand-in"

    def unlock_apt(source, target, fingerprint):
        shutil.copytree(source, target)
    for name, stand_in in (("make_apt", make_apt), ("check_apt", check_apt), ("unlock_apt", unlock_apt),
                           ("stop_agent", lambda home: None)):
        patcher = mock.patch.object(kc, name, stand_in)
        patcher.start()
        test.addCleanup(patcher.stop)


class Case(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="kc-test-"))
        self.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))
        patcher = mock.patch.object(kc, "SCRYPT", FAST)
        patcher.start()
        self.addCleanup(patcher.stop)
        if not REAL_GPG:
            fake_apt(self)

    def made(self, name="keys") -> Path:
        kc.make(self.root / name, offline=True)
        return self.root / name


class MinisignTests(unittest.TestCase):
    def test_a_key_signs_and_its_public_key_verifies(self):
        secret, public = kc.minisign_new()
        signature = kc.minisign_sign(secret, b"SHA256SUMS", "timestamp:0")
        self.assertTrue(kc.minisign_verifies(public, b"SHA256SUMS", signature))
        self.assertFalse(kc.minisign_verifies(public, b"SHA256SUMs", signature))
        _, other = kc.minisign_new()
        self.assertFalse(kc.minisign_verifies(other, b"SHA256SUMS", signature))
        changed = signature.replace("timestamp:0", "timestamp:1")
        self.assertFalse(kc.minisign_verifies(public, b"SHA256SUMS", changed))

    def test_the_file_forms_are_minisign_s(self):
        secret, public = kc.minisign_new()
        raw_secret = base64.b64decode(secret.splitlines()[1])
        raw_public = base64.b64decode(public.splitlines()[1])
        self.assertEqual((len(raw_secret), raw_secret[:6]), (158, b"Ed\0\0B2"))
        self.assertEqual((len(raw_public), raw_public[:2]), (42, b"Ed"))
        self.assertEqual(raw_secret[54:62], raw_public[2:10])          # the same key id
        self.assertEqual(raw_secret[94:126], raw_public[10:])          # libsodium's secret key ends with the public
        self.assertTrue(public.startswith("untrusted comment: minisign public key "))

    def test_a_damaged_or_encrypted_secret_key_is_refused(self):
        secret, _ = kc.minisign_new()
        raw = bytearray(base64.b64decode(secret.splitlines()[1]))
        raw[100] ^= 1
        with self.assertRaisesRegex(kc.CeremonyError, "checksum"):
            kc.minisign_sign("c\n" + base64.b64encode(bytes(raw)).decode() + "\n", b"x", "t")
        raw[100] ^= 1
        raw[2:4] = b"Sc"
        with self.assertRaisesRegex(kc.CeremonyError, "encrypted by minisign"):
            kc.minisign_sign("c\n" + base64.b64encode(bytes(raw)).decode() + "\n", b"x", "t")


class PlaceTests(unittest.TestCase):
    def test_a_route_is_seen_without_sending(self):
        connected = []

        class Socket:
            def __init__(self, family, kind):
                self.family = family

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def connect(self, address):
                connected.append(address)
                raise OSError("unreachable")
        with mock.patch.object(socket, "socket", Socket):
            self.assertFalse(kc.network_route())
        self.assertEqual([a[0] for a in connected], ["192.0.2.1", "2001:db8::1"])
        with mock.patch.object(Socket, "connect", lambda self, address: None), \
                mock.patch.object(socket, "socket", Socket):
            self.assertTrue(kc.network_route())

    def test_synced_folders_and_repositories_are_refused(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(root, True))
        self.assertIsNone(kc.private_place_problem(root / "keys"))
        self.assertIn("cloud", kc.private_place_problem(root / "Google Drive" / "keys"))
        self.assertIn("cloud", kc.private_place_problem(root / "OneDrive - Work" / "keys"))
        (root / "repo" / ".git").mkdir(parents=True)
        self.assertIn("git repository", kc.private_place_problem(root / "repo" / "sub" / "keys"))

    def test_a_gnupg_folder_too_deep_for_its_sockets_is_refused(self):
        with self.assertRaisesRegex(kc.CeremonyError, "too long for GnuPG"):
            kc.gpg(Path(tempfile.gettempdir()) / ("d" * 90), "--version")

    def test_the_gpg_creation_time_is_midnight_utc(self):
        self.assertEqual(kc.midnight_utc(1795375800.5), 1795305600)   # 2026-11-22 19:30:00.5 UTC


class CeremonyTests(Case):
    def test_make_writes_four_keys_and_their_public_halves(self):
        keys = self.made()
        self.assertEqual(sorted(p.name for p in keys.iterdir()), sorted(kc.TOP))
        info = json.loads((keys / "public" / kc.PUBLIC_JSON).read_text(encoding="ascii"))
        self.assertTrue(info["made_offline"])
        self.assertEqual(mf.public_key_of(mf.read_private_key(keys / kc.UPDATE_KEY)),
                         base64.b64decode(info["update_manifest"]))
        self.assertNotEqual(info["update_manifest"], info["adblock_resources"])
        published = b"".join(p.read_bytes() for p in (keys / "public").iterdir())
        for secret in (kc.UPDATE_KEY, kc.ADBLOCK_KEY):
            self.assertNotIn((keys / secret).read_text().strip().encode(), published)
        self.assertNotIn((keys / kc.MINISIGN_KEY).read_text().splitlines()[1].encode(), published)
        self.assertEqual(len(kc.check_keys(keys, keys / "public", root_needed=True)), 4)

    def test_make_never_writes_into_a_folder_that_holds_something(self):
        (self.root / "busy").mkdir()
        (self.root / "busy" / "note.txt").write_text("mine")
        with self.assertRaisesRegex(kc.CeremonyError, "not an empty folder"):
            kc.make(self.root / "busy", offline=True)
        self.assertEqual((self.root / "busy" / "note.txt").read_text(), "mine")

    def test_backup_then_restore_test(self):
        keys = self.made()
        sealed = self.root / "keys.thoronkeys"
        kc.backup(keys, sealed, PASSPHRASE)
        public = self.root / "published"
        shutil.copytree(keys / "public", public)
        kc.lock(keys)
        self.assertFalse(keys.exists())
        self.assertEqual(len(kc.restore_test(sealed, public, PASSPHRASE)), 4)
        with self.assertRaisesRegex(kc.CeremonyError, "backup is never written over"):
            kc.backup(self.made("again"), sealed, PASSPHRASE)

    def test_the_backup_holds_no_key_in_the_clear(self):
        keys = self.made()
        sealed = self.root / "keys.thoronkeys"
        kc.backup(keys, sealed, PASSPHRASE)
        raw = sealed.read_bytes()
        self.assertTrue(raw.startswith(kc.MAGIC))
        for name in (kc.UPDATE_KEY, kc.ADBLOCK_KEY):
            key = (keys / name).read_text().strip()
            self.assertNotIn(key.encode(), raw)
            self.assertNotIn(base64.b64decode(key), raw)
        self.assertNotIn(b"minisign", raw)

    def test_a_wrong_passphrase_or_a_changed_byte_is_refused(self):
        keys = self.made()
        sealed = self.root / "keys.thoronkeys"
        kc.backup(keys, sealed, PASSPHRASE)
        with self.assertRaisesRegex(kc.CeremonyError, "passphrase is wrong"):
            kc.restore_test(sealed, keys / "public", PASSPHRASE + "!")
        raw = bytearray(sealed.read_bytes())
        raw[-20] ^= 1
        (self.root / "changed").write_bytes(bytes(raw))
        with self.assertRaisesRegex(kc.CeremonyError, "changed or damaged"):
            kc.restore_test(self.root / "changed", keys / "public", PASSPHRASE)
        header = sealed.read_bytes().replace(b'"r": 8', b'"r": 9')
        (self.root / "header").write_bytes(header)
        with self.assertRaisesRegex(kc.CeremonyError, "settings"):
            kc.restore_test(self.root / "header", keys / "public", PASSPHRASE)

    def test_a_backup_of_other_keys_fails_the_restore_test(self):
        keys, other = self.made("one"), self.made("two")
        sealed = self.root / "one.thoronkeys"
        kc.backup(keys, sealed, PASSPHRASE)
        with self.assertRaises(kc.CeremonyError):
            kc.restore_test(sealed, other / "public", PASSPHRASE)

    def test_a_path_out_of_the_folder_is_refused(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as z:
            z.writestr("../outside.txt", b"x")
        with mock.patch.object(kc, "_packed", lambda files: buffer.getvalue()):
            sealed = kc.seal({}, PASSPHRASE)
        with self.assertRaisesRegex(kc.CeremonyError, "unexpected path"):
            kc.opened(sealed, PASSPHRASE)

    def test_unlock_gives_what_a_release_signs_with(self):
        keys = self.made()
        sealed = self.root / "keys.thoronkeys"
        kc.backup(keys, sealed, PASSPHRASE)
        out = self.root / "unlocked"
        info = kc.unlock(sealed, out, PASSPHRASE)
        self.assertEqual(sorted(p.name for p in out.iterdir()), sorted(kc.TOP))
        self.assertEqual((out / kc.MINISIGN_KEY).read_bytes(), (keys / kc.MINISIGN_KEY).read_bytes())
        self.assertEqual(info["apt_fingerprint"], json.loads((keys / "public" / kc.PUBLIC_JSON).read_text())[
            "apt_fingerprint"])
        kc.lock(out)
        self.assertFalse(out.exists())

    def test_lock_deletes_only_a_key_folder(self):
        other = self.root / "photos"
        other.mkdir()
        (other / "a.jpg").write_bytes(b"x")
        with self.assertRaisesRegex(kc.CeremonyError, "nothing was deleted"):
            kc.lock(other)
        self.assertTrue((other / "a.jpg").exists())

    def test_test_keys_are_marked(self):
        kc.make(self.root / "online", offline=False)
        info = kc.read_public(self.root / "online" / "public")
        self.assertIn("TEST KEYS", kc.where_they_go(info)[0])
        self.assertIn("kResourcesPublicKey", "\n".join(kc.where_they_go(info)))

    def test_make_refuses_with_a_network_route(self):
        with mock.patch.object(kc, "network_route", lambda: True):
            self.assertEqual(kc.main(["make", "--out", str(self.root / "k")]), 1)
        self.assertFalse((self.root / "k").exists())


@unittest.skipUnless(REAL_GPG, "GnuPG on Linux")
class GnuPGTests(Case):
    def test_the_apt_root_only_certifies_and_stays_in_the_backup(self):
        keys = self.made()
        home = keys / kc.APT_HOME
        rows = kc._colons(home, secret=True)
        own = [("".join(c for c in r[11] if c.islower()), r[0]) for r in rows if r[0] in ("sec", "ssb")]
        self.assertEqual(own, [("c", "sec"), ("s", "ssb")])     # the root only certifies, the subkey signs
        self.assertEqual([r[5] for r in rows if r[0] in ("sec", "ssb")], [str(kc.midnight_utc())] * 2)
        self.assertEqual([r[6] for r in rows if r[0] in ("sec", "ssb")], ["", ""])  # no expiry
        sealed = self.root / "keys.thoronkeys"
        kc.backup(keys, sealed, PASSPHRASE)
        out = self.root / "unlocked"
        kc.unlock(sealed, out, PASSPHRASE)
        unlocked = kc._colons(out / kc.APT_HOME, secret=True)
        self.assertEqual([r[14] for r in unlocked if r[0] == "sec"], ["#"])        # only the root's stub
        self.assertFalse((out / kc.APT_HOME / "openpgp-revocs.d").exists())
        kc.lock(out)

    def test_apt_repo_signs_with_the_unlocked_subkey(self):
        from tools.release import apt_repo
        keys = self.made()
        sealed = self.root / "keys.thoronkeys"
        kc.backup(keys, sealed, PASSPHRASE)
        out = self.root / "unlocked"
        info = kc.unlock(sealed, out, PASSPHRASE)
        inrelease, detached = apt_repo.sign(b"Origin: Thoron\n", out / kc.APT_HOME, info["apt_fingerprint"])
        (self.root / "Release").write_bytes(b"Origin: Thoron\n")
        (self.root / "Release.gpg").write_bytes(detached)
        if shutil.which("gpgv"):
            done = subprocess.run(["gpgv", "--keyring", str(out / "public" / kc.KEYRING),
                                   str(self.root / "Release.gpg"), str(self.root / "Release")], capture_output=True)
            self.assertEqual(done.returncode, 0, done.stderr)
        kc.lock(out)


if __name__ == "__main__":
    unittest.main()
