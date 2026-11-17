# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Tests of the parts of about_updater_states_check.py that do not need a browser."""
import base64
import hashlib
import ssl
import tempfile
import unittest
import urllib.request
import zipfile
from pathlib import Path

from tools.qa import about_updater_states_check as st
from tools.update import manifest as mf

# The public half the test key build trusts (chrome/browser/thoron_update/args.gni)
TEST_PUBLIC = base64.b64decode("9i/S9Os0cVBrrPIeJJEiTNqJucILUa97MBNquyuERHM=")


class StatesCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_test_key_is_the_one_the_test_build_trusts(self):
        self.assertEqual(mf.public_key_of(st.TEST_KEY), TEST_PUBLIC)
        self.assertNotEqual(mf.public_key_of(st.OTHER_KEY), TEST_PUBLIC)

    def test_manifests_verify_with_the_test_key_and_not_with_the_other(self):
        package = self.root / "thoron-158.0.8127.6501-win-x64-avx2-portable.zip"
        package.write_bytes(b"package")
        packages = {st.VARIANT: {"portable": {"full": st.entry(package, "v0.1.2")}}}
        raw, sig = st.signed("158.0.8127.6501", packages, thoron_version="0.1.2")
        data = mf.verify(raw, sig, TEST_PUBLIC, allowed_hosts=mf.DEFAULT_HOSTS)
        self.assertEqual(data["version"], "158.0.8127.6501")
        self.assertEqual(data["packages"][st.VARIANT]["portable"]["full"]["url"],
                         f"https://github.com/{st.GH_REPO}/releases/download/v0.1.2/{package.name}")
        raw, sig = st.signed("158.0.8127.6501", packages, key=st.OTHER_KEY)
        with self.assertRaises(mf.SignatureError):
            mf.verify(raw, sig, TEST_PUBLIC, allowed_hosts=mf.DEFAULT_HOSTS)
        raw, sig = st.signed("158.0.8127.6502", packages, min_updater="158.0.8127.6501")
        self.assertEqual(mf.verify(raw, sig, TEST_PUBLIC, allowed_hosts=mf.DEFAULT_HOSTS)["min_updater_version"],
                         "158.0.8127.6501")

    def test_the_newer_package_is_the_same_files_under_the_newer_folder(self):
        source = self.root / "old.zip"
        with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("ThoronPortable/Thoron.exe", b"launcher")
            z.writestr("ThoronPortable/Application/current", b"158.0.8127.6500\n")
            z.writestr("ThoronPortable/Application/158.0.8127.6500/thoron.exe", b"browser")
        target = st.renamed_package(source, "158.0.8127.6500", "158.0.8127.6501", self.root / "new.zip")
        with zipfile.ZipFile(target) as z:
            self.assertEqual(sorted(z.namelist()), ["ThoronPortable/Application/158.0.8127.6501/thoron.exe",
                                                    "ThoronPortable/Application/current", "ThoronPortable/Thoron.exe"])
            self.assertEqual(z.read("ThoronPortable/Application/158.0.8127.6501/thoron.exe"), b"browser")
            self.assertTrue(all(i.compress_type == zipfile.ZIP_STORED for i in z.infolist()))

    def test_versions_are_counted_up_in_the_last_part(self):
        self.assertEqual(st.bump("158.0.8127.6500", 1), "158.0.8127.6501")
        self.assertEqual(st.bump("158.0.8127.6599", 2), "158.0.8127.6601")

    def test_the_server_answers_as_github_with_its_own_certificate(self):
        key_file, cert_file, spki = st.certificate(self.root)
        with st.Server(key_file, cert_file) as server:
            server.files = {"update.json": b"{}"}
            context = ssl.create_default_context(cafile=str(cert_file))
            context.check_hostname = False
            url = f"https://127.0.0.1:{server.port}/{st.GH_REPO}/releases/latest/download/update.json"
            self.assertEqual(urllib.request.urlopen(url, context=context, timeout=10).read(), b"{}")
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(url.replace("update.json", "update.key"), context=context, timeout=10)
            self.assertEqual(caught.exception.code, 404)
            der = ssl.PEM_cert_to_DER_cert(cert_file.read_text())
            from cryptography import x509
            from cryptography.hazmat.primitives import serialization
            spki_der = x509.load_der_x509_certificate(der).public_key().public_bytes(
                serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
            self.assertEqual(spki, base64.b64encode(hashlib.sha256(spki_der).digest()).decode())

    def test_every_case_has_a_line_to_look_for(self):
        self.assertEqual(sorted(st.CASES), ["cannot verify", "error", "needs installer", "no package", "up to date"])
        self.assertTrue(st.UPDATING.search("Updating Thoron (42%)"))
        self.assertTrue(st.RELAUNCH.search("Nearly up to date! Relaunch Thoron to finish updating."))


if __name__ == "__main__":
    unittest.main()
