# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Memory-leak soak test (ROADMAP Q.4): the verdict, the process tree, the test pages and the report."""
import os
import random
import struct
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
import zlib
from pathlib import Path
from unittest import mock

from tools.qa import soak


def series(level=400.0, count=97, every=300.0, per_hour=0.0, noise=0.0, seed=1, step_at=None, step=0.0):
    """Settled samples: `count` of them, one every `every` seconds (97 every 5 minutes: an 8 h run)."""
    rnd = random.Random(seed)
    out = []
    for i in range(count):
        mb = level + per_hour * i * every / 3600 + (rnd.gauss(0, noise) if noise else 0.0)
        out.append((i * every, mb + (step if step_at is not None and i >= step_at else 0.0)))
    return out


class VerdictTests(unittest.TestCase):
    def test_steady(self):
        v = soak.analyse(series())
        self.assertTrue(v["judged"])
        self.assertFalse(v["leak"])
        self.assertEqual((v["slope"], v["growth"], v["noise"]), (0.0, 0.0, 0.0))
        self.assertEqual((v["samples"], v["judged_samples"]), (97, 49))
        self.assertAlmostEqual(v["hours"], 4.0)

    def test_noisy_but_flat(self):
        for seed in range(25):
            with self.subTest(seed=seed):
                self.assertFalse(soak.analyse(series(noise=8.0, seed=seed))["leak"])
                # a 10-minute run, a sample every 30 s: the same noise is far steeper per hour, and still no leak
                self.assertFalse(soak.analyse(series(noise=8.0, seed=seed, count=21, every=30.0))["leak"])

    def test_leaking(self):
        for seed in range(25):
            with self.subTest(seed=seed):
                v = soak.analyse(series(per_hour=30.0, noise=4.0, seed=seed))
                self.assertTrue(v["leak"])
                self.assertAlmostEqual(v["slope"], 30.0, delta=4.0)
                self.assertAlmostEqual(v["growth"], 120.0, delta=16.0)

    def test_a_slow_leak_under_the_limit_passes_and_a_lower_limit_catches_it(self):
        self.assertFalse(soak.analyse(series(per_hour=4.0))["leak"])
        self.assertTrue(soak.analyse(series(per_hour=4.0), threshold=2.0)["leak"])

    def test_a_step_up_then_flat(self):
        for at in (5, 20, 47, 55, 60, 72, 80, 90):      # in the warm-up half and anywhere in the judged half
            with self.subTest(at=at):
                self.assertFalse(soak.analyse(series(step_at=at, step=80.0))["leak"])
                self.assertFalse(soak.analyse(series(step_at=at, step=80.0, noise=3.0))["leak"])

    def test_growth_that_stopped_is_not_a_leak(self):
        # climbs 40 MB per hour through the third quarter of the run, flat in the last one
        samples = [(t, 400.0 + 40.0 * min(max(t - 14400, 0), 7200) / 3600) for t, _ in series()]
        v = soak.analyse(samples)
        self.assertGreater(v["slope"], v["threshold"])
        self.assertGreater(v["growth"], v["floor"])
        self.assertEqual(v["tail_slope"], 0.0)
        self.assertFalse(v["leak"])

    def test_a_leak_that_starts_late_is_caught(self):
        samples = [(t, 400.0 + 60.0 * max(t - 21600, 0) / 3600) for t, _ in series()]
        self.assertTrue(soak.analyse(samples)["leak"])

    def test_a_saw_tooth_is_not_a_leak(self):
        samples = [(t, 400.0 + 30.0 * (i % 6) / 6) for i, (t, _) in enumerate(series())]
        self.assertFalse(soak.analyse(samples)["leak"])

    def test_growth_below_the_noise_floor_is_not_judged_a_leak(self):
        # 40 MB per hour is a leak over 8 hours; over the judged 5 minutes of a 10-minute run it is 3 MB
        self.assertTrue(soak.analyse(series(per_hour=40.0))["leak"])
        short = soak.analyse(series(per_hour=40.0, count=21, every=30.0))
        self.assertGreater(short["slope"], short["threshold"])
        self.assertLess(short["growth"], short["floor"])
        self.assertFalse(short["leak"])

    def test_too_few_samples_are_not_judged(self):
        v = soak.analyse(series(count=soak.MIN_SETTLED - 1, per_hour=500.0))
        self.assertEqual((v["judged"], v["leak"], v["samples"]), (False, False, soak.MIN_SETTLED - 1))
        self.assertTrue(soak.analyse(series(count=soak.MIN_SETTLED))["judged"])

    def test_trend_line(self):
        line = [(float(x), 2.0 * x + 1.0) for x in range(20)]
        self.assertAlmostEqual(soak.theil_sen(line), 2.0)
        self.assertAlmostEqual(soak.scatter(line, 2.0), 0.0)
        wild = line[:8] + [(8.0, 500.0), (9.0, -300.0)] + line[10:]
        self.assertAlmostEqual(soak.theil_sen(wild), 2.0)           # two outliers do not move it
        self.assertEqual(soak.theil_sen([(1.0, 5.0)]), 0.0)
        self.assertEqual(soak.theil_sen([(1.0, 5.0), (1.0, 9.0)]), 0.0)
        self.assertAlmostEqual(soak.scatter([(0.0, 0.0), (1.0, 2.0), (2.0, -2.0), (3.0, 0.0)], 0.0), 1.4826)

    def test_noise_from_the_jumps(self):
        self.assertEqual(soak.jump_scatter([(0.0, 5.0)]), 0.0)
        self.assertAlmostEqual(soak.jump_scatter(series(per_hour=50.0)), 0.0)   # a steady climb is no noise
        self.assertEqual(soak.jump_scatter(series(step_at=40, step=90.0)), 0.0)  # nor is one step
        rnd = random.Random(7)
        noisy = [(float(i), 300.0 + 2.0 * i + rnd.gauss(0, 6.0)) for i in range(2000)]
        self.assertAlmostEqual(soak.jump_scatter(noisy), 6.0, delta=0.6)
        self.assertAlmostEqual(soak.scatter(noisy, 2.0), 6.0, delta=0.6)

    def test_the_larger_noise_estimate_counts(self):
        # few samples: the scatter around the line of the judged half can come out small by chance
        samples = series(noise=8.0, seed=13, count=21, every=30.0)
        v = soak.analyse(samples)
        half = samples[len(samples) // 2:]
        self.assertGreater(v["noise"], soak.scatter(half, soak.theil_sen(half)))
        self.assertEqual(v["noise"], soak.jump_scatter(samples))
        self.assertEqual(v["floor"], soak.NOISE_TIMES * v["noise"])
        self.assertFalse(v["leak"])

    def test_waiting_until_the_processes_stand_still(self):
        def waited(counts, quiet=5.0, limit=30.0):
            clock, left = [0.0], list(counts)
            ok = soak.wait_quiet(lambda: left.pop(0) if len(left) > 1 else left[0], quiet, limit,
                                 sleep=lambda s: clock.__setitem__(0, clock[0] + s), clock=lambda: clock[0])
            return ok, clock[0]

        self.assertEqual(waited([9]), (True, 5.0))                          # still from the start
        self.assertEqual(waited([15, 12, 9]), (True, 7.0))                  # two more leave, then 5 s of quiet
        self.assertEqual(waited([15, 15, 15, 12, 9]), (True, 9.0))
        self.assertEqual(waited(list(range(100, 0, -1))), (False, 30.0))    # never still: it gives up
        self.assertEqual(waited([9], quiet=0.5), (True, 0.5))

    def test_lengths_of_time(self):
        self.assertEqual([soak.seconds(t) for t in ("8h", "5m", "90s", "45", "1.5h", " 10 M ")],
                         [28800, 300, 90, 45, 5400, 600])
        for bad in ("", "0", "abc", "-5m", "5d", "h"):
            with self.assertRaises(ValueError):
                soak.seconds(bad)


def proc(pid, ppid, born, cmd="", mb=0):
    return {"pid": pid, "ppid": ppid, "born": born, "cmd": cmd, "private": mb * 2**20}


TREE = [proc(1, 0, 10, "init", 5),
        proc(10, 1, 100, "thoron.exe --user-data-dir=x about:blank", 100),
        proc(11, 10, 110, "thoron.exe --type=renderer --lang=en-US", 40),
        proc(12, 10, 105, "thoron.exe --type=gpu-process", 60),
        proc(13, 10, 106, "thoron.exe --type=utility --utility-sub-type=network.mojom.NetworkService", 20),
        proc(14, 10, 103, "thoron.exe --type=crashpad-handler --monitor-self-argument=--type=crashpad-handler", 6),
        proc(15, 14, 104, "thoron.exe --type=crashpad-handler", 6),
        proc(16, 10, 120, "thoron.exe --type=renderer --extension-process", 30),
        proc(20, 1, 50, "another.exe", 9999),
        proc(21, 11, 60, "orphan.exe: its parent 11 has gone, and the number went to a renderer", 7777)]


class ProcessTreeTests(unittest.TestCase):
    def test_family_is_every_descendant_and_nothing_else(self):
        self.assertEqual(sorted(p["pid"] for p in soak.family(TREE, 10)), [10, 11, 12, 13, 14, 15, 16])

    def test_a_process_older_than_its_parent_number_is_not_a_child(self):
        self.assertNotIn(21, [p["pid"] for p in soak.family(TREE, 10)])
        self.assertIn(21, [p["pid"] for p in soak.family([dict(p, born=0) for p in TREE], 10)])

    def test_a_missing_root_is_an_error(self):
        with self.assertRaises(soak.SoakError):
            soak.family(TREE, 99)

    def test_process_types(self):
        self.assertEqual([soak.process_type(p["cmd"]) for p in TREE[2:7]],
                         ["renderer", "gpu", "utility", "other", "other"])
        self.assertEqual(soak.process_type("helper.exe"), "other")

    def test_memory_by_type(self):
        m = soak.by_type(soak.family(TREE, 10), 10)
        self.assertEqual({t: m[t] for t in soak.TYPES},
                         {"browser": 100.0, "gpu": 60.0, "renderer": 70.0, "utility": 20.0, "other": 12.0})
        self.assertEqual((m["total"], m["processes"], m["renderers"]), (262.0, 7, 2))

    def test_csv_row_matches_the_header(self):
        row = soak.csv_row(12.34, "settled", 0, soak.by_type(soak.family(TREE, 10), 10))
        self.assertEqual(len(row), len(soak.CSV_HEADER))
        self.assertEqual(row[:4], [12.3, "settled", 0, 262.0])
        self.assertEqual(row[-2:], [7, 2])

    def test_linux_private_memory(self):
        status = ("Name:\tthoron\nVmRSS:\t  90000 kB\nRssAnon:\t   40000 kB\nRssFile:\t   50000 kB\n"
                  "VmSwap:\t    2000 kB\n")
        self.assertEqual(soak.linux_private(status), 42000 * 1024)
        self.assertEqual(soak.linux_private("Name:\tkthreadd\n"), 0)

    @unittest.skipUnless(os.name == "nt" or Path("/proc/self/status").is_file(), "no way to read processes here")
    def test_reads_this_process_and_a_child_from_the_system(self):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        try:
            tree = soak.process_tree(os.getpid())
            self.assertEqual(tree[0]["pid"], os.getpid())
            self.assertGreater(tree[0]["private"], 2**20)
            mine = [p for p in tree if p["pid"] == child.pid]
            self.assertEqual(len(mine), 1)
            self.assertIn("time.sleep(60)", mine[0]["cmd"])
            self.assertGreaterEqual(mine[0]["born"], tree[0]["born"])
        finally:
            child.kill()
            child.wait(timeout=20)


class PageTests(unittest.TestCase):
    def test_png_is_a_valid_picture_of_noise(self):
        data = soak.png(40, 30, seed=3)
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        chunks, at = {}, 8
        while at < len(data):
            size, kind = struct.unpack(">I4s", data[at:at + 8])
            body = data[at + 8:at + 8 + size]
            self.assertEqual(struct.unpack(">I", data[at + 8 + size:at + 12 + size])[0], zlib.crc32(kind + body))
            chunks[kind] = body
            at += 12 + size
        self.assertEqual(list(chunks), [b"IHDR", b"IDAT", b"IEND"])
        self.assertEqual(struct.unpack(">IIBBBBB", chunks[b"IHDR"]), (40, 30, 8, 2, 0, 0, 0))
        self.assertEqual(len(zlib.decompress(chunks[b"IDAT"])), 30 * (1 + 40 * 3))
        self.assertEqual(data, soak.png(40, 30, seed=3))
        self.assertNotEqual(data, soak.png(40, 30, seed=4))

    def test_pages_say_when_they_are_done_and_ask_for_nothing_outside(self):
        pages = {"dom": soak.dom_page(), "images": soak.images_page(), "script": soak.script_page()}
        self.assertEqual(tuple(pages), soak.KINDS)
        for kind, page in pages.items():
            with self.subTest(kind=kind):
                self.assertIn(f"fetch('/done/{kind}')", page)
                self.assertIn("done();", page)
                self.assertNotIn("http", page)
                self.assertNotIn("//", page.replace("</", ""))
        self.assertEqual(soak.dom_page(rows=7).count("<tr "), 7)
        self.assertEqual(soak.images_page(count=5).count("<img "), 5)

    def test_server_serves_the_pages_and_counts_the_finished_ones(self):
        with soak.Pages() as pages:
            self.assertTrue(pages.base.startswith("http://127.0.0.1:"))
            for kind in soak.KINDS:
                reply = urllib.request.urlopen(pages.url(kind), timeout=5)
                self.assertEqual(reply.headers["Cache-Control"], "no-store")
                self.assertIn(f"<title>soak {kind}</title>", reply.read().decode("utf-8"))
            picture = urllib.request.urlopen(pages.url("image/7.png"), timeout=5)
            self.assertEqual(picture.headers["Content-Type"], "image/png")
            self.assertEqual(picture.read()[:8], b"\x89PNG\r\n\x1a\n")
            for missing in ("nothing", "image/x.png"):
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(pages.url(missing), timeout=5)
                self.assertEqual(caught.exception.code, 404)
            self.assertFalse(pages.wait(1, 0.05))
            urllib.request.urlopen(pages.url("done/dom"), timeout=5).read()
            urllib.request.urlopen(pages.url("done/script"), timeout=5).read()
            self.assertTrue(pages.wait(2, 5))
            self.assertEqual(pages.loaded, 2)


class FakeBrowser:
    """Stands in for the browser's process: it counts how often it is ended."""

    def __init__(self):
        self.alive, self.killed = True, 0

    def poll(self):
        return None if self.alive else 0

    def kill(self):
        self.killed += 1
        self.alive = False

    def wait(self, timeout=None):
        return 0


class BrowserTests(unittest.TestCase):
    def test_the_browser_is_started_offline_with_its_sandbox_on(self):
        with mock.patch.object(soak.subprocess, "Popen") as popen:
            soak.launch(Path("thoron.exe"), Path("profile"), ("--one-more",))
        args = popen.call_args.args[0]
        self.assertEqual(args[0], "thoron.exe")
        for wanted in ("--headless=new", f"--user-data-dir={Path('profile')}", "--disable-background-networking",
                       "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
                       "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0"):
            self.assertIn(wanted, args)
        self.assertEqual(args[-2:], ["--one-more", "about:blank"])
        self.assertFalse([a for a in args if "no-sandbox" in a or "disable-gpu-sandbox" in a])

    def test_stop_asks_the_browser_to_close(self):
        browser, calls = FakeBrowser(), []

        class Socket:
            def __init__(self, url):
                calls.append(url)

            def call(self, method, **params):
                calls.append(method)
                browser.alive = False

            def close(self):
                calls.append("closed")

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(soak.time, "sleep"), \
                mock.patch.object(soak, "_get", return_value={"webSocketDebuggerUrl": "ws://127.0.0.1:9/x"}), \
                mock.patch.object(soak, "WebSocket", Socket), mock.patch.object(soak.subprocess, "run") as run:
            profile = Path(tmp) / "profile"
            (profile / "Default").mkdir(parents=True)
            soak.stop(browser, 9, profile)
            self.assertFalse(profile.exists())
        self.assertEqual(calls, ["ws://127.0.0.1:9/x", "Browser.close", "closed"])
        self.assertEqual(browser.killed, 0)
        run.assert_not_called()

    def test_stop_ends_only_the_process_it_started_when_it_does_not_close(self):
        for port in (None, 9):
            with self.subTest(port=port), tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(soak.time, "sleep"), mock.patch.object(soak.subprocess, "run") as run, \
                    mock.patch.object(soak, "_get", side_effect=OSError("no answer")):
                browser, profile = FakeBrowser(), Path(tmp) / "profile"
                profile.mkdir()
                soak.stop(browser, port, profile)
                self.assertEqual(browser.killed, 1)             # through its own handle
                self.assertFalse(profile.exists())
                run.assert_not_called()                         # no taskkill: nothing is ended by name or number


def result(samples, **changes):
    out = {"seconds": samples[-1][0] if samples else 0.0, "rounds": 100, "tabs": 6, "opened": 600, "loaded": 600,
           "peak": 800.0, "errors": [], "crash_dumps": [], "verdict": soak.analyse(samples),
           "slopes": {t: 0.0 for t in soak.TYPES}}
    out.update(changes)
    return out


class ReportTests(unittest.TestCase):
    def test_a_clean_run_passes(self):
        good = result(series(noise=2.0))
        self.assertEqual(soak.problems(good), [])
        text = soak.report(good)
        self.assertIn("8.00 h, 100 rounds of 6 tabs, 600 pages opened, 600 finished their work, 97 settled", text)
        self.assertIn("with the tabs open: at most 800.0", text)
        self.assertIn("trend over the second half (4.00 h, 49 samples)", text)
        self.assertIn("trend by process type, MB per hour: browser +0.00, gpu +0.00", text)
        self.assertTrue(text.endswith("SOAK: PASSED"))

    def test_a_leak_fails_with_its_numbers(self):
        leaking = result(series(per_hour=30.0))
        found = soak.problems(leaking)
        self.assertEqual(len(found), 1)
        self.assertIn("memory keeps growing: +30.0 MB per hour", found[0])
        self.assertIn("the limit is 10 MB per hour", found[0])
        self.assertTrue(soak.report(leaking).endswith("SOAK: FAILED (1 problem(s))"))

    def test_what_else_fails_a_run(self):
        flat = series()
        self.assertIn("only 500 of 600 pages", soak.problems(result(flat, loaded=500))[0])
        self.assertEqual(soak.problems(result(flat, loaded=580)), [])        # a few closed mid-load is no failure
        self.assertIn("only 0 of 0 pages", soak.problems(result(flat, opened=0, loaded=0))[0])
        self.assertIn("crash dump(s) written: a.dmp", soak.problems(result(flat, crash_dumps=["a.dmp"]))[0])
        self.assertEqual(soak.problems(result(flat, errors=["the run stopped early: x"])), ["the run stopped early: x"])
        short = result(series(count=5))
        self.assertIn("only 5 settled sample(s), 20 are needed", soak.problems(short)[0])
        self.assertIn("SOAK: FAILED", soak.report(short))

    def test_garbage_collection_that_could_not_be_forced(self):
        why = "garbage collection could not be forced: timed out"
        now_and_then = result(series(), unforced=[why] * 3)
        self.assertEqual(soak.problems(now_and_then), [])
        self.assertIn(f"Note: before 3 settled sample(s), {why}\n", soak.report(now_and_then))
        self.assertNotIn("Note:", soak.report(result(series())))
        never = result(series(), unforced=[why] * 97)
        self.assertEqual(soak.problems(never), [f"no settled sample is comparable: every time, {why}"])


if __name__ == "__main__":
    unittest.main()
