# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""The signed flat APT repository (ROADMAP P2.10): package names per variant, the index, Release and signing."""
import datetime as dt
import gzip
import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.release import apt_repo as ar
from tools.release import elf_check
from tools.release.tests.test_portable_linux import deb, the_deb

NOW = dt.datetime(2026, 11, 21, 12, 0, 0, tzinfo=dt.timezone.utc)


def members(data: bytes) -> dict:
    return dict(elf_check._ar_members(data))


class VariantDebTests(unittest.TestCase):
    def setUp(self):
        self.original = deb(the_deb())

    def test_the_sse4_build_is_a_package_of_its_own_that_excludes_the_avx2_one(self):
        made = ar.variant_deb(self.original, "linux-x64-sse4")
        fields = dict(ar.control_of(made))
        self.assertEqual(fields["Package"], "thoron-browser-sse4")
        self.assertIn("thoron-browser", [p.strip() for p in fields["Conflicts"].split(",")])
        self.assertIn("thoron-browser", [p.strip() for p in fields["Replaces"].split(",")])
        self.assertEqual(fields["Version"], "158.0.8127.6504-1")

    def test_the_avx2_build_keeps_its_name_and_excludes_the_sse4_one(self):
        fields = dict(ar.control_of(ar.variant_deb(self.original, "linux-x64-avx2")))
        self.assertEqual(fields["Package"], "thoron-browser")
        self.assertEqual(fields["Conflicts"], "thoron-browser-sse4")

    def test_the_arm64_build_is_left_as_it_is_but_for_its_control_file(self):
        fields = dict(ar.control_of(ar.variant_deb(self.original, "linux-arm64-armv8")))
        self.assertEqual(fields["Package"], "thoron-browser")
        self.assertNotIn("Conflicts", fields)

    def test_the_program_files_are_byte_for_byte_the_builds(self):
        made = members(ar.variant_deb(self.original, "linux-x64-sse4"))
        before = members(self.original)
        self.assertEqual(list(made)[:1], ["debian-binary"])
        self.assertEqual(made["data.tar.xz"], before["data.tar.xz"])
        self.assertEqual(made["debian-binary"], b"2.0\n")

    def test_a_deb_named_for_its_variant_already_is_left_byte_for_byte(self):
        once = ar.variant_deb(self.original, "linux-x64-sse4")
        self.assertEqual(ar.variant_deb(once, "linux-x64-sse4"), once)
        arm = ar.variant_deb(self.original, "linux-arm64-armv8")
        self.assertEqual(ar.variant_deb(arm, "linux-arm64-armv8"), arm)

    def test_existing_relations_are_kept(self):
        self.assertEqual(ar._relations("thoron-browser-unstable", ["thoron-browser"]),
                         "thoron-browser-unstable, thoron-browser")
        self.assertEqual(ar._relations("thoron-browser (<< 1)", ["thoron-browser"]), "thoron-browser (<< 1)")

    def test_an_unknown_variant_or_a_broken_deb_is_refused(self):
        with self.assertRaises(ar.AptError):
            ar.variant_deb(self.original, "linux-x64-avx512")
        with self.assertRaises(Exception):
            ar.variant_deb(b"not a deb", "linux-x64-sse4")

    def test_a_control_file_keeps_continuation_lines(self):
        fields = ar.parse_fields("Package: a\nDescription: one\n two\n .\n three\n")
        self.assertEqual(fields, [("Package", "a"), ("Description", "one\n two\n .\n three")])
        self.assertEqual(ar.parse_fields(ar.format_fields(fields)), fields)


class IndexTests(unittest.TestCase):
    def test_a_stanza_names_the_file_beside_the_index_and_its_hashes(self):
        data = ar.variant_deb(deb(the_deb()), "linux-x64-sse4")
        stanza = dict(ar.parse_fields(ar.packages_stanza(data, "x.deb")))
        self.assertEqual(stanza["Filename"], "apt/x.deb")
        self.assertEqual(stanza["Size"], str(len(data)))
        self.assertEqual(stanza["SHA256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(stanza["SHA512"], hashlib.sha512(data).hexdigest())
        self.assertNotIn("MD5sum", stanza)

    def test_the_release_lists_every_index_file_and_expires(self):
        files = {"Packages": b"P", "Packages.gz": gzip.compress(b"P", mtime=0)}
        text = ar.release_text(files, ["arm64", "amd64", "amd64"], NOW, 30)
        self.assertIn("Architectures: amd64 arm64\n", text)
        self.assertIn("Date: Sat, 21 Nov 2026 12:00:00 UTC\n", text)
        self.assertIn("Valid-Until: Mon, 21 Dec 2026 12:00:00 UTC\n", text)
        self.assertIn(f" {hashlib.sha256(b'P').hexdigest()}          1 Packages\n", text)
        self.assertIn("SHA512:\n", text)
        self.assertNotIn("MD5Sum", text)
        self.assertIn("Suite: apt/\n", text)  # the folder the source names: apt warns about any other

    def test_the_sources_file_trusts_only_thorons_keyring(self):
        text = ar.sources_text("KuchiSofts/thoron")
        self.assertIn("URIs: https://github.com/KuchiSofts/thoron/releases/download/\n", text)
        self.assertIn("Suites: apt/\n", text)  # no "./" in any request
        self.assertNotIn("./", text)
        self.assertIn("Signed-By: /usr/share/keyrings/thoron-archive-keyring.gpg\n", text)


@unittest.skipUnless(shutil.which("gpg") and shutil.which("gpgv") and os.name != "nt", "gpg on Linux")
class SignedBuildTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="apt repo "))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.home = self.dir / "gnupg"
        self.home.mkdir(mode=0o700)
        subprocess.run(["gpg", "--homedir", str(self.home), "--batch", "--passphrase", "", "--quick-gen-key",
                        "Thoron test <test@example.org>", "ed25519", "sign", "1d"], check=True, capture_output=True)
        listed = subprocess.run(["gpg", "--homedir", str(self.home), "--with-colons", "--list-keys"],
                                capture_output=True, text=True).stdout
        self.key = next(line.split(":")[9] for line in listed.splitlines() if line.startswith("fpr:"))
        for variant in ("linux-x64-avx2", "linux-x64-sse4", "linux-arm64-armv8"):
            files = the_deb()
            (self.dir / f"thoron-158.0.8127.6504-{variant}.deb").write_bytes(deb(files))

    def debs(self):
        return [(self.dir / f"thoron-158.0.8127.6504-{v}.deb", v)
                for v in ("linux-x64-avx2", "linux-x64-sse4")]

    def verify(self, folder: Path, name: str = "InRelease") -> bool:
        return subprocess.run(["gpgv", "--keyring", str(folder / ar.KEYRING), str(folder / name)],
                              capture_output=True).returncode == 0

    def test_the_repository_is_signed_and_a_changed_inrelease_is_refused(self):
        out = self.dir / "repo"
        names = sorted(p.name for p in ar.build(self.debs(), out, self.home, self.key, now=NOW))
        self.assertEqual(names, sorted(["InRelease", "Packages", "Packages.gz", "Release", "Release.gpg",
                                        "thoron-archive-keyring.gpg", "thoron-browser-sse4_158.0.8127.6504-1_amd64.deb",
                                        "thoron-browser_158.0.8127.6504-1_amd64.deb"]))
        self.assertTrue(self.verify(out))
        text = (out / "InRelease").read_text()
        self.assertIn(hashlib.sha256((out / "Packages").read_bytes()).hexdigest(), text)
        changed = text.replace("Valid-Until: Mon", "Valid-Until: Tue", 1)
        (out / "InRelease").write_text(changed)
        self.assertFalse(self.verify(out))

    def test_the_same_repository_is_signed_again_with_a_later_valid_until(self):
        out = self.dir / "repo"
        ar.build(self.debs(), out, self.home, self.key, now=NOW)
        packages = (out / "Packages").read_bytes()
        ar.resign(out, self.home, self.key, now=NOW + dt.timedelta(days=25))
        self.assertEqual((out / "Packages").read_bytes(), packages)
        self.assertIn("Valid-Until: Fri, 15 Jan 2027 12:00:00 UTC", (out / "InRelease").read_text())
        self.assertTrue(self.verify(out))
        deb = next(out.glob("thoron-browser-sse4_*.deb"))
        deb.write_bytes(deb.read_bytes() + b"x")
        with self.assertRaises(ar.AptError):
            ar.resign(out, self.home, self.key)

    def test_an_index_that_never_expires_or_a_second_build_of_one_name_is_refused(self):
        with self.assertRaises(ar.AptError):
            ar.build(self.debs(), self.dir / "a", self.home, self.key, valid_days=0)
        with self.assertRaises(ar.AptError):
            ar.build(self.debs()[:1] * 2, self.dir / "b", self.home, self.key)


if __name__ == "__main__":
    unittest.main()
