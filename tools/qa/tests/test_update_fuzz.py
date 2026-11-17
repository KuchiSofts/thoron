# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Tests of tools/qa/update_fuzz.py that need no fuzzer."""
import json
import tempfile
import unittest
from pathlib import Path

from tools.qa import update_fuzz as uf
from tools.update import manifest as mf


class SeedTests(unittest.TestCase):
    def test_every_manifest_seed_is_a_manifest_the_reference_reads(self):
        for data in uf.manifests():
            content = mf.parse(data, allowed_hosts=("github.com",))
            self.assertIn(content["channel"], ("stable", "beta"))

    def test_the_delta_lists_have_the_format_of_the_delta_tool(self):
        for data in uf.delta_lists():
            d = json.loads(data)
            self.assertEqual((d["format"], d["from"], d["to"]), (1, uf.FROM, uf.TO))
            self.assertTrue(d["files"])

    def test_seeds_are_written_with_the_byte_that_picks_the_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            count = uf.write_seeds(Path(tmp))
            self.assertEqual(count["manifest"], len(uf.manifests()) * 7)
            first = sorted((Path(tmp) / "manifest").iterdir())[0].read_bytes()
            self.assertIn(first[0], (0x00, 0x01, 0x03, 0x05, 0x11, 0x21, 0x41))
            self.assertEqual(first[1:2], b"{")


LOG = """INFO: Seed: 1
#2	INITED cov: 812 ft: 1040 corp: 49/40Kb exec/s: 0 rss: 60Mb
#65536	pulse  cov: 1290 ft: 3120 corp: 300/200Kb exec/s: 2184 rss: 90Mb
Done 7864320 runs in 3601 second(s)
"""


class SummaryTests(unittest.TestCase):
    def test_a_clean_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            found = uf.summary(LOG, Path(tmp))
            self.assertEqual((found["runs"], found["seconds"], found["coverage"], found["features"]),
                             (7864320, 3601, 1290, 3120))
            self.assertTrue(uf.report("x", found).startswith("x: CLEAN"))

    def test_a_crash_or_a_sanitizer_report_is_a_finding(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "crash-0a1b").write_bytes(b"x")
            found = uf.summary(LOG, Path(tmp))
            self.assertEqual(found["findings"], ["crash-0a1b"])
            self.assertIn("FOUND", uf.report("x", found))
            self.assertIn("FOUND", uf.report("x", uf.summary(LOG + "==12==ERROR: AddressSanitizer: heap", Path(tmp))))

    def test_a_run_that_never_started_is_not_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIn("NOT RUN", uf.report("x", uf.summary("cannot open corpus", Path(tmp))))


if __name__ == "__main__":
    unittest.main()
