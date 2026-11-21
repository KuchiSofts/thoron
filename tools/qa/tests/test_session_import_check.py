# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Tabs import (ROADMAP P3.15): the golden files hold the session that was built, their copies hold nothing of the
PC, and the comparison of a source with Thoron's session after the restore finds every difference that matters."""
import copy
import json
import struct
import unittest
from pathlib import Path

from tools.migrate import sessions
from tools.qa import session_golden as golden
from tools.qa import session_import_check as check

GOLDEN = Path(__file__).resolve().parents[2] / "migrate" / "tests" / "data" / "sessions"


def reading(browser: str) -> dict:
    return json.loads((GOLDEN / browser / "expected.json").read_text(encoding="utf-8"))


class GoldenTests(unittest.TestCase):
    def test_every_golden_file_holds_the_session_that_was_built(self):
        for browser in ("chrome", "thorium", "thoron"):
            with self.subTest(browser=browser):
                found = reading(browser)
                self.assertEqual(found["built_with"], "extension")
                base = f"http://127.0.0.1:{golden.PORT}/p/"
                got = golden.shape(found["session"], found["closed"])
                self.assertEqual(golden.plan_problems(golden.expected_plan(base, True), got), [])

    def test_the_plan_check_sees_a_difference(self):
        base = "http://127.0.0.1:1/p/"
        want = golden.expected_plan(base, True)
        got = copy.deepcopy(want)
        got["closed_windows"] = []
        self.assertEqual(golden.plan_problems(want, got), [])
        got["windows"][0]["tabs"][1]["navigations"][1]["title"] = ""
        self.assertEqual(golden.plan_problems(want, got), [])          # an empty title: a page not synced yet
        got["windows"][0]["tabs"][1]["navigations"][1]["title"] = "another"
        got["windows"][1]["show_state"] = "normal"
        got["closed_windows"] = [[["http://127.0.0.1:1/p/elsewhere"]]]
        self.assertEqual(len(golden.plan_problems(want, got)), 3)
        self.assertEqual(golden.plan_problems(want, {**got, "windows": got["windows"][:1]}), ["1 windows, not 2"])

    def test_the_copy_has_the_screen_and_the_desktop_taken_out_and_nothing_else(self):
        made = sessions.snss([
            sessions.command(sessions.S_WINDOW_BOUNDS3, struct.pack("<iiiiii", 7, 11, 22, 1920, 1040, 3)),
            sessions.command(sessions.S_WORKSPACE2, sessions.PickleWriter().int(7).string("{a-desktop-id}").done()),
            sessions.command(sessions.S_PLATFORM_ID, sessions.PickleWriter().string("platform").done()),
            sessions.command(sessions.S_WINDOW_TYPE, struct.pack("<ii", 7, 0))])
        clean = golden.sanitize(made)
        commands = sessions.raw_commands(clean)[0]
        self.assertEqual(struct.unpack("<iiiiii", commands[0][1]), (7, *golden.BOUNDS, 3))
        self.assertNotIn(b"desktop", clean)
        self.assertNotIn(b"platform", clean)
        self.assertEqual(commands[3:], sessions.raw_commands(made)[0][3:])
        window = sessions.PickleWriter().int(1).int(0).int(1).i64(5).int(11).int(22).int(1920).int(1040).int(1)
        closed = sessions.snss([sessions.command(sessions.T_WINDOW, window.string("{a-desktop-id}").int(0).done())])
        entry = sessions.read_closed(golden.sanitize_closed(closed))
        self.assertNotIn(b"desktop", golden.sanitize_closed(closed))
        self.assertEqual(sessions.raw_commands(golden.sanitize_closed(closed))[0][-1][0], sessions.MARKER)
        p = sessions._Pickle(sessions.raw_commands(golden.sanitize_closed(closed))[0][0][1])
        self.assertEqual([p.int(), p.int(), p.int(), p.i64(), p.int(), p.int(), p.int(), p.int()],
                         [1, 0, 1, 5, *golden.BOUNDS])
        self.assertEqual(entry["entries"], [])              # a window without tabs is not listed

    def test_the_page_server_names_each_page(self):
        self.assertIn(b"<title>Thoron session test work-a1</title>", golden.page("work-a1"))
        self.assertTrue(golden.NAME_RE.match("/p/work-a1") and not golden.NAME_RE.match("/p/../x"))


class CompareTests(unittest.TestCase):
    def setUp(self):
        found = reading("chrome")
        self.source, self.closed = found["session"], found["closed"]
        self.title = lambda url: golden.TITLE + url.rsplit("/", 1)[-1]

    def result(self) -> dict:
        out = copy.deepcopy(self.source)
        for w in out["windows"]:                                  # a restore renews every id and the bounds
            w["id"] += 1000
            w["bounds"] = [0, 0, 1, 1]
            renewed = {g["id"]: f"{i:032x}" for i, g in enumerate(w["groups"], 7)}
            for g in w["groups"]:
                g["id"] = renewed[g["id"]]
            for t in w["tabs"]:
                t["id"] += 1000
                t["group"] = None if t["group"] is None else renewed[t["group"]]
        return out

    def problems(self, result: dict, closed: dict | None = None) -> list[str]:
        return check.compare(self.source, result, self.title, self.closed, closed or self.closed)

    def test_the_same_session_with_new_ids_passes(self):
        self.assertEqual(check.compare(self.source, self.result(), self.title), [])

    def test_differences_in_windows_tabs_and_groups_are_found(self):
        cases = {
            "order": lambda r: r["windows"][0]["tabs"].reverse(),
            "pinned": lambda r: r["windows"][0]["tabs"][0].update(pinned=False),
            "colour": lambda r: r["windows"][0]["groups"][0].update(color="pink"),
            "collapsed": lambda r: r["windows"][0]["groups"][1].update(collapsed=False),
            "title": lambda r: r["windows"][0]["groups"][0].update(title="Other"),
            "history": lambda r: r["windows"][0]["tabs"][1]["navigations"].pop(),
            "current": lambda r: r["windows"][0]["tabs"][1].update(current=2),
            "chosen tab": lambda r: r["windows"][0].update(selected_tab=0),
            "active window": lambda r: r.update(active_window=1),
            "a window": lambda r: r["windows"].pop(),
            "a tab": lambda r: r["windows"][1]["tabs"].pop(),
            "show state": lambda r: r["windows"][0].update(show_state="maximized"),
        }
        for name, change in cases.items():
            with self.subTest(name):
                result = self.result()
                change(result)
                self.assertNotEqual(check.compare(self.source, result, self.title), [], name)

    def test_titles_must_stay_and_an_empty_one_may_become_the_page_s_title(self):
        result = self.result()
        navs = [n for w in result["windows"] for t in w["tabs"] for n in t["navigations"]]
        empty = [n for n in navs if n["title"] == ""]
        saved = [n for n in navs if n["title"] != ""]
        self.assertTrue(empty and saved)
        for n in empty:
            n["title"] = self.title(n["url"])
        self.assertEqual(check.compare(self.source, result, self.title), [])
        empty[0]["title"] = "something else"
        self.assertEqual(len(check.compare(self.source, result, self.title)), 1)
        empty[0]["title"] = self.title(empty[0]["url"])
        saved[0]["title"] = ""
        self.assertEqual(len(check.compare(self.source, result, self.title)), 1)

    def test_only_a_minimized_window_may_open_as_a_normal_one(self):
        result = self.result()
        result["windows"][1]["show_state"] = "normal"
        self.assertEqual(check.compare(self.source, result, self.title), [])
        result["windows"][0]["show_state"] = "minimized"
        self.assertEqual(len(check.compare(self.source, result, self.title)), 1)

    def test_a_normal_window_saved_as_default_passes_only_while_it_shows_normal(self):
        result = self.result()
        result["windows"][0]["show_state"] = "default"
        self.assertEqual(len(check.compare(self.source, result, self.title)), 1)
        self.assertEqual(check.compare(self.source, result, self.title, live=["normal", "minimized"]), [])
        self.assertEqual(len(check.compare(self.source, result, self.title, live=["minimized", None])), 1)
        self.assertFalse(check.saved_as_default("minimized", "default", "normal"))
        self.assertFalse(check.saved_as_default("normal", "maximized", "normal"))

    def test_the_recently_closed_list_keeps_the_source_s_entries_after_the_exit_s_windows(self):
        result = self.result()
        extra = copy.deepcopy([e for e in self.closed["entries"] if e["kind"] == "window"][0])
        self.assertEqual(self.problems(result, {"entries": [extra] + self.closed["entries"]}), [])
        tab = copy.deepcopy([e for e in self.closed["entries"] if e["kind"] == "tab"][0])
        self.assertEqual(len(self.problems(result, {"entries": [tab] + self.closed["entries"]})), 1)
        self.assertEqual(len(self.problems(result, {"entries": self.closed["entries"][1:]})), 1)
        self.assertEqual(len(self.problems(result, {"entries": []})), 1)

    def test_the_port_of_the_local_pages(self):
        self.assertEqual(check.port_of(self.source), golden.PORT)
        other = copy.deepcopy(self.source)
        other["windows"][0]["tabs"][0]["navigations"][0]["url"] = "https://example.com/"
        self.assertIsNone(check.port_of(other))
        other["windows"][0]["tabs"][0]["navigations"][0]["url"] = "http://127.0.0.1:99999999/p/x"
        self.assertIsNone(check.port_of(other))

    def test_the_live_state_of_each_window_is_found_by_its_chosen_page(self):
        first = self.source["windows"][0]
        chosen = first["tabs"][first["selected_tab"]]
        url = chosen["navigations"][chosen["current"]]["url"]
        self.assertEqual(check.live_show_states(self.source, {url: "normal"}), ["normal", None])


if __name__ == "__main__":
    unittest.main()
