# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Release script (ROADMAP P2.12, P3.2, S.9, P5.23). Keys are made in memory for one test run and never
written anywhere; nothing here runs minisign, 7-Zip, git or gh, and nothing contacts the network."""
import base64
import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.build import release_args as ra
from tools.release import adblock_resources as ar
from tools.release import changelog
from tools.release import package_audit
from tools.release import release as rel
from tools.update import manifest as mf

UPSTREAM_ARGS = 'target_os = "win"\nbundle_widevine_cdm = true\nenable_rlz = true\n'
GOOD_LIST = ["Chrome-bin/thoron.exe", "Chrome-bin/158.0.8127.3000/chrome.dll"]

BUILD, THORON, VARIANT = "158.0.8127.3000", "0.1.2", "win-x64-avx2"
NEXT_BUILD, NEXT_THORON = "158.0.8127.4500", "0.1.3"
GH_REPO = "KuchiSofts/thoron"
HOSTS = ("github.com",)
INSTALLER = f"thoron-{BUILD}-{VARIANT}-installer.exe"
INSTALLER_URL = f"https://github.com/{GH_REPO}/releases/download/v{THORON}/{INSTALLER}"
NOW = mf.parse_time("2026-12-01T12:00:00Z")
DAY = 86400
LOG = [{"author": "Dev", "subject": "fix: keep tab groups", "body": ""}]
SECURITY = [{"cve": "CVE-2026-0002", "severity": "Medium", "title": "Out of bounds read in Skia"},
            {"cve": "CVE-2026-0001", "severity": "High", "title": "Use after free in V8"}]
HIGHLIGHTS = "Security release. Chromium 158.0.8127.30 fixes CVE-2026-0001."
RESOURCES = json.dumps([{"name": "noop.js", "aliases": [], "kind": {"mime": "application/javascript"},
                         "content": base64.b64encode(b"(function() {})();").decode("ascii")}])
SERIAL = "2026120100"


def text(key: bytes) -> str:
    return base64.b64encode(key).decode("ascii")


class Fixture:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.src, self.out, self.dist = root / "src", root / "src/out/rel", root / "dist"
        (self.src / "chrome").mkdir(parents=True)
        self.out.mkdir(parents=True)
        (self.src / "chrome/VERSION").write_text(
            "MAJOR=158\nMINOR=0\nBUILD=8127\nPATCH=3000\nTHORON_REBUILD=0\n", encoding="utf-8")
        (self.out / "args.gn").write_text(ra.compose(UPSTREAM_ARGS, "win", "test"), encoding="ascii")
        (self.out / "mini_installer.exe").write_bytes(b"installer bytes")
        (self.out / "chrome.7z").write_bytes(b"7z")
        self.buildinfo = root / "BUILDINFO.json"
        self.buildinfo.write_text('{"variant": "win-x64-avx2"}', encoding="utf-8")

    def cleanup(self):
        self.tmp.cleanup()


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.f = Fixture()

    def tearDown(self):
        self.f.cleanup()

    def run_preflight(self, previous="156.0.8078.28", names=GOOD_LIST):
        return rel.preflight(self.f.src, self.f.out, "win", previous, lister=lambda archive: names)

    def test_clean_build_passes(self):
        version, problems = self.run_preflight()
        self.assertEqual(version, "158.0.8127.3000")
        self.assertEqual(problems, [])

    def test_version_not_set_is_refused(self):
        (self.f.src / "chrome/VERSION").write_text("MAJOR=158\nMINOR=0\nBUILD=8127\nPATCH=30\n", encoding="utf-8")
        _, problems = self.run_preflight()
        self.assertTrue([p for p in problems if "version.py set" in p])

    def test_version_must_be_higher_than_the_last_release(self):
        _, problems = self.run_preflight(previous="158.0.8127.3000")
        self.assertTrue([p for p in problems if "not higher" in p])

    def test_privacy_args_are_checked(self):
        (self.f.out / "args.gn").write_text(UPSTREAM_ARGS, encoding="ascii")
        _, problems = self.run_preflight()
        self.assertTrue([p for p in problems if "enable_rlz" in p])

    def test_package_audit_runs_on_the_installer_archive(self):
        _, problems = self.run_preflight(names=GOOD_LIST + ["Chrome-bin/thor_ver"])
        self.assertTrue([p for p in problems if "thor_ver" in p])


class AssembleTests(unittest.TestCase):
    def setUp(self):
        self.f = Fixture()

    def tearDown(self):
        self.f.cleanup()

    def test_files_names_and_checksums(self):
        files = rel.assemble(self.f.out, self.f.dist, "158.0.8127.3000", "win-x64-avx2", self.f.buildinfo)
        names = sorted(p.name for p in files)
        self.assertEqual(names, ["BUILDINFO-158.0.8127.3000-win-x64-avx2.json", "SHA256SUMS",
                                 "thoron-158.0.8127.3000-win-x64-avx2-installer.exe"])
        sums = (self.f.dist / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
        digest = hashlib.sha256(b"installer bytes").hexdigest()
        self.assertIn(f"{digest}  thoron-158.0.8127.3000-win-x64-avx2-installer.exe", sums)
        self.assertEqual(len(sums), 2)        # every file except SHA256SUMS itself

    def test_refuses_to_overwrite_an_existing_release_folder(self):
        rel.assemble(self.f.out, self.f.dist, "158.0.8127.3000", "win-x64-avx2", self.f.buildinfo)
        with self.assertRaises(rel.ReleaseError):
            rel.assemble(self.f.out, self.f.dist, "158.0.8127.3000", "win-x64-avx2", self.f.buildinfo)

    def test_variant_names_are_checked(self):
        with self.assertRaises(rel.ReleaseError):
            rel.assemble(self.f.out, self.f.dist, "158.0.8127.3000", "win x64; rm -rf", self.f.buildinfo)


class PublishTests(unittest.TestCase):
    def test_always_a_draft_and_never_unsigned(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp)
            (dist / "SHA256SUMS").write_text("x  a\n", encoding="utf-8")
            (dist / "NOTES.md").write_text("# Thoron\n", encoding="utf-8")
            with self.assertRaisesRegex(rel.ReleaseError, "signature"):
                rel.publish(dist, "158.0.8127.3000", "KuchiSofts/thoron", run=calls.append)
            (dist / "SHA256SUMS.minisig").write_text("sig", encoding="utf-8")
            rel.publish(dist, "158.0.8127.3000", "KuchiSofts/thoron", run=calls.append)
        cmd = calls[-1]
        self.assertEqual(cmd[:3], ["gh", "release", "create"])
        self.assertIn("--draft", cmd)
        self.assertIn("v158.0.8127.3000", cmd)
        self.assertEqual(cmd[cmd.index("--repo") + 1], "KuchiSofts/thoron")


class ReleaseFixture(Fixture):
    """A fake build ready for a whole release: Thoron's own version is set and the build wrote Thoron
    adblock's resources. The key files are names only: the keys are made here and stay in memory."""

    def __init__(self):
        super().__init__()
        root = Path(self.tmp.name)
        self.set_version(BUILD, THORON)
        (self.out / rel.ADBLOCK_RESOURCES).write_text(RESOURCES, encoding="utf-8")
        self.repo, self.keys = root / "repo", root / "keys"         # the keys folder is never made
        self.repo.mkdir()
        self.security, self.highlights = root / "security.json", root / "highlights.md"
        self.security.write_text(json.dumps(SECURITY), encoding="utf-8")
        self.highlights.write_text(HIGHLIGHTS + "\n", encoding="utf-8")
        self.private, self.public = ar.keygen()
        self.adblock_private, self.adblock_public = ar.keygen()
        self.key_reads = []

    def set_version(self, build: str, thoron: str | None):
        major, minor, build_, patch = build.split(".")
        lines = [f"MAJOR={major}", f"MINOR={minor}", f"BUILD={build_}", f"PATCH={patch}", "THORON_REBUILD=0"]
        lines += [f"THORON_VERSION={thoron}"] if thoron else []
        (self.src / "chrome/VERSION").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def main(self, *argv, clock: int = NOW, run=None) -> tuple[int, str, str]:
        """The command line, with the clock set and the outside tools (git, 7-Zip) answered from here.
        A key file is never opened: whoever asks for one gets the key of that name from memory."""
        keys = {"manifest.key": self.private, "adblock.key": self.adblock_private}

        def read_key(path: Path) -> bytes:
            self.key_reads.append(path)
            return keys[path.name]

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                mock.patch.object(mf, "read_private_key", side_effect=read_key), \
                mock.patch.object(rel.time, "time", return_value=float(clock)), \
                mock.patch.object(changelog, "_log", return_value=LOG), \
                mock.patch.object(package_audit, "list_archive", return_value=GOOD_LIST):
            code = rel.main([str(arg) for arg in argv], run=run)
        return code, out.getvalue(), err.getvalue()

    def prepare(self, *more, dist: Path | None = None, previous: str = "156.0.8078.28", **kw):
        return self.main("prepare", "--src", self.src, "--out", self.out, "--platform", "win", "--variant", VARIANT,
                         "--previous", previous, "--buildinfo", self.buildinfo, "--dist", dist or self.dist,
                         "--repo", self.repo, "--since", "v0.1.1", "--chromium-old", "156.0.8078.80", *more, **kw)

    def with_manifest(self, *more) -> tuple:
        return ("--manifest-key", self.keys / "manifest.key", "--manifest-public-key", text(self.public),
                "--gh-repo", GH_REPO, *(more or ("--first-manifest", "--min-updater-version", BUILD)))

    def with_adblock(self, serial: str = SERIAL) -> tuple:
        return ("--adblock-key", self.keys / "adblock.key", "--adblock-public-key", text(self.adblock_public),
                "--adblock-serial", serial)

    def publish(self, *, dist: Path | None = None, version: str = THORON, public: bytes | None = None, **kw):
        return self.main("publish", "--dist", dist or self.dist, "--version", version, "--gh-repo", GH_REPO,
                         "--manifest-public-key", text(public or self.public), **kw)

    def minisign_stand_in(self, dist: Path | None = None):
        """minisign is not run in a test; publish only looks for its file."""
        ((dist or self.dist) / "SHA256SUMS.minisig").write_text("stand-in\n", encoding="utf-8")

    def plan(self, **changes) -> rel.ManifestPlan:
        args = dict(channel="stable", critical=False, min_updater_version=BUILD, previous_manifest=None,
                    gh_repo=GH_REPO, published=NOW, valid_days=30)
        args.update(changes)
        return rel.manifest_plan(self.src, **args)


class ReleaseTestCase(unittest.TestCase):
    def setUp(self):
        self.f = ReleaseFixture()
        self.addCleanup(self.f.cleanup)

    def names(self, dist: Path | None = None) -> list[str]:
        return sorted(p.name for p in (dist or self.f.dist).iterdir())

    def manifest(self, dist: Path | None = None) -> tuple[bytes, bytes]:
        dist = dist or self.f.dist
        return (dist / "update.json").read_bytes(), (dist / "update.json.sig").read_bytes()

    def assert_nothing_packaged(self, dist: Path | None = None):
        self.assertFalse((dist or self.f.dist).exists())


class NotesTests(ReleaseTestCase):
    """S.9: prepare itself writes the security fixes and the hand-written opening into the notes."""

    def notes(self) -> str:
        return (self.f.dist / "NOTES.md").read_text(encoding="utf-8")

    def test_prepare_names_the_security_fixes_and_opens_with_the_highlights(self):
        code, _, err = self.f.prepare("--security", self.f.security, "--highlights", self.f.highlights)
        self.assertEqual(code, 0, err)
        notes = self.notes()
        self.assertIn("## Highlights\n\n" + HIGHLIGHTS + "\n", notes)
        self.assertIn("### Security fixes\n\n- CVE-2026-0001 (High): Use after free in V8\n"
                      "- CVE-2026-0002 (Medium): Out of bounds read in Skia\n", notes)
        order = [notes.index(h) for h in ("## Highlights", "## Chromium", "### Security fixes", "## Thoron changes",
                                         "## Downloads")]
        self.assertEqual(order, sorted(order))
        self.assertIn(f"| `{INSTALLER}` | `{hashlib.sha256(b'installer bytes').hexdigest()}` |", notes)

    def test_without_them_the_notes_are_as_before(self):
        self.assertEqual(self.f.prepare()[0], 0)
        notes = self.notes()
        self.assertNotIn("Security fixes", notes)
        self.assertNotIn("Highlights", notes)
        self.assertIn("Chromium 156.0.8078.80 to 158.0.8127.30", notes)
        self.assertIn("- keep tab groups", notes)

    def test_a_security_list_written_with_a_byte_order_mark_is_read(self):
        self.f.security.write_text(json.dumps(SECURITY), encoding="utf-8-sig")
        self.assertEqual(self.f.prepare("--security", self.f.security)[0], 0)
        self.assertIn("- CVE-2026-0001 (High): Use after free in V8", self.notes())

    def test_a_security_list_that_is_none_stops_before_anything_is_packaged(self):
        for name, content, says in (
                ("not JSON", "CVE-2026-0001 High", "security.json is not JSON"),
                ("no list", "{}", "a JSON list of at least one fix"),
                ("an empty list", "[]", "a JSON list of at least one fix"),
                ("a fix without a title", json.dumps([{"cve": "CVE-2026-0001", "severity": "High"}]),
                 "fix 1: title must be one line of text"),
                ("a severity of our own", json.dumps([dict(SECURITY[0], severity="Spicy")]),
                 "fix 1: severity must be one of Critical, High, Medium, Low")):
            with self.subTest(name):
                self.f.security.write_text(content, encoding="utf-8")
                code, _, err = self.f.prepare("--security", self.f.security)
                self.assertEqual(code, 2)
                self.assertIn(says, err)
                self.assert_nothing_packaged()

    def test_empty_highlights_and_a_missing_file_stop_before_anything_is_packaged(self):
        self.f.highlights.write_text(" \n", encoding="utf-8")
        code, _, err = self.f.prepare("--highlights", self.f.highlights)
        self.assertEqual(code, 2)
        self.assertIn("highlights.md is empty", err)
        code, _, err = self.f.prepare("--security", self.f.security.with_name("missing.json"))
        self.assertEqual(code, 2)
        self.assertIn("missing.json", err)
        self.assert_nothing_packaged()


class KeyTests(ReleaseTestCase):
    def test_a_key_file_inside_the_repository_the_build_or_the_release_folder_is_not_even_read(self):
        folders = (self.f.repo, self.f.src, self.f.out, self.f.dist)
        with mock.patch.object(mf, "read_private_key", side_effect=AssertionError("read")) as reader:
            for folder in folders:
                for path in (folder / "release.key", folder / "keys" / "deep" / "release.key",
                             folder / ".." / folder.name / "release.key"):
                    with self.subTest(path), self.assertRaisesRegex(rel.ReleaseError, "--manifest-key: the key "
                                                                    "file is inside"):
                        rel.read_signing_key(path, "--manifest-key", folders)
            self.assertEqual(reader.call_count, 0)

    def test_a_key_file_elsewhere_is_read_by_the_manifest_tool(self):
        path = self.f.keys / "manifest.key"
        with mock.patch.object(mf, "read_private_key", return_value=self.f.private) as reader:
            self.assertEqual(rel.read_signing_key(path, "--manifest-key", (self.f.repo, self.f.dist)), self.f.private)
        reader.assert_called_once_with(path)

    def test_a_file_that_holds_no_key_is_refused_without_showing_what_it_holds(self):
        secret = text(self.f.private[:-1])                          # a key cut short: 31 bytes
        with mock.patch.object(Path, "read_bytes", return_value=secret.encode("ascii")), \
                self.assertRaises(rel.ReleaseError) as refused:
            rel.read_signing_key(self.f.keys / "manifest.key", "--manifest-key", (self.f.repo,))
        self.assertIn("--manifest-key: the key file does not hold a 32-byte key", str(refused.exception))
        self.assertNotIn(secret, str(refused.exception))

    def test_a_public_key_is_32_usable_bytes_in_base64(self):
        self.assertEqual(rel.public_key_from(text(self.f.public), "--manifest-public-key"), self.f.public)
        for name, given in (("no base64", "not base64!"), ("a short key", text(self.f.public[:-1])),
                            ("a key of zeros", text(bytes(32))), ("a key of small order", text(bytes([1]) + bytes(31)))):
            with self.subTest(name), self.assertRaisesRegex(rel.ReleaseError, "--manifest-public-key"):
                rel.public_key_from(given, "--manifest-public-key")


class ManifestPartsTests(ReleaseTestCase):
    """P3.2, piece by piece: the plan, the packages from the files on disk, the checks before packaging,
    and the two files written."""

    def assembled(self) -> Path:
        rel.assemble(self.f.out, self.f.dist, BUILD, VARIANT, self.f.buildinfo)
        return self.f.dist

    def test_thorons_own_version_is_read_from_the_build_tree(self):
        self.assertEqual(rel.read_thoron_version(self.f.src), THORON)
        self.f.set_version(BUILD, None)
        self.assertIsNone(rel.read_thoron_version(self.f.src))
        with self.assertRaisesRegex(rel.ReleaseError, "version.py thoron"):
            self.f.plan()

    def test_a_package_is_served_from_the_release_tagged_with_thorons_version(self):
        self.assertEqual(rel.release_tag(THORON), "v0.1.2")
        self.assertEqual(self.f.plan().tag, "v0.1.2")
        self.assertEqual(rel.download_url(GH_REPO, "v0.1.2", INSTALLER), INSTALLER_URL)
        self.assertIsNone(mf.url_problem(INSTALLER_URL, HOSTS))
        with self.assertRaisesRegex(rel.ReleaseError, "--gh-repo must look like"):
            self.f.plan(gh_repo="github.com/KuchiSofts/thoron")

    def test_the_packages_are_the_files_in_the_release_folder(self):
        dist = self.assembled()
        entry = {"url": INSTALLER_URL, "size": 15, "sha256": hashlib.sha256(b"installer bytes").hexdigest()}
        self.assertEqual(rel.package_files(dist, BUILD, VARIANT), {"installed": dist / INSTALLER})
        self.assertEqual(rel.manifest_packages(dist, BUILD, VARIANT, GH_REPO, "v0.1.2"),
                         {VARIANT: {"installed": {"full": entry}}})
        (dist / INSTALLER).write_bytes(b"another installer")        # what is on disk is what is named
        changed = rel.manifest_packages(dist, BUILD, VARIANT, GH_REPO, "v0.1.2")[VARIANT]["installed"]["full"]
        self.assertEqual((changed["size"], changed["sha256"]), (17, hashlib.sha256(b"another installer").hexdigest()))
        (dist / INSTALLER).unlink()
        self.assertEqual(rel.manifest_packages(dist, BUILD, VARIANT, GH_REPO, "v0.1.2"), {})

    def test_the_first_manifest_is_told_the_oldest_updater_and_later_ones_keep_it(self):
        with self.assertRaisesRegex(rel.ReleaseError, "the first manifest of a channel needs --min-updater-version"):
            self.f.plan(min_updater_version=None)
        first = self.f.plan(min_updater_version="158.0.8127.2900")
        self.assertEqual((first.min_updater_version, first.previous), ("158.0.8127.2900", None))
        dist = self.assembled()
        rel.write_manifest(dist, first, BUILD, VARIANT, self.f.private, self.f.public, NOW)
        self.f.set_version(NEXT_BUILD, NEXT_THORON)
        kept = self.f.plan(min_updater_version=None, previous_manifest=dist / "update.json")
        self.assertEqual(kept.min_updater_version, "158.0.8127.2900")
        self.assertEqual(kept.previous["serial"], 2026120100)
        raised = self.f.plan(min_updater_version=BUILD, previous_manifest=dist / "update.json")
        self.assertEqual(raised.min_updater_version, BUILD)

    def test_what_is_given_as_the_manifest_before_must_be_one(self):
        other = self.f.buildinfo                                    # a file given by mistake
        with self.assertRaisesRegex(rel.ReleaseError, "--previous-manifest is not a manifest"):
            self.f.plan(previous_manifest=other)
        with self.assertRaises(OSError):
            self.f.plan(previous_manifest=other.with_name("missing.json"))

    def test_a_release_that_can_have_a_manifest_has_no_problem(self):
        self.assertEqual(rel.manifest_problems(self.f.plan(), BUILD, VARIANT, self.f.private, self.f.public), [])

    def test_what_stops_a_manifest_is_found_before_anything_is_packaged(self):
        def problems(plan=None, build=BUILD, variant=VARIANT, public=None):
            return rel.manifest_problems(plan or self.f.plan(), build, variant, self.f.private, public or self.f.public)

        self.assertIn("--manifest-key does not belong to the public key", problems(public=ar.keygen()[1])[0])
        self.assertIn("win-x64-avx512 is not a variant a manifest can name", problems(variant="win-x64-avx512")[0])
        self.assertIn("no package is made for linux-x64-avx2 yet", problems(variant="linux-x64-avx2")[0])
        self.assertIn("min_updater_version: must not be higher than version",
                      problems(self.f.plan(min_updater_version=NEXT_BUILD)))
        self.assertIn("expires: must be at most 90 days after published", problems(self.f.plan(valid_days=91)))
        self.assertTrue(problems(self.f.plan(channel="Stable"))[0].startswith("channel: must be a lower-case name"))
        self.assert_nothing_packaged()

    def test_a_manifest_must_follow_the_one_before_it(self):
        dist = self.assembled()
        rel.write_manifest(dist, self.f.plan(), BUILD, VARIANT, self.f.private, self.f.public, NOW)
        before = dict(min_updater_version=None, previous_manifest=dist / "update.json")

        def problems(build, thoron, **plan):
            self.f.set_version(build, thoron)
            return rel.manifest_problems(self.f.plan(**{**before, **plan}), build, VARIANT, self.f.private,
                                         self.f.public)

        self.assertEqual(problems(NEXT_BUILD, NEXT_THORON), [])
        self.assertEqual(problems(BUILD, THORON), [])               # the same release, signed again
        self.assertEqual(problems("158.0.8127.2900", NEXT_THORON),
                         ["min_updater_version: must not be higher than version"])
        self.assertEqual(problems("158.0.8127.2900", NEXT_THORON, min_updater_version="158.0.8127.2900"),
                         ["version: 158.0.8127.2900 is lower than the previous manifest's 158.0.8127.3000"])
        self.assertEqual(problems(NEXT_BUILD, THORON),
                         ["thoron_version: 0.1.2 is not higher than the previous release 0.1.2"])
        self.assertEqual(problems(NEXT_BUILD, NEXT_THORON, channel="beta"),
                         ["channel: beta cannot follow a manifest of channel stable"])
        self.assertIn("serial: the manifest before this one has 2026120100",
                      problems(NEXT_BUILD, NEXT_THORON, published=NOW - DAY)[0])

    def test_the_manifest_written_is_signed_and_verifies_with_the_public_key(self):
        dist = self.assembled()
        written = rel.write_manifest(dist, self.f.plan(critical=True), BUILD, VARIANT, self.f.private,
                                     self.f.public, NOW)
        self.assertEqual(written, [dist / "update.json", dist / "update.json.sig"])
        raw, signature = self.manifest()
        self.assertEqual(len(signature), 64)
        data = mf.verify(raw, signature, self.f.public, allowed_hosts=HOSTS)
        self.assertEqual(raw, mf.canonical(data))
        self.assertTrue(data["critical"])
        self.assertEqual(data["packages"], rel.manifest_packages(dist, BUILD, VARIANT, GH_REPO, "v0.1.2"))
        self.assertEqual(signature, mf.sign(raw, self.f.private, self.f.public, allowed_hosts=HOSTS, now=NOW))
        with self.assertRaises(mf.SignatureError):
            mf.verify(raw, signature, ar.keygen()[1], allowed_hosts=HOSTS)

    def test_nothing_is_written_when_the_manifest_cannot_be_signed(self):
        dist = self.assembled()
        for name, call, error in (
                ("another key's other half", lambda: rel.write_manifest(
                    dist, self.f.plan(), BUILD, VARIANT, self.f.private, ar.keygen()[1], NOW), ValueError),
                ("a clock behind the manifest", lambda: rel.write_manifest(
                    dist, self.f.plan(), BUILD, VARIANT, self.f.private, self.f.public, NOW - DAY), mf.ManifestError),
                ("a variant without a package", lambda: rel.write_manifest(
                    dist, self.f.plan(), BUILD, "win-x64-sse4", self.f.private, self.f.public, NOW), rel.ReleaseError)):
            with self.subTest(name), self.assertRaises(error):
                call()
            self.assertEqual(self.names(), [f"BUILDINFO-{BUILD}-{VARIANT}.json", "SHA256SUMS", INSTALLER])

    def test_a_manifest_in_the_folder_is_never_overwritten(self):
        dist = self.assembled()
        (dist / "update.json").write_bytes(b"the one before\n")
        with self.assertRaises(FileExistsError):
            rel.write_manifest(dist, self.f.plan(), BUILD, VARIANT, self.f.private, self.f.public, NOW)
        self.assertEqual((dist / "update.json").read_bytes(), b"the one before\n")
        self.assertFalse((dist / "update.json.sig").exists())

    def test_a_manifest_never_stays_in_the_folder_without_its_signature(self):
        dist = self.assembled()
        (dist / "update.json.sig").write_bytes(b"left from before")    # the second file cannot be written
        with self.assertRaises(FileExistsError):
            rel.write_manifest(dist, self.f.plan(), BUILD, VARIANT, self.f.private, self.f.public, NOW)
        self.assertFalse((dist / "update.json").exists())
        self.assertEqual((dist / "update.json.sig").read_bytes(), b"left from before")
        (dist / "update.json.sig").unlink()
        with mock.patch.object(mf, "verify", side_effect=mf.SignatureError("changed on the way to the disk")), \
                self.assertRaises(mf.SignatureError):                    # what was written does not read back
            rel.write_manifest(dist, self.f.plan(), BUILD, VARIANT, self.f.private, self.f.public, NOW)
        self.assertEqual(self.names(), [f"BUILDINFO-{BUILD}-{VARIANT}.json", "SHA256SUMS", INSTALLER])


class DryRunTests(ReleaseTestCase):
    """P3.2 from end to end on a fake build: prepare with a throwaway key, the manifest it wrote checked
    with the public key, a changed byte refused, and publish's checks up to the gh command, which is taken
    here and never run."""

    def prepared(self, *more) -> Path:
        code, out, err = self.f.prepare(*self.f.with_manifest(), *more)
        self.assertEqual(code, 0, out + err)
        self.f.minisign_stand_in()
        return self.f.dist

    def publish_refused(self, says: str, **kw):
        calls = []
        code, out, err = self.f.publish(run=calls.append, **kw)
        self.assertEqual(code, 1, out + err)
        self.assertIn(says, err)
        self.assertIn("nothing was published", out)
        self.assertEqual(calls, [])                                 # gh was never asked for anything

    def test_prepare_writes_a_signed_manifest_of_the_files_it_packaged(self):
        code, out, err = self.f.prepare(*self.f.with_manifest())
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.names(), [f"BUILDINFO-{BUILD}-{VARIANT}.json", "NOTES.md", "SHA256SUMS", INSTALLER,
                                        "update.json", "update.json.sig"])
        self.assertIn("update.json is signed: Thoron 0.1.2 (build 158.0.8127.3000), channel stable, good for "
                      "30 days; publish it with --version 0.1.2", out)
        self.assertIn(f"release {BUILD}: 5 file(s) in ", out)
        raw, signature = self.manifest()
        data = mf.verify(raw, signature, self.f.public, allowed_hosts=HOSTS)
        installer = (self.f.dist / INSTALLER).read_bytes()
        self.assertEqual(installer, b"installer bytes")
        self.assertEqual(data, {
            "schema": 1, "channel": "stable", "serial": 2026120100,
            "published": "2026-12-01T12:00:00Z", "expires": "2026-12-31T12:00:00Z",
            "version": BUILD, "thoron_version": THORON, "chromium_version": "158.0.8127.30",
            "critical": False, "min_updater_version": BUILD,
            "packages": {VARIANT: {"installed": {"full": {
                "url": INSTALLER_URL, "size": len(installer), "sha256": hashlib.sha256(installer).hexdigest()}}}}})
        sums = (self.f.dist / "SHA256SUMS").read_text(encoding="utf-8")
        self.assertIn(f"{data['packages'][VARIANT]['installed']['full']['sha256']}  {INSTALLER}\n", sums)
        self.assertNotIn("update.json", sums)                       # it carries its own signature

    def test_copies_of_thoron_take_the_manifest_prepare_wrote(self):
        self.prepared()
        raw, signature = self.manifest()

        def copy(installed: str, **state):
            args = dict(allowed_hosts=HOSTS, channel="stable", installed=installed, updater=BUILD, variant=VARIANT,
                        kind="installed", now=NOW + DAY)
            args.update(state)
            return mf.check_update(raw, signature, self.f.public, **args)

        older = copy("158.0.8127.2900")
        self.assertEqual(older.outcome, mf.UPDATE)
        self.assertEqual(older.full["url"], INSTALLER_URL)
        self.assertEqual(copy("0.0.0.0").outcome, mf.UPDATE)        # the small installer
        self.assertEqual(copy(BUILD).outcome, mf.UP_TO_DATE)
        self.assertEqual(copy("158.0.8127.2900", updater="158.0.8127.2900").outcome, mf.UPDATER_TOO_OLD)
        self.assertEqual(copy("158.0.8127.2900", variant="win-x64-sse4").outcome, mf.NO_PACKAGE)
        self.assertEqual(copy("158.0.8127.2900", now=NOW + 32 * DAY).outcome, mf.EXPIRED)

    def test_a_critical_release_says_so_in_its_manifest(self):
        self.prepared("--critical", "--manifest-days", "14", "--channel", "stable")
        data = mf.verify(*self.manifest(), self.f.public, allowed_hosts=HOSTS)
        self.assertEqual((data["critical"], data["expires"]), (True, "2026-12-15T12:00:00Z"))

    def test_publish_checks_the_folder_and_makes_a_draft_of_it(self):
        dist = self.prepared()
        self.assertEqual(rel.publish_problems(dist, THORON, GH_REPO, self.f.public, NOW), [])
        calls = []
        code, out, err = self.f.publish(run=calls.append)
        self.assertEqual(code, 0, out + err)
        self.assertIn("draft release v0.1.2 created", out)
        self.assertEqual(len(calls), 1)
        cmd = calls[0]
        self.assertEqual(cmd[:6], ["gh", "release", "create", "v0.1.2", "--draft", "--repo"])
        self.assertEqual(cmd[cmd.index("--notes-file") + 1], str(dist / "NOTES.md"))
        uploaded = cmd[cmd.index("--notes-file") + 2:]
        self.assertEqual(uploaded, [str(dist / name) for name in (
            f"BUILDINFO-{BUILD}-{VARIANT}.json", "SHA256SUMS", "SHA256SUMS.minisig", INSTALLER, "update.json",
            "update.json.sig")])

    def test_any_changed_byte_of_the_manifest_or_the_signature_is_refused(self):
        dist = self.prepared()
        raw, signature = self.manifest()
        for name, content in (("update.json", raw), ("update.json.sig", signature)):
            for offset in range(len(content)):
                flipped = content[:offset] + bytes([content[offset] ^ 0x01]) + content[offset + 1:]
                with self.assertRaises(mf.SignatureError):
                    mf.verify(*((flipped, signature) if name == "update.json" else (raw, flipped)), self.f.public,
                              allowed_hosts=HOSTS)
                (dist / name).write_bytes(flipped)
                found = rel.publish_problems(dist, THORON, GH_REPO, self.f.public, NOW)
                self.assertEqual(len(found), 1, (name, offset, found))
                self.assertIn("update manifest: the signature does not hold with the public key given", found[0])
            (dist / name).write_bytes(content)
        self.assertEqual(rel.publish_problems(dist, THORON, GH_REPO, self.f.public, NOW), [])
        self.assertGreater(len(raw), 500)

    def test_publish_refuses_a_manifest_with_a_changed_byte(self):
        dist = self.prepared()
        raw, _ = self.manifest()
        (dist / "update.json").write_bytes(raw.replace(b'"critical": false', b'"critical": true '))
        self.publish_refused("update manifest: the signature does not hold with the public key given")
        (dist / "update.json").write_bytes(raw + b"\n")
        self.publish_refused("update manifest: the signature does not hold")
        (dist / "update.json").write_bytes(raw)
        self.assertEqual(self.f.publish(run=lambda cmd: None)[0], 0)

    def test_publish_refuses_a_manifest_that_is_missing_unsigned_or_signed_by_another_key(self):
        dist = self.prepared()
        raw, signature = self.manifest()
        self.publish_refused("update manifest: the signature does not hold", public=ar.keygen()[1])
        (dist / "update.json.sig").unlink()
        self.publish_refused("update manifest: update.json is not signed (no update.json.sig)")
        (dist / "update.json.sig").write_bytes(base64.b64encode(signature))      # a signature in another form
        self.publish_refused("update manifest: the signature does not hold")
        (dist / "update.json.sig").write_bytes(signature)
        (dist / "update.json").unlink()
        self.publish_refused("update manifest: there is none (update.json)")
        (dist / "update.json").write_bytes(b"")
        self.publish_refused("update manifest: a manifest is 1 to 262144 bytes, not 0")

    def test_publish_takes_no_public_key_that_is_none(self):
        self.prepared()
        for name, key in (("zeros", bytes(32)), ("a short key", self.f.public[:-1])):
            with self.subTest(name):
                calls = []
                code, _, err = self.f.main("publish", "--dist", self.f.dist, "--version", THORON, "--gh-repo", GH_REPO,
                                           "--manifest-public-key", text(key), run=calls.append)
                self.assertEqual(code, 2)
                self.assertIn("--manifest-public-key", err)
                self.assertEqual(calls, [])
        with self.assertRaises(SystemExit):                         # and none at all
            self.f.main("publish", "--dist", self.f.dist, "--version", THORON, "--gh-repo", GH_REPO)

    def test_publish_refuses_a_manifest_whose_packages_are_not_the_folders(self):
        dist = self.prepared()
        self.publish_refused(f"{VARIANT}/installed/full is at {INSTALLER_URL}, which is no file of release "
                             f"v{BUILD} of {GH_REPO}", version=BUILD)       # the draft would get another tag
        installer = dist / INSTALLER
        installer.write_bytes(b"installer bytez")                   # the same length, another content
        self.publish_refused(f"update manifest: {VARIANT}/installed/full: the size and SHA-256 are not those of "
                             f"{INSTALLER} in the folder")
        self.publish_refused(f"{INSTALLER} does not have the SHA-256 that SHA256SUMS lists")
        installer.unlink()
        self.publish_refused(f"update manifest: {VARIANT}/installed/full names {INSTALLER}, which is not in the "
                             "folder")
        self.publish_refused(f"{INSTALLER} is in SHA256SUMS and not in the folder")

    def test_publish_refuses_a_manifest_no_copy_would_take_today(self):
        self.prepared()
        self.publish_refused("update manifest: expired 2026-12-31T12:00:00Z", clock=NOW + 32 * DAY)
        self.publish_refused("update manifest: published 2026-12-01T12:00:00Z is after this computer's clock",
                             clock=NOW - 2 * DAY)

    def test_publish_refuses_a_folder_with_a_file_prepare_did_not_write(self):
        dist = self.prepared()
        (dist / "notes for myself.txt").write_text("x", encoding="utf-8")
        self.publish_refused("notes for myself.txt is not in SHA256SUMS; only what prepare wrote belongs in the "
                             "folder")
        (dist / "notes for myself.txt").unlink()
        (dist / "old").mkdir()
        self.publish_refused("old is a folder; a release folder holds files only")
        (dist / "old").rmdir()
        (dist / "SHA256SUMS.minisig").unlink()
        self.publish_refused("no signature (SHA256SUMS.minisig)")

    def test_without_the_key_there_is_no_manifest_and_prepare_and_publish_say_so(self):
        code, out, err = self.f.prepare()
        self.assertEqual(code, 0, out + err)
        self.assertIn("release: no update manifest was made (no --manifest-key); publish will refuse this release",
                      out)
        self.assertIn("release: SHA256SUMS is not signed (no --minisign-key); publish will refuse it", out)
        self.assertEqual(self.names(), [f"BUILDINFO-{BUILD}-{VARIANT}.json", "NOTES.md", "SHA256SUMS", INSTALLER])
        self.assertEqual(self.f.key_reads, [])
        self.f.minisign_stand_in()
        self.publish_refused("update manifest: there is none (update.json); prepare makes it when it is given "
                             "--manifest-key")

    def test_the_private_key_is_read_from_the_path_given_and_written_nowhere(self):
        code, out, err = self.f.prepare(*self.f.with_manifest(), *self.f.with_adblock())
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.f.key_reads, [self.f.keys / "adblock.key", self.f.keys / "manifest.key"])
        self.assertFalse(self.f.keys.exists())
        written = b"".join(p.read_bytes() for p in Path(self.f.tmp.name).rglob("*") if p.is_file())
        said = (out + err).encode("utf-8")
        for key in (self.f.private, self.f.adblock_private):
            for form in (key, base64.b64encode(key), key.hex().encode("ascii")):
                self.assertNotIn(form, written)
                self.assertNotIn(form, said)

    def test_a_key_file_in_the_repository_stops_prepare_before_anything_is_packaged(self):
        for folder in (self.f.repo, self.f.dist, self.f.out):
            with self.subTest(folder.name):
                code, _, err = self.f.prepare("--manifest-key", folder / "manifest.key", "--manifest-public-key",
                                              text(self.f.public), "--gh-repo", GH_REPO, "--first-manifest",
                                              "--min-updater-version", BUILD)
                self.assertEqual(code, 2)
                self.assertIn("--manifest-key: the key file is inside", err)
                self.assertEqual(self.f.key_reads, [])
                self.assert_nothing_packaged()

    def test_a_key_that_is_not_the_one_copies_hold_stops_prepare_before_anything_is_packaged(self):
        code, out, err = self.f.prepare("--manifest-key", self.f.keys / "manifest.key", "--manifest-public-key",
                                        text(ar.keygen()[1]), "--gh-repo", GH_REPO, "--first-manifest",
                                        "--min-updater-version", BUILD)
        self.assertEqual(code, 1)
        self.assertIn("release: update manifest: --manifest-key does not belong to the public key", err)
        self.assertIn("1 problem(s); nothing was packaged", out)
        self.assert_nothing_packaged()

    def test_a_build_without_thorons_version_gets_no_manifest(self):
        self.f.set_version(BUILD, None)
        code, _, err = self.f.prepare(*self.f.with_manifest())
        self.assertEqual(code, 2)
        self.assertIn("chrome/VERSION has no THORON_VERSION", err)
        self.assert_nothing_packaged()

    def test_the_options_of_the_manifest_go_together(self):
        key = ("--manifest-key", self.f.keys / "manifest.key")
        public = ("--manifest-public-key", text(self.f.public))
        for name, argv, says in (
                ("no public key", key + ("--gh-repo", GH_REPO, "--first-manifest"),
                 "--manifest-key needs --manifest-public-key"),
                ("no repository", key + public + ("--first-manifest",), "--manifest-key needs --gh-repo"),
                ("nothing about the manifest before", key + public + ("--gh-repo", GH_REPO),
                 "--manifest-key needs --previous-manifest <the last update.json>, or --first-manifest"),
                ("a first manifest without the oldest updater", key + public + ("--gh-repo", GH_REPO, "--first-manifest"),
                 "the first manifest of a channel needs --min-updater-version"),
                ("options without the key", public + ("--critical", "--manifest-days", "0"),
                 "--manifest-public-key, --critical, --manifest-days: only with --manifest-key"),
                ("the ad blocker's options without its key", ("--adblock-serial", SERIAL),
                 "--adblock-serial: only with --adblock-key"),
                ("the ad blocker's key alone", ("--adblock-key", self.f.keys / "adblock.key"),
                 "--adblock-key needs --adblock-public-key, --adblock-serial")):
            with self.subTest(name):
                code, _, err = self.f.prepare(*argv)
                self.assertEqual(code, 2)
                self.assertIn(says, err)
                self.assert_nothing_packaged()
        with self.assertRaises(SystemExit):                         # both said about the manifest before
            self.f.prepare(*key, *public, "--gh-repo", GH_REPO, "--first-manifest", "--previous-manifest", "x")

    def test_a_folder_left_half_made_says_so_and_is_not_published(self):
        with mock.patch.object(mf, "sign", side_effect=mf.SignatureError("the signature just made does not verify")):
            code, _, err = self.f.prepare(*self.f.with_manifest())
        self.assertEqual(code, 2)
        self.assertIn("is incomplete; remove it before running prepare again", err)
        self.assertNotIn("update.json", self.names())
        self.f.minisign_stand_in()
        self.publish_refused("update manifest: there is none")

    def test_without_the_package_that_signs_prepare_says_so(self):
        missing = ModuleNotFoundError("No module named 'cryptography'", name="cryptography")
        with mock.patch.object(mf, "public_key_of", side_effect=missing):
            code, _, err = self.f.prepare(*self.f.with_manifest())
        self.assertEqual(code, 2)
        self.assertIn("need the Python package cryptography", err)
        self.assert_nothing_packaged()

    def test_the_next_release_follows_the_manifest_of_the_one_before(self):
        first = self.prepared()
        second = first.with_name("dist-next")
        self.f.set_version(NEXT_BUILD, NEXT_THORON)
        code, out, err = self.f.prepare(*self.f.with_manifest("--previous-manifest", first / "update.json"),
                                        dist=second, previous=BUILD, clock=NOW + 3600)
        self.assertEqual(code, 0, out + err)
        data = mf.verify(*self.manifest(second), self.f.public, allowed_hosts=HOSTS)
        self.assertEqual((data["serial"], data["version"], data["thoron_version"], data["min_updater_version"]),
                         (2026120101, NEXT_BUILD, NEXT_THORON, BUILD))
        self.assertEqual(mf.succession_problems(data, mf.verify(*self.manifest(), self.f.public, allowed_hosts=HOSTS)),
                         [])
        self.assertIn(f"/releases/download/v{NEXT_THORON}/thoron-{NEXT_BUILD}-{VARIANT}-installer.exe",
                      data["packages"][VARIANT]["installed"]["full"]["url"])
        self.f.minisign_stand_in(second)
        self.assertEqual(self.f.publish(dist=second, version=NEXT_THORON, run=lambda cmd: None, clock=NOW + 3600)[0], 0)

    def test_a_release_that_does_not_follow_the_manifest_before_is_not_packaged(self):
        first = self.prepared()
        second = first.with_name("dist-next")
        self.f.set_version(NEXT_BUILD, THORON)                      # a new build under the old Thoron version
        code, out, err = self.f.prepare(*self.f.with_manifest("--previous-manifest", first / "update.json"),
                                        dist=second, previous=BUILD)
        self.assertEqual(code, 1, out + err)
        self.assertIn("release: update manifest: thoron_version: 0.1.2 is not higher than the previous release 0.1.2",
                      err)
        self.assertIn("nothing was packaged", out)
        self.assert_nothing_packaged(second)


class AdblockBundleTests(ReleaseTestCase):
    """P5.23: with its key, prepare also signs the build's scriptlets and stand-ins of Thoron adblock."""

    def test_prepare_signs_the_resources_of_the_build(self):
        code, out, err = self.f.prepare(*self.f.with_adblock())
        self.assertEqual(code, 0, out + err)
        self.assertIn("thoron_adblock_resources.signed is signed (serial 2026120100); it is no part of the draft: "
                      "the owner uploads it to the release tagged adblock-resources", out)
        bundle = (self.f.dist / "thoron_adblock_resources.signed").read_bytes()
        self.assertEqual(ar.verify(bundle.decode("utf-8"), self.f.adblock_public), SERIAL)
        self.assertTrue(bundle.endswith(b"\n\n" + RESOURCES.encode("utf-8")))
        self.assertNotIn(b"\r", bundle)                             # byte for byte, on every system
        self.assertEqual(bundle.decode("utf-8"), ar.sign(RESOURCES, SERIAL, self.f.adblock_private))
        self.assertIsNone(ar.verify(bundle.decode("utf-8").replace("noop.js", "nooq.js"), self.f.adblock_public))
        self.assertIsNone(ar.verify(bundle.decode("utf-8"), self.f.public))      # the manifest's key is another one
        self.assertEqual(self.f.key_reads, [self.f.keys / "adblock.key"])
        self.assertNotIn("thoron_adblock_resources", (self.f.dist / "SHA256SUMS").read_text(encoding="utf-8"))

    def test_without_its_key_the_step_is_left_out(self):
        code, out, _ = self.f.prepare(*self.f.with_manifest())
        self.assertEqual(code, 0)
        self.assertNotIn("thoron_adblock_resources.signed", self.names())
        self.assertNotIn("adblock", out)

    def test_other_resources_can_be_named(self):
        other = json.dumps(json.loads(RESOURCES) * 2)
        path = Path(self.f.tmp.name) / "resources.json"
        path.write_text(other, encoding="utf-8")
        self.assertEqual(self.f.prepare(*self.f.with_adblock("2026120101"), "--adblock-resources", path)[0], 0)
        bundle = (self.f.dist / "thoron_adblock_resources.signed").read_text(encoding="utf-8")
        self.assertEqual(ar.verify(bundle, self.f.adblock_public), "2026120101")
        self.assertTrue(bundle.endswith("\n\n" + other))

    def test_what_cannot_be_signed_stops_prepare_before_anything_is_packaged(self):
        resources = self.f.out / rel.ADBLOCK_RESOURCES
        for name, argv, content, says in (
                ("a serial of eight digits", self.f.with_adblock("20261201"), RESOURCES, "the serial is ten digits"),
                ("another key's public half", self.f.with_adblock()[:3] + (text(ar.keygen()[1]), "--adblock-serial",
                                                                         SERIAL), RESOURCES,
                 "--adblock-key does not belong to the public key"),
                ("resources that are no list", self.f.with_adblock(), "{}", "not a list of resources"),
                ("resources that are no JSON", self.f.with_adblock(), "noop.js", "Thoron adblock's resources: ")):
            with self.subTest(name):
                resources.write_text(content, encoding="utf-8")
                code, _, err = self.f.prepare(*argv)
                self.assertEqual(code, 2)
                self.assertIn(says, err)
                self.assert_nothing_packaged()
        resources.unlink()
        code, _, err = self.f.prepare(*self.f.with_adblock())
        self.assertEqual(code, 2)
        self.assertIn("thoron_adblock_resources.json", err)
        self.assert_nothing_packaged()

    def test_a_signed_copy_that_does_not_verify_is_not_handed_out(self):
        with mock.patch.object(ar, "verify", return_value=None), self.assertRaisesRegex(rel.ReleaseError,
                                                                                         "do not verify"):
            rel.sign_adblock_bundle(RESOURCES, SERIAL, self.f.adblock_private, self.f.adblock_public)

    def test_the_bundle_is_prepared_with_the_release_and_left_out_of_the_draft(self):
        code, out, err = self.f.prepare(*self.f.with_manifest(), *self.f.with_adblock())
        self.assertEqual(code, 0, out + err)
        self.f.minisign_stand_in()
        self.assertIn("thoron_adblock_resources.signed", self.names())
        calls = []
        code, out, err = self.f.publish(run=calls.append)
        self.assertEqual(code, 0, out + err)
        self.assertIn("thoron_adblock_resources.signed is not in the draft; the owner uploads it to the release "
                      "tagged adblock-resources", out)
        self.assertFalse([arg for arg in calls[0] if "thoron_adblock_resources" in arg])
        self.assertIn(str(self.f.dist / "update.json.sig"), calls[0])


class ChecksumTests(ReleaseTestCase):
    def test_the_folder_must_be_what_sha256sums_lists(self):
        dist = self.f.dist
        rel.assemble(self.f.out, dist, BUILD, VARIANT, self.f.buildinfo)
        self.assertEqual(rel.checksum_problems(dist), [])
        for name in rel.UNLISTED:                                   # what a finished folder holds besides
            if name != "SHA256SUMS":
                (dist / name).write_bytes(b"x")
        self.assertEqual(rel.checksum_problems(dist), [])
        (dist / "release.key").write_bytes(b"x")                    # and what it must never hold
        self.assertEqual(rel.checksum_problems(dist),
                         ["release.key is not in SHA256SUMS; only what prepare wrote belongs in the folder"])
        (dist / "release.key").unlink()
        sums = dist / "SHA256SUMS"
        good = sums.read_text(encoding="utf-8")
        sums.write_text(good + "0" * 64 + "  ../outside.exe\n", encoding="utf-8", newline="\n")
        self.assertEqual(rel.checksum_problems(dist), ["SHA256SUMS has a line that is not `<sha256>  <file name>`"])
        sums.write_text(good + "0" * 64 + "  gone.exe\n", encoding="utf-8", newline="\n")
        self.assertEqual(rel.checksum_problems(dist), ["gone.exe is in SHA256SUMS and not in the folder"])


if __name__ == "__main__":
    unittest.main()
