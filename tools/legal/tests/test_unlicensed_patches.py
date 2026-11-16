# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""The patches without a licence stay withheld and are the only ones (ROADMAP L.1)."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from tools.legal import patch_licenses as pl
from tools.legal import unlicensed_patches as up

REPO = Path(__file__).resolve().parents[3]
DIFF = "diff --git a/x.cc b/x.cc\nindex 1..2 100644\n--- a/x.cc\n+++ b/x.cc\n@@ -1 +1 @@\n-a\n+b\n"
ROWS = [{"patch": "ours.patch", "origin": "Thoron", "license": "BSD-3-Clause", "evidence": "patch header"},
        {"patch": "bare.patch", "origin": "Somebody", "license": pl.NOT_STATED, "evidence": "research: no licence"}]
INVENTORY = pl.render_table(ROWS)
RESEARCH = "patch\torigin\tlicense\tevidence\nbare.patch\tSomebody\tNOT STATED\tno licence is published\n"
UPSTREAM = json.dumps({"withheld": {"other/bare.patch": "0" * 40, "other/thorium-default-api-keys.patch": "1" * 40}})
OVERLAY = {"other/ours.patch", "patch_scripts/series/series"}
DECISIONS = "# Patches without a licence\n\n## 1. `bare.patch`\n\nDrop it.\n"


def header(licence: str) -> str:
    return f"Origin: x\nAuthor: x\nLicense: {licence}\n\n"


class RecordTests(unittest.TestCase):
    def problems(self, **changed) -> list[str]:
        args = {"inventory_md": INVENTORY, "research_tsv": RESEARCH, "upstream_json": UPSTREAM, "overlay": OVERLAY,
                "decisions_md": DECISIONS}
        return up.problems(**{**args, **changed})

    def test_records_that_agree_have_no_problem(self):
        self.assertEqual(up.without_licence(INVENTORY), ["bare.patch"])
        self.assertEqual(self.problems(), [])

    def test_a_patch_without_a_licence_must_be_withheld(self):
        only_keys = json.dumps({"withheld": {"other/thorium-default-api-keys.patch": "1" * 40}})
        self.assertEqual(self.problems(upstream_json=only_keys),
                         ["bare.patch: no licence, but not withheld in source/UPSTREAM.json"])

    def test_it_must_not_be_in_the_overlay_and_neither_may_the_credentials(self):
        found = self.problems(overlay=OVERLAY | {"other/bare.patch", "other/thorium-default-api-keys.patch"})
        self.assertEqual(len(found), 2)
        self.assertTrue(all("it is published" in p for p in found))

    def test_nothing_else_is_withheld(self):
        more = json.dumps({"withheld": {"other/bare.patch": "0" * 40, "other/ours.patch": "2" * 40}})
        self.assertEqual(self.problems(upstream_json=more),
                         ["other/ours.patch: withheld in source/UPSTREAM.json, but it has a licence and is no known exception"])

    def test_the_research_must_say_the_same(self):
        licensed = RESEARCH.replace("NOT STATED", "MIT")
        self.assertEqual(self.problems(research_tsv=licensed), ["bare.patch: NOT STATED in the inventory, MIT in the research"])
        self.assertIn("no row in the research", self.problems(research_tsv="patch\torigin\tlicense\tevidence\n")[0])
        # a header that names a licence wins in the inventory; the research row then shows the difference
        turned = pl.render_table([ROWS[0], dict(ROWS[1], license="BSD-3-Clause")])
        found = self.problems(inventory_md=turned)
        self.assertIn("bare.patch: NOT STATED in the research, BSD-3-Clause in the inventory", found)
        self.assertIn("other/bare.patch: withheld in source/UPSTREAM.json, but it has a licence and is no known exception", found)

    def test_every_one_has_a_decision(self):
        self.assertEqual(self.problems(decisions_md="# Patches without a licence\n\nbare.patch is mentioned.\n"),
                         ["bare.patch: no section in docs/legal/UNLICENSED_PATCHES.md"])

    def test_unknown_is_a_problem(self):
        unknown = pl.render_table(ROWS + [{"patch": "new.patch", "origin": "unknown", "license": "UNKNOWN", "evidence": "x"}])
        self.assertEqual(self.problems(inventory_md=unknown), ["new.patch: the inventory says UNKNOWN; research it first"])

    def test_a_release_may_not_carry_one(self):
        self.assertEqual(self.problems(release=True), ["bare.patch: still without a licence; a release may not carry it"])
        resolved = pl.render_table(ROWS[:1])
        keys_only = json.dumps({"withheld": {"other/thorium-default-api-keys.patch": "1" * 40}})
        self.assertEqual(self.problems(inventory_md=resolved, research_tsv="", upstream_json=keys_only, release=True), [])


class TreeTests(unittest.TestCase):
    def tree(self, tmp: str, patches: dict[str, str]) -> Path:
        tree = Path(tmp)
        (tree / "other").mkdir()
        (tree / "patch_scripts/series").mkdir(parents=True)
        for name, text in patches.items():
            (tree / "other" / name).write_text(text, encoding="utf-8")
        (tree / "patch_scripts/series/series").write_text("".join(f"other/{n}\n" for n in patches), encoding="utf-8")
        return tree

    def test_a_series_that_matches_the_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = self.tree(tmp, {"ours.patch": header("BSD-3-Clause") + DIFF, "bare.patch": header("NOT STATED") + DIFF})
            self.assertEqual(up.tree_problems(tree, INVENTORY), [])

    def test_a_patch_without_a_row_and_a_row_without_a_patch(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = self.tree(tmp, {"ours.patch": header("BSD-3-Clause") + DIFF, "new.patch": header("MIT") + DIFF})
            found = up.tree_problems(tree, INVENTORY)
            self.assertEqual(len(found), 2)
            self.assertIn("new.patch: in the series, but the inventory has no row for it", found[0])
            self.assertEqual(found[1], "bare.patch: a row in the inventory, but not in the series")

    def test_headers_say_not_stated_for_exactly_these_patches(self):
        with tempfile.TemporaryDirectory() as tmp:
            # the header is read wherever it stands before the diff, also below a long description
            long = "A description.\n" * 60
            tree = self.tree(tmp, {"ours.patch": long + header("NOT STATED") + DIFF, "bare.patch": header("MIT") + DIFF})
            found = up.tree_problems(tree, INVENTORY)
            self.assertEqual(found, ["ours.patch: its header says NOT STATED, the inventory says it has a licence",
                                     "bare.patch: its header says MIT, the inventory says NOT STATED"])


class RepositoryTests(unittest.TestCase):
    def test_the_repository_agrees_with_itself(self):
        bare, found = up.check(REPO)
        self.assertEqual(found, [])
        withheld = json.loads((REPO / up.UPSTREAM).read_text(encoding="utf-8"))["withheld"]
        self.assertEqual({Path(p).name for p in withheld}, set(bare) | {Path(p).name for p in up.OTHER_WITHHELD})

    def test_check_names_a_missing_record_and_main_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(up.check(Path(tmp)), ([], ["docs/legal/PATCH_LICENSES.md is not in the repository"]))
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                self.assertEqual(up.main(["check", "--repo", tmp]), 1)
            self.assertIn("1 problem(s)", out.getvalue())
            self.assertIn("unlicensed_patches: docs/legal/PATCH_LICENSES.md", err.getvalue())


if __name__ == "__main__":
    unittest.main()
