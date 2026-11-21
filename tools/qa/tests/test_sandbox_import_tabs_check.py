# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Open tabs and extensions in Settings' import (ROADMAP P3.22, P3.14): the browsers made for the Sandbox, the
comparison of their windows with Thoron's session, and the reading of the results."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from tools.qa import sandbox_import_tabs_check as check


def thoron_session() -> dict:
    """Thoron's session after all six imports, as tools/migrate/sessions.py reads it: every source window, with
    new ids for windows, tabs and groups, the Settings window besides."""
    windows = []
    for _name, golden, _user_data, _single in check.SOURCES:
        reading = json.loads((check.GOLDEN / golden / "expected.json").read_text(encoding="utf-8"))
        for w in reading["session"]["windows"]:
            w = copy.deepcopy(w)
            renewed = {g["id"]: f"{i:032x}" for i, g in enumerate(w["groups"], 99)}
            for g in w["groups"]:
                g["id"] = renewed[g["id"]]
            for t in w["tabs"]:
                t["group"] = renewed.get(t["group"])
            w["show_state"] = "normal"
            windows.append(w)
    settings = {"type": "normal", "selected_tab": 0, "groups": [], "tabs": [
        {"pinned": False, "group": None, "current": 0,
         "navigations": [{"index": 0, "url": "chrome://settings/importData", "title": "Settings"}]}]}
    return {"session": {"windows": [settings] + windows}}


class SourcesTests(unittest.TestCase):
    def test_each_browser_keeps_its_profile_where_it_does(self):
        with tempfile.TemporaryDirectory() as d:
            listed = check.make_sources(Path(d))
            self.assertEqual([s["name"] for s in listed], [s[0] for s in check.SOURCES])
            self.assertEqual(listed[-1]["name"], "Chrome")
            chrome = Path(d) / "chrome"
            state = json.loads((chrome / "Local State").read_text(encoding="utf-8"))
            self.assertIn("Default", state["profile"]["info_cache"])
            self.assertTrue(list((chrome / "Default/Sessions").glob("Session_*")))
            prefs = json.loads((chrome / "Default/Preferences").read_text(encoding="utf-8"))
            settings = prefs["extensions"]["settings"]
            self.assertTrue(settings[check.STORE_EXTENSION]["from_webstore"])
            self.assertEqual(settings[check.UNPACKED_EXTENSION]["location"], 4)
            opera = Path(d) / "opera"                          # its only profile is the folder itself
            self.assertTrue((opera / "Preferences").is_file() and list((opera / "Sessions").glob("Session_*")))
            self.assertFalse(list((Path(d) / "edge/Default/Sessions").glob("Tabs_*")))


class CompareTests(unittest.TestCase):
    def test_every_source_window_with_new_ids_passes(self):
        reading = json.dumps(thoron_session())
        self.assertEqual(check.compare_tabs(check.expected_windows(), reading), [])
        self.assertEqual(len(check.expected_windows()), 10)

    def test_what_did_not_come_over_as_it_was_is_found(self):
        cases = {
            "a window": lambda s: s["session"]["windows"].pop(),
            "order": lambda s: s["session"]["windows"][1]["tabs"].reverse(),
            "pinned": lambda s: s["session"]["windows"][1]["tabs"][0].update(pinned=False),
            "colour": lambda s: s["session"]["windows"][1]["groups"][0].update(color="pink"),
            "collapsed": lambda s: s["session"]["windows"][1]["groups"][1].update(collapsed=False),
            "group name": lambda s: s["session"]["windows"][1]["groups"][0].update(title="Other"),
            "history": lambda s: s["session"]["windows"][1]["tabs"][1]["navigations"].pop(),
            "current": lambda s: s["session"]["windows"][1]["tabs"][1].update(current=0),
            "selected": lambda s: s["session"]["windows"][1].update(selected_tab=0),
            "no group": lambda s: s["session"]["windows"][1]["tabs"][1].update(group=None),
        }
        for name, change in cases.items():
            with self.subTest(name):
                session = thoron_session()
                change(session)
                self.assertNotEqual(check.compare_tabs(check.expected_windows(), json.dumps(session)), [], name)

    def test_an_extra_window_of_the_test_pages_is_found(self):
        session = thoron_session()
        session["session"]["windows"].append(copy.deepcopy(session["session"]["windows"][1]))
        self.assertEqual(len(check.compare_tabs(check.expected_windows(), json.dumps(session))), 1)
        self.assertEqual(len(check.compare_tabs(check.expected_windows(), "not json")), 1)


class ProblemsTests(unittest.TestCase):
    def found(self) -> dict:
        return {
            "installed": True, "done": True,
            "imports": {name: {"status": "succeeded"} for name, *_ in check.SOURCES},
            "session": json.dumps(thoron_session()),
            "extensions": json.dumps([{"id": check.STORE_EXTENSION, "state": "DISABLED", "location": "FROM_STORE",
                                       "reasons": {"suspiciousInstall": False, "blockedByPolicy": False}}]),
            "report": json.dumps({"format": 1, "imported": {"open_tabs": 7, "extensions_to_install_from_the_store": 1},
                                  "left_out": {"extensions_not_from_the_store": 1}}),
        }

    def test_a_good_run_passes(self):
        self.assertEqual({k: v for k, v in check.problems(self.found()).items() if v}, {})

    def test_each_failure_is_named(self):
        cases = {
            "imported": lambda f: f["imports"]["Opera"].update(status="failed"),
            "extensions": lambda f: f.update(extensions=json.dumps([])),
            "the report": lambda f: f.update(report=json.dumps({"imported": {"open_tabs": 2}})),
        }
        for step, change in cases.items():
            with self.subTest(step):
                found = self.found()
                change(found)
                self.assertTrue(check.problems(found)[step], step)
        found = self.found()
        found["extensions"] = json.dumps([{"id": check.STORE_EXTENSION, "state": "DISABLED", "location": "FROM_STORE",
                                           "reasons": {"blockedByPolicy": True}},
                                          {"id": check.UNPACKED_EXTENSION, "state": "ENABLED", "location": "UNPACKED"}])
        self.assertEqual(len(check.problems(found)["extensions"]), 2)
        found = self.found()
        found["report"] = found["report"].replace('"format": 1', '"format": 1, "x": "http://127.0.0.1:47615/p/a"')
        self.assertTrue(check.problems(found)["the report"])


if __name__ == "__main__":
    unittest.main()
