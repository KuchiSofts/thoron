# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""The session reader and the tabs import (ROADMAP P3.15): golden files of real browsers read to their JSON, the
browser's replay rules, and bad input (cut, flipped, oversized) that gives SessionError and nothing else."""
import contextlib
import io
import json
import os
import random
import re
import shutil
import struct
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from tools.migrate import fuzz_sessions as fuzz
from tools.migrate import import_profile as ip
from tools.migrate import sessions as s

GOLDEN = Path(__file__).resolve().parent / "data" / "sessions"
BROWSERS = ("chrome", "thorium", "thoron")
NAV = s.navigation_pickle


def folder_link(link: Path, target: Path, junction: bool) -> bool:
    """Makes `link` point at the folder `target`: a junction (Windows only, needs no rights) or a symbolic link.
    False when this system cannot make that kind."""
    if junction:
        return os.name == "nt" and subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                                                 capture_output=True).returncode == 0
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        return False
    return True


def remove_link(link: Path) -> None:
    """Removes the link or junction at `link`, never what it points at."""
    try:
        os.rmdir(link)                  # a junction, or a link to a folder on Windows
    except OSError:
        os.unlink(link)


def golden(browser: str) -> tuple[Path, Path, dict]:
    folder = GOLDEN / browser
    session = next(folder.glob("Session_*"))
    tabs = next(folder.glob("Tabs_*"))
    return session, tabs, json.loads((folder / "expected.json").read_text(encoding="utf-8"))


def cmd(cid: int, fmt: str, *values) -> bytes:
    return s.command(cid, struct.pack(fmt, *values))


def window(wid: int, kind: int = 0) -> bytes:
    return cmd(s.S_WINDOW_TYPE, "<ii", wid, kind)


def tab(wid: int, tid: int, visual: int, *urls: str) -> list[bytes]:
    out = [cmd(s.S_TAB_WINDOW, "<ii", wid, tid), cmd(s.S_TAB_INDEX, "<ii", tid, visual)]
    out += [s.command(s.S_NAVIGATION, NAV(tid, i, u, u.upper())) for i, u in enumerate(urls)]
    return out + [cmd(s.S_SELECTED_NAVIGATION, "<ii", tid, len(urls) - 1)]


def metadata(token: tuple, title: str, colour: int, collapsed: bool, saved: str | None = None) -> bytes:
    w = s.PickleWriter().u64(token[0]).u64(token[1]).string16(title).u32(colour).bool(collapsed).bool(bool(saved))
    if saved:
        w.string(saved)
    return s.command(s.S_GROUP_METADATA2, w.done())


def urls(t: dict) -> list[str]:
    return [n["url"] for n in t["navigations"]]


class GoldenTests(unittest.TestCase):
    def test_each_browser_reads_to_its_json(self):
        for browser in BROWSERS:
            with self.subTest(browser=browser):
                session, tabs, expected = golden(browser)
                self.assertEqual(s.read_session(session.read_bytes()), expected["session"])
                self.assertEqual(s.read_closed(tabs.read_bytes()), expected["closed"])

    def test_vivaldi_and_opera_read_to_their_json(self):
        # each browser's own session (made in Windows Sandbox by sandbox_vivaldi_opera_check.py): one window with the
        # two local pages it was opened with; no recently closed list was written
        for browser in ("vivaldi", "opera"):
            with self.subTest(browser=browser):
                folder = GOLDEN / browser
                expected = json.loads((folder / "expected.json").read_text(encoding="utf-8"))
                reading = s.read_session(next(folder.glob("Session_*")).read_bytes())
                self.assertEqual(reading, expected["session"])
                urls = [n["url"] for w in reading["windows"] for t in w["tabs"] for n in t["navigations"]]
                self.assertEqual(urls, ["http://127.0.0.1:47640/p/thoron-tab-one",
                                        "http://127.0.0.1:47640/p/thoron-tab-two"])

    def test_the_golden_sessions_hold_what_was_built(self):
        for browser in BROWSERS:
            with self.subTest(browser=browser):
                reading = golden(browser)[2]["session"]
                self.assertEqual(s.counts(reading), {"windows": 2, "tabs": 7, "groups": 3, "pinned": 1})
                first, second = reading["windows"]
                self.assertEqual([(g["title"], g["color"], g["collapsed"]) for g in first["groups"]],
                                 [("Work", "blue", False), ("Later", "red", True)])
                self.assertEqual(second["groups"][0]["title"], "Notes \u00e9\u00fc")
                self.assertEqual((first["selected_tab"], second["selected_tab"], reading["active_window"]), (4, 1, 0))
                self.assertEqual((first["show_state"], second["show_state"]), ("normal", "minimized"))
                gone_back = first["tabs"][1]
                self.assertEqual((len(gone_back["navigations"]), gone_back["current"]), (3, 1))
                self.assertTrue(first["tabs"][0]["pinned"])
                self.assertEqual(reading["skipped"], {"unknown": 0, "malformed": 0, "over_limit": 0})
                self.assertTrue(reading["marker"] and reading["complete"])

    def test_copying_a_golden_file_command_by_command_gives_its_bytes(self):
        for browser in BROWSERS:
            for path in golden(browser)[:2]:
                data = path.read_bytes()
                self.assertEqual(s.rewrite(data, lambda cid, payload: payload), data)

    def test_the_golden_files_hold_no_path_address_or_page_of_a_pc(self):
        patterns = (r"(?<![A-Za-z])[A-Za-z]:[\\/]", r"(?i)[\\/]users[\\/]", r"[\w.+-]+@[\w-]+\.[A-Za-z]{2,}", r"file:", r"extension:",
                    r"https?://(?!127\.0\.0\.1:47615(?![0-9]))")       # only the local test pages and their origin
        for browser in BROWSERS:
            for path in list(golden(browser)[:2]) + [GOLDEN / browser / "expected.json"]:
                raw = path.read_bytes()
                for text in (raw.decode("latin-1"), raw.decode("utf-16-le", "replace"),
                             raw[1:].decode("utf-16-le", "replace")):
                    for pattern in patterns:
                        found = re.search(pattern, text)
                        self.assertIsNone(found, f"{browser}/{path.name} holds {found and found.group()!r}")


class BadInputTests(unittest.TestCase):
    def setUp(self):
        self.data = golden("chrome")[0].read_bytes()
        self.tabs = golden("chrome")[1].read_bytes()

    def read_any(self, data: bytes) -> None:
        for reader in (s.read_session, s.read_closed):
            try:
                json.dumps(reader(data))
            except s.SessionError:
                pass

    def test_headers_that_are_refused(self):
        for data, why in ((b"", "empty"), (b"SNS", "SNSS"), (b"XXXX\x03\x00\x00\x00", "SNSS"),
                          (b"SNSS\x01\x00\x00\x00", "version 1"), (b"SNSS\x05\x00\x00\x00", "encrypted"),
                          (b"SNSS\x04\x00\x00\x00", "encrypted")):
            with self.subTest(data=data), self.assertRaisesRegex(s.SessionError, why):
                s.read_session(data)
        with self.assertRaises(s.SessionError):
            s.read_session("SNSS")              # not bytes

    def test_every_cut_reads_or_is_refused(self):
        offsets = list(range(0, 80)) + list(range(80, len(self.data), 61)) + [len(self.data) - 1]
        for n in offsets:
            self.read_any(self.data[:n])
        reading = s.read_session(self.data[:len(self.data) - 5])
        self.assertFalse(reading["complete"])

    def test_flipped_bits_read_or_are_refused(self):
        rng = random.Random(7)
        for data in (self.data, self.tabs):
            for _ in range(250):
                flipped = bytearray(data)
                for _ in range(rng.randint(1, 6)):
                    i = rng.randrange(len(flipped))
                    flipped[i] ^= 1 << rng.randrange(8)
                self.read_any(bytes(flipped))

    def test_a_huge_command_size_is_a_torn_end(self):
        data = s.snss([window(1)]) + struct.pack("<HB", 0xFFFF, s.S_TAB_WINDOW) + b"\0" * 10
        reading = s.read_session(data)
        self.assertEqual((reading["complete"], reading["commands"]), (False, 1))
        self.assertFalse(s.read_session(s.snss([]) + b"\x00")["complete"])
        self.assertFalse(s.read_session(s.snss([]) + b"\x00\x00\x07")["complete"])     # size 0

    def test_huge_lengths_inside_a_pickle_are_malformed_commands(self):
        for length in (0x7FFFFFFF, 0xFFFFFFFF, 0x80000000, 40):
            body = struct.pack("<iiI", 2, 0, length)        # a tab, an index, then the address's length
            payload = struct.pack("<I", len(body)) + body
            reading = s.read_session(s.snss([window(1), s.command(s.S_NAVIGATION, payload)]))
            self.assertEqual(reading["skipped"]["malformed"], 1)
        bad_pickle = s.command(s.S_NAVIGATION, struct.pack("<I", 0xFFFFFFF0) + b"\0" * 8)
        self.assertEqual(s.read_session(s.snss([bad_pickle]))["skipped"]["malformed"], 1)

    def test_a_file_larger_than_the_limit_is_refused_before_it_is_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            big = Path(tmp) / "Session_1"
            big.write_bytes(self.data)
            with mock.patch.object(s, "MOST_FILE_BYTES", 1000):
                with self.assertRaisesRegex(s.SessionError, "larger"):
                    s.read_bytes(big)
                with self.assertRaisesRegex(s.SessionError, "larger"):
                    s.read_session(self.data)
            with self.assertRaisesRegex(s.SessionError, "cannot be read"):
                s.read_bytes(Path(tmp) / "missing")

    def test_too_many_commands_or_too_much_work_is_refused(self):
        with mock.patch.object(s, "MOST_COMMANDS", 10), self.assertRaisesRegex(s.SessionError, "commands"):
            s.read_session(self.data)
        many = [window(1)] + tab(1, 2, 0, *[f"http://127.0.0.1/{i}" for i in range(400)])
        prunes = [cmd(s.S_PRUNED, "<iii", 2, 5000, 1)] * 2000
        started = time.perf_counter()
        with mock.patch.object(s, "MOST_WORK", 50_000), self.assertRaisesRegex(s.SessionError, "too long"):
            s.read_session(s.snss(many + prunes))
        self.assertLess(time.perf_counter() - started, 5)

    def test_counts_past_the_limits_are_skipped_and_counted(self):
        commands = [window(1)]
        for tid in range(2, 12):
            commands += tab(1, tid, tid, f"http://127.0.0.1/{tid}")
        with mock.patch.object(s, "MOST_TABS", 3):
            reading = s.read_session(s.snss(commands))
        self.assertEqual(len(reading["windows"][0]["tabs"]), 3)
        self.assertGreater(reading["skipped"]["over_limit"], 0)
        with mock.patch.object(s, "MOST_NAVIGATIONS", 2):
            reading = s.read_session(s.snss([window(1)] + tab(1, 2, 0, "a", "b", "c", "d")))
        self.assertEqual(urls(reading["windows"][0]["tabs"][0]), ["a", "b"])

    def test_unknown_and_malformed_commands_are_skipped_and_counted(self):
        data = s.snss([window(1)] + tab(1, 2, 0, "http://127.0.0.1/a") + [
            s.command(99, b"anything"), s.command(200, b""), cmd(s.S_PINNED, "<i", 2),
            s.command(s.S_GROUP_METADATA2, b"\x01\x02"), cmd(s.S_ACTIVE_WINDOW, "<ii", 1, 1)])
        reading = s.read_session(data)
        self.assertEqual(reading["skipped"], {"unknown": 2, "malformed": 3, "over_limit": 0})
        self.assertEqual(reading["unknown_ids"], [99, 200])
        self.assertEqual(urls(reading["windows"][0]["tabs"][0]), ["http://127.0.0.1/a"])

    def test_text_that_is_not_valid_unicode_is_replaced(self):
        raw = s.PickleWriter().int(2).int(0).bytes(b"http://127.0.0.1/\xff").string16_raw(b"\x00\xd8")
        payload = raw.bytes(b"").int(0).done()
        reading = s.read_session(s.snss([window(1), cmd(s.S_TAB_WINDOW, "<ii", 1, 2),
                                          s.command(s.S_NAVIGATION, payload)]))
        nav = reading["windows"][0]["tabs"][0]["navigations"][0]
        self.assertEqual((nav["url"], nav["title"]), ("http://127.0.0.1/\ufffd", "\ufffd"))
        json.dumps(reading)


class ReplayTests(unittest.TestCase):
    """The browser's rules (session_service_commands.cc), on small made-up files."""

    def test_order_windows_and_what_is_dropped(self):
        data = s.snss([window(5), window(3), cmd(s.S_WINDOW_BOUNDS3, "<iiiiii", 3, 1, 2, 30, 40, 2),
                       *tab(5, 10, 1, "b"), *tab(5, 11, 0, "a"), *tab(5, 12, 1, "c"), *tab(3, 13, 0, "x"),
                       *tab(7, 14, 0, "no type, a constrained window"), cmd(s.S_TAB_INDEX, "<ii", 15, 0),
                       s.command(s.S_NAVIGATION, NAV(15, 0, "no window", "")), *tab(3, 16, 1),
                       cmd(s.S_SELECTED_TAB, "<ii", 5, 1), cmd(s.S_SELECTED_TAB, "<ii", 3, 9),
                       cmd(s.S_ACTIVE_WINDOW, "<i", 5)])
        reading = s.read_session(data)
        self.assertEqual([w["id"] for w in reading["windows"]], [3, 5])           # by id: the order they opened
        self.assertEqual([urls(t) for t in reading["windows"][1]["tabs"]], [["a"], ["b"], ["c"]])
        self.assertEqual(reading["windows"][1]["selected_tab"], 1)                  # visual index 1, first by id
        self.assertEqual(reading["windows"][0]["selected_tab"], 0)                  # no tab at 9: the first
        self.assertEqual((reading["windows"][0]["show_state"], reading["windows"][0]["bounds"]),
                         ("minimized", [1, 2, 30, 40]))
        self.assertEqual(reading["active_window"], 1)
        self.assertEqual(len(reading["windows"][0]["tabs"]), 1)                     # a tab without pages is dropped

    def test_closing_a_tab_or_a_window(self):
        data = s.snss([window(1), window(2), *tab(1, 3, 0, "a"), *tab(1, 4, 1, "b"), *tab(2, 5, 0, "c"),
                       cmd(s.S_TAB_CLOSED, "<i4xq", 3, 0), cmd(s.S_WINDOW_CLOSED, "<i4xq", 2, 0)])
        reading = s.read_session(data)
        self.assertEqual([[urls(t) for t in w["tabs"]] for w in reading["windows"]], [[["b"]]])

    def test_navigations_are_replaced_pruned_and_the_current_one_found(self):
        data = s.snss([window(1), *tab(1, 2, 0, "a", "b", "c", "d", "e"),
                       s.command(s.S_NAVIGATION, NAV(2, 1, "b2", "B2")),            # same index: replaced
                       cmd(s.S_SELECTED_NAVIGATION, "<ii", 2, 3),
                       cmd(s.S_PRUNED, "<iii", 2, 0, 2)])                          # a and b2 gone, d is at 1
        t = s.read_session(data)["windows"][0]["tabs"][0]
        self.assertEqual(urls(t), ["c", "d", "e"])
        self.assertEqual([n["index"] for n in t["navigations"]], [0, 1, 2])
        self.assertEqual(t["current"], 1)
        data = s.snss([window(1), *tab(1, 2, 0, "a", "b", "c"), cmd(s.S_PRUNED_BACK, "<ii", 2, 1),
                       cmd(s.S_SELECTED_NAVIGATION, "<ii", 2, 7)])
        t = s.read_session(data)["windows"][0]["tabs"][0]
        self.assertEqual((urls(t), t["current"]), (["a"], 0))                       # past the end: the last
        data = s.snss([window(1), *tab(1, 2, 0, "a", "b", "c"), cmd(s.S_PRUNED_FRONT, "<ii", 2, 2),
                       cmd(s.S_PRUNED_FRONT, "<ii", 2, 0)])                         # 0 is malformed
        reading = s.read_session(data)
        self.assertEqual((urls(reading["windows"][0]["tabs"][0]), reading["skipped"]["malformed"]), (["c"], 1))

    def test_pinned_tabs_groups_and_their_looks(self):
        work, other = (1, 2), (0xFFFFFFFFFFFFFFFF, 3)
        data = s.snss([window(1), *tab(1, 2, 0, "p"), cmd(s.S_PINNED, "<i?3x", 2, True), *tab(1, 3, 1, "g1"),
                       *tab(1, 4, 2, "g2"), *tab(1, 5, 3, "h"),
                       cmd(s.S_TAB_GROUP, "<i4xQQ?7x", 4, *other, True), cmd(s.S_TAB_GROUP, "<i4xQQ?7x", 3, *work, True),
                       cmd(s.S_TAB_GROUP, "<i4xQQ?7x", 5, *work, True), cmd(s.S_TAB_GROUP, "<i4xQQ?7x", 5, 0, 0, False),
                       metadata(work, "Work \u05d0", 4, True, "0e4c1a34-5f7c-4b1e-9d2a-6f3b8c2d1e0f"),
                       metadata(work, "Work", 99, False)])                         # the last one counts; 99 is grey
        w = s.read_session(data)["windows"][0]
        self.assertEqual([t["pinned"] for t in w["tabs"]], [True, False, False, False])
        self.assertEqual([g["id"] for g in w["groups"]], ["00000000000000010000000000000002",
                                                          "ffffffffffffffff0000000000000003"])
        self.assertEqual([(g["title"], g["color"], g["collapsed"]) for g in w["groups"]],
                         [("Work", "grey", False), ("", "grey", False)])            # a group without looks: plain
        self.assertEqual([t["group"] is None for t in w["tabs"]], [True, False, False, True])

    def test_an_older_bounds_command_and_window_types(self):
        data = s.snss([window(1, 1), cmd(s.S_WINDOW_BOUNDS2, "<iiiii?3x", 1, 0, 0, 5, 6, True), *tab(1, 2, 0, "a"),
                       window(3, 17), *tab(3, 4, 0, "b")])
        first, second = s.read_session(data)["windows"]
        self.assertEqual((first["type"], first["show_state"], second["type"]), ("popup", "maximized", 17))


class ClosedTests(unittest.TestCase):
    """The recently closed list (tab_restore_service_impl.cc)."""

    def entry_tab(self, tid: int, *names: str, current: int = 0) -> list[bytes]:
        return [cmd(s.T_SELECTED_NAVIGATION, "<iiq", tid, current, 0)] + [
            s.command(s.T_NAVIGATION, NAV(tid, 40 + i, n, n)) for i, n in enumerate(names)]

    def test_tabs_windows_and_groups_newest_first(self):
        group = s.PickleWriter().u64(1).u64(2).int(30).int(1).int(9).string16("G").u32(2).bool(False).i64(0).done()
        window_fields = s.PickleWriter().int(20).int(1).int(2).i64(0).int(0).int(0).int(0).int(0).int(3).string("")
        data = s.snss([*self.entry_tab(1, "a", "b", current=1), cmd(s.T_PINNED, "<?", True),
                       s.command(s.T_WINDOW, window_fields.int(0).done()), *self.entry_tab(2, "w1"),
                       *self.entry_tab(3, "w2"), s.command(s.T_CREATE_GROUP, group), *self.entry_tab(4, "g")])
        entries = s.read_closed(data)["entries"]
        self.assertEqual([e["kind"] for e in entries], ["group", "window", "tab"])
        self.assertEqual((entries[2]["pinned"], entries[2]["current"], urls(entries[2])), (True, 1, ["a", "b"]))
        self.assertEqual([n["index"] for n in entries[2]["navigations"]], [0, 1])       # numbered by order
        self.assertEqual((entries[1]["show_state"], entries[1]["selected_tab"], entries[1]["bounds"]),
                         ("maximized", 1, None))
        self.assertEqual([urls(t) for t in entries[1]["tabs"]], [["w1"], ["w2"]])
        self.assertEqual((entries[0]["title"], entries[0]["color"]), ("G", "red"))

    def test_a_restored_entry_leaves_and_invalid_ones_are_dropped(self):
        data = s.snss([*self.entry_tab(1, "a"), *self.entry_tab(2, "b"), cmd(s.T_RESTORED, "<i", 1),
                       *self.entry_tab(3, current=0), *self.entry_tab(5, "c", current=4),
                       s.command(s.T_NAVIGATION, NAV(9, 0, "x", "x"))])
        reading = s.read_closed(data)
        self.assertEqual([urls(e) for e in reading["entries"]], [["b"]])
        data = s.snss([s.command(s.T_NAVIGATION, NAV(9, 0, "x", "x")), cmd(s.T_PINNED, "<?", True), s.command(77, b"")])
        reading = s.read_closed(data)
        self.assertEqual((reading["entries"], reading["skipped"]["malformed"], reading["unknown_ids"]), ([], 2, [77]))


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="thoron-sessions-")).resolve()   # a short (8.3) name too
        self.profile = self.tmp / "User Data" / "Default"
        (self.profile / "Sessions").mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def put(self, name: str, data: bytes) -> Path:
        path = self.profile / "Sessions" / name
        path.write_bytes(data)
        return path

    def test_the_newest_file_with_a_complete_state_is_read(self):
        old = s.snss([window(1), *tab(1, 2, 0, "old")])
        self.put("Session_9", old)
        self.put("Session_10", s.snss([window(1), *tab(1, 2, 0, "new")]))
        self.put("Session_11", s.snss([window(1), *tab(1, 2, 0, "unfinished")], marker=False))
        self.put("Session_12", b"SNSS\x05\x00\x00\x00")
        self.put("Session_x", old)
        self.put("Tabs_3", s.snss([]))
        self.assertEqual([p.name for p in s.session_files(self.profile / "Sessions", "Session")],
                         ["Session_12", "Session_11", "Session_10", "Session_9"])
        reading = s.read_profile(self.profile)
        self.assertEqual(reading["session"]["file"], "Session_10")
        self.assertEqual(urls(reading["session"]["windows"][0]["tabs"][0]), ["new"])
        self.assertEqual(reading["closed"]["file"], "Tabs_3")
        self.assertEqual(len(reading["notes"]), 2)

    def test_nothing_to_read(self):
        reading = s.read_profile(self.tmp / "nowhere")
        self.assertEqual((reading["session"], reading["closed"], reading["notes"]), (None, None, []))
        (self.profile / "Sessions_Encrypted").mkdir()
        (self.profile / "Sessions_Encrypted" / "Session_1").write_bytes(b"SNSS\x05\x00\x00\x00")
        self.assertIn("encrypted", s.read_profile(self.profile)["notes"][0])

    def test_the_command_line_only_reads(self):
        path = self.put("Session_5", golden("thorium")[0].read_bytes())
        before = path.read_bytes()
        for args in (["read", "--profile", str(self.profile)], ["read", "--file", str(path)]):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(s.main(args), 0)
            self.assertEqual(json.loads(out.getvalue())["format" if "--profile" in args else "commands"],
                             s.FORMAT if "--profile" in args else s.read_session(before)["commands"])
        self.assertEqual(path.read_bytes(), before)
        bad = self.put("Session_6", b"nope")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(s.main(["read", "--file", str(bad)]), 2)


class ImportTests(unittest.TestCase):
    def setUp(self):
        quiet = mock.patch.object(ip, "QUIET_SECONDS", 0)   # written just before; see the test below
        quiet.start()
        self.addCleanup(quiet.stop)
        self.tmp = Path(tempfile.mkdtemp(prefix="thoron-tabs-import-")).resolve()   # a short (8.3) name too
        self.src = self.tmp / "Chrome" / "User Data" / "Default"
        (self.src / "Sessions").mkdir(parents=True)
        session, tabs, self.expected = golden("chrome")
        for f in (session, tabs):
            shutil.copy2(f, self.src / "Sessions" / f.name)
        self.put_src("Session_1", s.snss([window(1), *tab(1, 2, 0, "an older session")]))
        self.dst = self.tmp / "Thoron" / "User Data" / "Default"
        self.dst.mkdir(parents=True)
        (self.dst / "Preferences").write_text("{}", encoding="utf-8")
        (self.dst.parent / "Local State").write_text(json.dumps({"os_crypt": {"encrypted_key": "k"}, "was": {"x": 1}}),
                                                     encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def put_src(self, name: str, data: bytes) -> None:
        (self.src / "Sessions" / name).write_bytes(data)

    def snapshot(self, root: Path) -> dict:
        return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}

    def test_the_newest_session_comes_over_verified_and_reads_the_same(self):
        before = self.snapshot(self.src)
        done = s.import_sessions(self.src, self.dst)
        self.assertEqual(self.snapshot(self.src), before)                     # the source is never changed
        self.assertEqual(sorted(done["files"]), sorted(p.name for p in GOLDEN.joinpath("chrome").glob("*_*")))
        self.assertEqual((done["windows"], done["tabs"], done["groups"], done["pinned"], done["closed"]),
                         (2, 7, 3, 1, 3))
        self.assertTrue(done["verified"] and done["source_unchanged"])
        reading = s.read_profile(self.dst)
        self.assertEqual({k: v for k, v in reading["session"].items() if k != "file"}, self.expected["session"])
        self.assertEqual({k: v for k, v in reading["closed"].items() if k != "file"}, self.expected["closed"])

    def test_the_links_to_the_source_s_saved_groups_are_left_out(self):
        done = s.import_sessions(self.src, self.dst)
        self.assertEqual(done["unlinked_groups"], 3)
        changed = {"Session": (s.S_GROUP_METADATA2,), "Tabs": (s.T_GROUP_DATA, s.T_CREATE_GROUP)}
        for name in done["files"]:
            copied, original = (self.dst / "Sessions" / name).read_bytes(), (self.src / "Sessions" / name).read_bytes()
            prefix = name.split("_")[0]
            self.assertNotEqual(copied, original)
            self.assertEqual(s.unlink_saved_groups(copied, prefix), (copied, 0))   # nothing linked is left
            self.assertEqual(s.unlink_saved_groups(original, prefix)[0], copied)
            kept = [[(c, p) for c, p in s.raw_commands(data)[0] if c not in changed[prefix]]
                    for data in (original, copied)]
            self.assertEqual(kept[0], kept[1])                                    # every other command as it was

    def test_commands_thoron_would_stop_at_are_left_out_of_the_copy(self):
        vendor = s.command(120, b"another browser's own data")
        damaged = cmd(s.S_PINNED, "<i", 2)
        commands = [window(1), *tab(1, 2, 0, "http://127.0.0.1/a"), vendor, *tab(1, 3, 1, "http://127.0.0.1/b"),
                    damaged, cmd(s.S_PINNED, "<i?3x", 3, True)]
        original = s.snss(commands)
        copy, done = s.prepare_copy(original, "Session")
        self.assertEqual(done, {"unlinked_groups": 0, "left_out": 2})
        self.assertEqual(copy, s.snss([c for c in commands if c not in (vendor, damaged)]))
        self.assertEqual(s.essence(s.read_session(copy)), s.essence(s.read_session(original)))
        self.assertEqual(s.read_session(copy)["skipped"], {"unknown": 0, "malformed": 0, "over_limit": 0})
        for name in ("Session_13439326313952943", "Session_1"):
            (self.src / "Sessions" / name).unlink(missing_ok=True)
        self.put_src("Session_7", original)
        done = s.import_sessions(self.src, self.dst)
        self.assertEqual(done["left_out"], 2)
        self.assertEqual((self.dst / "Sessions" / "Session_7").read_bytes(), copy)

    def test_a_skipped_command_in_the_closed_list_changes_nothing(self):
        window_fields = s.PickleWriter().int(20).int(0).int(2).i64(0).int(0).int(0).int(0).int(0).int(1).string("")
        tab_of = [cmd(s.T_SELECTED_NAVIGATION, "<iiq", 5, 0, 0), s.command(s.T_NAVIGATION, NAV(5, 0, "w1", ""))]
        restored_too_early = cmd(s.T_RESTORED, "<i", 99)
        data = s.snss([s.command(s.T_WINDOW, window_fields.int(0).done()), *tab_of, restored_too_early,
                       cmd(s.T_SELECTED_NAVIGATION, "<iiq", 6, 0, 0), s.command(s.T_NAVIGATION, NAV(6, 0, "w2", ""))])
        reading = s.read_closed(data)
        self.assertEqual([[urls(t) for t in e["tabs"]] for e in reading["entries"]], [[["w1"], ["w2"]]])
        copy, done = s.prepare_copy(data, "Tabs")
        self.assertEqual(done["left_out"], 1)
        self.assertNotIn(restored_too_early, copy)
        self.assertEqual(s.essence(s.read_closed(copy)), s.essence(reading))

    def test_a_session_written_a_moment_ago_is_refused(self):
        # THREAT_MODEL I2: the source's browser may still be closing (the golden files keep their old dates)
        for f in (self.src / "Sessions").iterdir():
            os.utime(f, None)
        before = self.snapshot(self.tmp)
        with mock.patch.object(ip, "QUIET_SECONDS", 15):
            with self.assertRaisesRegex(s.ImportRefused, "a moment ago"):
                s.import_sessions(self.src, self.dst)
        self.assertEqual(self.snapshot(self.tmp), before)

    def test_refusals_change_nothing(self):
        (self.src.parent / "lockfile").write_bytes(b"")
        before = self.snapshot(self.tmp)
        with self.assertRaisesRegex(s.ImportRefused, "source browser is running"):
            s.import_sessions(self.src, self.dst)
        self.assertEqual(self.snapshot(self.tmp), before)
        (self.src.parent / "lockfile").unlink()
        (self.dst.parent / "lockfile").write_bytes(b"")
        with self.assertRaisesRegex(s.ImportRefused, "Thoron is running"):
            s.import_sessions(self.src, self.dst)
        (self.dst.parent / "lockfile").unlink()
        (self.dst / "Preferences").unlink()
        with self.assertRaisesRegex(s.ImportRefused, "start Thoron once"):
            s.import_sessions(self.src, self.dst)
        (self.dst / "Preferences").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(s.ImportRefused, "overlap"):
            s.import_sessions(self.dst, self.dst)
        with self.assertRaisesRegex(s.ImportRefused, "not a profile folder"):
            s.import_sessions(self.tmp / "missing", self.dst)
        empty = self.tmp / "Empty" / "Default"
        empty.mkdir(parents=True)
        with self.assertRaisesRegex(s.ImportRefused, "no session"):
            s.import_sessions(empty, self.dst)
        self.assertFalse((self.dst / "Sessions").exists())

    def test_thoron_s_own_session_is_refused_or_set_aside(self):
        own = self.dst / "Sessions"
        own.mkdir()
        (own / "Session_5").write_bytes(b"thoron's own")
        (own / "Tabs_5").write_bytes(b"thoron's closed")
        before = self.snapshot(self.dst)
        with self.assertRaisesRegex(s.ImportRefused, "session of its own"):
            s.import_sessions(self.src, self.dst)
        self.assertEqual(self.snapshot(self.dst), before)
        done = s.import_sessions(self.src, self.dst, set_aside=True)
        aside = own / done["set_aside"]
        self.assertEqual((aside / "Session_5").read_bytes(), b"thoron's own")
        self.assertEqual((aside / "Tabs_5").read_bytes(), b"thoron's closed")
        self.assertEqual(s.read_profile(self.dst)["session"]["file"], done["files"][0])

    def test_a_file_already_there_is_never_written_over(self):
        own = self.dst / "Sessions"
        own.mkdir()
        name = next(p.name for p in GOLDEN.joinpath("chrome").glob("Tabs_*"))
        (own / name).write_bytes(b"keep")
        real = s.session_files       # Thoron's own files are looked at too late for this case: hide them
        with mock.patch.object(s, "session_files", lambda folder, prefix: [] if folder == own else real(folder, prefix)):
            with self.assertRaisesRegex(s.ImportRefused, "already exists"):
                s.import_sessions(self.src, self.dst)
        self.assertEqual((own / name).read_bytes(), b"keep")

    def test_restore_on_next_start(self):
        state = self.dst.parent / "Local State"
        s.restore_on_next_start(self.dst.parent)
        written = json.loads(state.read_text(encoding="utf-8"))
        self.assertEqual(written, {"os_crypt": {"encrypted_key": "k"}, "was": {"x": 1, "restarted": True}})
        self.assertEqual(sorted(p.name for p in self.dst.parent.iterdir()), ["Default", "Local State"])
        state.write_text("{broken", encoding="utf-8")
        with self.assertRaisesRegex(s.ImportRefused, "cannot be read"):
            s.restore_on_next_start(self.dst.parent)
        self.assertEqual(state.read_text(encoding="utf-8"), "{broken")
        state.write_text("[]", encoding="utf-8")
        with self.assertRaisesRegex(s.ImportRefused, "not what a browser writes"):
            s.restore_on_next_start(self.dst.parent)

    def test_the_temporary_local_state_goes_on_failure_too(self):
        # threat model I8: the file written before the switch lies beside Local State, inside the destination, and
        # is deleted whether the switch works or not
        state = self.dst.parent / "Local State"
        before = state.read_bytes()
        with mock.patch.object(s.os, "replace", side_effect=OSError("the disk is full")):
            with self.assertRaisesRegex(s.ImportRefused, "could not be written"):
                s.restore_on_next_start(self.dst.parent)
        self.assertEqual(state.read_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.dst.parent.iterdir()), ["Default", "Local State"])

    def test_a_sessions_folder_that_is_a_link_or_junction_is_refused(self):
        # threat model I4: nothing outside the two profiles is read or written through a link
        held = self.tmp / "Held elsewhere"
        shutil.move(str(self.src / "Sessions"), str(held))
        outside = self.tmp / "Outside"
        outside.mkdir()
        made = 0
        for junction in (False, True):
            with self.subTest(junction=junction):
                if not folder_link(self.src / "Sessions", held, junction):
                    continue
                made += 1
                try:
                    with self.assertRaisesRegex(s.ImportRefused, "link or junction"):
                        s.import_sessions(self.src, self.dst)
                    self.assertFalse((self.dst / "Sessions").exists())
                finally:
                    remove_link(self.src / "Sessions")
                shutil.copytree(held, self.src / "Sessions")
                self.assertTrue(folder_link(self.dst / "Sessions", outside, junction))
                try:
                    with self.assertRaisesRegex(s.ImportRefused, "link or junction"):
                        s.import_sessions(self.src, self.dst)
                finally:
                    remove_link(self.dst / "Sessions")
                    shutil.rmtree(self.src / "Sessions")
                self.assertEqual(list(outside.iterdir()), [])
        self.assertTrue(held.is_dir())
        if not made:
            self.skipTest("this system can make no link to a folder")

    def test_a_session_file_that_is_a_link_is_passed_over(self):
        outside = self.tmp / "outside session"
        outside.write_bytes(s.snss([window(1), *tab(1, 2, 0, "http://127.0.0.1/outside")]))
        link = self.src / "Sessions" / "Session_99999999999999999"        # newer than every real one
        try:
            link.symlink_to(outside)
        except OSError:
            self.skipTest("this system can make no link to a file")
        self.assertNotIn(link, s.session_files(self.src / "Sessions", "Session"))
        done = s.import_sessions(self.src, self.dst)
        self.assertNotIn(link.name, done["files"])
        self.assertFalse((self.dst / "Sessions" / link.name).exists())

    def test_the_command_line_import(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = s.main(["import", "--from", str(self.src), "--to", str(self.dst), "--restore-on-next-start"])
        self.assertEqual(code, 0)
        text = out.getvalue()
        self.assertIn("2 window(s), 7 tab(s), 3 group(s), 1 pinned", text)
        self.assertIn("3 group(s) come over as Thoron's own", text)
        self.assertTrue(json.loads((self.dst.parent / "Local State").read_text(encoding="utf-8"))["was"]["restarted"])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(s.main(["import", "--from", str(self.src), "--to", str(self.dst)]), 1)
        self.assertIn("session of its own", out.getvalue())


class FuzzerTests(unittest.TestCase):
    """The fuzzer of the reader (threat model I3; the long runs are by hand): a fixed short run keeps every promise
    the import relies on, and the fuzzer does tell a reader that breaks one."""

    def test_a_fixed_run_of_mutated_inputs_reads_or_is_refused(self):
        inputs = fuzz.corpus()
        self.assertGreaterEqual(len(inputs), 2 * len(BROWSERS) + 2)       # the golden files and the made-up ones
        for seed in range(300):
            with self.subTest(seed=seed):
                fuzz.check(fuzz.mutate(random.Random(seed), inputs))

    def test_the_same_seed_gives_the_same_input(self):
        inputs = fuzz.corpus()
        self.assertEqual(fuzz.mutate(random.Random(7), inputs), fuzz.mutate(random.Random(7), inputs))

    def test_a_reader_that_breaks_its_promise_is_found(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as errors:
            with mock.patch.object(s, "read_session", side_effect=IndexError("a crash")):
                self.assertEqual(fuzz.main(["--repeat", "1"]), 1)
        self.assertIn("IndexError", errors.getvalue())
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(fuzz.main(["--repeat", "1"]), 0)
        self.assertIn("no crash", out.getvalue())


if __name__ == "__main__":
    unittest.main()
