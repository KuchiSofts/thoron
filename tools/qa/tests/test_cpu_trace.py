# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Tests of the parts of cpu_trace.py that do not need a browser."""
import unittest

from tools.qa import cpu_trace as ct

SECOND = 10_000_000          # processor time and timestamps come in 100 ns


def sample(t: float, rows: list[tuple[int, str, float]]) -> dict:
    return {"t": int(t * SECOND), "rows": [{"pid": pid, "kind": kind, "cpu": int(cpu * SECOND), "ws": 0}
                                          for pid, kind, cpu in rows]}


class TraceTests(unittest.TestCase):
    def test_usage_is_the_share_of_one_core(self):
        points = ct.usage([sample(0, [(1, "browser", 0.0), (2, "gpu-process", 1.0)]),
                           sample(10, [(1, "browser", 1.0), (2, "gpu-process", 6.0), (3, "renderer", 9.0)])])
        by_pid = {p["pid"]: p for p in points}
        self.assertAlmostEqual(by_pid[1]["pct"], 10.0)
        self.assertAlmostEqual(by_pid[2]["pct"], 50.0)
        self.assertEqual(by_pid[2]["kind"], "gpu")
        self.assertNotIn(3, by_pid)                   # seen first in the last sample: nothing to compare

    def test_a_process_that_stays_busy_is_a_runaway_and_bursts_are_not(self):
        busy, bursts = [], []
        for i in range(40):                          # 40 intervals of 5 s
            busy.append({"at": i * 5.0, "pid": 7, "kind": "utility", "pct": 80.0, "seconds": 5.0})
            bursts.append({"at": i * 5.0, "pid": 8, "kind": "renderer", "pct": 95.0 if i % 10 < 4 else 3.0,
                           "seconds": 5.0})
        found = ct.runaways(busy + bursts, limit=50, sustain=120)
        self.assertEqual([(r["pid"], r["kind"]) for r in found], [(7, "utility")])
        self.assertEqual(found[0]["seconds"], 200)
        self.assertEqual(found[0]["median_pct"], 80.0)
        self.assertEqual(ct.runaways(bursts, limit=50, sustain=120), [])

    def test_summary(self):
        samples = [sample(0, [(1, "browser", 0.0)]), sample(5, [(1, "browser", 0.5)]),
                   sample(10, [(1, "browser", 0.5), (2, "renderer", 0.0)])]
        result = ct.summary(samples, ct.usage(samples))
        self.assertEqual(result["processes"], {"fewest": 1, "most": 2})
        self.assertEqual(result["kinds"]["browser"]["most_pct"], 10.0)
        self.assertEqual(result["kinds"]["browser"]["median_pct"], 5.0)

    def test_kinds(self):
        self.assertEqual(ct.kind_of("browser"), "browser")
        self.assertEqual(ct.kind_of("crashpad-handler"), "crashpad")
        self.assertEqual(ct.kind_of("broker"), "other")


if __name__ == "__main__":
    unittest.main()
