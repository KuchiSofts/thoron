# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""The key ceremony's Windows Sandbox (ROADMAP P2.11): what it may read and write, and what it is given. The
ceremony itself runs in a real Sandbox in the release checks (docs/release/KEYS.md, section 5)."""
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.release import key_ceremony_sandbox as ks


class SandboxTests(unittest.TestCase):
    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="ks-test-"))
        self.addCleanup(lambda: shutil.rmtree(self.work, ignore_errors=True))

    def test_no_network_and_only_the_out_folder_is_writable(self):
        config = ks.wsb({"in": Path(r"C:\w\in"), "python": Path(r"C:\py"), "git": Path(r"C:\git")}, Path(r"C:\o"))
        self.assertIn("<Networking>Disable</Networking>", config)
        self.assertIn("<ClipboardRedirection>Disable</ClipboardRedirection>", config)
        for name in ("in", "python", "git"):
            self.assertIn(f"<SandboxFolder>C:\\Ceremony\\{name}</SandboxFolder><ReadOnly>true</ReadOnly>", config)
        self.assertIn("<HostFolder>C:\\o</HostFolder><SandboxFolder>C:\\Ceremony\\out</SandboxFolder>"
                      "<ReadOnly>false</ReadOnly>", config)
        self.assertEqual(config.count("<ReadOnly>false</ReadOnly>"), 1)

    def test_the_sandbox_gets_the_ceremony_and_a_passphrase_only_when_given(self):
        with mock.patch.object(ks, "git_folder", lambda: Path(r"C:\git")):
            folders = ks.stage(self.work, None)
        inside = folders["in"]
        for name in ks.MODULES:
            self.assertTrue((inside / name).is_file(), name)
        self.assertTrue((inside / "site" / "cryptography" / "__init__.py").is_file())
        self.assertIn("network_route()", (inside / "ceremony.py").read_text(encoding="utf-8"))
        self.assertFalse((inside / "passphrase.txt").exists())
        with mock.patch.object(ks, "git_folder", lambda: Path(r"C:\git")):
            ks.stage(self.work / "t", "a test passphrase")
        self.assertTrue((self.work / "t" / "in" / "passphrase.txt").is_file())

    def test_a_made_passphrase_is_long_random_and_never_written_over(self):
        made = ks.make_passphrase(self.work / "pass" / "passphrase.txt")
        self.assertEqual(len(made), 39)
        self.assertEqual(made.count("-"), 7)
        self.assertTrue(set(made.replace("-", "")) <= set(ks.PASSPHRASE_LETTERS))
        self.assertGreaterEqual(len(made.replace("-", "")) * 4.95, 158)          # bits: 32 letters of 31
        self.assertEqual((self.work / "pass" / "passphrase.txt").read_text(encoding="ascii"), made + "\n")
        self.assertNotEqual(made, ks.make_passphrase(self.work / "pass" / "other.txt"))
        with self.assertRaisesRegex(ks.kc.CeremonyError, "never written over"):
            ks.make_passphrase(self.work / "pass" / "passphrase.txt")
        with self.assertRaisesRegex(ks.kc.CeremonyError, "the passphrase"):
            ks.make_passphrase(self.work / "Google Drive" / "passphrase.txt")

    def test_backup_copies_are_checked_and_never_written_over(self):
        backup = self.work / "thoron-keys-2026-11-23.thoronkeys"
        backup.write_bytes(b"THORON-KEYS\n" + bytes(range(256)))
        copies = ks.copy_backup(backup, [self.work / "a", self.work / "b"])
        self.assertEqual([c.read_bytes() for c in copies], [backup.read_bytes()] * 2)
        with self.assertRaisesRegex(ks.kc.CeremonyError, "never written over"):
            ks.copy_backup(backup, [self.work / "a"])

    def test_a_folder_that_holds_something_is_refused(self):
        (self.work / "note.txt").write_text("mine")
        with mock.patch.object(ks, "SANDBOX", Path(__file__)), mock.patch.object(ks, "sandbox_running", lambda: False):
            with self.assertRaisesRegex(ks.kc.CeremonyError, "not an empty folder"):
                ks.run(self.work, timeout=1)
        self.assertEqual((self.work / "note.txt").read_text(), "mine")


if __name__ == "__main__":
    unittest.main()
