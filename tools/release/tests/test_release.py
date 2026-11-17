# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Release script (ROADMAP P2.12, P3.2, S.9, P5.23, and its gates P2.24, L.2, P2.8, L.3, D.10, D.9). Keys
are made in memory for one test run and never written anywhere; nothing here runs minisign, 7-Zip, git or
gh, and nothing contacts the network: the repository's tags and upstream's contributors are answered from
the fixture."""
import base64
import contextlib
import hashlib
import io
import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from tools.build import release_args as ra
from tools.credits import contributors
from tools.docs import check_docs
from tools.legal import patch_licenses
from tools.release import adblock_resources as ar
from tools.release import changelog
from tools.release import package_audit
from tools.release import release as rel
from tools.release import version as ver
from tools.release.tests.test_portable import program
from tools.update import manifest as mf

UPSTREAM_ARGS = 'target_os = "win"\nbundle_widevine_cdm = true\nenable_rlz = true\n'
GOOD_LIST = ["Chrome-bin/thoron.exe", "Chrome-bin/158.0.8127.3000/chrome.dll"]

BUILD, THORON, VARIANT = "158.0.8127.3000", "0.1.2", "win-x64-avx2"
NEXT_BUILD, NEXT_THORON = "158.0.8127.4500", "0.1.3"
GH_REPO = "KuchiSofts/thoron"
HOSTS = ("github.com",)
INSTALLER = f"thoron-{BUILD}-{VARIANT}-installer.exe"
INSTALLER_URL = f"https://github.com/{GH_REPO}/releases/download/v{THORON}/{INSTALLER}"
PORTABLE = f"thoron-{BUILD}-{VARIANT}-portable.zip"
PORTABLE_URL = f"https://github.com/{GH_REPO}/releases/download/v{THORON}/{PORTABLE}"
LICENCES = f"thoron-{BUILD}-licenses.zip"
RECORD = f"BUILDINFO-{BUILD}-{VARIANT}.json"
COMMIT = "0123456789abcdef0123456789abcdef01234567"
# A stand-in with the marks of the real text: its title, its version and its last line.
GPL = ("                    GNU GENERAL PUBLIC LICENSE\n                       Version 3, 29 June 2007\n\n"
       "  (the terms, left out of a test)\n\n                     END OF TERMS AND CONDITIONS\n")
PEOPLE = [{"type": "User", "login": "Alex313031", "contributions": 4905},
          {"type": "User", "login": "gz83", "contributions": 18},
          {"type": "Anonymous", "name": "Someone Else", "email": "someone@example.com", "contributions": 1}]
CHANGELOG = ("# Changelog\n\nOne line per change.\n\n## [Unreleased]\n\n### Added\n\n"
             "- **Updates:** Thoron updates itself from inside.\n- **Portable:** a package that runs without\n"
             "  installing.\n\n### Fixed\n\n- **Tabs:** tab groups are kept.\n")
INVENTORY = patch_licenses.render_table([
    {"patch": "a.patch", "origin": "Thorium (Alex313031, gz83)", "license": "BSD-3-Clause", "evidence": "x"},
    {"patch": "b.patch", "origin": "ungoogled-chromium, Bromite", "license": "BSD-3-Clause AND GPL-3.0",
     "evidence": "y"}])
SOAK_REPORT = f"Soak: 8.00 h, 4168 rounds of 6 tabs\nBuild: {BUILD}\nSOAK: PASSED\n"
BENCH = {"browser": "Thoron", "startup_ms": {"median": 400.0, "spread_pct": 1.0},
         "memory_1_tab_mb": {"median": 180.0, "spread_pct": 1.0},
         "memory_20_tabs_mb": {"median": 900.0, "spread_pct": 1.0},
         "idle_cpu_pct": {"median": 0.4, "spread_pct": 20.0}}
CREDITS = ("# Credits\n\nThorium, ungoogled-chromium and Bromite.\n\n" + contributors.START + "\n"
           + contributors.render_contributors(PEOPLE) + contributors.END + "\n")
REPO_FILES = {"CHANGELOG.md": CHANGELOG, "CREDITS.md": CREDITS, "LICENSE.md": "BSD 3-Clause License\n",
              "NOTICE": "Thoron - third-party notices\n\nLicences: BSD-3-Clause and GPL-3.0.\n",
              "docs/legal/PATCH_LICENSES.md": INVENTORY,
              # the other licence records (L.1): they agree, and no patch is without a licence
              "tools/legal/patch_origins.tsv": "patch\torigin\tlicense\tevidence\n",
              "source/UPSTREAM.json": json.dumps({"withheld": {"other/thorium-default-api-keys.patch": "0" * 40}}),
              "docs/legal/UNLICENSED_PATCHES.md": "# Patches without a licence\n\nNone is left.\n",
              # the upstream audit's lines for the notes (P2.2)
              "docs/security/UPSTREAM_AUDIT_M158.md": "# Audit\n\n## 9. For the release notes\n\n"
                                                      "- Every upstream change was read.\n- Nothing hidden\n"
                                                      "  came in.\n\n## 10. Review\n",
              # the performance baseline (Q.3)
              "docs/perf/baseline.json": json.dumps(BENCH),
              "docs/wiki/Home.md": "# Thoron\n\nSee [Versions](Versions).\n"}
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
        # the portable package's launcher (a window program) and updater (a console program), as built
        (self.out / "thoron_launcher.exe").write_bytes(program(2, tail=b"launcher"))
        (self.out / "thoron_update.exe").write_bytes(program(3, tail=b"updater"))
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

    def test_the_installer_is_found_by_the_name_the_build_gives_it(self):
        (self.f.out / "mini_installer.exe").unlink()
        (self.f.out / "thoron_AVX2_mini_installer.exe").write_bytes(b"avx2 installer")
        (self.f.out / "thoron_AVX2_mini_installer.exe.pdb").write_bytes(b"not an installer")
        (self.f.out / "ThoronSetup.exe").write_bytes(b"not the installer either")
        self.assertEqual(rel.built_installer(self.f.out, "win").name, "thoron_AVX2_mini_installer.exe")
        rel.assemble(self.f.out, self.f.dist, "158.0.8127.3000", "win-x64-avx2", self.f.buildinfo)
        self.assertEqual((self.f.dist / "thoron-158.0.8127.3000-win-x64-avx2-installer.exe").read_bytes(),
                         b"avx2 installer")

    def test_no_installer_or_two_installers_are_refused_before_anything_is_written(self):
        (self.f.out / "thoron_ARM64_installer.exe").write_bytes(b"left by another configuration")
        with self.assertRaisesRegex(rel.ReleaseError, "more than one installer"):
            rel.assemble(self.f.out, self.f.dist, "158.0.8127.3000", "win-x64-avx2", self.f.buildinfo)
        self.assertFalse(self.f.dist.exists())
        for name in ("mini_installer.exe", "thoron_ARM64_installer.exe"):
            (self.f.out / name).unlink()
        with self.assertRaisesRegex(rel.ReleaseError, "no installer"):
            rel.built_installer(self.f.out, "win")
        self.assertIsNone(rel.built_installer(self.f.out, "linux"))

    def test_symbols_are_kept_beside_the_release_folder_never_in_it(self):
        chrome_bin = self.f.out / "Chrome-bin"
        (chrome_bin / "158.0.8127.3000").mkdir(parents=True)
        (chrome_bin / "thoron.exe").write_bytes(b"exe")
        (chrome_bin / "158.0.8127.3000/chrome.dll").write_bytes(b"dll")
        for name in ("chrome.dll.pdb", "thoron.exe.pdb", "mini_installer.exe.pdb", "unit_tests.exe.pdb"):
            (self.f.out / name).write_bytes(name.encode())
        rel.assemble(self.f.out, self.f.dist, "158.0.8127.3000", "win-x64-avx2", self.f.buildinfo)
        kept = rel.keep_symbols(self.f.out, self.f.dist, "158.0.8127.3000", "win-x64-avx2", chrome_bin,
                                ["mini_installer.exe", "ThoronSetup.exe"])
        self.assertEqual(kept, self.f.dist.parent / "dist-symbols" / "win-x64-avx2")
        self.assertEqual(sorted(p.name for p in kept.iterdir()),
                         ["BUILDINFO-158.0.8127.3000-win-x64-avx2.json", "SHA256SUMS", "chrome.dll.pdb",
                          "mini_installer.exe.pdb", "thoron.exe.pdb"])   # a test program's symbols are not kept
        self.assertFalse([p for p in self.f.dist.iterdir() if p.suffix == ".pdb" or p.is_dir()])
        self.assertEqual(rel.checksum_problems(self.f.dist), [])
        self.assertEqual(len((kept / "SHA256SUMS").read_text(encoding="utf-8").splitlines()), 4)
        with self.assertRaisesRegex(rel.ReleaseError, "never overwritten"):
            rel.keep_symbols(self.f.out, self.f.dist, "158.0.8127.3000", "win-x64-avx2", chrome_bin, [])

    def test_no_symbols_kept_when_the_build_wrote_none(self):
        rel.assemble(self.f.out, self.f.dist, "158.0.8127.3000", "win-x64-avx2", self.f.buildinfo)
        self.assertIsNone(rel.keep_symbols(self.f.out, self.f.dist, "158.0.8127.3000", "win-x64-avx2", None,
                                           ["mini_installer.exe"]))
        self.assertFalse((self.f.dist.parent / "dist-symbols").exists())

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
            with self.assertRaisesRegex(rel.ReleaseError, "no one commit for the tag to stand on"):
                rel.publish(dist, "158.0.8127.3000", "KuchiSofts/thoron", run=calls.append)
            self.assertEqual(calls, [])
            (dist / RECORD).write_text(json.dumps({"thoron_commit": COMMIT}), encoding="utf-8")
            rel.publish(dist, "158.0.8127.3000", "KuchiSofts/thoron", run=calls.append)
        cmd = calls[-1]
        self.assertEqual(cmd[:3], ["gh", "release", "create"])
        self.assertIn("--draft", cmd)
        self.assertIn("v158.0.8127.3000", cmd)
        self.assertEqual(cmd[cmd.index("--repo") + 1], "KuchiSofts/thoron")
        self.assertEqual(cmd[cmd.index("--target") + 1], COMMIT)    # the tag stands on the commit that was built


class ReleaseFixture(Fixture):
    """A fake build ready for a whole release, and the repository it is released from. Thoron's own
    version is set, the build wrote its record, its browser folder, the GPL text and Thoron adblock's
    resources; the repository holds the changelog, the credits and the wiki, and one release is tagged.
    The key files are names only: the keys are made here and stay in memory."""

    def __init__(self):
        super().__init__()
        root = Path(self.tmp.name)
        self.repo, self.keys = root / "repo", root / "keys"         # the keys folder is never made
        self.repo.mkdir()
        for name, content in REPO_FILES.items():
            self.repo_file(name, content)
        self.gpl = self.src / rel.GPL_TEXT
        self.gpl.parent.mkdir(parents=True)
        self.gpl.write_text(GPL, encoding="utf-8", newline="\n")
        self.tags = ["v0.1.1"]                                      # what git lists as the repository's tags
        self.people = list(PEOPLE)                                  # what GitHub lists as upstream's contributors
        self.fetches, self.tag_asks = [], []
        self.set_version(BUILD, THORON)
        (self.out / rel.ADBLOCK_RESOURCES).write_text(RESOURCES, encoding="utf-8")
        self.security, self.highlights = root / "security.json", root / "highlights.md"
        self.security.write_text(json.dumps(SECURITY), encoding="utf-8")
        self.highlights.write_text(HIGHLIGHTS + "\n", encoding="utf-8")
        self.private, self.public = ar.keygen()
        self.adblock_private, self.adblock_public = ar.keygen()
        self.key_reads = []

    def repo_file(self, name: str, content: str) -> Path:
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        return path

    def set_version(self, build: str, thoron: str | None):
        """The build tree of that version, with what a build of it writes and the wiki page that names it."""
        major, minor, build_, patch = build.split(".")
        lines = [f"MAJOR={major}", f"MINOR={minor}", f"BUILD={build_}", f"PATCH={patch}", "THORON_REBUILD=0"]
        lines += [f"THORON_VERSION={thoron}"] if thoron else []
        (self.src / "chrome/VERSION").write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.record(source_tag=f"v{thoron}" if thoron else None, chromium_tag=ver.split(build)[0])
        self.browser({"thoron.exe": b"program", f"{build}/chrome.dll": b"dll"})
        if thoron:
            self.repo_file("docs/wiki/Versions.md", f"# Versions\n\nThe newest version is **{thoron}**.\n")

    def record(self, **changes):
        """BUILDINFO as tools/build/buildinfo.py writes it for a release build, with `changes`."""
        info = {"variant": VARIANT, "source_tag": f"v{THORON}", "chromium_tag": "158.0.8127.30",
                "thoron_commit": COMMIT, "thoron_dirty": False}
        info.update(changes)
        self.buildinfo.write_text(json.dumps(info), encoding="utf-8")

    def browser(self, files: dict):
        """The build's browser folder, which becomes the portable package."""
        folder = self.out / rel.CHROME_BIN
        shutil.rmtree(folder, ignore_errors=True)
        for name, data in files.items():
            (folder / name).parent.mkdir(parents=True, exist_ok=True)
            (folder / name).write_bytes(data)

    def main(self, *argv, clock: int = NOW, run=None) -> tuple[int, str, str]:
        """The command line, with the clock set and the outside tools (git, 7-Zip, gh) answered from here.
        A key file is never opened: whoever asks for one gets the key of that name from memory."""
        keys = {"manifest.key": self.private, "adblock.key": self.adblock_private}

        def read_key(path: Path) -> bytes:
            self.key_reads.append(path)
            return keys[path.name]

        def fetch(repo: str) -> list:
            self.fetches.append(repo)
            if isinstance(self.people, Exception):
                raise self.people
            return list(self.people)

        def tags(repo: Path) -> list:
            self.tag_asks.append(repo)
            return list(self.tags)

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                mock.patch.object(mf, "read_private_key", side_effect=read_key), \
                mock.patch.object(rel.time, "time", return_value=float(clock)), \
                mock.patch.object(changelog, "_log", return_value=LOG), \
                mock.patch.object(ver, "release_tags", side_effect=tags), \
                mock.patch.object(contributors, "fetch", side_effect=fetch), \
                mock.patch.object(check_docs, "private_strings_file", return_value=self.repo / "no-such-list"), \
                mock.patch.object(package_audit, "list_archive", return_value=GOOD_LIST):
            code = rel.main([str(arg) for arg in argv], run=run)
        return code, out.getvalue(), err.getvalue()

    def prepare(self, *more, dist: Path | None = None, previous: str = "156.0.8078.28", bench: dict | None = None,
                soak: str | None = None, **kw):
        bench_file = self.repo.parent / "bench.json"
        bench_file.write_text(json.dumps(bench or BENCH), encoding="utf-8")
        soak_file = self.repo.parent / "soak.txt"
        soak_file.write_text(soak if soak is not None else SOAK_REPORT, encoding="utf-8")
        return self.main("prepare", "--src", self.src, "--out", self.out, "--platform", "win", "--variant", VARIANT,
                         "--previous", previous, "--buildinfo", self.buildinfo, "--dist", dist or self.dist,
                         "--repo", self.repo, "--since", "v0.1.1", "--chromium-old", "156.0.8078.80",
                         "--bench", bench_file, "--soak", soak_file, *more, **kw)

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
        self.assertIn("- **Tabs:** tab groups are kept.", notes)

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
        self.assertIn("win-x64-avx10 is not a variant a manifest can name", problems(variant="win-x64-avx10")[0])
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
        self.assertEqual(self.names(), [RECORD, "NOTES.md", "SHA256SUMS", LICENCES, INSTALLER, PORTABLE,
                                        "update.json", "update.json.sig"])
        self.assertIn("update.json is signed: Thoron 0.1.2 (build 158.0.8127.3000), channel stable, good for "
                      "30 days; publish it with --version 0.1.2", out)
        self.assertIn(f"release {BUILD}: 7 file(s) in ", out)
        raw, signature = self.manifest()
        data = mf.verify(raw, signature, self.f.public, allowed_hosts=HOSTS)
        installer, portable = (self.f.dist / INSTALLER).read_bytes(), (self.f.dist / PORTABLE).read_bytes()
        self.assertEqual(installer, b"installer bytes")
        self.assertEqual(data, {
            "schema": 1, "channel": "stable", "serial": 2026120100,
            "published": "2026-12-01T12:00:00Z", "expires": "2026-12-31T12:00:00Z",
            "version": BUILD, "thoron_version": THORON, "chromium_version": "158.0.8127.30",
            "critical": False, "min_updater_version": BUILD,
            "packages": {VARIANT: {
                "installed": {"full": {"url": INSTALLER_URL, "size": len(installer),
                                       "sha256": hashlib.sha256(installer).hexdigest()}},
                "portable": {"full": {"url": PORTABLE_URL, "size": len(portable),
                                      "sha256": hashlib.sha256(portable).hexdigest()}}}}})
        sums = (self.f.dist / "SHA256SUMS").read_text(encoding="utf-8")
        for kind, name in (("installed", INSTALLER), ("portable", PORTABLE)):
            self.assertIn(f"{data['packages'][VARIANT][kind]['full']['sha256']}  {name}\n", sums)
        self.assertEqual([line.split("  ")[1] for line in sums.splitlines()], [RECORD, LICENCES, INSTALLER, PORTABLE])
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
        carried = copy("158.0.8127.2900", kind="portable")          # a portable copy gets the portable package
        self.assertEqual((carried.outcome, carried.full["url"]), (mf.UPDATE, PORTABLE_URL))

    def test_a_critical_release_says_so_in_its_manifest(self):
        self.prepared("--critical", "--manifest-days", "14", "--channel", "stable")
        data = mf.verify(*self.manifest(), self.f.public, allowed_hosts=HOSTS)
        self.assertEqual((data["critical"], data["expires"]), (True, "2026-12-15T12:00:00Z"))

    def test_publish_checks_the_folder_and_makes_a_draft_of_it(self):
        """The dry run from a fake build to the draft command, with every step of prepare on the way."""
        dist = self.prepared("--security", self.f.security, "--highlights", self.f.highlights)
        self.assertEqual(self.f.fetches, ["Alex313031/thorium"])    # the contributors were made again
        notes = (dist / "NOTES.md").read_text(encoding="utf-8")
        order = [notes.index(part) for part in (
            "# Thoron 0.1.2\n", "Thoron 0.1.2 (build 158.0.8127.3000) is based on Chromium 158.0.8127.30",
            "## Highlights", "### Security fixes", "## Thoron changes\n\n### Added\n\n- **Updates:** Thoron updates "
            "itself from inside.\n- **Portable:** a package that runs without installing.\n\n### Fixed\n\n- **Tabs:** "
            "tab groups are kept.\n", f"| `{PORTABLE}` |", "## Source and licences\n\nThe source of this release is "
            f"the tag `v0.1.2` of this repository (commit `{COMMIT}`), applied to Chromium at its tag `158.0.8127.30`",
            f"the other licence texts are in `{LICENCES}`", "## Credits")]
        self.assertEqual(order, sorted(order))
        self.assertNotIn("keep tab groups", notes)                  # a commit's subject is no line of the notes
        with zipfile.ZipFile(dist / LICENCES) as bundle:
            self.assertEqual(bundle.read("licenses/GPL-3.0.txt").decode("utf-8"), GPL)
        with zipfile.ZipFile(dist / PORTABLE) as package:
            self.assertIn(f"ThoronPortable/Application/{BUILD}/thoron.exe", package.namelist())
            self.assertIn("ThoronPortable/Thoron.exe", package.namelist())
        self.assertEqual(rel.publish_problems(dist, THORON, GH_REPO, self.f.public, NOW), [])
        calls = []
        with mock.patch.object(rel.subprocess, "run", side_effect=AssertionError("publish ran a program")):
            code, out, err = self.f.publish(run=calls.append)
        self.assertEqual(code, 0, out + err)
        self.assertIn("draft release v0.1.2 created", out)
        self.assertEqual(len(calls), 1)                             # the draft, and nothing else
        cmd = calls[0]
        self.assertEqual(cmd[:6], ["gh", "release", "create", "v0.1.2", "--draft", "--repo"])
        self.assertEqual(cmd[cmd.index("--target") + 1], COMMIT)
        self.assertEqual(cmd[cmd.index("--title") + 1], "Thoron 0.1.2")
        self.assertEqual(cmd[cmd.index("--notes-file") + 1], str(dist / "NOTES.md"))
        uploaded = cmd[cmd.index("--notes-file") + 2:]
        self.assertEqual(uploaded, [str(dist / name) for name in (
            RECORD, "SHA256SUMS", "SHA256SUMS.minisig", LICENCES, INSTALLER, PORTABLE, "update.json",
            "update.json.sig")])
        self.assertIn("release: the wiki is not published from here.", out)
        self.assertTrue(out.endswith("    py -3 -I tools/docs/publish_wiki.py --repo KuchiSofts/thoron --dry-run\n"
                                     "    py -3 -I tools/docs/publish_wiki.py --repo KuchiSofts/thoron\n"))

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
        self.assertEqual(self.names(), [RECORD, "NOTES.md", "SHA256SUMS", LICENCES, INSTALLER, PORTABLE])
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
        self.f.tags.append(f"v{THORON}")                            # the first draft was published
        self.f.set_version(NEXT_BUILD, NEXT_THORON)
        code, out, err = self.f.prepare(*self.f.with_manifest("--previous-manifest", first / "update.json"),
                                        dist=second, previous=BUILD, clock=NOW + 3600,
                                        soak=SOAK_REPORT.replace(BUILD, NEXT_BUILD))
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


class GateTestCase(ReleaseTestCase):
    """A gate of prepare: what it refuses is said, and nothing is packaged."""

    def refused(self, says: str, *argv, **kw):
        code, out, err = self.f.prepare(*argv, **kw)
        self.assertEqual(code, 1, out + err)
        self.assertIn(f"release: {says}", err)
        self.assertIn("nothing was packaged", out)
        self.assert_nothing_packaged()

    def passes(self, *argv):
        code, out, err = self.f.prepare(*argv)
        self.assertEqual(code, 0, out + err)
        shutil.rmtree(self.f.dist)


class VersionGateTests(GateTestCase):
    """P2.24: a release gets the next Thoron version after the newest release tag, and no other."""

    def test_the_next_version_after_the_last_release_tag_passes(self):
        self.passes()                                               # 0.1.2 after v0.1.1
        self.f.tags += ["adblock-resources", "v158.0.8127.3000", "vNext"]       # no releases
        self.passes()
        self.f.set_version(BUILD, "0.2.0")                          # the next minor version
        self.passes()

    def test_a_version_that_is_not_the_next_one_is_refused(self):
        for thoron, tags, says in (
                ("0.1.3", ["v0.1.1"], "Thoron 0.1.3 is not the next version: after the last release 0.1.1 comes "
                                      "0.1.2 or 0.2.0"),
                ("0.1.2", ["v0.1.1", "v0.1.2"], "Thoron 0.1.2 is not the next version: after the last release 0.1.2 "
                                                "comes 0.1.3 or 0.2.0"),
                ("0.1.2", ["v0.1.2", "v0.1.10", "v0.1.9"], "Thoron 0.1.2 is not the next version: after the last "
                                                           "release 0.1.10 comes 0.1.11 or 0.2.0"),
                ("0.2.1", ["v0.1.1"], "Thoron 0.2.1 is not the next version"),
                ("1.0.0", ["v0.1.1"], "Thoron 1.0.0 is not the next version")):
            with self.subTest(thoron=thoron, tags=tags):
                self.f.set_version(BUILD, thoron)
                self.f.tags = tags
                self.refused(f"Thoron version: {says}")

    def test_with_no_release_tag_the_first_version_is_0_1_1(self):
        self.f.tags = []
        self.refused("Thoron version: Thoron 0.1.2 is not the next version: no release is tagged yet, and the first "
                     "is 0.1.1")
        self.f.set_version(BUILD, "0.1.1")
        self.passes()

    def test_a_build_without_thorons_version_is_refused(self):
        self.f.set_version(BUILD, None)
        self.refused("Thoron version: chrome/VERSION has no THORON_VERSION: run tools/release/version.py thoron first")

    def test_the_tags_asked_for_are_those_of_the_repository_given(self):
        self.passes()
        self.assertEqual(self.f.tag_asks, [self.f.repo])


class SourceTests(GateTestCase):
    """L.2: no release without the source tag and the Chromium tag in BUILDINFO and the text of the GPL."""

    def test_a_build_record_that_names_its_source_has_no_problem(self):
        info = json.loads(self.f.buildinfo.read_text(encoding="utf-8"))
        self.assertEqual(rel.source_problems(info, THORON, "158.0.8127.30"), [])

    def test_a_build_record_without_its_source_is_refused(self):
        for name, changes, says in (
                ("no source tag", {"source_tag": None}, "BUILDINFO: no source tag (source_tag)"),
                ("another release's tag", {"source_tag": "v0.1.1"},
                 "BUILDINFO: the source tag is v0.1.1, and the build is Thoron 0.1.2 (v0.1.2)"),
                ("no Chromium tag", {"chromium_tag": ""}, "BUILDINFO: no Chromium tag (chromium_tag)"),
                ("the build number for Chromium's tag", {"chromium_tag": BUILD},
                 "BUILDINFO: the Chromium tag is 158.0.8127.3000, and the build is made of Chromium 158.0.8127.30"),
                ("no commit", {"thoron_commit": None}, "BUILDINFO: no commit (thoron_commit) for the source tag"),
                ("a short commit", {"thoron_commit": COMMIT[:12]}, "BUILDINFO: no commit (thoron_commit)"),
                ("uncommitted changes", {"thoron_dirty": True}, "BUILDINFO: the build was not made from a tree with "
                                                                "nothing uncommitted (thoron_dirty)")):
            with self.subTest(name):
                self.f.record(**changes)
                self.refused(says)

    def test_a_record_as_it_was_written_before_names_nothing_and_is_refused(self):
        self.f.buildinfo.write_text('{"variant": "win-x64-avx2", "chromium_version": "158.0.8127.3000"}',
                                    encoding="utf-8")
        code, _, err = self.f.prepare()
        self.assertEqual(code, 1)
        for says in ("no source tag", "no Chromium tag", "no commit", "the build was not made from a tree with "
                                                                       "nothing uncommitted"):
            self.assertIn(f"release: BUILDINFO: {says}", err)
        self.f.buildinfo.write_text("not a record", encoding="utf-8")
        code, _, err = self.f.prepare()
        self.assertEqual(code, 2)
        self.assertIn("BUILDINFO.json is not JSON", err)
        self.assert_nothing_packaged()

    def test_a_build_tree_without_the_whole_gpl_text_is_refused(self):
        self.f.gpl.write_text(GPL.replace("END OF TERMS AND CONDITIONS", ""), encoding="utf-8")
        self.refused("licences: third_party/thoron_notices/LICENSE.GPL-3.0 is not the whole GNU GPL version 3: it "
                     "lacks 'END OF TERMS AND CONDITIONS'")
        self.f.gpl.write_text("BSD 3-Clause License\n", encoding="utf-8")
        self.refused("licences: third_party/thoron_notices/LICENSE.GPL-3.0 is not the whole GNU GPL version 3")
        self.f.gpl.unlink()
        self.refused("licences: the build tree has no third_party/thoron_notices/LICENSE.GPL-3.0")

    def test_a_licence_file_missing_from_the_repository_is_refused(self):
        (self.f.repo / "LICENSE.md").unlink()
        self.refused("licences: LICENSE.md is not in the repository; the licence bundle holds it")

    def test_the_release_carries_the_licence_bundle_with_the_gpl_text(self):
        (self.f.repo / "NOTICE").write_bytes(b"Thoron - third-party notices\r\n\r\nBSD-3-Clause and GPL-3.0.\r\n")
        self.assertEqual(self.f.prepare()[0], 0)
        with zipfile.ZipFile(self.f.dist / LICENCES) as bundle:
            self.assertEqual(bundle.namelist(), ["licenses/CREDITS.md", "licenses/GPL-3.0.txt", "licenses/LICENSE.md",
                                                 "licenses/NOTICE", "licenses/PATCH_LICENSES.md"])
            self.assertEqual(bundle.read("licenses/GPL-3.0.txt"), self.f.gpl.read_bytes())
            self.assertEqual(bundle.read("licenses/NOTICE"),        # the repository's line ends, not the checkout's
                             b"Thoron - third-party notices\n\nBSD-3-Clause and GPL-3.0.\n")
            self.assertEqual(bundle.read("licenses/PATCH_LICENSES.md").decode("utf-8"), INVENTORY)
        digest = hashlib.sha256((self.f.dist / LICENCES).read_bytes()).hexdigest()
        self.assertIn(f"{digest}  {LICENCES}\n", (self.f.dist / "SHA256SUMS").read_text(encoding="utf-8"))
        self.assertEqual(rel.licence_bundle_problems(self.f.dist), [])

    def test_the_same_texts_give_the_same_bundle(self):
        texts, problems = rel.licence_texts(self.f.repo, self.f.src)
        self.assertEqual(problems, [])
        first = rel.write_licence_bundle(Path(self.f.tmp.name) / "a.zip", texts)
        second = rel.write_licence_bundle(Path(self.f.tmp.name) / "b.zip", dict(reversed(texts.items())))
        self.assertEqual(first.read_bytes(), second.read_bytes())
        with self.assertRaises(FileExistsError):                    # never over another file
            rel.write_licence_bundle(first, texts)

    def test_publish_refuses_a_folder_whose_source_is_not_the_drafts_tag(self):
        dist = self.f.dist
        self.assertEqual(self.f.prepare(*self.f.with_manifest())[0], 0)
        self.f.minisign_stand_in()
        self.assertEqual(rel.source_tag_problems(dist, "v0.1.2"), [])
        self.assertEqual(rel.source_tag_problems(dist, "v0.1.3"),
                         [f"{RECORD} names the source tag v0.1.2, and the draft would be tagged v0.1.3"])
        calls = []
        code, _, err = self.f.publish(version="0.1.3", run=calls.append)
        self.assertEqual((code, calls), (1, []))
        self.assertIn(f"release: source: {RECORD} names the source tag v0.1.2, and the draft would be tagged v0.1.3",
                      err)
        (dist / RECORD).unlink()
        self.assertEqual(rel.source_tag_problems(dist, "v0.1.2"),
                         ["no build record (BUILDINFO-*.json) in the folder names the source of the release"])

    def test_publish_refuses_a_folder_without_the_gpl_text(self):
        dist = self.f.dist
        self.assertEqual(self.f.prepare(*self.f.with_manifest())[0], 0)
        self.f.minisign_stand_in()
        bundle = dist / LICENCES
        bundle.unlink()
        calls = []
        code, _, err = self.f.publish(run=calls.append)
        self.assertEqual((code, calls), (1, []))
        self.assertIn("release: licences: no licence bundle (thoron-<version>-licenses.zip) in the folder", err)
        rel.write_licence_bundle(bundle, {"NOTICE": b"notices\n"})
        self.assertEqual(rel.licence_bundle_problems(dist), [f"{LICENCES} holds no licenses/GPL-3.0.txt"])
        bundle.unlink()
        rel.write_licence_bundle(bundle, {"GPL-3.0.txt": b"GNU GENERAL PUBLIC LICENSE\n"})
        self.assertIn(f"GPL-3.0.txt in {LICENCES} is not the whole GNU GPL version 3",
                      rel.licence_bundle_problems(dist)[0])


class PortableStepTests(GateTestCase):
    """P2.8, P3.12: prepare calls tools/release/portable.py with the build's launcher and updater, and the
    release holds the portable .zip."""

    def test_the_release_holds_the_portable_zip_and_no_unpacked_package(self):
        self.assertEqual(self.f.prepare()[0], 0)
        self.assertIn(PORTABLE, self.names())
        self.assertFalse([p for p in self.f.dist.iterdir() if p.is_dir()])
        with zipfile.ZipFile(self.f.dist / PORTABLE) as package:
            self.assertEqual(package.namelist(), [
                f"ThoronPortable/Application/{BUILD}/{BUILD}/chrome.dll",
                f"ThoronPortable/Application/{BUILD}/thoron.exe",
                f"ThoronPortable/Application/{BUILD}/thoron_update.exe", "ThoronPortable/Application/current", "ThoronPortable/README.txt", "ThoronPortable/Thoron.exe",
                "ThoronPortable/variant"])
            self.assertEqual(package.read(f"ThoronPortable/Application/{BUILD}/thoron.exe"), b"program")
            self.assertEqual(package.read("ThoronPortable/Thoron.exe"),
                             (self.f.out / "thoron_launcher.exe").read_bytes())
            self.assertEqual(package.read(f"ThoronPortable/Application/{BUILD}/thoron_update.exe"),
                             (self.f.out / "thoron_update.exe").read_bytes())
            self.assertEqual(package.read("ThoronPortable/Application/current"), f"{BUILD}\n".encode("ascii"))
            self.assertEqual(package.read("ThoronPortable/variant"), f"{VARIANT}\n".encode("ascii"))
        self.assertEqual(rel.portable.audit(self.f.dist / PORTABLE), [])
        digest = hashlib.sha256((self.f.dist / PORTABLE).read_bytes()).hexdigest()
        self.assertIn(f"{digest}  {PORTABLE}\n", (self.f.dist / "SHA256SUMS").read_text(encoding="utf-8"))
        self.assertEqual(rel.package_files(self.f.dist, BUILD, VARIANT),
                         {"installed": self.f.dist / INSTALLER, "portable": self.f.dist / PORTABLE})
        self.assertEqual(sorted(p.name for p in (self.f.out / rel.CHROME_BIN).iterdir()), [BUILD, "thoron.exe"])

    def test_a_launcher_or_an_updater_that_may_not_be_packaged_is_refused(self):
        launcher, updater = self.f.out / "thoron_launcher.exe", self.f.out / "thoron_update.exe"
        good = launcher.read_bytes(), updater.read_bytes()
        for name, launcher_bytes, updater_bytes, says in (
                ("a console launcher", good[1], good[1], "portable package: the launcher thoron_launcher.exe must "
                                                         "be a window program"),
                ("a 32-bit launcher", program(2, machine=0x14C), good[1], "portable package: the launcher "
                                                                          "thoron_launcher.exe is not a program "
                                                                          "for x64"),
                ("a script for an updater", good[0], b"@echo off\r\n", "portable package: the updater "
                                                                       "thoron_update.exe is not a Windows "
                                                                       "program")):
            with self.subTest(name):
                launcher.write_bytes(launcher_bytes)
                updater.write_bytes(updater_bytes)
                self.refused(says)
        launcher.write_bytes(good[0])
        updater.unlink()
        self.refused("portable package: the updater thoron_update.exe is missing (--launcher and --updater name them)")

    def test_the_launcher_and_the_updater_can_be_named(self):
        elsewhere = Path(self.f.tmp.name) / "parts"
        elsewhere.mkdir()
        for name in ("thoron_launcher.exe", "thoron_update.exe"):
            shutil.move(self.f.out / name, elsewhere / f"signed {name}")
        self.refused("portable package: the launcher thoron_launcher.exe is missing")
        self.assertEqual(self.f.prepare("--launcher", elsewhere / "signed thoron_launcher.exe",
                                        "--updater", elsewhere / "signed thoron_update.exe")[0], 0)
        with zipfile.ZipFile(self.f.dist / PORTABLE) as package:
            self.assertEqual(package.read("ThoronPortable/Thoron.exe"),
                             (elsewhere / "signed thoron_launcher.exe").read_bytes())

    def test_a_variant_the_launcher_does_not_know_gets_no_portable_package(self):
        self.refused("portable package: the variant win-x64-avx512 has no portable package: its launcher knows "
                     "win-x64-avx2 and win-x64-sse4", "--variant", "win-x64-avx512")

    def test_the_variant_must_be_the_one_the_build_was_made_for(self):
        self.f.record(variant="win-x64-sse4")
        self.refused("portable package: the build record says the build is for win-x64-sse4, and the release is "
                     "for win-x64-avx2: the package would tell its launcher the wrong processors")

    def test_a_browser_folder_that_already_holds_an_updater_is_refused(self):
        self.f.browser({"thoron.exe": b"program", f"{BUILD}/chrome.dll": b"dll", "thoron_update.exe": b"x"})
        self.refused("portable package: the browser folder already holds thoron_update.exe")

    def test_a_browser_folder_that_may_not_be_packaged_is_refused(self):
        good = {"thoron.exe": b"program", f"{BUILD}/chrome.dll": b"dll"}
        for name, files, says in (
                ("a profile", {**good, "User Data/Default/Preferences": b"{}"},
                 "portable package: profile data or a leftover of a used browser: User Data/Default/Preferences"),
                ("Widevine", {**good, f"{BUILD}/WidevineCdm/manifest.json": b"{}"},
                 "portable package: package audit: Widevine must not be bundled"),
                ("no program", {f"{BUILD}/chrome.dll": b"dll"}, "portable package: package audit: the program "
                                                                "thoron.exe is missing"),
                ("another build", {"thoron.exe": b"program", f"{NEXT_BUILD}/chrome.dll": b"dll"},
                 f"portable package: the browser folder holds version {NEXT_BUILD}, and the build is {BUILD}")):
            with self.subTest(name):
                self.f.browser(files)
                self.refused(says)
        shutil.rmtree(self.f.out / rel.CHROME_BIN)
        self.refused("portable package: the browser folder Chrome-bin is not there (--chrome-bin names it)")

    def test_the_browser_folder_can_be_named(self):
        elsewhere = Path(self.f.tmp.name) / "staging" / "Chrome-bin"
        elsewhere.parent.mkdir()
        shutil.move(self.f.out / rel.CHROME_BIN, elsewhere)
        self.assertEqual(self.f.prepare("--chrome-bin", elsewhere)[0], 0)
        self.assertIn(PORTABLE, self.names())

    def test_a_package_that_fails_while_it_is_made_stops_prepare_and_the_folder_is_called_incomplete(self):
        with mock.patch.object(rel.portable, "build", side_effect=rel.portable.PortableError("the .zip does not hold "
                                                                                             "the package's files")):
            code, _, err = self.f.prepare()
        self.assertEqual(code, 2)
        self.assertIn("release: portable package: the .zip does not hold the package's files", err)
        self.assertIn("is incomplete; remove it before running prepare again", err)
        self.assertNotIn("SHA256SUMS", self.names())

    def test_a_linux_release_folder_gets_no_windows_package(self):
        files = rel.assemble(self.f.out, self.f.dist, BUILD, "linux-x64-avx2", self.f.buildinfo,
                             self.f.out / rel.CHROME_BIN)
        self.assertEqual([p.name for p in files], [f"BUILDINFO-{BUILD}-linux-x64-avx2.json", "SHA256SUMS"])


class CreditsTests(GateTestCase):
    """L.3: the contributors are made again, and CREDITS.md and NOTICE must be current; nothing is rewritten."""

    def test_current_files_have_no_problem(self):
        self.assertEqual(rel.credits_problems(self.f.repo, PEOPLE), [])
        credits = self.f.repo / "CREDITS.md"
        credits.write_bytes(credits.read_bytes().replace(b"\n", b"\r\n"))      # a Windows checkout
        self.assertEqual(rel.credits_problems(self.f.repo, PEOPLE), [])

    def test_a_contributor_list_that_is_out_of_date_stops_the_release_and_is_not_rewritten(self):
        before = (self.f.repo / "CREDITS.md").read_bytes()
        for name, people in (
                ("one more commit", [dict(PEOPLE[0], contributions=4906)] + PEOPLE[1:]),
                ("a new contributor", PEOPLE + [{"type": "User", "login": "newcomer", "contributions": 2}]),
                ("one gone", PEOPLE[:2])):
            with self.subTest(name):
                self.f.people = people
                self.refused("credits: CREDITS.md: the list of upstream contributors is out of date: run "
                             "tools/credits/contributors.py and commit the result")
                self.assertEqual((self.f.repo / "CREDITS.md").read_bytes(), before)
        self.assertEqual(self.f.fetches, ["Alex313031/thorium"] * 3)

    def test_no_email_is_read_into_the_list(self):
        made = contributors.render_contributors(PEOPLE)
        self.assertIn("- Someone Else (1 commit)", made)
        self.assertNotIn("@example.com", made)

    def test_a_saved_list_is_used_instead_of_asking_github(self):
        saved = Path(self.f.tmp.name) / "contributors.json"
        saved.write_text(json.dumps(PEOPLE), encoding="utf-8")
        self.passes("--contributors", saved)
        self.assertEqual(self.f.fetches, [])
        saved.write_text(json.dumps(PEOPLE[:2]), encoding="utf-8")
        self.refused("credits: CREDITS.md: the list of upstream contributors is out of date", "--contributors", saved)
        for content, says in (("{}", "contributors.json is not a list of contributors"),
                              ("[", "contributors.json is not JSON")):
            saved.write_text(content, encoding="utf-8")
            code, _, err = self.f.prepare("--contributors", saved)
            self.assertEqual(code, 2)
            self.assertIn(says, err)
        self.assertEqual(self.f.fetches, [])
        self.assert_nothing_packaged()

    def test_when_github_cannot_be_asked_prepare_says_how_to_go_on(self):
        self.f.people = FileNotFoundError("gh")
        code, _, err = self.f.prepare()
        self.assertEqual(code, 2)
        self.assertIn("the contributors of Alex313031/thorium could not be read from GitHub with gh "
                      "(FileNotFoundError); --contributors takes a saved list instead", err)
        self.assert_nothing_packaged()

    def test_credits_without_the_markers_are_a_problem(self):
        self.f.repo_file("CREDITS.md", "# Credits\n\nThorium, ungoogled-chromium and Bromite.\n")
        self.assertEqual(rel.credits_problems(self.f.repo, PEOPLE),
                         ["CREDITS.md: markers <!-- contributors:start --> ... <!-- contributors:end --> not found"])

    def test_every_origin_and_licence_of_the_patch_inventory_is_credited_and_named(self):
        rows = patch_licenses.read_table(INVENTORY) + [
            {"patch": "c.patch", "origin": "Thorium (Alex313031, gz83); idea from Iridium", "license": "MIT",
             "evidence": "z"}]
        self.f.repo_file("docs/legal/PATCH_LICENSES.md", patch_licenses.render_table(rows))
        self.assertEqual(rel.credits_problems(self.f.repo, PEOPLE), [
            "CREDITS.md does not credit Iridium, an origin in docs/legal/PATCH_LICENSES.md",
            "NOTICE does not name the licence MIT, which docs/legal/PATCH_LICENSES.md lists"])
        self.refused("credits: CREDITS.md does not credit Iridium, an origin in docs/legal/PATCH_LICENSES.md")
        self.f.repo_file("CREDITS.md", CREDITS + "\nIridium.\n")
        self.f.repo_file("NOTICE", "Licences: BSD-3-Clause, GPL-3.0 and MIT.\n")
        self.assertEqual(rel.credits_problems(self.f.repo, PEOPLE), [])

    def test_the_audit_summary_is_read_for_the_notes(self):
        self.assertEqual(changelog.audit_lines(self.f.repo),
                         ("UPSTREAM_AUDIT_M158.md", ["Every upstream change was read.", "Nothing hidden came in."]))
        # the commits of the repository do not matter here
        with mock.patch.object(changelog, "_log", return_value=[]):
            notes = changelog.render(BUILD, "156.0.8078.80", "158.0.8127.30", self.f.repo, "v0.1.1",
                                     audit=changelog.audit_lines(self.f.repo))
        self.assertIn("## Upstream audit", notes)
        self.assertIn("- Nothing hidden came in.", notes)
        (self.f.repo / "docs/security/UPSTREAM_AUDIT_M158.md").unlink()
        self.assertEqual(changelog.audit_lines(self.f.repo), (None, []))

    def test_an_injected_regression_blocks_a_dry_run_release_until_it_is_explained(self):
        slower = dict(BENCH, startup_ms={"median": 480.0, "spread_pct": 1.0})
        found = rel.performance_problems(self.f.repo, None, THORON)
        self.assertEqual(len(found), 1)
        self.assertIn("no benchmark", found[0])
        bench = self.f.repo.parent / "slower.json"
        bench.write_text(json.dumps(slower), encoding="utf-8")
        found = rel.performance_problems(self.f.repo, bench, THORON)
        self.assertEqual(len(found), 1)
        self.assertIn("startup_ms rose 20.0 %", found[0])
        self.f.repo_file("docs/perf/EXPLAINED.md",
                         f"# Explained\n\n- {THORON} startup_ms: the lists load at start; 80 ms, accepted.\n")
        self.assertEqual(rel.performance_problems(self.f.repo, bench, THORON), [])

    def test_a_patch_without_a_licence_stops_a_release(self):
        self.assertEqual(rel.licence_record_problems(self.f.repo), [])
        rows = patch_licenses.read_table(INVENTORY) + [
            {"patch": "c.patch", "origin": "Someone", "license": patch_licenses.NOT_STATED, "evidence": "z"}]
        self.f.repo_file("docs/legal/PATCH_LICENSES.md", patch_licenses.render_table(rows))
        found = rel.licence_record_problems(self.f.repo)
        self.assertTrue(found)
        self.assertTrue(any("c.patch" in p for p in found), found)

    def test_licence_records_that_cannot_be_read_stop_a_release(self):
        (self.f.repo / "tools/legal/patch_origins.tsv").unlink()
        self.assertEqual(rel.licence_record_problems(self.f.repo),
                         ["tools/legal/patch_origins.tsv is not in the repository"])

    def test_missing_files_are_problems(self):
        for name in ("CREDITS.md", "NOTICE", "docs/legal/PATCH_LICENSES.md"):
            (self.f.repo / name).unlink()
        self.assertEqual(rel.credits_problems(self.f.repo, PEOPLE),
                         [f"{name} is not in the repository" for name in ("CREDITS.md", "NOTICE",
                                                                          "docs/legal/PATCH_LICENSES.md")])
        self.f.repo_file("docs/legal/PATCH_LICENSES.md", "# Patch licence inventory\n")
        self.assertIn("docs/legal/PATCH_LICENSES.md lists no patch", rel.credits_problems(self.f.repo, PEOPLE))


class ChangelogStepTests(GateTestCase):
    """D.10, D.4: the notes' changes are the lines of the short changelog, and a release has some."""

    def notes(self) -> str:
        return (self.f.dist / "NOTES.md").read_text(encoding="utf-8")

    def test_what_waits_under_unreleased_becomes_the_notes(self):
        code, out, err = self.f.prepare()
        self.assertEqual(code, 0, out + err)
        self.assertIn("release: the notes list the changes under [Unreleased] of CHANGELOG.md", out)
        self.assertIn("## Thoron changes\n\n### Added\n\n- **Updates:** Thoron updates itself from inside.\n"
                      "- **Portable:** a package that runs without installing.\n\n### Fixed\n\n"
                      "- **Tabs:** tab groups are kept.\n\n## Upstream Thorium", self.notes())
        self.assertTrue(self.notes().startswith("# Thoron 0.1.2\n\nThoron 0.1.2 (build 158.0.8127.3000) is based on "
                                                "Chromium 158.0.8127.30"))

    def test_the_section_of_the_version_is_taken_when_there_is_one(self):
        self.f.repo_file("CHANGELOG.md", "# Changelog\n\n## [Unreleased]\n\n### Added\n\n- **Later:** not yet.\n\n"
                         "## [0.1.2] - 2026-12-01\n\nBuilt on Chromium 158.0.8127.30.\n\n### Security\n\n"
                         "- **Updates:** the manifest is signed.\n\n## [0.1.1] - 2026-11-20\n\n### Added\n\n"
                         "- **First:** the first release.\n")
        code, out, err = self.f.prepare()
        self.assertEqual(code, 0, out + err)
        self.assertIn("the notes list the changes under [0.1.2] of CHANGELOG.md", out)
        self.assertIn("## Thoron changes\n\n### Security\n\n- **Updates:** the manifest is signed.\n\n## Upstream",
                      self.notes())
        for other in ("not yet", "the first release"):
            self.assertNotIn(other, self.notes())

    def test_a_release_without_a_line_in_the_changelog_is_refused(self):
        for name, text, says in (
                ("nothing waits", "# Changelog\n\n## [Unreleased]\n\n## [0.1.1] - 2026-11-20\n\n### Added\n\n- x\n",
                 "changelog: the changelog lists no change under [Unreleased]"),
                ("headings only", "# Changelog\n\n## [Unreleased]\n\n### Added\n\n### Fixed\n",
                 "changelog: the changelog lists no change under [Unreleased]"),
                ("its own section is empty", "# Changelog\n\n## [Unreleased]\n\n### Added\n\n- x\n\n## [0.1.2] - "
                 "2026-12-01\n", "changelog: the changelog lists no change under [0.1.2]"),
                ("no section to take", "# Changelog\n\n## [0.1.1] - 2026-11-20\n\n### Added\n\n- x\n",
                 "changelog: the changelog has no [Unreleased] section")):
            with self.subTest(name):
                self.f.repo_file("CHANGELOG.md", text)
                self.refused(says)
        (self.f.repo / "CHANGELOG.md").unlink()
        self.refused("changelog: CHANGELOG.md is not in the repository")

    def test_a_changelog_that_is_not_in_its_short_form_is_refused(self):
        for name, text, says in (
                ("a paragraph for a change", CHANGELOG + "\nThis one took a while to get right.\n",
                 "line 17: not a change (`- text`, one line per change) and not a section heading"),
                ("a section of its own", CHANGELOG.replace("### Fixed", "### Bug fixes"),
                 "line 13: `### Bug fixes`: the sections are Added, Changed, Fixed, Removed, Security"),
                ("a change under no section", CHANGELOG.replace("### Added\n\n", ""),
                 "line 7: a change outside Added, Changed, Fixed, Removed, Security"),
                ("a list inside a change", CHANGELOG.replace("  installing.", "  - installing."),
                 "line 11: not a change (`- text`, one line per change) and not a section heading")):
            with self.subTest(name):
                self.f.repo_file("CHANGELOG.md", text)
                self.refused(f"changelog: the changelog is not in its short form: {says}")


class WikiStepTests(GateTestCase):
    """D.9: the wiki pages are linted and name the version; publishing them is never done from here."""

    def test_the_wiki_of_the_tree_has_no_problem(self):
        self.assertEqual(rel.wiki_problems(self.f.repo, THORON), [])

    def test_pages_that_fail_the_linter_stop_the_release(self):
        dash = chr(0x2014)
        for name, page, text, says in (
                ("a link to no page", "Home.md", "# Thoron\n\n[Install](Install)\n",
                 "wiki: docs/wiki/Home.md:3: no wiki page -> Install"),
                ("a link to no heading", "Home.md", "# Thoron\n\n[Versions](Versions#history)\n",
                 "wiki: docs/wiki/Home.md:3: broken anchor -> Versions#history"),
                ("a long dash", "Home.md", f"# Thoron\n\nFast {dash} and private.\n",
                 "wiki: docs/wiki/Home.md:3: long dash, use '-' (house style)"),
                ("a path of one PC", "Install.md", "# Install\n\nUnpack it to C:\\Users\\someone\\Thoron.\n",  # privacy-check: allow
                 "wiki: docs/wiki/Install.md:3: private data (user directory path)")):
            with self.subTest(name):
                path = self.f.repo / "docs/wiki" / page
                before = path.read_bytes() if path.exists() else None
                self.f.repo_file(f"docs/wiki/{page}", text)
                self.refused(says)
                if before is None:
                    path.unlink()
                else:
                    path.write_bytes(before)

    def test_a_wiki_without_its_home_page_or_its_folder_stops_the_release(self):
        (self.f.repo / "docs/wiki/Home.md").unlink()
        self.refused("wiki: docs/wiki: no Home.md; a wiki needs its home page")
        shutil.rmtree(self.f.repo / "docs/wiki")
        self.refused("wiki: docs/wiki is not in the repository")

    def test_the_wiki_names_the_version_being_released(self):
        for text in ("# Versions\n\nThe newest version is **0.1.1**.\n", "# Versions\n\nNow 0.1.20 and 10.1.2.\n"):
            self.f.repo_file("docs/wiki/Versions.md", text)
            self.refused("wiki: docs/wiki/Versions.md does not name Thoron 0.1.2: the wiki is updated with every "
                         "release")
        self.f.repo_file("docs/wiki/Versions.md", "# Versions\n\nThe newest version is 0.1.2.\n")
        self.assertEqual(rel.wiki_problems(self.f.repo, THORON), [])
        (self.f.repo / "docs/wiki/Versions.md").unlink()
        self.f.repo_file("docs/wiki/Home.md", "# Thoron\n")
        self.refused("wiki: docs/wiki/Versions.md does not name Thoron 0.1.2")

    def test_the_commands_that_publish_the_wiki_are_printed_and_never_run(self):
        self.assertEqual(rel.wiki_commands(GH_REPO), [
            "py -3 -I tools/docs/publish_wiki.py --repo KuchiSofts/thoron --dry-run",
            "py -3 -I tools/docs/publish_wiki.py --repo KuchiSofts/thoron"])
        self.assertEqual(self.f.prepare(*self.f.with_manifest())[0], 0)
        self.f.minisign_stand_in()
        calls = []
        with mock.patch("tools.docs.publish_wiki.publish", side_effect=AssertionError("the wiki was published")), \
                mock.patch.object(rel.subprocess, "run", side_effect=AssertionError("publish ran a program")):
            code, out, _ = self.f.publish(run=calls.append)
        self.assertEqual(code, 0)
        self.assertEqual([cmd[:3] for cmd in calls], [["gh", "release", "create"]])
        for command in rel.wiki_commands(GH_REPO):
            self.assertIn(f"    {command}\n", out)


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


class DeltaReleaseTests(unittest.TestCase):
    """ROADMAP P4.1: the release's delta packages, their place in the manifest and their sizes in the notes."""

    def test_names_and_the_sizes_section(self):
        self.assertEqual(rel.delta_name("158.0.8127.3000", "158.0.8127.3010", "win-x64-avx2"),
                         "thoron-158.0.8127.3000-to-158.0.8127.3010-win-x64-avx2-portable.delta")
        self.assertEqual(rel.update_sizes([], 100), "")
        text = rel.update_sizes([{"from": "158.0.8127.3000", "delta_bytes": 8 * 1024 * 1024, "same": 233,
                                  "patch": 29, "whole": 0}], 220 * 1024 * 1024)
        self.assertIn("## Update sizes", text)
        self.assertIn("- From 158.0.8127.3000: 8.0 MiB, 3.6 % of the whole package (233 files the same, "
                      "29 patched, 0 whole).", text)
        self.assertNotIn(chr(0x2014), text)    # no long dash in the notes

    def test_the_manifest_names_the_portable_deltas(self):
        with tempfile.TemporaryDirectory() as d:
            dist = Path(d)
            version, variant = "158.0.8127.3010", "win-x64-avx2"
            (dist / rel.portable_name(version, variant)).write_bytes(b"zip")
            (dist / rel.delta_name("158.0.8127.3000", version, variant)).write_bytes(b"delta")
            (dist / rel.delta_name("158.0.8127.2000", "158.0.8127.2500", variant)).write_bytes(b"other")
            packages = rel.manifest_packages(dist, version, variant, "KuchiSofts/thoron", "v0.1.2")
            deltas = packages[variant]["portable"]["deltas"]
            self.assertEqual(sorted(deltas), ["158.0.8127.3000"])
            self.assertEqual(deltas["158.0.8127.3000"]["size"], 5)
            self.assertTrue(deltas["158.0.8127.3000"]["url"].endswith(
                rel.delta_name("158.0.8127.3000", version, variant)))

    def test_at_most_three_deltas(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(rel.ReleaseError):
                rel.add_deltas(Path(d), Path(d), "158.0.8127.3010", "win-x64-avx2", [Path(d)] * 4,
                               Path("zucchini.exe"))



class SetupReleaseTests(unittest.TestCase):
    """ROADMAP P3.19: the ThoronSetup.exe a release ships."""

    def test_the_setup_for_tests_never_ships(self):
        with tempfile.TemporaryDirectory() as d:
            shipped = Path(d) / "ThoronSetup.exe"
            shipped.write_bytes(b"MZ" + b"\0" * 100 + b"a program")
            self.assertEqual(rel.setup_problems(shipped), [])
            for mark in rel.SETUP_TEST_MARKS:
                with self.subTest(mark=mark):
                    shipped.write_bytes(b"MZ" + b"\0" * 100 + mark)
                    self.assertEqual(len(rel.setup_problems(shipped)), 1)
            shipped.write_bytes(b"not a program")
            self.assertIn("is not a Windows program", rel.setup_problems(shipped)[0])


class SoakGateTests(unittest.TestCase):
    """ROADMAP Q.4: a release needs a passing 8-hour soak test of its own build."""

    def problems(self, text):
        with tempfile.TemporaryDirectory() as d:
            report = Path(d) / "soak.txt"
            report.write_text(text, encoding="utf-8")
            return rel.soak_problems(report, BUILD)

    def test_a_passing_run_of_this_build(self):
        self.assertEqual(self.problems(SOAK_REPORT), [])

    def test_what_is_refused(self):
        self.assertEqual(len(rel.soak_problems(None, BUILD)), 1)
        self.assertIn("not 8", self.problems(SOAK_REPORT.replace("8.00 h", "0.17 h"))[0])
        self.assertIn("not " + BUILD, self.problems(SOAK_REPORT.replace(BUILD, "158.0.8127.2000"))[0])
        self.assertIn("did not pass",
                      self.problems(SOAK_REPORT.replace("SOAK: PASSED", "SOAK: FAILED (1 problem(s))"))[0])
        self.assertEqual(len(self.problems("nothing")), 3)


if __name__ == "__main__":
    unittest.main()
