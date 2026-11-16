# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""The performance gate of a release (ROADMAP Q.3)."""
import unittest

from tools.qa import perf_gate as pg


def run(median, spread=1.0):
    return {"median": median, "spread_pct": spread, "runs": 5, "repeatable": spread <= 3}


BASE = {"browser": "Thoron 0.1.1", "startup_ms": run(400.0), "memory_1_tab_mb": run(180.0),
        "memory_20_tabs_mb": run(900.0), "idle_cpu_pct": run(0.4, 20.0)}


class RegressionTests(unittest.TestCase):
    def test_the_same_or_better_is_no_regression(self):
        self.assertEqual(pg.regressions(BASE, BASE), [])
        better = dict(BASE, startup_ms=run(300.0), memory_20_tabs_mb=run(800.0))
        self.assertEqual(pg.regressions(BASE, better), [])

    def test_an_injected_regression_is_found(self):
        slower = dict(BASE, startup_ms=run(480.0))  # 20 % and 80 ms
        found = pg.regressions(BASE, slower)
        self.assertEqual([r["measure"] for r in found], ["startup_ms"])
        self.assertEqual(found[0]["rise_pct"], 20.0)

    def test_a_small_rise_is_not_one(self):
        # 9 % is under the share; 25 ms is under the amount
        self.assertEqual(pg.regressions(BASE, dict(BASE, startup_ms=run(436.0))), [])
        small = dict(BASE, startup_ms=run(100.0))
        self.assertEqual(pg.regressions(small, dict(small, startup_ms=run(125.0))), [])
        # idle CPU from 0.4 to 0.8: 100 % but not half a point
        self.assertEqual(pg.regressions(BASE, dict(BASE, idle_cpu_pct=run(0.8, 20.0))), [])

    def test_noise_is_not_a_regression(self):
        noisy = dict(BASE, memory_20_tabs_mb=run(1020.0, spread=8.0))  # 13 % rise, but runs spread 8 %
        self.assertEqual(pg.regressions(BASE, noisy), [])
        steady = dict(BASE, memory_20_tabs_mb=run(1020.0, spread=1.0))
        self.assertEqual([r["measure"] for r in pg.regressions(BASE, steady)], ["memory_20_tabs_mb"])

    def test_a_measure_not_measured_is_a_problem(self):
        found = pg.problems(BASE, {k: v for k, v in BASE.items() if k != "idle_cpu_pct"}, "0.1.2", "")
        self.assertEqual(found, ["idle_cpu_pct was not measured for this release"])
        # a measure the baseline lacks is not asked for
        self.assertEqual(pg.regressions({"startup_ms": run(400.0)}, {"startup_ms": run(400.0)}), [])


class ExplanationTests(unittest.TestCase):
    SLOWER = dict(BASE, startup_ms=run(480.0))

    def test_unexplained_blocks(self):
        found = pg.problems(BASE, self.SLOWER, "0.1.2", "")
        self.assertEqual(len(found), 1)
        self.assertIn("startup_ms rose 20.0 %", found[0])

    def test_an_explanation_for_the_version_and_the_measure_lets_it_pass(self):
        md = "# Explained\n\n- 0.1.2 startup_ms: the ad blocker loads its lists at start; 80 ms, accepted.\n"
        self.assertEqual(pg.problems(BASE, self.SLOWER, "0.1.2", md), [])

    def test_an_explanation_of_another_version_or_measure_or_without_a_reason_does_not(self):
        for md in ("- 0.1.1 startup_ms: an older release had the same rise, explained then.\n",
                   "- 0.1.2 memory_1_tab_mb: something else entirely rose in this one.\n",
                   "- 0.1.2 startup_ms: ok\n",
                   "0.1.2 startup_ms: not written as a list item, so not read.\n"):
            self.assertEqual(len(pg.problems(BASE, self.SLOWER, "0.1.2", md)), 1, md)


if __name__ == "__main__":
    unittest.main()
