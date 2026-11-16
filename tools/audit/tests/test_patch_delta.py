# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
import contextlib
import io
import json
import unittest

from tools.audit import patch_delta
from tools.audit.tests.gitfixture import GitRepo

PATCH = b"""diff --git a/ui/menu.cc b/ui/menu.cc
index 1111111..2222222 100644
--- a/ui/menu.cc
+++ b/ui/menu.cc
@@ -10,3 +10,3 @@ void Show() {
   int a = 1;
-  int delay = 400;
+  int delay = 1;
   int b = 2;
"""
# The same change after upstream moved to a newer Chromium: other offsets, index line and context.
REFRESHED = b"""diff --git a/ui/menu.cc b/ui/menu.cc
index 3333333..4444444 100644
--- a/ui/menu.cc
+++ b/ui/menu.cc
@@ -42,3 +42,3 @@ void ShowMenu() {
   int first = 1;
-  int delay = 400;
+  int delay = 1;
   int b = 2;
"""
CHANGED = REFRESHED.replace(b"+  int delay = 1;", b"+  int delay = 0;")


class PatchDeltaTests(unittest.TestCase):
    def setUp(self):
        self.repo = GitRepo()
        self.repo.write("other/menu.patch", PATCH)
        self.repo.write("README.md", b"text\n")
        self.base = self.repo.commit("base")

    def tearDown(self):
        self.repo.cleanup()

    def delta(self, base=None, target="HEAD", paths=()):
        return patch_delta.compare(self.repo.path, base or self.base, target, list(paths))

    def test_refreshed_patch_is_the_same_change(self):
        self.repo.write("other/menu.patch", REFRESHED)
        self.repo.write("README.md", b"other text\n")      # not a patch: not listed
        self.repo.commit("refresh")
        self.assertEqual(self.delta(), [{"path": "other/menu.patch", "state": "same", "gained": [], "lost": []}])

    def test_changed_inner_line_is_reported_with_its_file(self):
        self.repo.write("other/menu.patch", CHANGED)
        self.repo.commit("change")
        (entry,) = self.delta()
        self.assertEqual(entry["state"], "changed")
        self.assertEqual(entry["gained"], [["ui/menu.cc", "+  int delay = 0;"]])
        self.assertEqual(entry["lost"], [["ui/menu.cc", "+  int delay = 1;"]])

    def test_added_and_deleted_patches_are_listed(self):
        self.repo.remove("other/menu.patch")
        self.repo.write("other/new.patch", PATCH)
        self.repo.commit("swap")
        self.assertEqual([(e["path"], e["state"]) for e in self.delta()],
                         [("other/menu.patch", "deleted"), ("other/new.patch", "added")])

    def test_header_like_line_inside_a_hunk_does_not_hide_a_change(self):
        # An added line "++ b/x" shows as "+++ b/x" and a removed "-- a/x" as "--- a/x"; both are content.
        body = (b"diff --git a/a.txt b/a.txt\n--- a/a.txt\n+++ b/a.txt\n@@ -1,2 +1,2 @@\n keep\n"
                b"--- a/old\n+++ b/evil\n")
        self.repo.write("other/tricky.patch", body)
        base2 = self.repo.commit("tricky")
        self.repo.write("other/tricky.patch", body.replace(b"+++ b/evil", b"+++ b/evil2"))
        self.repo.commit("tricky changed")
        (entry,) = self.delta(base=base2)
        self.assertEqual(entry["state"], "changed")
        self.assertEqual(entry["gained"], [["a.txt", "+++ b/evil2"]])

    def test_change_outside_the_hunks_is_not_called_the_same(self):
        # A binary patch has no hunks; its payload must still count.
        binary = b"diff --git a/x.bin b/x.bin\nindex 1111111..2222222 100644\nGIT binary patch\nliteral 4\nLc${NkWMxY\n"
        self.repo.write("other/bin.patch", binary)
        base2 = self.repo.commit("binary patch")
        self.repo.write("other/bin.patch", binary.replace(b"Lc${NkWMxY", b"Lc${NkWMxZ"))
        self.repo.commit("binary patch changed")
        (entry,) = self.delta(base=base2)
        self.assertEqual(entry["state"], "changed")
        self.assertEqual(entry["gained"], [["x.bin", "Lc${NkWMxZ"]])
        self.assertEqual(entry["lost"], [["x.bin", "Lc${NkWMxY"]])

    def test_crlf_patch_compares_like_lf(self):
        self.repo.write("other/menu.patch", REFRESHED.replace(b"\n", b"\r\n"))
        self.repo.commit("crlf refresh")
        self.assertEqual(self.delta()[0]["state"], "same")

    def test_trees_and_path_filter_compare_an_overlay_with_upstream(self):
        self.repo.write("source/overlay/other/menu.patch", CHANGED)
        self.repo.write("source/overlay/other/ours.patch", PATCH)
        self.repo.commit("overlay")
        entries = self.delta(target="HEAD:source/overlay", paths=["other/menu.patch"])
        self.assertEqual([(e["path"], e["state"]) for e in entries], [("other/menu.patch", "changed")])

    def test_option_like_revision_is_refused(self):
        with self.assertRaises(ValueError):
            self.delta(target="--output=x")

    def test_main_prints_a_summary_and_json(self):
        self.repo.write("other/menu.patch", CHANGED)
        self.repo.write("other/new.patch", PATCH)
        self.repo.commit("change and add")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(patch_delta.main([self.repo.path, self.base, "HEAD", "--show"]), 0)
        text = out.getvalue()
        self.assertIn("changed  other/menu.patch", text)
        self.assertIn("gained [ui/menu.cc] +  int delay = 0;", text)
        self.assertIn("2 patch file(s): 0 same, 1 changed, 1 added, 0 deleted", text)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            patch_delta.main([self.repo.path, self.base, "HEAD", "--json"])
        self.assertEqual([e["state"] for e in json.loads(out.getvalue())], ["changed", "added"])


if __name__ == "__main__":
    unittest.main()
