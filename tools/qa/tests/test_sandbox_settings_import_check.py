# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Tests of the parts of sandbox_settings_import_check.py that do not need Windows Sandbox."""
import ast
import unittest

from tools.qa import sandbox_settings_import_check as si

BOTH = '{"bookmark": true, "history": true}'
GOOD = {"installed": True, "thorium_before": BOTH, "settings_open": True,
        "listed": '["Microsoft Edge", "Thorium", "Bookmarks HTML File"]', "chosen": 1,
        "windows_before": 1, "windows_with_request": 2, "status_while_running": "inProgress",
        "thorium_still_runs": True, "thorium_closed": True, "status": "succeeded",
        "thoron_after": BOTH, "thorium_after": BOTH, "done": True, "cookie_in_thoron": True,
        "report": '{"format": 1, "source": "Thorium", "time": "2026-11-18T05:00:00.000Z", '
                  '"imported": {"bookmarks": 1, "history": 1, "passwords": 0, "cookies": 1}, '
                  '"left_out": {"passwords_locked_by_chrome": 0}}'}


GOOD_REPORT = GOOD["report"]


class ProblemsTests(unittest.TestCase):
    def test_an_import_that_did_what_settings_says(self):
        found = si.problems(GOOD)
        self.assertEqual(sum(len(v) for v in found.values()), 0, found)

    def test_each_step_that_goes_wrong(self):
        cases = [
            ({"thorium_before": '{"bookmark": true, "history": false}'}, "setup"),
            ({"listed": '["Microsoft Edge", "Bookmarks HTML File"]'}, "listed"),
            ({"listed": '["Thorium", "Thoron"]'}, "listed"),
            ({"windows_with_request": 1}, "running"),
            ({"status_while_running": "succeeded"}, "running"),
            ({"thorium_still_runs": False}, "running"),
            ({"status": "failed"}, "import"),
            ({"thorium_closed": False}, "import"),
            ({"thoron_after": '{"bookmark": true, "history": false}'}, "the data"),
            ({"thorium_after": '{"bookmark": false, "history": true}'}, "the data"),
            ({"report": ""}, "the report"),
            ({"report": '{"format": 1, "source": "Thorium", "imported": {"bookmarks": 0, "history": 1, "cookies": 1}, "left_out": {}}'},
             "the report"),
            ({"report": GOOD_REPORT.replace('"Thorium"', '"Thorium https://example.org/x"')}, "the report"),
            ({"report": GOOD_REPORT.replace('"Thorium"', '"Thorium came-along"')}, "the report"),
            ({"cookie_in_thoron": False}, "the cookie"),
            ({"report": GOOD_REPORT.replace('"cookies": 1', '"cookies": 0')}, "the cookie"),
        ]
        for change, step in cases:
            with self.subTest(change=change):
                found = si.problems({**GOOD, **change})
                self.assertEqual(len(found[step]), 1, found)
                self.assertEqual(sum(len(v) for v in found.values()), 1, found)


class ScriptTests(unittest.TestCase):
    def test_the_data_script_is_python_and_writes_only_made_up_data(self):
        ast.parse(si.DATA)
        self.assertIn("example.org/thoron-import-bookmark", si.DATA)
        self.assertIn("example.org/thoron-import-history", si.DATA)

    def test_the_dialog_is_used_by_its_element_ids(self):
        for element in ("'browserSelect'", "'import'", "importStatus_"):
            self.assertIn(element, si.RUN)
        self.assertIn("SendWait('{ENTER}')", si.RUN)        # the request's default button, not its words

    def test_thorium_is_closed_the_way_a_person_closes_it(self):
        self.assertIn("CloseMainWindow()", si.RUN)
        thorium_part = si.RUN.split("Mark 'Thorium closed; Try again'")[1].split("Mark 'the data'")[0]
        self.assertNotIn("Stop-Process", thorium_part)


if __name__ == "__main__":
    unittest.main()
