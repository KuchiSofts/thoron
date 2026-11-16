# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Release notes generator (ROADMAP P2.13)."""
import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.release import changelog as cl


def git(repo, *args, env_name="Dev", env_mail="dev@users.noreply.github.com"):
    return subprocess.run(["git", "-c", f"user.name={env_name}", "-c", f"user.email={env_mail}",
                           "-c", "commit.gpgsign=false", *args], cwd=repo, check=True,
                          capture_output=True, text=True).stdout.strip()


def commit(repo, subject, body="", author="Dev", name="f.txt"):
    p = Path(repo) / name
    p.write_text(p.read_text(encoding="utf-8") + subject + "\n" if p.exists() else subject + "\n", encoding="utf-8")
    git(repo, "add", "-A")
    msg = subject + ("\n\n" + body if body else "")
    git(repo, "commit", "-q", "-m", msg, env_name=author, env_mail=f"{author}@users.noreply.github.com")
    return git(repo, "rev-parse", "HEAD")


class GroupingTests(unittest.TestCase):
    def test_prefixes_group_and_are_stripped(self):
        groups = cl.group_commits(["sec: close a hole", "fix: tab colours", "perf: faster start",
                                   "ui: new icon", "build: faster CI", "docs: guide", "Something else",
                                   "Merge pull request #9 from x/y"])
        self.assertEqual(groups["Security"], ["close a hole"])
        self.assertEqual(groups["Fixes"], ["tab colours"])
        self.assertEqual(groups["Performance"], ["faster start"])
        self.assertEqual(groups["User interface"], ["new icon"])
        self.assertEqual(groups["Build"], ["faster CI"])
        self.assertEqual(groups["Documentation"], ["guide"])
        self.assertEqual(groups["Other changes"], ["Something else"])
        self.assertNotIn("Merge pull request #9 from x/y", sum(groups.values(), []))

    def test_security_comes_first(self):
        self.assertEqual(cl.CATEGORIES[0], "Security")

    def test_issue_references(self):
        self.assertEqual(cl.issues(["Fixes #12", "closes #3 and fixes #12", "see #99"]), [3, 12])


class SeriesTests(unittest.TestCase):
    def test_added_removed_refreshed(self):
        old = {"other/a.patch": "A", "other/b.patch": "B", "other/c.patch": "C"}
        new = {"other/a.patch": "A", "other/b.patch": "B2", "other/d.patch": "D"}
        ch = cl.series_changes(old, new)
        self.assertEqual(ch, {"added": ["d.patch"], "removed": ["c.patch"], "refreshed": ["b.patch"]})


class SecurityTests(unittest.TestCase):
    def test_sorted_by_severity_then_cve(self):
        fixes = [{"cve": "CVE-2026-2", "severity": "Medium", "title": "m"},
                 {"cve": "CVE-2026-3", "severity": "Critical", "title": "c"},
                 {"cve": "CVE-2026-1", "severity": "High", "title": "h"}]
        self.assertEqual([f["cve"] for f in cl.sort_security(fixes)], ["CVE-2026-3", "CVE-2026-1", "CVE-2026-2"])

    def test_unknown_severity_is_refused(self):
        with self.assertRaises(cl.NotesError):
            cl.sort_security([{"cve": "CVE-1", "severity": "Spicy", "title": "x"}])

    def test_every_problem_of_a_security_list_is_named(self):
        fix = {"cve": "CVE-2026-1", "severity": "High", "title": "Use after free in V8"}
        self.assertEqual(cl.security_problems([fix, dict(fix, exploited=True)]), [])
        for wrong in ([], {}, None, "CVE-2026-1", fix):
            with self.subTest(wrong):
                self.assertEqual(cl.security_problems(wrong),
                                 ["a security list is a JSON list of at least one fix (leave it out when there is "
                                  "none)"])
        self.assertEqual(cl.security_problems([fix, "CVE-2026-2", {"cve": "", "severity": "Spicy"},
                                               dict(fix, title="two\nlines", severity=3)]),
                         ["fix 2: must be an object with cve, severity and title",
                          "fix 3: cve must be one line of text",
                          "fix 3: severity must be one of Critical, High, Medium, Low",
                          "fix 3: title must be one line of text",
                          "fix 4: severity must be one line of text",
                          "fix 4: title must be one line of text"])

    def test_a_security_list_is_read_from_its_file_or_refused_as_a_whole(self):
        fixes = [{"cve": "CVE-2026-1", "severity": "High", "title": "Use after free in V8"}]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "security.json"
            for encoding in ("utf-8", "utf-8-sig"):                 # with or without a byte order mark
                path.write_text(json.dumps(fixes), encoding=encoding)
                self.assertEqual(cl.read_security(path), fixes)
            for content, says in (("[", "security.json is not JSON"),
                                  ("[]", "security.json: a security list is a JSON list of at least one fix"),
                                  (json.dumps([{"cve": "CVE-2026-1"}]),
                                   "security.json: fix 1: severity must be one line of text; fix 1: title must be")):
                with self.subTest(content), self.assertRaises(cl.NotesError) as refused:
                    path.write_text(content, encoding="utf-8")
                    cl.read_security(path)
                self.assertIn(says, str(refused.exception))


SHORT = """# Changelog

All notable changes, one line per change.
- a list in the opening is not a change

## [Unreleased]

### Added

- **Updates:** the browser looks for a new version by itself.
- **Portable:** a package that runs without installing,
  from any folder,
  also from a USB drive.

### Fixed

- **Tabs:** tab groups are kept.

## [0.1.1] - 2026-12-01

Built on Chromium 158.0.8127.30.

### Security

- **Updates:** the update manifest is signed.

[Unreleased]: https://example.org/compare
"""


class ShortChangelogTests(unittest.TestCase):
    """D.10: per version, one line per change under Added, Changed, Fixed, Removed and Security."""

    def test_the_changes_by_version_and_section(self):
        versions, problems = cl.short_changelog(SHORT)
        self.assertEqual(problems, [])
        self.assertEqual(list(versions), ["Unreleased", "0.1.1"])
        self.assertEqual(versions["Unreleased"], {
            "Added": ["**Updates:** the browser looks for a new version by itself.",
                      "**Portable:** a package that runs without installing, from any folder, also from a USB drive."],
            "Fixed": ["**Tabs:** tab groups are kept."]})
        self.assertEqual(versions["0.1.1"], {"Security": ["**Updates:** the update manifest is signed."]})
        self.assertEqual(cl.short_changelog(SHORT.replace("\n", "\r\n")), (versions, []))     # a Windows checkout

    def test_what_is_not_in_the_short_form_is_named_by_its_line(self):
        for name, text, found in (
                ("a paragraph", "## [Unreleased]\n\n### Added\n\n- a\n\nIt took a while.\n",
                 [(7, "not a change (`- text`, one line per change) and not a section heading")]),
                ("another section", "## [Unreleased]\n\n### Performance\n\n- faster\n",
                 [(3, "`### Performance`: the sections are Added, Changed, Fixed, Removed, Security")]),
                ("a section twice", "## [Unreleased]\n\n### Added\n\n- a\n\n### Fixed\n\n- b\n\n### Added\n\n- c\n",
                 [(11, "`### Added` is there twice under one version")]),
                ("a change under no section", "## [Unreleased]\n\n- a\n",
                 [(3, "a change outside Added, Changed, Fixed, Removed, Security")]),
                ("a list inside a change", "## [Unreleased]\n\n### Added\n\n- a\n  - b\n",
                 [(6, "not a change (`- text`, one line per change) and not a section heading")]),
                ("another bullet", "## [Unreleased]\n\n### Added\n\n* a\n",
                 [(5, "not a change (`- text`, one line per change) and not a section heading")]),
                ("a change without text", "## [Unreleased]\n\n### Added\n\n- \n",
                 [(5, "not a change (`- text`, one line per change) and not a section heading")]),
                ("a wrapped part after an empty line", "## [Unreleased]\n\n### Added\n\n- a\n\n  b\n",
                 [(7, "not a change (`- text`, one line per change) and not a section heading")]),
                ("a deeper heading", "## [Unreleased]\n\n### Added\n\n#### Tabs\n\n- a\n",
                 [(5, "not a change (`- text`, one line per change) and not a section heading")]),
                ("a version twice", "## [0.1.1] - 2026-12-01\n\n## [0.1.1] - 2026-12-02\n", [(3, "[0.1.1] is there twice")]),
                ("a heading that names no version", "## Unreleased\n",
                 [(1, "a version heading is `## [0.1.1] - YYYY-MM-DD` or `## [Unreleased]`")])):
            with self.subTest(name):
                self.assertEqual(cl.short_changelog(text)[1], found)

    def test_a_release_takes_its_own_section_or_what_waits(self):
        self.assertEqual(cl.release_changes(SHORT, "0.1.1"),
                         ("0.1.1", {"Security": ["**Updates:** the update manifest is signed."]}))
        for version in ("0.1.2", None):
            name, changes = cl.release_changes(SHORT, version)
            self.assertEqual((name, list(changes)), ("Unreleased", ["Added", "Fixed"]))

    def test_a_release_without_a_change_or_with_a_changelog_in_another_form_is_refused(self):
        for text, version, says in (
                ("## [Unreleased]\n\n### Added\n", None, "the changelog lists no change under [Unreleased]"),
                ("## [Unreleased]\n\n### Added\n\n- a\n\n## [0.1.2] - 2026-12-01\n", "0.1.2",
                 "the changelog lists no change under [0.1.2]"),
                ("## [0.1.1] - 2026-12-01\n\n### Added\n\n- a\n", "0.1.2", "the changelog has no [Unreleased] section"),
                ("## [Unreleased]\n\n### Added\n\n- a\n" + "\ntext\n" * 7, None,
                 "the changelog is not in its short form: line 7: not a change (`- text`, one line per change) and "
                 "not a section heading; line 9: ")):
            with self.subTest(says), self.assertRaises(cl.NotesError) as refused:
                cl.release_changes(text, version)
            self.assertIn(says, str(refused.exception))
        self.assertTrue(str(refused.exception).endswith("; and 2 more"))


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.repo = root / "thoron"
        self.up = root / "upstream"
        for r in (self.repo, self.up):
            r.mkdir()
            git(r, "init", "-q")
        self.base = commit(self.repo, "docs: start")
        commit(self.repo, "sec: refuse Google API keys", "Fixes #7")
        commit(self.repo, "fix: keep tab groups")
        self.up_base = commit(self.up, "M158 start", author="gz83")
        commit(self.up, "Refresh patches", author="gz83")
        commit(self.up, "Fix FFmpeg on Linux", author="Alex313031")
        commit(self.up, "Fix FFmpeg on ARM", author="Alex313031")

    def tearDown(self):
        self.tmp.cleanup()

    def notes(self, **kw):
        args = dict(version="158.0.8127.3000", chromium_old="156.0.8078.80", chromium_new="158.0.8127.30",
                    repo=self.repo, since=self.base, upstream=self.up, upstream_since=self.up_base,
                    series={"added": ["ks-x.patch"], "removed": ["GPC.patch"], "refreshed": []},
                    security=[{"cve": "CVE-2026-9", "severity": "High", "title": "Use after free in V8"}],
                    artifacts=["a" * 64 + "  thoron_AVX2_mini_installer.exe"])
        args.update(kw)
        return cl.render(**args)

    def test_sections_in_design_order(self):
        text = self.notes()
        order = ["# Thoron 158.0.8127.3000", "## Chromium", "## Thoron changes", "## Upstream Thorium",
                 "## Patches", "## Fixed issues", "## Downloads", "## Credits"]
        positions = [text.index(h) for h in order]
        self.assertEqual(positions, sorted(positions))

    def test_content(self):
        text = self.notes()
        self.assertIn("Chromium 156.0.8078.80 to 158.0.8127.30", text)
        self.assertIn("CVE-2026-9", text)
        self.assertIn("refuse Google API keys", text)
        self.assertLess(text.index("### Security"), text.index("### Fixes"))
        self.assertIn("#7", text)
        self.assertIn("ks-x.patch", text)
        self.assertIn("GPC.patch", text)
        self.assertIn("thoron_AVX2_mini_installer.exe", text)

    def test_upstream_commits_are_credited_by_author(self):
        text = self.notes()
        self.assertIn("Fix FFmpeg on Linux (Alex313031)", text)
        self.assertIn("Refresh patches (gz83)", text)
        self.assertIn("Alex313031 (2 commits)", text)

    def test_house_style_and_no_emails(self):
        text = self.notes(security=[{"cve": "CVE-1", "severity": "Low", "title": "a " + chr(0x2014) + " b"}])
        self.assertNotIn(chr(0x2014), text)
        self.assertNotIn(chr(0x2013), text)
        self.assertNotIn("@users.noreply", text)

    def test_thorons_changes_come_from_the_short_changelog_when_it_is_given(self):
        text = self.notes(changes=cl.release_changes(SHORT)[1], thoron_version="0.1.2")
        self.assertTrue(text.startswith("# Thoron 0.1.2\n\nThoron 0.1.2 (build 158.0.8127.3000) is based on Chromium "
                                        "158.0.8127.30 and the Thorium patch series.\n"))
        self.assertIn("## Thoron changes\n\n### Added\n\n- **Updates:** the browser looks for a new version by itself.\n"
                      "- **Portable:** a package that runs without installing, from any folder, also from a USB drive."
                      "\n\n### Fixed\n\n- **Tabs:** tab groups are kept.\n\n## Upstream Thorium", text)
        self.assertNotIn("refuse Google API keys", text)            # the commits are not listed beside it
        self.assertIn("## Fixed issues\n\n#7", text)                # and still say which issues were fixed
        self.assertIn("Fix FFmpeg on Linux (Alex313031)", text)
        ordered = self.notes(changes={"Security": ["s"], "Removed": ["r"], "Added": ["a"], "Changed": []})
        self.assertIn("### Added\n\n- a\n\n### Removed\n\n- r\n\n### Security\n\n- s\n", ordered)
        self.assertNotIn("### Changed", ordered)
        self.assertIn("## Thoron changes\n\nNo changes of our own.", self.notes(changes={}))

    def test_the_source_and_the_licences_are_named_when_given(self):
        self.assertNotIn("## Source and licences", self.notes())
        text = self.notes(source={"tag": "v0.1.2", "commit": "0123456789abcdef0123456789abcdef01234567",
                                  "chromium_tag": "158.0.8127.30", "licences": "thoron-158.0.8127.3000-licenses.zip"})
        self.assertIn("## Source and licences\n\nThe source of this release is the tag `v0.1.2` of this repository "
                      "(commit `0123456789abcdef0123456789abcdef01234567`), applied to Chromium at its tag "
                      "`158.0.8127.30`. Parts of Thoron are under the GNU General Public License version 3; `NOTICE` "
                      "says which. Its text and the other licence texts are in `thoron-158.0.8127.3000-licenses.zip`, "
                      "and in the browser at `chrome://credits`.\n\n## Credits", text)
        self.assertLess(text.index("## Downloads"), text.index("## Source and licences"))

    def test_cli_takes_the_changes_from_the_changelog(self):
        changelog = Path(self.tmp.name) / "CHANGELOG.md"
        changelog.write_text(SHORT, encoding="utf-8")
        out = Path(self.tmp.name) / "NOTES.md"
        args = ["--version", "158.0.8127.3000", "--chromium-old", "156.0.8078.80", "--chromium-new", "158.0.8127.30",
                "--repo", str(self.repo), "--since", self.base, "--changelog", str(changelog), "--out", str(out)]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cl.main(args + ["--thoron-version", "0.1.1"]), 0)
        text = out.read_text(encoding="utf-8")
        self.assertIn("# Thoron 0.1.1\n", text)
        self.assertIn("### Security\n\n- **Updates:** the update manifest is signed.\n", text)
        self.assertNotIn("tab groups are kept", text)
        changelog.write_text(SHORT.replace("### Fixed", "### Fixes"), encoding="utf-8")
        out.unlink()
        said = io.StringIO()
        with contextlib.redirect_stderr(said):
            self.assertEqual(cl.main(args), 2)
        self.assertIn("changelog: the changelog is not in its short form: line 15: `### Fixes`", said.getvalue())
        self.assertFalse(out.exists())

    def test_cli_writes_the_notes(self):
        sec = Path(self.tmp.name) / "security.json"
        sec.write_text(json.dumps([{"cve": "CVE-2026-9", "severity": "High", "title": "x"}]), encoding="utf-8")
        out = Path(self.tmp.name) / "NOTES.md"
        rc = cl.main(["--version", "158.0.8127.3000", "--chromium-old", "156.0.8078.80", "--chromium-new",
                      "158.0.8127.30", "--repo", str(self.repo), "--since", self.base, "--security", str(sec),
                      "--out", str(out)])
        self.assertEqual(rc, 0)
        self.assertIn("CVE-2026-9", out.read_text(encoding="utf-8"))

    def test_cli_refuses_a_security_list_that_is_none(self):
        sec = Path(self.tmp.name) / "security.json"
        sec.write_text(json.dumps([{"cve": "CVE-2026-9", "severity": "High"}]), encoding="utf-8")
        out = Path(self.tmp.name) / "NOTES.md"
        said = io.StringIO()
        with contextlib.redirect_stderr(said):
            rc = cl.main(["--version", "158.0.8127.3000", "--chromium-old", "156.0.8078.80", "--chromium-new",
                          "158.0.8127.30", "--repo", str(self.repo), "--since", self.base, "--security", str(sec),
                          "--out", str(out)])
        self.assertEqual(rc, 2)
        self.assertIn("changelog: security.json: fix 1: title must be one line of text", said.getvalue())
        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
