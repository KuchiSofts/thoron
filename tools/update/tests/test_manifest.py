# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""The update manifest (ROADMAP P3.1, P3.2): the schema, the exact bytes, the signature, and what a copy
of Thoron does with a manifest. Keys are made in memory for one test run and never written anywhere."""
import base64
import contextlib
import hashlib
import io
import json
import random
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.release import adblock_resources as ar
from tools.release import release
from tools.release import version as ver
from tools.update import manifest as mf

HOSTS = ("github.com",)
NEW, OLD = "158.0.8127.4500", "158.0.8127.3000"
PUBLISHED = mf.parse_time("2026-12-01T12:00:00Z")
EXPIRES = mf.parse_time("2026-12-31T12:00:00Z")
NOW = PUBLISHED + 3600
DAY = 86400
SERIAL = 2026120100
AVX2 = ("packages", "win-x64-avx2")
INSTALLED = AVX2 + ("installed",)
FULL = INSTALLED + ("full",)
DELTAS = INSTALLED + ("deltas",)
URL = "https://github.com/KuchiSofts/thoron/releases/download/v0.1.2/thoron.exe"
ENTRY = {"url": URL, "size": 1, "sha256": "0" * 64}
SPEC = Path(__file__).resolve().parents[3] / "docs" / "update" / "MANIFEST.md"

# The example of the spec, signed once with a key that was made for it and thrown away: a fixed vector
# for the C++ updater's tests. When example() changes, sign it with a new throwaway key and replace both
# values here and in docs/update/MANIFEST.md.
VECTOR_PUBLIC_KEY = "a21d28d09d8eb9b329c984c3a47d1c885630be54588bfc6720634ef2d23cccbc"
VECTOR_SIGNATURE = ("945aa027baf3df0751a4dbf005dacc89f9d100fb24d2e3d7bcfbf62e6027abed"
                    "45fd2727f0d246fd41da72cdcb1a5d937290f265dfe017c5076ec50544fad70a")


def sample() -> dict:
    return json.loads(mf.example())


def put(path: tuple, value):
    def change(data):
        for key in path[:-1]:
            data = data[key]
        data[path[-1]] = value
    return change


def drop(path: tuple):
    def change(data):
        for key in path[:-1]:
            data = data[key]
        del data[path[-1]]
    return change


def changed(*changes) -> dict:
    data = sample()
    for change in changes:
        change(data)
    return data


def small() -> bytes:
    """A manifest with one package: short enough to change every bit of it."""
    full = sample()["packages"]["win-x64-avx2"]["installed"]["full"]
    return mf.serialize(changed(put(("packages",), {"win-x64-avx2": {"installed": {"full": full}}})),
                        allowed_hosts=HOSTS)


def raw_signature(private_key: bytes, message: bytes) -> bytes:
    """An Ed25519 signature of any bytes, as a careless or hostile holder of the key could make."""
    from cryptography.hazmat.primitives.asymmetric import ed25519
    return ed25519.Ed25519PrivateKey.from_private_bytes(private_key).sign(message)


def signed(manifest: bytes, private_key: bytes, public_key: bytes, now: int = NOW) -> bytes:
    return mf.sign(manifest, private_key, public_key, allowed_hosts=HOSTS, now=now)


def other_digits(text: str) -> str:
    """The same text with its last digit as an Arabic-Indic one: a digit to Unicode, not to this format."""
    return text[:-1] + chr(0x660 + int(text[-1]))


# (what is wrong, the change to the example, what the message must say)
INVALID = [
    ("an unknown top-level key", put(("notes",), "x"), 'unknown key "notes"'),
    ("schema 2", put(("schema",), 2), "schema: must be 1"),
    ("schema as text", put(("schema",), "1"), "schema: must be 1"),
    ("schema as true", put(("schema",), True), "schema: must be 1"),
    ("a channel in upper case", put(("channel",), "Stable"), "channel: must be a lower-case name"),
    ("an empty channel", put(("channel",), ""), "channel: must be a lower-case name"),
    ("a channel with a space", put(("channel",), "stable channel"), "channel: must be a lower-case name"),
    ("a channel of 33 letters", put(("channel",), "s" * 33), "channel: must be a lower-case name"),
    ("a channel as a number", put(("channel",), 5), "channel: must be a lower-case name"),
    ("critical as text", put(("critical",), "true"), "critical: must be true or false"),
    ("critical as 1", put(("critical",), 1), "critical: must be true or false"),
    ("a version of three numbers", put(("version",), "158.0.8127"), "version: must be a build version"),
    ("a version with a leading zero", put(("version",), "158.0.8127.04500"), "version: must be a build version"),
    ("a version part above 65535", put(("version",), "158.0.8127.70000"), "version: 158.0.8127.70000: each part"),
    ("a version as a number", put(("version",), 158), "version: must be a build version"),
    ("a version with a line end", put(("version",), NEW + "\n"), "version: must be a build version"),
    ("a Thoron version of four numbers", put(("thoron_version",), "0.1.2.0"), "thoron_version: must be a Thoron"),
    ("a Thoron version with a leading zero", put(("thoron_version",), "0.01.2"), "thoron_version: must be a"),
    ("the Chromium version of another build", put(("chromium_version",), "158.0.8127.30"),
     "chromium_version: build 158.0.8127.4500 is Chromium 158.0.8127.45, not 158.0.8127.30"),
    ("a Chromium version that is none", put(("chromium_version",), "158"), "chromium_version: must be a build"),
    ("an updater version above the version", put(("min_updater_version",), "158.0.8127.4501"),
     "min_updater_version: must not be higher than version"),
    ("an updater version that is none", put(("min_updater_version",), "latest"), "min_updater_version: must be a"),
    ("published without Z", put(("published",), "2026-12-01T12:00:00"), "published: must be a UTC time"),
    ("published with an offset", put(("published",), "2026-12-01T12:00:00+00:00"), "published: must be a UTC"),
    ("published with a space", put(("published",), "2026-12-01 12:00:00Z"), "published: must be a UTC time"),
    ("published as seconds", put(("published",), PUBLISHED), "published: must be a UTC time"),
    ("published in month 13", put(("published",), "2026-13-01T12:00:00Z"), "published: is not a real date"),
    ("published on 30 February", put(("published",), "2026-02-30T12:00:00Z"), "published: is not a real date"),
    ("published at 24 o'clock", put(("published",), "2026-12-01T24:00:00Z"), "published: is not a real date"),
    ("published before 1970", put(("published",), "1969-12-31T23:59:59Z"), "published: must not be before 1970"),
    ("expires before published", put(("expires",), "2026-11-30T12:00:00Z"), "expires: must be later than"),
    ("expires at published", put(("expires",), "2026-12-01T12:00:00Z"), "expires: must be later than published"),
    ("expires more than 90 days on", put(("expires",), mf.format_time(PUBLISHED + 90 * DAY + 1)),
     "expires: must be at most 90 days after published"),
    ("expires as a date only", put(("expires",), "2026-12-31"), "expires: must be a UTC time"),
    ("a serial as text", put(("serial",), "2026120100"), "serial: must be a whole number"),
    ("a serial as true", put(("serial",), True), "serial: must be a whole number"),
    ("a serial of zero", put(("serial",), 0), "serial: must be a whole number"),
    ("a serial above 31 bits", put(("serial",), 2**31), "serial: must be a whole number from 1 to 2147483647"),
    ("a serial of another day", put(("serial",), 2026120200), "serial: must be the UTC day of published"),
    ("packages as a list", put(("packages",), []), "packages: must be an object with at least one variant"),
    ("no packages", put(("packages",), {}), "packages: must be an object with at least one variant"),
    ("an unknown operating system", put(("packages", "mac-x64-avx2"), {"installed": {"full": ENTRY}}),
     "packages/mac-x64-avx2: unknown variant"),
    ("AVX2 on ARM64", put(("packages", "win-arm64-avx2"), {"installed": {"full": ENTRY}}),
     "packages/win-arm64-avx2: unknown variant"),
    ("a variant without its processor", put(("packages", "win-x64"), {"installed": {"full": ENTRY}}),
     "packages/win-x64: unknown variant"),
    ("a variant with nothing in it", put(AVX2, {}), "packages/win-x64-avx2: must be an object with installed"),
    ("a variant as a list", put(AVX2, [ENTRY]), "packages/win-x64-avx2: must be an object with installed"),
    ("an unknown package kind", put(AVX2 + ("msi",), {"full": ENTRY}),
     "packages/win-x64-avx2/msi: unknown package kind"),
    ("a package as a list", put(INSTALLED, []), "packages/win-x64-avx2/installed: must be an object with full"),
    ("a package without its full package", drop(FULL), 'packages/win-x64-avx2/installed: missing key "full"'),
    ("an unknown key in a package", put(INSTALLED + ("patch",), ENTRY),
     'packages/win-x64-avx2/installed: unknown key "patch"'),
    ("deltas with none in it", put(DELTAS, {}), "installed/deltas: must hold 1 to 8 deltas"),
    ("nine deltas", put(DELTAS, {f"158.0.8127.{n}": ENTRY for n in range(2000, 2009)}),
     "installed/deltas: must hold 1 to 8 deltas"),
    ("deltas as a list", put(DELTAS, [ENTRY]), "installed/deltas: must hold 1 to 8 deltas"),
    ("a delta from the manifest's own version", put(DELTAS + (NEW,), ENTRY),
     "deltas/158.0.8127.4500: a delta applies from a version lower than the manifest's"),
    ("a delta from a higher version", put(DELTAS + ("158.0.8127.4600",), ENTRY),
     "deltas/158.0.8127.4600: a delta applies from a version lower than the manifest's"),
    ("a delta from no version", put(DELTAS + ("previous",), ENTRY), "deltas/previous: must be a build version"),
    ("a delta from a version with a leading zero", put(DELTAS + ("158.0.8127.03000",), ENTRY),
     "deltas/158.0.8127.03000: must be a build version"),
    ("a delta that is no file", put(DELTAS + (OLD,), URL), "deltas/158.0.8127.3000: must be an object with url"),
    ("a file as text", put(FULL, URL), "installed/full: must be an object with url, size and sha256"),
    ("a file without a url", drop(FULL + ("url",)), 'installed/full: missing key "url"'),
    ("a file without a size", drop(FULL + ("size",)), 'installed/full: missing key "size"'),
    ("a file without a hash", drop(FULL + ("sha256",)), 'installed/full: missing key "sha256"'),
    ("an unknown key in a file", put(FULL + ("md5",), "0" * 32), 'installed/full: unknown key "md5"'),
    ("a size of zero", put(FULL + ("size",), 0), "full/size: must be a whole number of bytes from 1 to"),
    ("a size below zero", put(FULL + ("size",), -1), "full/size: must be a whole number of bytes"),
    ("a size as text", put(FULL + ("size",), "104857600"), "full/size: must be a whole number of bytes"),
    ("a size as true", put(FULL + ("size",), True), "full/size: must be a whole number of bytes"),
    ("a size with a fraction", put(FULL + ("size",), 1.5), "full/size: must be a whole number of bytes"),
    ("a size above 31 bits", put(FULL + ("size",), 2**31), "full/size: must be a whole number of bytes"),
    ("a hash in upper case", put(FULL + ("sha256",), "A" * 64), "full/sha256: must be 64 lower-case hex digits"),
    ("a hash of 63 digits", put(FULL + ("sha256",), "a" * 63), "full/sha256: must be 64 lower-case hex digits"),
    ("a hash of 65 digits", put(FULL + ("sha256",), "a" * 65), "full/sha256: must be 64 lower-case hex digits"),
    ("a hash that is not hex", put(FULL + ("sha256",), "g" * 64), "full/sha256: must be 64 lower-case hex"),
    ("a hash as a number", put(FULL + ("sha256",), 0), "full/sha256: must be 64 lower-case hex digits"),
    ("a hash with a line end", put(FULL + ("sha256",), "a" * 64 + "\n"), "full/sha256: must be 64 lower-case"),
    ("a hash in other digits", put(FULL + ("sha256",), other_digits("1" * 64)), "full/sha256: must be 64"),
    ("a version in other digits", put(("version",), other_digits(NEW)), "version: must be a build version"),
    ("a Thoron version in other digits", put(("thoron_version",), other_digits("0.1.12")),
     "thoron_version: must be a Thoron version"),
    ("a Thoron version with a line end", put(("thoron_version",), "0.1.2\n"), "thoron_version: must be a Thoron"),
    ("an updater version in other digits", put(("min_updater_version",), other_digits(OLD)),
     "min_updater_version: must be a build version"),
    ("a channel with a line end", put(("channel",), "stable\n"), "channel: must be a lower-case name"),
    ("published in other digits", put(("published",), "2026-12-0" + chr(0x661) + "T12:00:00Z"),
     "published: must be a UTC time"),
    ("published with a line end", put(("published",), "2026-12-01T12:00:00Z\n"), "published: must be a UTC time"),
    ("expires with a line end", put(("expires",), "2026-12-31T12:00:00Z\n"), "expires: must be a UTC time"),
    ("the version of nothing installed", put(("version",), "0.0.0.0"),
     "version: 0.0.0.0 stands for nothing installed and is no release"),
    ("a delta from nothing installed", put(DELTAS + ("0.0.0.0",), ENTRY),
     "deltas/0.0.0.0: a delta applies from a release; 0.0.0.0 stands for nothing installed"),
    ("a delta from a version in other digits", put(DELTAS + (other_digits(OLD),), ENTRY),
     'deltas/"158.0.8127.300\\u0660": must be a build version'),
    ("an unknown key in a delta's file", put(DELTAS + (OLD, "md5"), "0" * 32),
     'installed/deltas/158.0.8127.3000: unknown key "md5"'),
    ("a delta's file without a size", drop(DELTAS + (OLD, "size")),
     'installed/deltas/158.0.8127.3000: missing key "size"'),
    ("a delta's size as text", put(DELTAS + (OLD, "size"), "1"), "deltas/158.0.8127.3000/size: must be a whole"),
    ("a delta's hash in upper case", put(DELTAS + (OLD, "sha256"), "A" * 64),
     "deltas/158.0.8127.3000/sha256: must be 64 lower-case hex digits"),
]

# (what is wrong with the address, the address, what the message must say)
BAD_URLS = [
    ("plain http", "http://github.com/a.exe", "must be https://<host>/<path>"),
    ("another scheme", "ftp://github.com/a.exe", "must be https://<host>/<path>"),
    ("no scheme", "github.com/a.exe", "must be https://<host>/<path>"),
    ("HTTPS in upper case", "HTTPS://github.com/a.exe", "must be https://<host>/<path>"),
    ("a host that is not allowed", "https://downloads.example.net/a.exe",
     "host downloads.example.net is not on the allow-list (github.com)"),
    ("an allowed host as the start of another", "https://github.com.example.net/a.exe", "is not on the allow-list"),
    ("a host under an allowed one", "https://files.github.com/a.exe", "is not on the allow-list"),
    ("a host with a dot at the end", "https://github.com./a.exe", "is not on the allow-list"),
    ("a host in upper case", "https://GitHub.com/a.exe", "must be https://<host>/<path>"),
    ("a user name", "https://github.com@example.com/a.exe", "must be https://<host>/<path>"),
    ("a port", "https://github.com:8443/a.exe", "must be https://<host>/<path>"),
    ("an address in brackets", "https://[::1]/a.exe", "must be https://<host>/<path>"),
    ("a query", "https://github.com/a.exe?x=1", "must be https://<host>/<path>"),
    ("a fragment", "https://github.com/a.exe#x", "must be https://<host>/<path>"),
    ("an escape", "https://github.com/a%2Fb.exe", "must be https://<host>/<path>"),
    ("a backslash", "https://github.com\\a.exe", "must be https://<host>/<path>"),
    ("an empty segment", "https://github.com//a.exe", "must be https://<host>/<path>"),
    ("a slash at the end", "https://github.com/a/", "must be https://<host>/<path>"),
    ("no path", "https://github.com", "must be https://<host>/<path>"),
    ("a space", "https://github.com/a b.exe", "must be https://<host>/<path>"),
    ("a line end", URL + "\n", "must be https://<host>/<path>"),
    ("a letter outside ASCII", "https://github.com/" + chr(0xE9) + ".exe", "must be https://<host>/<path>"),
    ("a step up", "https://github.com/a/../b.exe", 'must not have "." or ".." as a path segment'),
    ("a step in place", "https://github.com/./a.exe", 'must not have "." or ".." as a path segment'),
    ("1025 characters", "https://github.com/" + "a" * 1006, "must be at most 1024 characters"),
    ("a list", [URL], "must be a string"),
]


class SchemaTests(unittest.TestCase):
    def test_the_example_is_a_valid_manifest_with_every_key(self):
        data = sample()
        self.assertEqual(mf.problems(data, HOSTS), [])
        self.assertEqual(sorted(data), sorted(mf.TOP_KEYS))
        self.assertEqual(data["chromium_version"], ver.split(data["version"])[0])
        self.assertEqual(sorted(data["packages"]["win-x64-avx2"]["installed"]["deltas"]), [OLD])

    def test_what_else_is_valid(self):
        full = {"full": ENTRY}
        valid = {
            "another channel": put(("channel",), "beta-2"),
            "not critical": put(("critical",), False),
            "an updater version equal to the version": put(("min_updater_version",), NEW),
            "good for exactly 90 days": put(("expires",), mf.format_time(PUBLISHED + 90 * DAY)),
            "the last serial of the day": put(("serial",), SERIAL + 99),
            "a portable package alone": put(AVX2, {"portable": full}),
            "every variant": put(("packages",), {v: {"installed": full, "portable": full} for v in mf.VARIANTS}),
            "eight deltas": put(DELTAS, {f"158.0.8127.{n}": ENTRY for n in range(2000, 2008)}),
            "the largest size": put(FULL + ("size",), 2**31 - 1),
            "a path of every allowed character": put(FULL + ("url",), "https://github.com/A-z_0.9~+/x.tar.xz"),
            "an address of 1024 characters": put(FULL + ("url",), "https://github.com/" + "a" * 1005),
        }
        for name, change in valid.items():
            with self.subTest(name):
                self.assertEqual(mf.problems(changed(change), HOSTS), [])

    def test_each_invalid_manifest_is_refused_with_a_message_that_names_the_field(self):
        for name, change, message in INVALID:
            with self.subTest(name):
                data = changed(change)
                found = mf.problems(data, HOSTS)
                self.assertTrue(any(message in problem for problem in found), found)
                with self.assertRaises(mf.ManifestError) as refused:
                    mf.serialize(data, allowed_hosts=HOSTS)
                self.assertIn(message, str(refused.exception))

    def test_every_top_level_key_is_required(self):
        for key in mf.TOP_KEYS:
            with self.subTest(key):
                self.assertIn(f'missing key "{key}"', mf.problems(changed(drop((key,))), HOSTS))

    def test_only_https_addresses_on_allowed_hosts_and_of_the_plain_form(self):
        for name, url, message in BAD_URLS:
            with self.subTest(name):
                self.assertIn(message, mf.url_problem(url, frozenset(HOSTS)) or "accepted")
                found = mf.problems(changed(put(FULL + ("url",), url)), HOSTS)
                self.assertEqual(len(found), 1, found)
                self.assertTrue(found[0].startswith("packages/win-x64-avx2/installed/full/url: "), found)
        delta = changed(put(DELTAS + (OLD, "url"), "http://github.com/a.delta"))
        self.assertIn("deltas/158.0.8127.3000/url: must be https", mf.problems(delta, HOSTS)[0])

    def test_the_allowed_hosts_are_the_callers(self):
        self.assertEqual(mf.problems(sample(), ("example.org", "github.com")), [])
        found = mf.problems(sample(), ("example.org",))
        self.assertEqual(len(found), 4)     # every package of the example
        self.assertTrue(all("host github.com is not on the allow-list (example.org)" in p for p in found), found)
        for wrong in ("github.com", (), ("GitHub.com",), ("github",), ("https://github.com",), (b"github.com",),
                      ("github.com\n",), None, 5, [["github.com"]]):
            with self.subTest(wrong), self.assertRaises(ValueError):
                mf.problems(sample(), wrong)

    def test_names_from_a_manifest_are_shown_escaped_and_short(self):
        odd = "x\x1b[2J\nmanifest: OK"
        found = mf.problems(changed(put(("packages", odd), {}), put(("packages", "v" * 500), {}), put((odd,), 1),
                                    put(INSTALLED + (odd,), 1), put(DELTAS + (odd,), ENTRY)), HOSTS)
        self.assertEqual(len(found), 5, found)
        text = "\n".join(found)
        self.assertTrue(text.isascii())
        self.assertNotIn("\x1b", text)
        self.assertEqual(text.count("\n"), len(found) - 1)
        self.assertIn('unknown key "x\\u001b[2J\\nmanifest: OK"', found[0])
        self.assertIn('packages/"x\\u001b[2J\\nmanifest: OK": unknown variant', text)
        self.assertIn('installed: unknown key "x\\u001b[2J\\nmanifest: OK"', text)
        self.assertIn('deltas/"x\\u001b[2J\\nmanifest: OK": must be a build version', text)
        self.assertTrue(all(len(problem) < 220 for problem in found), found)

    def test_keys_that_json_cannot_give_are_problems_not_errors(self):
        for key in (b"x", 5, None, 1.5, frozenset(), (1, 2)):
            with self.subTest(key):
                self.assertEqual(len(mf.problems(changed(put((key,), 1)), HOSTS)), 1)
                self.assertEqual(len(mf.problems(changed(put(FULL + (key,), 1)), HOSTS)), 1)
                self.assertEqual(len(mf.problems(changed(put(("packages", key), {})), HOSTS)), 1)

    def test_every_problem_is_reported_not_only_the_first(self):
        found = mf.problems(changed(put(("schema",), 2), put(("critical",), "no"), put(FULL + ("size",), 0)), HOSTS)
        self.assertEqual(len(found), 3, found)

    def test_what_is_not_an_object_is_not_a_manifest(self):
        for data in ([], "manifest", 1, None, True):
            with self.subTest(data):
                self.assertEqual(mf.problems(data, HOSTS), ["a manifest is one JSON object"])

    def test_the_variants_are_names_the_release_script_takes(self):
        self.assertEqual(mf.VARIANTS, ("win-x64-avx2", "win-x64-sse4", "win-x64-avx512", "win-arm64-armv8",
                                       "linux-x64-avx2", "linux-x64-sse4", "linux-x64-avx512", "linux-arm64-armv8"))
        for variant in mf.VARIANTS:
            self.assertTrue(release._VARIANT.match(variant), variant)

    def test_times_are_utc_to_the_second_in_one_written_form(self):
        self.assertEqual(mf.parse_time("1970-01-01T00:00:00Z"), 0)
        self.assertEqual(mf.parse_time("2028-02-29T23:59:59Z") + 1, mf.parse_time("2028-03-01T00:00:00Z"))
        self.assertEqual(mf.format_time(PUBLISHED), "2026-12-01T12:00:00Z")
        self.assertEqual(EXPIRES - PUBLISHED, 30 * DAY)
        for wrong in ("2027-02-29T00:00:00Z", "2026-12-01T23:59:60Z", "2026-12-01T12:00:00z",
                      "2026-12-01T12:00:00.000Z", "2026-12-01T12:00Z", " 2026-12-01T12:00:00Z", None, 0):
            with self.subTest(wrong), self.assertRaises(ValueError):
                mf.parse_time(wrong)


class BytesTests(unittest.TestCase):
    def refused(self, manifest: bytes, message: str) -> str:
        with self.assertRaises(mf.ManifestError) as refused:
            mf.parse(manifest, allowed_hosts=HOSTS)
        self.assertIn(message, str(refused.exception))
        return str(refused.exception)

    def test_only_real_bytes_are_read(self):
        class Shifty(bytes):
            def __bytes__(self):
                return mf.example()

        raw = mf.example()
        for other in (bytearray(raw), memoryview(raw), raw.decode("ascii"), Shifty(b"{}\n"), [raw], None):
            with self.subTest(type(other).__name__), self.assertRaises(TypeError):
                mf.parse(other, allowed_hosts=HOSTS)

    def test_the_example_reads_back_byte_for_byte(self):
        raw = mf.example()
        data = mf.parse(raw, allowed_hosts=HOSTS)
        self.assertEqual(data, sample())
        self.assertEqual(mf.serialize(data, allowed_hosts=HOSTS), raw)
        self.assertTrue(raw.startswith(b'{\n  "channel": "stable",\n') and raw.endswith(b'"\n}\n'))

    def test_one_content_has_one_written_form(self):
        raw, data = mf.example(), sample()
        other_forms = {
            "one line": json.dumps(data, sort_keys=True).encode("ascii") + b"\n",
            "no spaces": json.dumps(data, sort_keys=True, separators=(",", ":")).encode("ascii") + b"\n",
            "four spaces a level": json.dumps(data, sort_keys=True, indent=4).encode("ascii") + b"\n",
            "keys in another order": json.dumps(dict(reversed(data.items())), indent=2).encode("ascii") + b"\n",
            "no line end at the end": raw[:-1],
            "two line ends at the end": raw + b"\n",
            "a space at the start": b" " + raw,
            "a space at the end of a line": raw.replace(b"{\n", b"{ \n", 1),
            "an escape for a plain letter": raw.replace(b'"stable"', b'"stabl\\u0065"'),
            "an escaped slash": raw.replace(b"https://", b"https:\\/\\/", 1),
        }
        for name, manifest in other_forms.items():
            with self.subTest(name):
                self.assertNotEqual(manifest, raw)
                self.refused(manifest, "not in canonical form")

    def test_the_written_form_is_what_the_spec_words_and_needs_no_json_library(self):
        def written(value, level=0) -> str:     # section 3 of the spec, line for line
            if value is True or value is False:
                return "true" if value else "false"
            if isinstance(value, int):
                return str(value)
            if isinstance(value, str):
                return '"' + value + '"'
            members = ["  " * (level + 1) + '"' + key + '": ' + written(value[key], level + 1)
                       for key in sorted(value, key=lambda k: k.encode("ascii"))]
            return "{\n" + ",\n".join(members) + "\n" + "  " * level + "}"

        package = {"full": ENTRY, "deltas": {f"158.0.8127.{n}": ENTRY for n in range(8)}}
        every = changed(put(("packages",), {v: {"installed": package, "portable": {"full": ENTRY}}
                                            for v in mf.VARIANTS}), put(("critical",), False))
        for data in (sample(), every):
            raw = mf.serialize(data, allowed_hosts=HOSTS)
            self.assertEqual((written(data) + "\n").encode("ascii"), raw)
            self.assertLess(len(raw), mf.MAX_MANIFEST_BYTES)

    def test_only_printable_ascii_and_lf(self):
        raw = mf.example()
        self.refused(raw.replace(b"\n", b"\r\n"), "offset 1: a CR (line ends are LF alone)")
        self.refused(raw.replace(b"  ", b"\t"), "offset 2: a tab")
        self.refused(b"\xef\xbb\xbf" + raw, "offset 0: a byte that is no text")
        self.refused(raw + b"\x00", f"offset {len(raw)}: a byte that is no text")
        self.refused(raw.replace(b"stable", b"stabl\xc3\xa9"), "offset 21: a byte that is no text")
        self.refused(raw.replace(b"stable", b"stabl\x7f"), "offset 21: a byte that is no text")
        secret = bytes(range(0x80, 0xA0))       # a binary file given by mistake: none of it is repeated
        message = self.refused(secret, "offset 0: a byte that is no text")
        self.assertNotIn("80", message)

    def test_json_that_two_readers_could_read_differently(self):
        raw = mf.example()
        self.refused(raw.replace(b'  "schema": 1,\n', b'  "schema": 1,\n  "schema": 1,\n'), 'duplicate key "schema"')
        self.refused(raw.replace(b'"size": 9437184,', b'"size": 9437184,\n            "size": 1,'),
                     'duplicate key "size"')
        for number in (b"9437184.0", b"9437e3", b"1E2", b"NaN", b"Infinity", b"-Infinity", b"0.5"):
            with self.subTest(number):
                self.refused(raw.replace(b'"size": 9437184', b'"size": ' + number),
                             "a number that is not a whole number written in digits")
        self.refused(raw.replace(b'"schema": 1', b'"schema": 01'), "not JSON")
        self.refused(raw.replace(b'"schema": 1', b'"schema": -0'), "schema: must be 1")
        self.refused(raw.replace(b'"critical": true', b'"critical": null'), "critical: must be true or false")

    def test_what_is_not_a_manifest_at_all(self):
        raw = mf.example()
        self.refused(b"", "a manifest is 1 to 262144 bytes, not 0")
        self.refused(b" " * (mf.MAX_MANIFEST_BYTES + 1), "a manifest is 1 to 262144 bytes, not 262145")
        self.refused(b" " * mf.MAX_MANIFEST_BYTES, "not JSON")
        self.refused(b"update\n", "not JSON")
        self.refused(raw[:200], "not JSON")
        self.refused(raw + raw, "not JSON")
        self.refused(b"[" * 100000, "not JSON")
        for other in (b"[]\n", b'"manifest"\n', b"1\n", b"null\n"):
            self.refused(other, "a manifest is one JSON object")
        self.refused(b"{}\n", 'missing key "channel"')

    def test_another_file_given_by_mistake_is_not_repeated_in_the_message(self):
        for other in (b"3e7 is how this file starts\n", b"12E+5 and so on\n", b"-0.25\n", b"8675309 then text\n",
                      b"words only\n"):
            with self.subTest(other[:4]):
                message = self.refused(other, "")
                self.assertNotIn(other[:3].decode("ascii"), message)

    def test_a_manifest_is_refused_for_an_address_outside_the_callers_hosts(self):
        with self.assertRaises(mf.ManifestError) as refused:
            mf.parse(mf.example(), allowed_hosts=("example.org",))
        self.assertIn("host github.com is not on the allow-list", str(refused.exception))
        self.assertEqual(len(refused.exception.problems), 4)


class SignatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private, cls.public = ar.keygen()
        cls.raw = mf.example()
        cls.signature = signed(cls.raw, cls.private, cls.public)

    def refused(self, manifest: bytes, signature: bytes, public_key: bytes = None):
        with self.assertRaises(mf.SignatureError):
            mf.verify(manifest, signature, public_key or self.public, allowed_hosts=HOSTS)

    def test_a_signed_manifest_verifies_and_gives_its_content(self):
        self.assertEqual(mf.verify(self.raw, self.signature, self.public, allowed_hosts=HOSTS), sample())
        self.assertTrue(mf.signature_holds(self.raw, self.signature, self.public))

    def test_the_signature_is_64_bytes_apart_from_the_manifest_over_prefix_and_bytes(self):
        self.assertEqual(len(self.signature), 64)
        self.assertEqual(mf.SIGNATURE_PREFIX, b"thoron-update-manifest-v1\n")
        self.assertEqual(mf.signed_message(self.raw), b"thoron-update-manifest-v1\n" + self.raw)
        self.assertEqual(self.signature, raw_signature(self.private, mf.signed_message(self.raw)))
        self.assertEqual(self.signature, signed(self.raw, self.private, self.public))
        self.assertEqual(mf.public_key_of(self.private), self.public)

    def test_any_changed_bit_of_the_manifest_fails_and_nothing_is_parsed(self):
        raw = small()
        signature = signed(raw, self.private, self.public)
        self.assertLess(len(raw), 700)
        tried = 0
        with mock.patch.object(mf, "parse", side_effect=AssertionError("read before the signature held")), \
                mock.patch.object(json, "loads", side_effect=AssertionError("read before the signature held")):
            for offset in range(len(raw)):
                for bit in range(8):
                    flipped = raw[:offset] + bytes([raw[offset] ^ (1 << bit)]) + raw[offset + 1:]
                    self.assertFalse(mf.signature_holds(flipped, signature, self.public), (offset, bit))
                    tried += 1
                self.refused(raw[:offset] + bytes([raw[offset] ^ 0xFF]) + raw[offset + 1:], signature)
        self.assertEqual(tried, len(raw) * 8)
        self.assertEqual(mf.verify(raw, signature, self.public, allowed_hosts=HOSTS)["serial"], SERIAL)

    def test_any_changed_bit_of_the_signature_fails(self):
        for offset in range(len(self.signature)):
            for change in [1 << bit for bit in range(8)] + [0xFF]:
                flipped = self.signature[:offset] + bytes([self.signature[offset] ^ change]) + \
                    self.signature[offset + 1:]
                self.assertFalse(mf.signature_holds(self.raw, flipped, self.public), (offset, change))
            self.refused(self.raw, self.signature[:offset] + bytes([self.signature[offset] ^ 0x01]) +
                         self.signature[offset + 1:])

    def test_a_byte_more_or_less_fails(self):
        self.refused(self.raw[:-1], self.signature)
        self.refused(self.raw + b"\n", self.signature)
        self.refused(b"\n" + self.raw, self.signature)
        self.refused(self.raw, self.signature[:-1])
        self.refused(self.raw, self.signature + b"\x00")
        self.refused(self.raw, b"")
        self.refused(self.raw, base64.b64encode(self.signature))
        self.refused(self.raw, bytes(64))

    def test_a_signature_with_s_out_of_range_fails(self):
        order = 2**252 + 27742317777372353535851937790883648493
        s = int.from_bytes(self.signature[32:], "little")
        self.assertLess(s, order)
        tried = 0
        for times in range(1, 16):       # the same S plus the group order: equal on the curve, not as bytes
            if s + times * order < 2**256:
                self.refused(self.raw, self.signature[:32] + (s + times * order).to_bytes(32, "little"))
                tried += 1
        self.assertGreaterEqual(tried, 7)

    def test_another_key_fails(self):
        self.refused(self.raw, self.signature, ar.keygen()[1])
        self.refused(self.raw, self.signature, self.public[:-1])
        self.refused(self.raw, self.signature, self.public + b"\x00")
        self.refused(self.raw, self.signature, bytes(32))

    def test_the_weak_keys_are_the_points_of_small_order(self):
        # edwards25519 from its equation, so the list is checked against the curve and not against a copy
        p = 2**255 - 19
        d = -121665 * pow(121666, -1, p) % p
        order = 2**252 + 27742317777372353535851937790883648493

        def add(a, b):
            k = d * a[0] * b[0] * a[1] * b[1] % p
            return ((a[0] * b[1] + b[0] * a[1]) * pow(1 + k, -1, p) % p,
                    (a[1] * b[1] + a[0] * b[0]) * pow(1 - k, -1, p) % p)

        def times(n, point):
            total = (0, 1)
            while n:
                if n & 1:
                    total = add(total, point)
                point, n = add(point, point), n >> 1
            return total

        def on_curve(y):
            square = (y * y - 1) * pow(d * y * y + 1, -1, p) % p
            x = pow(square, (p + 3) // 8, p)
            if (x * x - square) % p:
                x = x * pow(2, (p - 1) // 4, p) % p
            return None if (x * x - square) % p else (x, y)

        small_order, y = set(), 2
        while len(small_order) < 8:
            point, y = on_curve(y), y + 1
            if point:
                torsion = times(order, point)
                small_order |= {times(n, torsion) for n in range(8)}
        self.assertEqual(len(small_order), 8)
        self.assertTrue(all(times(8, point) == (0, 1) for point in small_order))
        written = {point[1].to_bytes(32, "little") for point in small_order}     # y; the sign of x is the top bit
        written |= {(y + p).to_bytes(32, "little") for y in (0, 1)}              # the same y written above p
        self.assertEqual(written, mf.WEAK_KEYS)
        self.assertEqual(len(mf.WEAK_KEYS), 7)

    def test_what_is_no_key_verifies_nothing(self):
        made_up = bytes([1]) + bytes(63)      # R the neutral point and S zero: this fits a key of small order
        for masked in sorted(mf.WEAK_KEYS):
            for key in (masked, masked[:31] + bytes([masked[31] | 0x80])):
                with self.subTest(key.hex()):
                    self.assertFalse(mf.usable_key(key))
                    self.assertFalse(mf.signature_holds(self.raw, self.signature, key))
                    for n in range(64):
                        message = b"%d\n" % n
                        self.assertFalse(mf.signature_holds(message, made_up, key))
                        self.assertFalse(mf.signature_holds(message, key + bytes(32), key))
                        self.assertFalse(mf.signature_holds(message, bytes(64), key))
                    self.refused(self.raw, made_up, key)
        self.assertTrue(mf.usable_key(self.public))
        for wrong in (self.public[:-1], self.public + b"\x00", b""):
            self.assertFalse(mf.usable_key(wrong))
        with self.assertRaises(TypeError):
            mf.usable_key(bytearray(self.public))

    def test_only_real_bytes_are_verified(self):
        class Shifty(bytes):                  # says it is the signed manifest, holds another
            def __bytes__(self):
                return mf.example()

        cases = ((Shifty(small()), self.signature, self.public),
                 (bytearray(self.raw), self.signature, self.public),
                 (memoryview(self.raw), self.signature, self.public),
                 (self.raw.decode("ascii"), self.signature, self.public),
                 (self.raw, list(self.signature), self.public),
                 (self.raw, bytearray(self.signature), self.public),
                 (self.raw, self.signature, bytearray(self.public)),
                 (self.raw, self.signature, None))
        for manifest, signature, key in cases:
            names = "/".join(type(value).__name__ for value in (manifest, signature, key))
            with self.subTest(names), self.assertRaises(TypeError):
                mf.verify(manifest, signature, key, allowed_hosts=HOSTS)
            with self.subTest(names + " holds"), self.assertRaises(TypeError):
                mf.signature_holds(manifest, signature, key)

    def test_a_signature_made_for_another_purpose_fails(self):
        for name, message in {
            "the bare bytes, no purpose": self.raw,
            "another schema": b"thoron-update-manifest-v2\n" + self.raw,
            "the prefix without its line end": b"thoron-update-manifest-v1" + self.raw,
            "the checksum of the manifest": hashlib.sha256(self.raw).digest(),
        }.items():
            with self.subTest(name):
                self.refused(self.raw, raw_signature(self.private, message))

    def test_a_signature_of_the_ad_blockers_resources_is_none_of_a_manifest_and_the_reverse(self):
        resources = json.dumps([{"name": "noop.js", "kind": {"mime": "application/javascript"},
                                 "content": base64.b64encode(b"(function() {})();").decode("ascii")}])
        made = ar.sign(resources, "2026120100", self.private)       # the same key, the other tool
        self.assertEqual(ar.verify(made, self.public), "2026120100")
        theirs = base64.b64decode(made.split("\n")[2].removeprefix("signature: "))
        self.assertEqual(len(theirs), 64)
        self.refused(self.raw, theirs)
        self.refused(ar.message("2026120100", resources), theirs)   # even the very bytes it was made for
        self.assertFalse(ar.message("2026120100", resources).startswith(mf.SIGNATURE_PREFIX))
        self.assertFalse(mf.signed_message(self.raw).startswith(ar.HEADER.encode("ascii")))
        ours = base64.b64encode(self.signature).decode("ascii")
        self.assertIsNone(ar.verify(f"{ar.HEADER}\nserial: 2026120100\nsignature: {ours}\n\n{resources}", self.public))

    def test_signed_bytes_that_are_no_manifest_are_refused_after_the_signature(self):
        compact = json.dumps(sample(), sort_keys=True).encode("ascii") + b"\n"
        extra = mf.canonical(changed(put(("notes",), "x")))
        for name, manifest, message in (("another written form", compact, "not in canonical form"),
                                        ("an unknown key", extra, 'unknown key "notes"'),
                                        ("an empty object", b"{}\n", "missing key"),
                                        ("no JSON", b"update\n", "not JSON")):
            with self.subTest(name):
                signature = raw_signature(self.private, mf.signed_message(manifest))
                with self.assertRaises(mf.ManifestError) as refused:
                    mf.verify(manifest, signature, self.public, allowed_hosts=HOSTS)
                self.assertIn(message, str(refused.exception))
                self.refused(manifest, self.signature)      # and with a wrong signature it is never read

    def test_only_a_valid_manifest_in_its_written_form_is_signed(self):
        for manifest in (json.dumps(sample()).encode("ascii"), mf.canonical(changed(put(("schema",), 2))),
                         self.raw + b"\n", b"{}\n", b""):
            with self.subTest(manifest[:20]), self.assertRaises(mf.ManifestError):
                signed(manifest, self.private, self.public)
        with self.assertRaises(mf.ManifestError):
            mf.sign(self.raw, self.private, self.public, allowed_hosts=("example.org",), now=NOW)
        with self.assertRaises(TypeError):
            signed(bytearray(self.raw), self.private, self.public)

    def test_nothing_is_signed_that_a_copy_would_refuse_for_its_dates(self):
        slack = mf.SIGNING_SLACK_SECONDS
        self.assertEqual(slack, 600)
        self.assertEqual(signed(self.raw, self.private, self.public, now=PUBLISHED - slack), self.signature)
        self.assertEqual(signed(self.raw, self.private, self.public, now=EXPIRES - 1), self.signature)
        for name, now, message in (
                ("dated ahead of the clock", PUBLISHED - slack - 1,
                 "published: 2026-12-01T12:00:00Z is ahead of the clock (2026-12-01T11:49:59Z)"),
                ("dated a year ahead", PUBLISHED - 365 * DAY, "is ahead of the clock (2025-12-01T12:00:00Z)"),
                ("expired this second", EXPIRES, "expires: 2026-12-31T12:00:00Z has passed"),
                ("expired long ago", EXPIRES + 365 * DAY, "has passed (the clock says 2027-12-31T12:00:00Z)")):
            with self.subTest(name), self.assertRaises(mf.ManifestError) as refused:
                signed(self.raw, self.private, self.public, now=now)
            self.assertIn(message, str(refused.exception))
        for now in (float(NOW), None, "2026-12-01T12:00:00Z", float("nan"), True):
            with self.subTest(now), self.assertRaises(TypeError):
                signed(self.raw, self.private, self.public, now=now)

    def test_nothing_is_signed_with_a_key_other_than_the_one_copies_hold(self):
        other_private, other_public = ar.keygen()
        for name, private, public in (("another private key", other_private, self.public),
                                      ("another public key", self.private, other_public),
                                      ("a short private key", self.private[:-1], self.public),
                                      ("a long private key", self.private + b"\x00", self.public),
                                      ("no private key", b"", self.public),
                                      ("a short public key", self.private, self.public[:-1]),
                                      ("a public key of zeros", self.private, bytes(32)),
                                      ("a public key of small order", self.private, bytes([1]) + bytes(31))):
            with self.subTest(name), self.assertRaises(ValueError) as refused:
                signed(self.raw, private, public)
            self.assertNotIn(base64.b64encode(self.private).decode("ascii"), str(refused.exception))
            self.assertNotIn(self.private.hex(), str(refused.exception))

    def test_a_signature_that_does_not_verify_is_not_handed_out(self):
        for name, wrong in (("zeros", bytes(64)), ("a short one", self.signature[:-1]),
                            ("a signature of the bare bytes", raw_signature(self.private, self.raw))):
            with self.subTest(name), mock.patch.object(mf, "_raw_signature", return_value=wrong), \
                    self.assertRaises(mf.SignatureError):
                signed(self.raw, self.private, self.public)

    def test_a_valid_signature_does_not_open_other_hosts(self):
        with self.assertRaises(mf.ManifestError):
            mf.verify(self.raw, self.signature, self.public, allowed_hosts=("example.org",))
        with self.assertRaises(ValueError):
            mf.verify(self.raw, self.signature, self.public, allowed_hosts="github.com")

    def test_too_many_bytes_are_refused_unread(self):
        huge = b" " * (mf.MAX_MANIFEST_BYTES + 1)
        with mock.patch.object(mf, "signature_holds", side_effect=AssertionError("checked")), \
                self.assertRaises(mf.ManifestError):
            mf.verify(huge, self.signature, self.public, allowed_hosts=HOSTS)


# The outcomes in the order of their checks: steps 7 to 14 of the spec.
ORDER = (mf.WRONG_CHANNEL, mf.REPLAYED, mf.NOT_YET_VALID, mf.EXPIRED, mf.DOWNGRADE, mf.UPDATER_TOO_OLD,
         mf.NO_PACKAGE, mf.UPDATE)


class DecisionTests(unittest.TestCase):
    def decide(self, data: dict = None, **state) -> mf.Decision:
        args = dict(channel="stable", installed=OLD, updater=OLD, variant="win-x64-avx2", kind="installed", now=NOW)
        args.update(state)
        decision = mf.decide(data or sample(), **args)
        self.assertIn(decision.outcome, mf.OUTCOMES)
        self.assertTrue(decision.detail)
        if decision.outcome != mf.UPDATE:
            if decision.outcome != mf.UPDATER_TOO_OLD:      # P4.6: that one may carry the full package
                self.assertIsNone(decision.full)
            self.assertIsNone(decision.delta)
        return decision

    def test_a_newer_version_is_an_update_with_its_packages(self):
        decision, packages = self.decide(), sample()["packages"]["win-x64-avx2"]
        self.assertEqual(decision.outcome, mf.UPDATE)
        self.assertEqual(decision.full, packages["installed"]["full"])
        self.assertEqual(decision.delta, packages["installed"]["deltas"][OLD])
        self.assertTrue(decision.manifest["critical"])
        self.assertEqual(decision.remember_serial, SERIAL)
        self.assertFalse(decision.cannot_verify)
        portable = self.decide(kind="portable")
        self.assertEqual((portable.full, portable.delta), (packages["portable"]["full"], None))

    def test_a_delta_is_offered_only_from_exactly_the_installed_version(self):
        for installed in ("158.0.8127.2900", "158.0.8127.3001", "0.0.0.0"):
            with self.subTest(installed):
                decision = self.decide(installed=installed, updater=NEW)
                self.assertEqual((decision.outcome, decision.delta), (mf.UPDATE, None))
                self.assertTrue(decision.full)

    def test_the_installed_version_is_up_to_date(self):
        decision = self.decide(installed=NEW)
        self.assertEqual(decision.outcome, mf.UP_TO_DATE)
        self.assertEqual(decision.remember_serial, SERIAL)
        self.assertFalse(decision.cannot_verify)

    def test_a_manifest_below_the_installed_version_is_a_downgrade_and_installs_nothing(self):
        for installed in ("158.0.8127.4501", "158.0.8128.0", "159.0.0.0"):
            with self.subTest(installed):
                decision = self.decide(installed=installed)
                self.assertEqual(decision.outcome, mf.DOWNGRADE)
                self.assertTrue(decision.cannot_verify)
                self.assertIn("nothing older is ever installed", decision.detail)
                self.assertEqual(decision.remember_serial, SERIAL)      # still the channel's current word

    def test_a_serial_below_one_already_accepted_is_a_replay(self):
        decision = self.decide(last_serial=SERIAL + 1)
        self.assertEqual(decision.outcome, mf.REPLAYED)
        self.assertTrue(decision.cannot_verify)
        self.assertIsNone(decision.manifest)
        self.assertIsNone(decision.remember_serial)
        self.assertEqual(self.decide(last_serial=SERIAL).outcome, mf.UPDATE)      # the same manifest again
        self.assertEqual(self.decide(last_serial=SERIAL - 1).outcome, mf.UPDATE)
        self.assertEqual(self.decide(last_serial=SERIAL + 1, installed=NEW).outcome, mf.REPLAYED)

    def test_an_expired_manifest_is_cannot_verify_never_up_to_date(self):
        skew = mf.CLOCK_SKEW_SECONDS
        self.assertEqual(skew, DAY)
        self.assertEqual(self.decide(now=EXPIRES + skew).outcome, mf.UPDATE)
        for installed in (OLD, NEW):
            with self.subTest(installed):
                decision = self.decide(now=EXPIRES + skew + 1, installed=installed)
                self.assertEqual(decision.outcome, mf.EXPIRED)
                self.assertTrue(decision.cannot_verify)
                self.assertIsNone(decision.manifest)
                self.assertIsNone(decision.remember_serial)
        self.assertEqual(self.decide(now=EXPIRES + 1, skew=0).outcome, mf.EXPIRED)
        self.assertEqual(self.decide(now=EXPIRES, skew=0).outcome, mf.UPDATE)
        self.assertEqual(self.decide(now=EXPIRES + 365 * DAY, installed=NEW).outcome, mf.EXPIRED)

    def test_a_manifest_dated_after_the_clock_is_not_yet_valid(self):
        skew = mf.CLOCK_SKEW_SECONDS
        self.assertEqual(self.decide(now=PUBLISHED - skew).outcome, mf.UPDATE)
        decision = self.decide(now=PUBLISHED - skew - 1)
        self.assertEqual(decision.outcome, mf.NOT_YET_VALID)
        self.assertTrue(decision.cannot_verify)
        self.assertIsNone(decision.manifest)
        self.assertIsNone(decision.remember_serial)     # a serial from the future is not kept
        self.assertEqual(self.decide(now=PUBLISHED - 1, skew=0).outcome, mf.NOT_YET_VALID)
        self.assertEqual(self.decide(now=PUBLISHED, skew=0).outcome, mf.UPDATE)
        self.assertEqual(self.decide(now=0, installed=NEW).outcome, mf.NOT_YET_VALID)

    def test_a_clock_outside_the_calendar_is_still_an_outcome(self):
        for now, outcome in ((10**15, mf.EXPIRED), (253402300800, mf.EXPIRED), (2**40, mf.EXPIRED),
                             (-10**15, mf.NOT_YET_VALID), (-1, mf.NOT_YET_VALID)):
            with self.subTest(now):
                decision = self.decide(now=now)
                self.assertEqual(decision.outcome, outcome)
                self.assertIsNone(decision.remember_serial)

    def test_a_manifest_of_another_channel_is_refused(self):
        decision = self.decide(channel="beta")
        self.assertEqual(decision.outcome, mf.WRONG_CHANNEL)
        self.assertTrue(decision.cannot_verify)
        self.assertIsNone(decision.manifest)
        self.assertIsNone(decision.remember_serial)
        self.assertEqual(self.decide(changed(put(("channel",), "beta")), channel="beta").outcome, mf.UPDATE)

    def test_an_updater_below_the_minimum_does_not_apply_the_release(self):
        decision = self.decide(updater="158.0.8127.2999")
        self.assertEqual(decision.outcome, mf.UPDATER_TOO_OLD)
        self.assertFalse(decision.cannot_verify)
        self.assertEqual(decision.remember_serial, SERIAL)
        self.assertIn("needs an updater of 158.0.8127.3000 or later", decision.detail)
        # P4.6: the full package comes with it, for the updater inside it to apply; never a delta
        self.assertEqual(decision.full, self.decide().full)
        self.assertIsNotNone(decision.full)
        self.assertIsNone(decision.delta)
        self.assertIsNone(self.decide(updater="158.0.8127.2999", variant="linux-x64-avx2").full)
        self.assertEqual(self.decide(updater="158.0.8127.2999", variant="linux-x64-avx2").outcome,
                         mf.UPDATER_TOO_OLD)
        self.assertEqual(self.decide(updater=OLD).outcome, mf.UPDATE)
        self.assertEqual(self.decide(installed=NEW, updater="1.0.0.0").outcome, mf.UP_TO_DATE)   # nothing to apply

    def test_a_release_without_a_package_for_this_copy(self):
        for variant, kind in (("linux-x64-avx2", "installed"), ("win-arm64-armv8", "portable"),
                              ("win-x64-sse4", "portable")):
            with self.subTest(variant=variant, kind=kind):
                decision = self.decide(variant=variant, kind=kind)
                self.assertEqual(decision.outcome, mf.NO_PACKAGE)
                self.assertFalse(decision.cannot_verify)
                self.assertEqual(decision.remember_serial, SERIAL)
        self.assertEqual(self.decide(variant="win-x64-sse4").outcome, mf.UPDATE)

    def test_the_checks_come_in_one_order(self):
        # A copy for which every check fails; then one thing is put right at a time.
        state = dict(channel="beta", last_serial=SERIAL + 1, now=PUBLISHED - 2 * DAY, installed="159.0.0.0",
                     updater="1.0.0.0", variant="linux-x64-avx2")
        put_right = ({}, {"channel": "stable"}, {"last_serial": SERIAL}, {"now": EXPIRES + 2 * DAY}, {"now": NOW},
                     {"installed": OLD}, {"updater": OLD}, {"variant": "win-x64-avx2"})
        for outcome, change in zip(ORDER, put_right, strict=True):
            state.update(change)
            with self.subTest(outcome):
                self.assertEqual(self.decide(**state).outcome, outcome)
        current = self.decide(installed=NEW, updater="1.0.0.0", variant="linux-x64-avx2")
        self.assertEqual(current.outcome, mf.UP_TO_DATE)      # decided with the version, before updater and package

    def test_what_the_caller_gets_wrong_is_an_error_not_an_outcome(self):
        for state in ({"variant": "win-x64"}, {"kind": "msi"}, {"variant": ["win-x64-avx2"]}, {"channel": "Stable"},
                      {"channel": None}, {"skew": -1}, {"last_serial": -1}):
            with self.subTest(state), self.assertRaises(ValueError):
                self.decide(**state)
        for state in ({"installed": "158.0"}, {"updater": "0.1.2"}, {"installed": "158.0.8127.03000"},
                      {"installed": None}, {"updater": other_digits(OLD)}, {"installed": OLD + "\n"}):
            with self.subTest(state), self.assertRaises(ver.VersionError):
                self.decide(**state)
        for state in ({"now": float(NOW)}, {"now": float("nan")}, {"now": None}, {"skew": 1.5},
                      {"last_serial": "0"}, {"now": True}):
            with self.subTest(state), self.assertRaises(TypeError):
                self.decide(**state)

    def test_no_outcome_that_cannot_verify_is_called_up_to_date(self):
        self.assertEqual(mf.CANNOT_VERIFY, {mf.BAD_SIGNATURE, mf.MALFORMED, mf.WRONG_CHANNEL, mf.REPLAYED,
                                            mf.NOT_YET_VALID, mf.EXPIRED, mf.DOWNGRADE})
        self.assertTrue(mf.CANNOT_VERIFY < set(mf.OUTCOMES))
        self.assertEqual(len(set(mf.OUTCOMES)), 11)


class CheckUpdateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private, cls.public = ar.keygen()
        cls.raw = mf.example()
        cls.signature = signed(cls.raw, cls.private, cls.public)

    def check(self, manifest: bytes, signature: bytes, public_key: bytes = None, **state) -> mf.Decision:
        args = dict(allowed_hosts=HOSTS, channel="stable", installed=OLD, updater=OLD, variant="win-x64-avx2",
                    kind="installed", now=NOW)
        args.update(state)
        return mf.check_update(manifest, signature, public_key or self.public, **args)

    def test_from_the_two_files_to_an_update(self):
        decision = self.check(self.raw, self.signature)
        self.assertEqual(decision.outcome, mf.UPDATE)
        self.assertEqual(decision.full["size"], 104857600)
        self.assertEqual(self.check(self.raw, self.signature, installed=NEW).outcome, mf.UP_TO_DATE)
        self.assertEqual(self.check(self.raw, self.signature, now=EXPIRES + 2 * DAY).outcome, mf.EXPIRED)
        self.assertEqual(self.check(self.raw, self.signature, last_serial=SERIAL + 1).outcome, mf.REPLAYED)
        self.assertEqual(self.check(self.raw, self.signature, skew=0, now=EXPIRES + 1).outcome, mf.EXPIRED)

    def test_bad_input_is_an_outcome_and_hands_out_nothing(self):
        changed_byte = self.raw.replace(b"4500", b"4600", 1)
        junk = b"update\n"
        cases = (
            ("a changed manifest", changed_byte, self.signature, mf.BAD_SIGNATURE),
            ("a changed signature", self.raw, self.signature[::-1], mf.BAD_SIGNATURE),
            ("no signature", self.raw, b"", mf.BAD_SIGNATURE),
            ("a signature of another manifest", small(), self.signature, mf.BAD_SIGNATURE),
            ("signed bytes that are no manifest", junk, raw_signature(self.private, mf.signed_message(junk)),
             mf.MALFORMED),
            ("no manifest", b"", self.signature, mf.MALFORMED),
            ("too many bytes", b" " * (mf.MAX_MANIFEST_BYTES + 1), self.signature, mf.MALFORMED),
        )
        for name, manifest, signature, outcome in cases:
            with self.subTest(name):
                decision = self.check(manifest, signature)
                self.assertEqual(decision.outcome, outcome)
                self.assertTrue(decision.cannot_verify)
                self.assertEqual((decision.manifest, decision.remember_serial, decision.full, decision.delta),
                                 (None, None, None, None))

    def test_a_copy_built_without_its_key_takes_nothing(self):
        # Zeros are what a build holds before the real key is put in. With such a key, and with any other
        # point of small order, a signature that anybody can write down would fit some manifests.
        for n in range(100):
            manifest = mf.serialize(changed(put(("serial",), SERIAL + n)), allowed_hosts=HOSTS)
            for key in (bytes(32), bytes([1]) + bytes(31)):
                for signature in (bytes(64), bytes([1]) + bytes(63), key + bytes(32)):
                    decision = self.check(manifest, signature, public_key=key)
                    self.assertEqual(decision.outcome, mf.BAD_SIGNATURE, (n, key.hex(), signature.hex()))

    def test_a_host_the_updater_does_not_allow_is_malformed_even_when_signed(self):
        self.assertEqual(self.check(self.raw, self.signature, allowed_hosts=("example.org",)).outcome, mf.MALFORMED)

    def test_what_the_caller_gets_wrong_is_an_error_whatever_the_files_hold(self):
        for state, error in (({"variant": "win-x64"}, ValueError), ({"kind": "msi"}, ValueError),
                             ({"channel": ""}, ValueError), ({"installed": "158"}, ver.VersionError),
                             ({"updater": None}, ver.VersionError), ({"now": 1.5}, TypeError),
                             ({"last_serial": -1}, ValueError), ({"allowed_hosts": "github.com"}, ValueError)):
            for files in ((self.raw, self.signature), (b"update\n", b"")):
                with self.subTest(state=state, good=files[0] == self.raw), self.assertRaises(error):
                    self.check(*files, **state)
        with self.assertRaises(TypeError):
            self.check(bytearray(self.raw), self.signature)

    def test_whatever_the_two_files_hold_is_an_outcome(self):
        rng = random.Random(20261116)
        accepted = 0
        for _ in range(1500):
            blob = bytearray(self.raw)
            for _ in range(rng.randint(1, 4)):
                at, action = rng.randrange(len(blob)), rng.random()
                if action < 0.4:
                    blob[at] = rng.randrange(256)
                elif action < 0.7:
                    del blob[at]
                else:
                    blob.insert(at, rng.choice(b' \n\t"{}[],:0123456789abcdefxyz\\u.-'))
            blob = bytes(blob)
            decision = self.check(blob, raw_signature(self.private, mf.signed_message(blob)))   # signed as it is
            self.assertIn(decision.outcome, mf.OUTCOMES)
            if decision.outcome != mf.MALFORMED:        # read as a manifest: then it is in the one written form
                accepted += 1
                self.assertEqual(mf.canonical(mf.parse(blob, allowed_hosts=HOSTS)), blob)
            if blob != self.raw:                        # and under the signature of the example it is nothing
                self.assertEqual(self.check(blob, self.signature).outcome, mf.BAD_SIGNATURE)
        self.assertGreater(accepted, 10)


class BuildTests(unittest.TestCase):
    def build(self, **changes) -> bytes:
        args = dict(channel="stable", version=NEW, thoron_version="0.1.2", critical=False, min_updater_version=OLD,
                    packages={"win-x64-avx2": {"installed": {"full": ENTRY}}}, published=PUBLISHED,
                    allowed_hosts=HOSTS)
        args.update(changes)
        return mf.build(**args)

    def test_a_built_manifest_is_valid_and_fills_in_what_follows_from_the_rest(self):
        raw = self.build()
        data = mf.parse(raw, allowed_hosts=HOSTS)
        self.assertEqual(data["schema"], 1)
        self.assertEqual(data["chromium_version"], "158.0.8127.45")
        self.assertEqual(data["serial"], SERIAL)
        self.assertEqual((data["published"], data["expires"]), ("2026-12-01T12:00:00Z", "2026-12-31T12:00:00Z"))
        self.assertEqual(mf.parse(self.build(valid_days=7), allowed_hosts=HOSTS)["expires"], "2026-12-08T12:00:00Z")

    def test_what_is_not_valid_is_not_built(self):
        for name, changes, message in (
                ("no version", {"version": "newest"}, "version: must be a build version"),
                ("a version as a number", {"version": 158}, "version: must be a build version"),
                ("the version of nothing installed", {"version": "0.0.0.0", "min_updater_version": "0.0.0.0"},
                 "version: 0.0.0.0 stands for nothing installed"),
                ("no Thoron version", {"thoron_version": "0.1"}, "thoron_version: must be a Thoron version"),
                ("a host that is not allowed", {"allowed_hosts": ("example.org",)}, "is not on the allow-list"),
                ("good for too long", {"valid_days": 91}, "expires: must be at most 90 days"),
                ("good for no time", {"valid_days": 0}, "expires: must be later than published"),
                ("good for longer than the calendar", {"valid_days": 10**9}, "published: "),
                ("no clock", {"published": None}, "published is the clock in whole seconds"),
                ("a clock with a fraction", {"published": float(PUBLISHED)}, "published is the clock in whole"),
                ("days with a fraction", {"valid_days": 1.5}, "valid_days a whole number of days"),
                ("no packages", {"packages": {}}, "packages: must be an object"),
                ("critical unsaid", {"critical": None}, "critical: must be true or false"),
                ("a manifest before it that is none", {"previous": {}},
                 'the manifest before this one: missing key "channel"'),
                ("a manifest before it with a serial alone", {"previous": {"serial": 1}},
                 'the manifest before this one: missing key "version"')):
            with self.subTest(name), self.assertRaises(mf.ManifestError) as refused:
                self.build(**changes)
            self.assertIn(message, str(refused.exception))

    def test_the_serial_is_the_day_and_a_count_above_the_manifest_before(self):
        self.assertEqual(mf.next_serial(PUBLISHED), SERIAL)
        self.assertEqual(mf.next_serial(PUBLISHED, 2026113007), SERIAL)
        self.assertEqual(mf.next_serial(PUBLISHED, SERIAL), SERIAL + 1)
        self.assertEqual(mf.next_serial(PUBLISHED, SERIAL + 98), SERIAL + 99)
        self.assertEqual(mf.next_serial(mf.parse_time("2026-12-01T23:59:59Z")), SERIAL)
        self.assertEqual(mf.next_serial(mf.parse_time("2026-12-02T00:00:00Z")), 2026120200)
        for previous in (SERIAL + 99, 2026120200):      # the day is full; the one before is from a later day
            with self.subTest(previous), self.assertRaises(mf.ManifestError):
                mf.next_serial(PUBLISHED, previous)

    def test_a_manifest_follows_the_one_before_it(self):
        first = mf.parse(self.build(version=OLD, thoron_version="0.1.1"), allowed_hosts=HOSTS)
        again = mf.parse(self.build(version=OLD, thoron_version="0.1.1", previous=first, published=PUBLISHED + DAY),
                         allowed_hosts=HOSTS)     # the same release, signed again with a later expiry
        self.assertEqual((again["serial"], again["expires"]), (2026120200, "2027-01-01T12:00:00Z"))
        release_ = mf.parse(self.build(previous=again, published=PUBLISHED + DAY), allowed_hosts=HOSTS)
        self.assertEqual(release_["serial"], 2026120201)
        self.assertEqual(mf.succession_problems(release_, again), [])
        for name, changes, message in (
                ("a lower version", {"version": "158.0.8127.2900", "thoron_version": "0.1.3",
                                     "min_updater_version": "158.0.8127.2900"},
                 "version: 158.0.8127.2900 is lower than the previous manifest's 158.0.8127.4500"),
                ("the same build under another Thoron version", {"thoron_version": "0.1.3"},
                 "thoron_version: build 158.0.8127.4500 is Thoron 0.1.2 in the previous manifest, not 0.1.3"),
                ("a new build under the same Thoron version", {"version": "158.0.8127.4501"},
                 "thoron_version: 0.1.2 is not higher than the previous release 0.1.2"),
                ("another channel", {"channel": "beta"}, "channel: beta cannot follow a manifest of channel stable"),
                ("an earlier time", {"published": PUBLISHED}, "serial: the manifest before this one has")):
            with self.subTest(name), self.assertRaises(mf.ManifestError) as refused:
                self.build(previous=release_, **{"published": PUBLISHED + 2 * DAY, **changes})
            self.assertIn(message, str(refused.exception))
        self.assertEqual(mf.succession_problems(release_, release_),
                         ["serial: 2026120201 is not higher than the previous manifest's 2026120201"])
        earlier = dict(release_, serial=2026120202, published="2026-12-02T00:00:00Z")
        self.assertEqual(mf.succession_problems(earlier, release_),
                         ["published: 2026-12-02T00:00:00Z is before the previous manifest's 2026-12-02T12:00:00Z"])

    def test_a_package_on_disk_becomes_its_entry(self):
        content = b"thoron" * 300000
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "thoron.exe"
            path.write_bytes(content)
            entry = mf.file_entry(path, URL)
        self.assertEqual(entry, {"url": URL, "size": 1800000, "sha256": hashlib.sha256(content).hexdigest()})
        data = mf.parse(self.build(packages={"win-x64-avx2": {"portable": {"full": entry}}}), allowed_hosts=HOSTS)
        self.assertEqual(data["packages"]["win-x64-avx2"]["portable"]["full"], entry)


class CommandLineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private, cls.public = ar.keygen()
        cls.public_text = base64.b64encode(cls.public).decode("ascii")

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.manifest = Path(folder.name) / "update.json"
        self.manifest.write_bytes(mf.example())
        self.signature = Path(folder.name) / "update.json.sig"

    def run_tool(self, *argv, clock: int = NOW) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                mock.patch.object(mf, "read_private_key", return_value=self.private), \
                mock.patch.object(mf.time, "time", return_value=float(clock)):     # the key stays in memory
            code = mf.main([str(arg) for arg in argv])
        return code, out.getvalue(), err.getvalue()

    def sign(self, *more, clock: int = NOW) -> tuple[int, str, str]:
        return self.run_tool("sign", self.manifest, "--key", "release.key", "--public-key", self.public_text,
                             *more, clock=clock)

    def test_example_prints_the_example_and_writes_it_byte_for_byte(self):
        code, out, _ = self.run_tool("example")
        self.assertEqual((code, out), (0, mf.example().decode("ascii")))
        copy = self.manifest.with_name("example.json")
        self.assertEqual(self.run_tool("example", "--out", copy)[0], 0)
        self.assertEqual(copy.read_bytes(), mf.example())

    def test_example_gives_a_byte_stream_the_bytes_as_they_are(self):
        stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", newline="\r\n")
        with contextlib.redirect_stdout(stream):
            self.assertEqual(mf.main(["example"]), 0)
        stream.flush()
        self.assertEqual(stream.buffer.getvalue(), mf.example())

    def test_example_does_not_overwrite_a_file(self):
        self.manifest.write_bytes(b"the real one\n")
        code, out, _ = self.run_tool("example", "--out", self.manifest)
        self.assertEqual(code, 1)
        self.assertIn("exists; a file is never overwritten", out)
        self.assertEqual(self.manifest.read_bytes(), b"the real one\n")

    def test_validate_says_ok_or_lists_every_problem(self):
        code, out, _ = self.run_tool("validate", self.manifest)
        self.assertEqual(code, 0)
        self.assertIn("OK, Thoron 0.1.2 (build 158.0.8127.4500), channel stable, serial 2026120100", out)
        self.manifest.write_bytes(mf.canonical(changed(put(("schema",), 2), put(("notes",), "x"))))
        code, out, err = self.run_tool("validate", self.manifest)
        self.assertEqual(code, 1)
        self.assertIn('manifest: unknown key "notes"\nmanifest: schema: must be 1\n', err)
        self.assertIn("refused, 2 problem(s)", out)

    def test_validate_takes_the_allowed_hosts(self):
        code, _, err = self.run_tool("validate", self.manifest, "--host", "example.org")
        self.assertEqual(code, 1)
        self.assertIn("host github.com is not on the allow-list (example.org)", err)
        both = ("--host", "example.org", "--host", "github.com")
        self.assertEqual(self.run_tool("validate", self.manifest, *both)[0], 0)

    def test_a_file_that_cannot_be_read_is_an_error(self):
        code, _, err = self.run_tool("validate", self.manifest.with_name("missing.json"))
        self.assertEqual(code, 2)
        self.assertIn("missing.json", err)

    def test_sign_then_verify(self):
        code, out, _ = self.sign("--first")
        self.assertEqual(code, 0, out)
        self.assertIn("signed, Thoron 0.1.2", out)
        self.assertEqual(self.signature.read_bytes(), signed(mf.example(), self.private, self.public))
        self.assertEqual(self.manifest.read_bytes(), mf.example())
        code, out, _ = self.run_tool("verify", self.manifest, "--public-key", self.public_text)
        self.assertEqual(code, 0, out)
        self.assertIn("the signature holds, Thoron 0.1.2 (build 158.0.8127.4500)", out)
        code, out, _ = self.sign("--first")
        self.assertEqual(code, 1)
        self.assertIn("a file is never overwritten", out)

    def test_sign_is_told_the_key_copies_hold_and_what_came_before(self):
        base = ("sign", self.manifest, "--key", "release.key")
        for argv in (base + ("--public-key", self.public_text),                       # neither --previous nor --first
                     base + ("--public-key", self.public_text, "--first", "--previous", self.manifest),
                     base + ("--first",)):                                             # no --public-key
            with self.subTest(argv[4:]), self.assertRaises(SystemExit):
                self.run_tool(*argv)
        other = base64.b64encode(ar.keygen()[1]).decode("ascii")
        zeros = base64.b64encode(bytes(32)).decode("ascii")
        for name, public_text in (("the public key of another key", other), ("a public key of zeros", zeros),
                                  ("a short public key", base64.b64encode(self.public[:-1]).decode("ascii"))):
            with self.subTest(name):
                code, _, err = self.run_tool(*base, "--public-key", public_text, "--first")
                self.assertEqual(code, 2)
                self.assertTrue(err.startswith("manifest: "))
        self.assertFalse(self.signature.exists())

    def test_sign_refuses_a_manifest_a_copy_would_refuse_for_its_dates(self):
        code, _, err = self.sign("--first", clock=PUBLISHED - DAY)
        self.assertEqual(code, 1)
        self.assertIn("published: 2026-12-01T12:00:00Z is ahead of the clock (2026-11-30T12:00:00Z)", err)
        code, _, err = self.sign("--first", clock=EXPIRES + 1)
        self.assertEqual(code, 1)
        self.assertIn("expires: 2026-12-31T12:00:00Z has passed", err)
        self.assertFalse(self.signature.exists())

    def test_verify_refuses_a_change_another_key_and_an_old_manifest(self):
        self.sign("--first")
        verify = ("verify", self.manifest, "--public-key")
        code, out, _ = self.run_tool(*verify, self.public_text, "--now", "2027-02-01T00:00:00Z")
        self.assertEqual(code, 1)
        self.assertIn("REFUSED (expired)", out)
        code, out, _ = self.run_tool(*verify, self.public_text, clock=EXPIRES + 2 * DAY)     # the clock itself
        self.assertEqual(code, 1)
        self.assertIn("REFUSED (expired)", out)
        code, out, _ = self.run_tool(*verify, self.public_text, "--now", "2026-11-01T00:00:00Z")
        self.assertIn("REFUSED (not_yet_valid)", out)
        code, out, _ = self.run_tool(*verify, self.public_text, "--last-serial", "2026120101")
        self.assertIn("REFUSED (replayed)", out)
        code, out, _ = self.run_tool(*verify, self.public_text, "--channel", "beta")
        self.assertIn("REFUSED (wrong_channel)", out)
        code, out, _ = self.run_tool(*verify, base64.b64encode(ar.keygen()[1]).decode("ascii"))
        self.assertEqual(code, 1)
        self.assertIn("REFUSED (bad_signature)", out)
        self.manifest.write_bytes(mf.example().replace(b"4500", b"4600", 1))
        code, out, _ = self.run_tool(*verify, self.public_text)
        self.assertEqual(code, 1)
        self.assertIn("REFUSED (bad_signature)", out)

    def test_verify_takes_no_key_that_is_none_and_no_argument_it_would_ignore(self):
        self.sign("--first")
        verify = ("verify", self.manifest, "--public-key")
        def text(key: bytes) -> str:
            return base64.b64encode(key).decode("ascii")

        for name, argv in (("no base64", verify + ("not base64",)),
                           ("a key of zeros", verify + (text(bytes(32)),)),
                           ("a key of small order", verify + (text(bytes([1]) + bytes(31)),)),
                           ("a short key", verify + (text(self.public[:-1]),)),
                           ("a variant without a copy", verify + (self.public_text, "--variant", "win-x64-avx2")),
                           ("an updater without a copy", verify + (self.public_text, "--updater", OLD)),
                           ("a copy without its variant", verify + (self.public_text, "--installed", OLD)),
                           ("a serial below zero", verify + (self.public_text, "--last-serial", "-5")),
                           ("an empty clock", verify + (self.public_text, "--now", ""))):
            with self.subTest(name):
                code, out, err = self.run_tool(*argv)
                self.assertEqual(code, 2, out + err)
                self.assertTrue(err.startswith("manifest: "), err)
                self.assertNotIn("the signature holds", out)

    def test_verify_shows_what_an_installed_copy_would_do(self):
        self.sign("--first")
        copy = ("verify", self.manifest, "--public-key", self.public_text, "--variant", "win-x64-avx2",
                "--kind", "installed", "--installed")
        code, out, _ = self.run_tool(*copy, OLD)
        self.assertEqual(code, 0, out)
        self.assertIn("manifest: update: 158.0.8127.4500 (Thoron 0.1.2) replaces 158.0.8127.3000", out)
        self.assertIn("full package https://github.com/KuchiSofts/thoron/releases/download/v0.1.2/"
                      "thoron-158.0.8127.4500-win-x64-avx2-installer.exe (104857600 bytes)", out)
        self.assertIn("-win-x64-avx2-installed.delta (9437184 bytes)", out)
        code, out, _ = self.run_tool(*copy, NEW)
        self.assertEqual(code, 0)
        self.assertIn("manifest: up_to_date:", out)
        for name, argv, outcome in (("a newer copy", copy + ("158.0.8127.4600",), "downgrade"),
                                    ("an old updater", copy + (OLD, "--updater", "158.0.8127.2000"), "updater_too_old"),
                                    ("no package", copy[:4] + ("--variant", "win-x64-sse4", "--kind", "portable",
                                                               "--installed", OLD), "no_package")):
            with self.subTest(name):
                code, out, _ = self.run_tool(*argv)
                self.assertEqual(code, 1)
                self.assertIn(f"manifest: {outcome}:", out)
                # P4.6: an old updater is shown the full package, for the updater in it; never a delta
                if outcome == "updater_too_old":
                    self.assertIn("full package https", out)
                    self.assertNotIn("delta", out.split("updater_too_old:", 1)[1])
                else:
                    self.assertNotIn("package https", out)

    def test_sign_refuses_what_is_not_valid_or_goes_back(self):
        previous = self.manifest.with_name("previous.json")
        previous.write_bytes(mf.example())
        code, out, err = self.sign("--previous", previous)
        self.assertEqual(code, 1)
        self.assertIn("serial: 2026120100 is not higher than the previous manifest's 2026120100", err)
        self.assertFalse(self.signature.exists())
        self.manifest.write_bytes(json.dumps(sample()).encode("ascii"))
        code, _, err = self.sign("--first")
        self.assertEqual(code, 1)
        self.assertIn("not in canonical form", err)
        self.assertFalse(self.signature.exists())

    def test_sign_accepts_the_next_manifest(self):
        previous = self.manifest.with_name("previous.json")
        previous.write_bytes(mf.build(
            channel="stable", version=OLD, thoron_version="0.1.1", critical=False, min_updater_version=OLD,
            packages={"win-x64-avx2": {"installed": {"full": ENTRY}}}, published=PUBLISHED - DAY, allowed_hosts=HOSTS))
        out_file = self.manifest.with_name("detached.sig")
        code, out, _ = self.sign("--previous", previous, "--out", out_file)
        self.assertEqual(code, 0, out)
        self.assertFalse(self.signature.exists())
        self.assertEqual(self.run_tool("verify", self.manifest, "--public-key", self.public_text, "--signature",
                                       out_file)[0], 0)

    def test_the_key_file_holds_32_bytes_in_base64(self):
        text = base64.b64encode(self.private) + b"\n"       # read from memory: no key file is written
        with mock.patch.object(Path, "read_bytes", return_value=text):
            self.assertEqual(mf.read_private_key(Path("release.key")), self.private)
        for wrong in (b"not base64!", base64.b64encode(self.private[:-1]), b""):
            with self.subTest(wrong[:8]), mock.patch.object(Path, "read_bytes", return_value=wrong), \
                    self.assertRaises(ValueError) as refused:
                mf.read_private_key(Path("release.key"))
            self.assertNotIn(base64.b64encode(self.private[:-1]).decode("ascii"), str(refused.exception))

    def test_without_the_package_that_signs_the_tool_says_so(self):
        self.sign("--first")
        with mock.patch.object(mf, "_ed25519", side_effect=ImportError("no cryptography")):
            code, _, err = self.run_tool("verify", self.manifest, "--public-key", self.public_text)
        self.assertEqual(code, 2)
        self.assertIn("need the Python package cryptography", err)


class SpecTests(unittest.TestCase):
    """docs/update/MANIFEST.md and this tool say the same."""

    @classmethod
    def setUpClass(cls):
        cls.text = SPEC.read_text(encoding="utf-8")

    def rows(self, first_cell: str) -> list[list[str]]:
        """The cells of the table rows of the spec whose first cell matches."""
        found = []
        for line in self.text.splitlines():
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if line.startswith("|") and re.fullmatch(first_cell, cells[0]):
                found.append(cells)
        return found

    def test_the_spec_shows_the_example_byte_for_byte(self):
        self.assertIn("```json\n" + mf.example().decode("ascii") + "```\n", self.text)
        self.assertIn(f"{len(mf.example())} bytes", self.text)
        self.assertIn(hashlib.sha256(mf.example()).hexdigest(), self.text)

    def test_the_vector_of_the_spec_verifies(self):
        public, signature = bytes.fromhex(VECTOR_PUBLIC_KEY), bytes.fromhex(VECTOR_SIGNATURE)
        self.assertEqual(mf.verify(mf.example(), signature, public, allowed_hosts=HOSTS), sample())
        self.assertIn(VECTOR_PUBLIC_KEY, self.text)
        self.assertIn(VECTOR_SIGNATURE[:64] + "\n" + VECTOR_SIGNATURE[64:], self.text)

    def test_the_steps_of_the_spec_are_the_order_of_the_checks(self):
        steps = self.rows(r"[0-9]+")
        self.assertEqual([int(cells[0]) for cells in steps], list(range(1, 15)))
        outcomes = [re.search(r"`([a-z_]+)`", cells[-1]).group(1) for cells in steps]
        before = [mf.MALFORMED, mf.BAD_SIGNATURE] + [mf.MALFORMED] * 4      # steps 1 to 6: the bytes
        self.assertEqual(outcomes, before + list(ORDER))
        self.assertIn(f"`{mf.DOWNGRADE}`; `{mf.UP_TO_DATE}`", steps[10][-1])

    def test_the_outcomes_of_the_spec_are_the_tools(self):
        table = {cells[0].strip("`"): cells for cells in self.rows(r"`[a-z_]+`")
                 if len(cells) == 4 and cells[0].strip("`") in mf.OUTCOMES}
        self.assertEqual(sorted(table), sorted(mf.OUTCOMES))
        copies = {mf.UPDATE: {}, mf.UP_TO_DATE: {"installed": NEW}, mf.WRONG_CHANNEL: {"channel": "beta"},
                  mf.REPLAYED: {"last_serial": SERIAL + 1}, mf.NOT_YET_VALID: {"now": 0},
                  mf.EXPIRED: {"now": EXPIRES + 2 * DAY}, mf.DOWNGRADE: {"installed": "159.0.0.0"},
                  mf.UPDATER_TOO_OLD: {"updater": "1.0.0.0"}, mf.NO_PACKAGE: {"variant": "linux-x64-avx2"}}
        for outcome, cells in table.items():
            with self.subTest(outcome):
                stored = False                  # bad_signature and malformed: nothing was read
                if outcome in copies:
                    state = dict(channel="stable", installed=OLD, updater=OLD, variant="win-x64-avx2",
                                 kind="installed", now=NOW)
                    state.update(copies[outcome])
                    decision = mf.decide(sample(), **state)
                    self.assertEqual(decision.outcome, outcome)
                    stored = decision.remember_serial is not None
                self.assertEqual(cells[3], "Yes" if stored else "No")
                self.assertEqual(cells[2].startswith("Cannot verify"), outcome in mf.CANNOT_VERIFY)
        self.assertTrue(table[mf.UP_TO_DATE][2].startswith("Up to date"))

    def test_the_copies_of_the_spec_get_the_outcomes_it_says(self):
        copies = self.rows(r"`[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+`")
        copies = [[cell.strip("`") for cell in cells[:6]] + [cells[6]] for cells in copies if len(cells) == 7]
        self.assertGreaterEqual(len(copies), 12)
        seen = set()
        for installed, updater, variant, kind, clock, serial, says in copies:
            with self.subTest(says):
                decision = mf.decide(sample(), channel="stable", installed=installed, updater=updater,
                                     variant=variant, kind=kind, now=mf.parse_time(clock), last_serial=int(serial))
                self.assertEqual(decision.outcome, re.match(r"`([a-z_]+)`", says).group(1))
                if decision.outcome == mf.UPDATE:
                    self.assertEqual(decision.delta is not None, "delta from" in says)
                    self.assertEqual(decision.delta is None, "full package only" in says)
                seen.add(decision.outcome)
        self.assertEqual(seen, set(ORDER) - {mf.WRONG_CHANNEL} | {mf.UP_TO_DATE})

    def test_the_spec_lists_the_keys_that_are_none(self):
        for key in sorted(mf.WEAK_KEYS):
            self.assertIn(key.hex(), self.text)

    def test_the_spec_names_every_key_outcome_variant_and_limit(self):
        for name in mf.TOP_KEYS + mf.OUTCOMES + mf.VARIANTS + mf.KINDS + mf.FILE_KEYS + ("full", "deltas"):
            with self.subTest(name):
                self.assertIn(f"`{name}`", self.text)
        self.assertIn(f"the {len(mf.SIGNATURE_PREFIX)} bytes `thoron-update-manifest-v1` and LF", self.text)
        self.assertIn("hex `" + " ".join(f"{byte:02x}" for byte in mf.SIGNATURE_PREFIX) + "`", self.text)
        for limit in (mf.SIGNATURE_PREFIX.decode("ascii").strip(), str(mf.MAX_MANIFEST_BYTES),
                      str(mf.MAX_MANIFEST_BYTES + 1), str(mf.MAX_INT), str(mf.MAX_URL_CHARS),
                      f"{mf.MAX_VALID_SECONDS // DAY} days", f"1 to {mf.MAX_DELTAS}",
                      f"{mf.CLOCK_SKEW_SECONDS // 3600} hours", f"{mf.DEFAULT_VALID_DAYS} days",
                      f"{mf.SIGNING_SLACK_SECONDS // 60} minutes", mf.MANIFEST_NAME, mf.SIGNATURE_NAME):
            with self.subTest(limit):
                self.assertIn(limit, self.text)


if __name__ == "__main__":
    unittest.main()
