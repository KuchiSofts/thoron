# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Tests of the parts of sandbox_first_run_check.py that do not need Windows Sandbox."""
import unittest

from tools.qa import sandbox_first_run_check as fr

BEFORE = {"http": "", "https": "", "html": ""}
GOOD = {"installed": True, "choices_before": BEFORE,
        "first_tabs": ["chrome://thoron-welcome/", "chrome://newtab/"],
        "default_state": '{"id":1,"result":{"result":{"type":"string","value":"{\\"button\\":true,\\"already\\":false}"}}}',
        "default_settings_opened": True, "choices_after_default": BEFORE,
        "import_tabs": ["chrome://settings/importData", "chrome://newtab/"],
        "second_tabs": ["chrome://newtab/"], "choices_after": BEFORE, "done": True}


class ProblemsTests(unittest.TestCase):
    def test_a_first_start_that_did_what_the_page_says(self):
        found = fr.problems(GOOD)
        self.assertEqual(sum(len(v) for v in found.values()), 0, found)

    def test_each_promise_that_is_not_kept(self):
        cases = [
            ({"first_tabs": ["chrome://newtab/"]}, "first start", "not the welcome page"),
            ({"first_tabs": []}, "first start", "not the welcome page"),
            ({"default_state": '{"value":"{\\"button\\":false,\\"already\\":true}"}'}, "default", "does not offer"),
            ({"default_settings_opened": False}, "default", "settings page did not open"),
            ({"choices_after_default": {**BEFORE, "http": "ThoronHTML"}}, "default", "changed without the person"),
            ({"import_tabs": ["chrome://thoron-welcome/"]}, "import", "import dialog did not open"),
            ({"second_tabs": ["chrome://thoron-welcome/"]}, "declined", "came again"),
            ({"second_tabs": []}, "declined", "did not start"),
            ({"choices_after": {**BEFORE, "html": "ThoronHTML"}}, "declined", "changed"),
        ]
        for change, step, words in cases:
            with self.subTest(change=change):
                found = fr.problems({**GOOD, **change})
                self.assertEqual(len(found[step]), 1, found)
                self.assertIn(words, found[step][0])
                self.assertEqual(sum(len(v) for v in found.values()), 1, found)

    def test_a_single_tab_saved_as_a_string_still_counts(self):
        self.assertEqual(fr.problems({**GOOD, "first_tabs": "chrome://thoron-welcome/"})["first start"], [])


class ScriptTests(unittest.TestCase):
    def test_the_check_presses_the_page_by_its_element_ids_and_reads_tabs_by_address(self):
        self.assertIn("getElementById('make-default').click()", fr.RUN)
        self.assertIn("getElementById('import').click()", fr.RUN)
        self.assertIn("/json/list", fr.RUN)
        self.assertIn("127.0.0.1", fr.RUN)

    def test_it_never_confirms_a_default_browser_itself(self):
        self.assertNotIn("UserChoice' -Name", fr.RUN)          # it only reads the person's choice
        self.assertIn("Stop-Process -Force", fr.RUN)


if __name__ == "__main__":
    unittest.main()
