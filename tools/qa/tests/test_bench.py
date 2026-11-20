# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Offline benchmark harness (ROADMAP Q.1)."""
import json
import time
import unittest
import urllib.request

from tools.qa import bench

PROCS = [
    {"pid": 1, "ppid": 0, "ws": 100, "cpu": 5.0},
    {"pid": 10, "ppid": 1, "ws": 1000, "cpu": 1.0},     # browser
    {"pid": 11, "ppid": 10, "ws": 200, "cpu": 0.5},     # renderer
    {"pid": 12, "ppid": 10, "ws": 300, "cpu": 0.25},    # gpu
    {"pid": 13, "ppid": 11, "ws": 50, "cpu": 0.25},     # grandchild
    {"pid": 20, "ppid": 1, "ws": 9999, "cpu": 9.0},     # unrelated
]


class TreeTests(unittest.TestCase):
    def test_tree_includes_every_descendant_and_nothing_else(self):
        self.assertEqual(sorted(p["pid"] for p in bench.tree(PROCS, 10)), [10, 11, 12, 13])

    def test_totals(self):
        self.assertEqual(bench.total(PROCS, 10, "ws"), 1550)
        self.assertEqual(bench.total(PROCS, 10, "cpu"), 2.0)

    def test_missing_root_is_an_error(self):
        with self.assertRaises(bench.BenchError):
            bench.tree(PROCS, 99)

    def test_a_cycle_of_reused_ids_ends(self):
        # Windows reuses ids: 30 names 31 as its parent and 31 names 30 (a stuck benchmark run, 2026-11-20)
        procs = PROCS + [{"pid": 30, "ppid": 31, "ws": 1, "cpu": 0.0}, {"pid": 31, "ppid": 30, "ws": 2, "cpu": 0.0},
                         {"pid": 32, "ppid": 32, "ws": 4, "cpu": 0.0}]
        self.assertEqual(sorted(p["pid"] for p in bench.tree(procs, 30)), [30, 31])
        self.assertEqual(bench.total(procs, 31, "ws"), 3)
        self.assertEqual([p["pid"] for p in bench.tree(procs, 32)], [32])


class StatsTests(unittest.TestCase):
    def test_median_and_spread(self):
        s = bench.summarise([100.0, 102.0, 98.0, 101.0, 99.0])
        self.assertEqual(s["median"], 100.0)
        self.assertAlmostEqual(s["spread_pct"], 4.0)
        self.assertEqual(s["runs"], 5)
        self.assertFalse(s["repeatable"])           # 4 % > 3 %

    def test_repeatable_within_three_percent(self):
        self.assertTrue(bench.summarise([100.0, 101.0, 99.5])["repeatable"])

    def test_near_zero_measure_uses_its_floor(self):
        values = [0.10, 0.14, 0.12, 0.11, 0.13]          # 33 % spread, 0.04 points apart
        self.assertFalse(bench.summarise(values)["repeatable"])
        s = bench.summarise(values, bench.REPEATABLE_FLOOR["idle_cpu_pct"])
        self.assertTrue(s["repeatable"])
        self.assertAlmostEqual(s["range"], 0.04)
        self.assertFalse(bench.summarise([0.1, 0.5, 0.3], 0.1)["repeatable"])   # 0.4 points apart

    def test_markdown_names_the_floor(self):
        md = bench.to_markdown({"browser": "thoron", "version": "158",
                                "idle_cpu_pct": bench.summarise([0.10, 0.14, 0.12], 0.1)})
        self.assertIn("within 0.1 of each other (they were within 0.04)", md)

    def test_needs_three_runs(self):
        with self.assertRaises(bench.BenchError):
            bench.summarise([1.0, 2.0])


class PingServerTests(unittest.TestCase):
    def test_records_the_first_ping_and_serves_the_page(self):
        with bench.PingServer() as server:
            page = urllib.request.urlopen(server.url("page"), timeout=5).read().decode("utf-8")
            self.assertIn("/ping", page)
            self.assertNotIn("http://", page.replace(server.base, ""))   # nothing outside the local server
            t0 = time.monotonic()
            urllib.request.urlopen(server.url("ping"), timeout=5).read()
            self.assertTrue(server.wait(5))
            self.assertGreaterEqual(server.first_ping, t0)

    def test_listens_on_loopback_only(self):
        with bench.PingServer() as server:
            self.assertTrue(server.base.startswith("http://127.0.0.1:"))


class ReportTests(unittest.TestCase):
    def test_markdown_and_json(self):
        results = {"browser": "thoron.exe", "version": "158.0.8127.30",
                   "startup_ms": bench.summarise([500.0, 505.0, 495.0])}
        md = bench.to_markdown(results)
        self.assertIn("| startup_ms | 500.0 | 2.0 % | 3 | yes |", md)
        json.loads(json.dumps(results))


class WarmupTests(unittest.TestCase):
    def test_the_warmup_runs_are_dropped(self):
        self.assertEqual(bench.without_warmup([1469.0, 515.0, 563.0, 719.0, 672.0, 600.0], 1),
                         [515.0, 563.0, 719.0, 672.0, 600.0])
        self.assertEqual(bench.without_warmup([1.0, 2.0, 3.0], 0), [1.0, 2.0, 3.0])



class ProfilesTests(unittest.TestCase):
    def test_the_picker_is_told_by_its_address(self):
        self.assertTrue(bench.picker_ready([{"type": "browser_ui", "url": "chrome://profile-picker/"}]))
        self.assertFalse(bench.picker_ready([{"type": "page", "url": "chrome://newtab/"}]))
        self.assertFalse(bench.picker_ready([]))
        self.assertEqual(len(bench.PROFILES), 4)

    def test_four_windows_are_four_pages(self):
        pages = [{"type": "page", "url": "chrome://newtab/"}] * 3
        self.assertFalse(bench.profile_windows_ready(pages))
        self.assertFalse(bench.profile_windows_ready(pages + [{"type": "service_worker", "url": "x"}]))
        self.assertTrue(bench.profile_windows_ready(pages + [{"type": "page", "url": "about:blank"}]))

    def test_the_four_profiles_open_together(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Local State").write_text(json.dumps({"profile": {"info_cache": {}}}), encoding="utf-8")
            bench.windows_template(root)
            state = json.loads((root / "Local State").read_text(encoding="utf-8"))
            self.assertIs(state["browser"]["show_profile_picker_on_startup"], False)
            self.assertEqual(state["profile"]["last_active_profiles"], list(bench.PROFILES))
            self.assertIn("info_cache", state["profile"])


class DevToolsPortTests(unittest.TestCase):
    """The port file is read only once the browser has written it (an empty file is still being written)."""

    def test_an_empty_file_is_waited_for(self):
        import tempfile
        import threading
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder).resolve()
            port_file = profile / "DevToolsActivePort"
            port_file.write_text("", encoding="utf-8")
            later = threading.Timer(0.5, lambda: port_file.write_text("9\n/devtools/browser/x\n", encoding="utf-8"))
            later.start()
            started = time.monotonic()
            bench._open_tabs(profile, [], timeout=10)
            later.join()
            self.assertGreaterEqual(time.monotonic() - started, 0.4)

    def test_no_file_in_time(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(bench.BenchError):
                bench._open_tabs(Path(folder), [], timeout=0.5)


if __name__ == "__main__":
    unittest.main()
