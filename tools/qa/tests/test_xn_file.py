# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""X-notifier's file of accounts, written and read for the checks (ROADMAP P5.80)."""
import base64
import unittest

from tools.qa import xn_file as xn

PASSPHRASE = "made-up passphrase"
BLOCK = bytes.fromhex("00112233445566778899aabbccddeeff")


class AesTests(unittest.TestCase):
    def test_the_standard_s_examples(self):
        # FIPS 197, appendix C.1 and C.3
        self.assertEqual(xn.aes_block(BLOCK, bytes(range(16))).hex(), "69c4e0d86a7b0430d8cdb78070b4c55a")
        self.assertEqual(xn.aes_block(BLOCK, bytes(range(32))).hex(), "8ea2b7ca516745bfeafc49904b496089")

    def test_the_key_is_one_block_twice(self):
        key = xn.key_of(PASSPHRASE)
        self.assertEqual(key.hex(), "cca67f531936ab2692ef5c3afed58447" * 2)
        typed = PASSPHRASE.encode().ljust(32, b"\0")
        self.assertEqual(key[:16], xn.aes_block(typed[:16], typed))

    def test_a_long_passphrase_counts_by_its_first_32_bytes(self):
        self.assertEqual(xn.key_of("x" * 32), xn.key_of("x" * 40))
        self.assertNotEqual(xn.key_of("x" * 31), xn.key_of("x" * 32))


class LineTests(unittest.TestCase):
    TEXT = "gmail\talice@example.com\tmade-up-password-1\t20261116"

    def test_a_known_line(self):
        line = xn.encrypt(self.TEXT, PASSPHRASE, bytes(range(8)))
        self.assertEqual(line, "AAECAwQFBgcSzWH+aVkUnPm8ZrgffLDX4mgi/NUPZLf7t9hn0pTVX2MAb39Lxpqs9YP5bj3xGICJJF8=")
        self.assertEqual(xn.decrypt(line, PASSPHRASE), self.TEXT)

    def test_the_line_is_the_start_and_the_text_s_length(self):
        raw = base64.b64decode(xn.encrypt(self.TEXT, PASSPHRASE, bytes(range(8))))
        self.assertEqual(raw[:8], bytes(range(8)))
        self.assertEqual(len(raw), 8 + len(self.TEXT))

    def test_other_letters_and_another_passphrase(self):
        text = "gmail\tzoë@example.org\tпароль\t7"
        self.assertEqual(xn.decrypt(xn.encrypt(text, "pässphrase"), "pässphrase"), text)
        self.assertNotEqual(xn.decrypt(xn.encrypt(text, PASSPHRASE), "another"), text)


class FileTests(unittest.TestCase):
    ACCOUNTS = [("gmail", "alice@example.com", "pw one"), ("app_forums", "bob", "pw2")]

    def test_the_form(self):
        text = xn.write(self.ACCOUNTS, PASSPHRASE, preferences=[("accounts.[gmail#alice@example.com].alias", 0, "Work")])
        lines = text.split("\r\n")
        self.assertEqual(lines[0], "[---<info>---]")
        self.assertEqual(lines[2], "[---<preferences>---]")
        self.assertEqual(lines[3], "accounts.[gmail#alice@example.com].alias\t0\tWork")
        self.assertEqual(lines[4], "[---<accounts>---]")
        self.assertEqual(lines[-1], "[------]")
        self.assertEqual(len(lines), 8)
        self.assertNotIn("pw one", text)

    def test_read_back(self):
        got = xn.read(xn.write(self.ACCOUNTS, PASSPHRASE, token="42"), PASSPHRASE)
        self.assertEqual(got["token"], "42")
        self.assertEqual(got["accounts"], self.ACCOUNTS)
        self.assertEqual(got["preferences"], [("soundUrl", "0", "")])

    def test_what_does_not_open(self):
        text = xn.write(self.ACCOUNTS, PASSPHRASE)
        self.assertIsNone(xn.read(text, "another"))
        self.assertIsNone(xn.read("not such a file", PASSPHRASE))
        self.assertIsNone(xn.read("[---<info>---]\r\nAAAA\r\n[------]", PASSPHRASE))

    def test_a_line_of_another_file_is_left_out(self):
        text = xn.write(self.ACCOUNTS, PASSPHRASE, token="42")
        stray = xn.encrypt("gmail\teve@example.com\tpw\t43", PASSPHRASE)
        text = text.replace("[------]", stray + "\r\n[------]")
        self.assertEqual(xn.read(text, PASSPHRASE)["accounts"], self.ACCOUNTS)


if __name__ == "__main__":
    unittest.main()
