# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Tests of the Firefox session reader and import (ROADMAP P4.8)."""
import json
import os
import random
import struct
import sys
import tempfile
import time
import unittest
from pathlib import Path

from tools.migrate import firefox_sessions as fs
from tools.migrate import fuzz_firefox_sessions as fuzz
from tools.migrate import sessions as snss
from tools.qa import firefox_session_golden as golden_maker

GOLDEN = Path(__file__).resolve().parent / "data" / "sessions" / "firefox"


def page(n, title=None):
    return {"url": f"https://example.com/{n}", "title": title if title is not None else f"Page {n}"}


def session(*windows, **extra):
    return {"windows": list(windows), **extra}


def packed(state) -> bytes:
    return fs.encode_mozlz4(json.dumps(state).encode("utf-8"))


class Lz4Tests(unittest.TestCase):
    def test_all_literals_round_trip(self):
        for size in (0, 1, 14, 15, 16, 269, 270, 271, 5000):
            data = bytes(random.Random(size).randrange(256) for _ in range(size))
            self.assertEqual(fs.decode_mozlz4(fs.encode_mozlz4(data)), data)

    def test_copies_and_overlapping_copies(self):
        # "abc" then a copy of 9 from 3 back (overlapping) then literals "xyz"
        block = bytes([0x35]) + b"abc" + struct.pack("<H", 3) + bytes([0x30]) + b"xyz"
        self.assertEqual(fs.lz4_block(block, 3 + 9 + 3), b"abc" + b"abcabcabc" + b"xyz")
        long_copy = bytes([0x1F]) + b"a" + struct.pack("<H", 1) + bytes([255, 3]) + bytes([0x10]) + b"b"
        self.assertEqual(fs.lz4_block(long_copy, 1 + 15 + 255 + 3 + 4 + 1), b"a" * (1 + 277) + b"b")

    def test_bad_blocks_are_refused(self):
        bad = {
            "a copy before the start": bytes([0x10]) + b"a" + struct.pack("<H", 2) + bytes([0x10]) + b"b",
            "offset zero": bytes([0x10]) + b"a" + struct.pack("<H", 0) + bytes([0x10]) + b"b",
            "end inside an offset": bytes([0x10]) + b"a" + b"\x01",
            "end inside a length": bytes([0xF0]) + b"\xff",
            "literals past the end": bytes([0x50]) + b"ab",
            "nothing": b"",
        }
        for name, block in bad.items():
            with self.subTest(name), self.assertRaises(fs.FirefoxSessionError):
                fs.lz4_block(block, 100)

    def test_the_size_must_be_exact_and_capped(self):
        data = fs.encode_mozlz4(b"hello")
        for size in (4, 6, 0):
            wrong = bytearray(data)
            struct.pack_into("<I", wrong, 8, size)
            with self.assertRaises(fs.FirefoxSessionError):
                fs.decode_mozlz4(bytes(wrong))
        huge = bytearray(data)
        struct.pack_into("<I", huge, 8, fs.MOST_UNPACKED_BYTES + 1)
        with self.assertRaisesRegex(fs.FirefoxSessionError, "more than"):
            fs.decode_mozlz4(bytes(huge))
        with self.assertRaisesRegex(fs.FirefoxSessionError, "no mozLz4 header"):
            fs.decode_mozlz4(b"mozLz41\0" + data[8:])


class GoldenTests(unittest.TestCase):
    """A session Firefox 160 itself wrote (tools/qa/firefox_session_golden.py)."""

    def setUp(self):
        self.data = (GOLDEN / "sessionstore.jsonlz4").read_bytes()

    def test_the_reading_is_the_expected_one(self):
        expected = json.loads((GOLDEN / "expected.json").read_text(encoding="utf-8"))
        self.assertEqual(fs.read_firefox_session(self.data), expected)

    def test_it_is_the_session_that_was_built(self):
        reading = fs.read_firefox_session(self.data)
        # Firefox headless calls its first window maximized; everything else is as built
        self.assertEqual(golden_maker.plan_problems(reading), ["window 0: show_state is 'maximized', not 'normal'"])

    def test_it_names_nothing_of_the_pc_it_was_made_on(self):
        self.assertEqual(fs.private_problems(fs.decode_mozlz4(self.data)), [])

    def test_the_thoron_file_reads_back_as_the_same_session(self):
        reading = fs.read_firefox_session(self.data)
        back = snss.read_session(fs.to_snss(reading, timestamp=13_400_000_000_000_000))
        self.assertEqual(fs.same_session(reading, back), [])
        self.assertTrue(back["marker"])
        self.assertEqual(back["skipped"]["unknown"] + back["skipped"]["malformed"], 0)
        self.assertEqual(snss.counts(back), {"windows": 2, "tabs": 7, "groups": 3, "pinned": 1})


class ReadingTests(unittest.TestCase):
    def read(self, state):
        return fs.read_firefox_session(packed(state))

    def test_only_web_pages_come_over(self):
        tabs = [{"entries": [{"url": "about:newtab"}]},
                {"entries": [{"url": "about:home"}, page(1), {"url": "moz-extension://x/a.html"}, page(2)],
                 "index": 3},
                {"entries": [{"url": "javascript:alert(1)"}, {"url": "data:text/html,x"}]},
                {"entries": [{"url": "file:///C:/notes.html", "title": "Notes"}, {"url": "ftp://example.com/f"}]}]
        r = self.read(session({"tabs": tabs, "selected": 2}))
        w = r["windows"][0]
        self.assertEqual([[n["url"] for n in t["navigations"]] for t in w["tabs"]],
                         [["https://example.com/1", "https://example.com/2"],
                          ["file:///C:/notes.html", "ftp://example.com/f"]])
        self.assertEqual(w["tabs"][0]["current"], 0)          # Firefox's page 3 (an extension's) was the current
        self.assertEqual(w["selected_tab"], 0)
        self.assertEqual(r["dropped"], {"windows": 0, "tabs": 2, "navigations": 5, "malformed": 0})

    def test_the_current_page_and_long_histories(self):
        r = self.read(session({"tabs": [{"entries": [page(1), page(2), page(3)]},            # no index: the last
                                        {"entries": [page(1), page(2)], "index": 99},           # past the end
                                        {"entries": [page(1), page(2)], "index": -4},           # before the start
                                        {"entries": [page(i) for i in range(200)], "index": 150}]}))
        tabs = r["windows"][0]["tabs"]
        self.assertEqual([t["current"] for t in tabs[:3]], [2, 1, 0])
        long_tab = tabs[3]
        self.assertEqual(len(long_tab["navigations"]), fs.MOST_NAVIGATIONS)
        self.assertEqual(long_tab["navigations"][long_tab["current"]]["url"], "https://example.com/149")
        self.assertEqual([n["index"] for n in long_tab["navigations"]], list(range(fs.MOST_NAVIGATIONS)))
        self.assertEqual(r["dropped"]["navigations"], 150)

    def test_groups_pins_and_order(self):
        tabs = [{"entries": [page(1)], "groupId": "g1"}, {"entries": [page(2)], "pinned": True, "groupId": "g1"},
                {"entries": [page(3)], "groupId": "g1"}, {"entries": [page(4)]},
                {"entries": [page(5)], "groupId": "g1"},              # comes back to g1 after another tab
                {"entries": [page(6)], "groupId": "g2"}, {"entries": [page(7)], "groupId": "missing"}]
        groups = [{"id": "g1", "name": "One", "color": "gray", "collapsed": True},
                  {"id": "g2", "name": "Two", "color": "violet"}]
        r = self.read(session({"tabs": tabs, "groups": groups, "selected": 3}))
        w = r["windows"][0]
        self.assertEqual([t["navigations"][0]["url"][-1] for t in w["tabs"]], list("2134567"))   # pinned first
        self.assertTrue(w["tabs"][0]["pinned"])
        self.assertIsNone(w["tabs"][0]["group"])                                  # a pinned tab is in no group
        g1 = w["groups"][0]["id"]
        self.assertEqual([t["group"] for t in w["tabs"]][1:4], [g1, g1, None])
        self.assertIsNone(w["tabs"][4]["group"])                                  # groups stay side by side
        self.assertEqual(w["tabs"][5]["group"], w["groups"][1]["id"])
        self.assertIsNone(w["tabs"][6]["group"])
        self.assertEqual([(g["title"], g["color"], g["collapsed"]) for g in w["groups"]],
                         [("One", "grey", True), ("Two", "grey", False)])
        self.assertEqual(w["selected_tab"], 2)                                    # page 3, after the pinned move
        self.assertEqual(len({g["id"] for g in w["groups"]}), 2)
        self.assertRegex(g1, r"^[0-9a-f]{32}$")
        self.assertEqual(self.read(session({"tabs": tabs, "groups": groups}))["windows"][0]["groups"][0]["id"], g1)

    def test_windows_and_the_active_one(self):
        r = self.read(session({"tabs": [{"entries": [{"url": "about:blank"}]}]},
                              {"tabs": [{"entries": [page(1)]}], "sizemode": "minimized",
                               "screenX": 2 ** 40, "screenY": -5, "width": "wide", "height": 300},
                              selectedWindow=2))
        self.assertEqual(len(r["windows"]), 1)
        self.assertEqual(r["active_window"], 0)
        self.assertEqual(r["windows"][0]["show_state"], "minimized")
        self.assertEqual(r["windows"][0]["bounds"], [2 ** 31 - 1, -5, 0, 300])
        self.assertEqual(r["dropped"]["windows"], 1)

    def test_text_is_kept_as_thoron_can_store_it(self):
        raw = ('{"windows":[{"tabs":[{"entries":[{"url":"https://example.com/\\ud800","title":"a\\ud800b"},'
               '{"url":"https://example.com/ok","title":"' + "t" * 3000 + '"}]}]}]}')
        r = fs.read_firefox_session(fs.encode_mozlz4(raw.encode("utf-8")))
        navs = r["windows"][0]["tabs"][0]["navigations"]
        self.assertEqual(navs[0]["title"], "a\ufffdb")
        self.assertEqual(len(navs[1]["title"]), fs.MOST_TITLE_CHARS)
        long_url = page("x" * (fs.MOST_URL_BYTES + 1))
        r = self.read(session({"tabs": [{"entries": [long_url, page(1)]}]}))
        self.assertEqual([n["url"] for n in r["windows"][0]["tabs"][0]["navigations"]], ["https://example.com/1"])

    def test_recently_closed_tabs(self):
        r = self.read(session({"tabs": [{"entries": [page(1)]}],
                               "_closedTabs": [{"state": {"entries": [page(8), page(9)], "index": 1}},
                                               {"state": {"entries": [{"url": "about:blank"}]}}, "junk"]}))
        self.assertEqual([[n["url"][-1] for n in t["navigations"]] for t in r["closed_tabs"]], [["8", "9"]])
        self.assertEqual(r["closed_tabs"][0]["current"], 0)

    def test_what_is_not_a_session_is_refused_with_its_own_error(self):
        cases = [b"", b"mozLz40\0", fs.encode_mozlz4(b"\xff\xfe"), fs.encode_mozlz4(b"[" * 100000),
                 fs.encode_mozlz4(b"[]"), fs.encode_mozlz4(b'{"windows": {}}'), fs.encode_mozlz4(b"1e999999"),
                 fs.encode_mozlz4(b'{"windows": [' + b"{}," * (fs.MOST_WINDOWS + 1) + b"{}]}"),
                 fs.encode_mozlz4(b"9" * 5000), b"x" * (fs.MOST_FILE_BYTES + 1)]
        for data in cases:
            with self.subTest(data=data[:20]), self.assertRaises(fs.FirefoxSessionError):
                fs.read_firefox_session(data)
        self.assertTrue(issubclass(fs.FirefoxSessionError, snss.SessionError))

    def test_too_many_tabs_is_refused(self):
        tabs = [{"entries": []}] * (fs.MOST_TABS + 1)
        with self.assertRaisesRegex(fs.FirefoxSessionError, "more than"):
            self.read(session({"tabs": tabs}))


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.firefox = root / "firefox" / "abcd.default-release"
        self.firefox.mkdir(parents=True)
        self.thoron = root / "thoron" / "User Data" / "Default"
        self.thoron.mkdir(parents=True)
        (self.thoron / "Preferences").write_text("{}", encoding="utf-8")
        (self.thoron.parent / "Local State").write_text("{}", encoding="utf-8")
        self.put("sessionstore.jsonlz4", (GOLDEN / "sessionstore.jsonlz4").read_bytes())

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, name, data, age=3600):
        path = self.firefox / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        when = time.time() - age
        os.utime(path, (when, when))
        return path

    def test_the_session_comes_over_and_reads_as_firefox_s(self):
        before = (self.firefox / "sessionstore.jsonlz4").read_bytes()
        done = fs.import_session(self.firefox, self.thoron, now=1_800_000_000)
        self.assertEqual(done["written"], f"Session_{(1_800_000_000 + 11644473600) * 1_000_000}")
        self.assertEqual((done["windows"], done["tabs"], done["groups"], done["pinned"]), (2, 7, 3, 1))
        written = snss.read_session((self.thoron / "Sessions" / done["written"]).read_bytes())
        self.assertEqual(fs.same_session(fs.read_firefox_session(before), written), [])
        self.assertEqual((self.firefox / "sessionstore.jsonlz4").read_bytes(), before)
        snss.restore_on_next_start(self.thoron.parent)
        self.assertTrue(json.loads((self.thoron.parent / "Local State").read_text(encoding="utf-8"))["was"]["restarted"])

    def test_the_newest_file_that_reads_is_taken(self):
        newer = fs.encode_mozlz4(json.dumps(session({"tabs": [{"entries": [page(1)]}]})).encode())
        self.put("sessionstore-backups/recovery.jsonlz4", newer, age=600)
        self.put("sessionstore-backups/recovery.baklz4", b"damaged", age=60)
        path, reading, notes = fs.newest_session(self.firefox)
        self.assertEqual(path.name, "recovery.jsonlz4")
        self.assertEqual(snss.counts(reading)["tabs"], 1)
        self.assertEqual(len(notes), 1)

    def test_refusals(self):
        with self.assertRaisesRegex(fs.ImportRefused, "has started"):
            fs.import_session(self.firefox, self.thoron.parent / "Profile 9")
        self.put("sessionstore.jsonlz4", (GOLDEN / "sessionstore.jsonlz4").read_bytes(), age=1)
        with self.assertRaisesRegex(fs.ImportRefused, "a moment ago"):
            fs.import_session(self.firefox, self.thoron)
        self.put("sessionstore.jsonlz4", packed(session({"tabs": [{"entries": [{"url": "about:home"}]}]})))
        with self.assertRaisesRegex(fs.ImportRefused, "no window with a web page"):
            fs.import_session(self.firefox, self.thoron)
        (self.firefox / "sessionstore.jsonlz4").unlink()
        with self.assertRaisesRegex(fs.ImportRefused, "no session to import"):
            fs.import_session(self.firefox, self.thoron)
        self.assertFalse((self.thoron / "Sessions").exists())

    def test_thoron_s_own_session_is_kept_aside_only_when_asked(self):
        (self.thoron / "Sessions").mkdir()
        own = self.thoron / "Sessions" / "Session_13400000000000000"
        own.write_bytes(snss.snss([]))
        with self.assertRaisesRegex(fs.ImportRefused, "session of its own"):
            fs.import_session(self.firefox, self.thoron)
        done = fs.import_session(self.firefox, self.thoron, set_aside=True)
        self.assertFalse(own.exists())
        self.assertTrue((self.thoron / "Sessions" / done["set_aside"] / own.name).is_file())

    @unittest.skipUnless(sys.platform == "win32", "Firefox's lock is a Windows file it holds open")
    def test_a_running_firefox_is_refused(self):
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateFileW.restype = wintypes.HANDLE
        lock = str(self.firefox / "parent.lock")
        handle = kernel32.CreateFileW(lock, 0xC0000000, 0, None, 2, 0x04000000, None)   # no sharing, delete on close
        self.assertNotEqual(handle, wintypes.HANDLE(-1).value)
        try:
            self.assertTrue(fs.firefox_running(self.firefox))
            with self.assertRaisesRegex(fs.ImportRefused, "Firefox is running"):
                fs.import_session(self.firefox, self.thoron)
        finally:
            kernel32.CloseHandle(handle)
        self.assertFalse(fs.firefox_running(self.firefox))


class FuzzTests(unittest.TestCase):
    def test_a_fixed_run_finds_nothing(self):
        states = fuzz.corpus()
        for seed in range(20261117, 20261117 + 400):
            data = fuzz.mutate(random.Random(seed), states)
            with self.subTest(seed=seed):
                fuzz.check(data)

    def test_a_made_up_session_reads_back_from_thoron_s_file(self):
        for state in fuzz.made_up():
            fuzz.check(packed(state))


if __name__ == "__main__":
    unittest.main()
