# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Tests of the parts of sandbox_guides_check.py that do not need Windows Sandbox."""
import unittest

from tools.qa import sandbox_guides_check as gc

GOOD = {"readonly_result": "Image: x | Text: Thoron could not be installed | Text: 109 | Pane: ",
        "readonly_exit": 109, "install_question_found": True, "install_done_found": True, "install_exit": 0,
        "install_folder": True, "install_entry": "Thoron 0.1.1", "install_task": True, "first_window": True,
        "first_profile": True, "mode_file": "off", "mode_scheduled_exit": 9, "remove_backup": True,
        "remove_question": True, "remove_boxes": ["box = Off"], "remove_program_gone": True,
        "remove_entry_gone": True, "remove_task_gone": True, "remove_profile_kept": True,
        "portable_hash_matches": True, "portable_extracted": True, "portable_window": True,
        "portable_profile": True, "portable_gone": True, "done": True}


class ProblemsTests(unittest.TestCase):
    def test_a_run_that_followed_every_step(self):
        found = gc.problems(GOOD)
        self.assertEqual(sum(len(v) for v in found.values()), 0, found)

    def test_each_step_that_differs_from_its_guide(self):
        cases = [
            ({"readonly_result": "Text: something else"}, "install, step 3: read-only folder", "109"),
            ({"readonly_exit": 0}, "install, step 3: read-only folder", "ended with 0"),
            ({"install_question_found": False}, "install, step 4", "no question"),
            ({"install_done_found": False}, "install, step 4", "no message at the end"),
            ({"install_exit": "timeout"}, "install, step 4", "ended with timeout"),
            ({"install_folder": False}, "install, step 5", "no thoron.exe"),
            ({"install_entry": None}, "install, step 6", "list of installed apps"),
            ({"install_task": False}, "install, step 7", "no daily update task"),
            ({"first_profile": False}, "first start", "make its profile"),
            ({"mode_file": ""}, "updates, section 4", "update-mode holds"),
            ({"mode_scheduled_exit": 4}, "updates, section 4", "ended with 4"),
            ({"remove_question": False}, "remove, installed, step 3", "no Uninstall question"),
            ({"remove_boxes": ["box = On"]}, "remove, installed, step 4", "not unticked"),
            ({"remove_boxes": []}, "remove, installed, step 4", "not unticked"),
            ({"remove_profile_kept": False}, "remove, installed", "profile was not kept"),
            ({"remove_task_gone": False}, "remove, installed", "daily task"),
            ({"portable_hash_matches": False}, "portable, step 2", "SHA-256"),
            ({"portable_extracted": False}, "portable, step 3", "Extract All"),
            ({"portable_profile": False}, "portable, step 4", "User Data"),
            ({"portable_gone": False}, "remove, portable", "could not be deleted"),
            ({"error_install": "boom"}, "script", "error_install: boom"),
        ]
        for change, step, words in cases:
            with self.subTest(change=change):
                found = gc.problems({**GOOD, **change})
                self.assertEqual(len(found[step]), 1, found)
                self.assertIn(words, found[step][0])
                self.assertEqual(sum(len(v) for v in found.values()), 1, found)

    def test_a_single_box_saved_as_a_string_still_counts(self):
        self.assertEqual(gc.problems({**GOOD, "remove_boxes": "box = Off"})["remove, installed, step 4"], [])


class ScriptTests(unittest.TestCase):
    def test_buttons_are_pressed_by_id_or_by_default_never_by_their_words(self):
        # Windows names the buttons in its own language: the script does not depend on their text
        self.assertIn("[Dialogs]::Click($d, 6)", gc.RUN)          # IDYES, the installer's Install
        self.assertIn("[Dialogs]::Click($d, 1)", gc.RUN)          # IDOK
        self.assertIn("SendWait('{ENTER}')", gc.RUN)             # the uninstall question's default button
        self.assertNotIn("FindButton 'OK'", gc.RUN)
        self.assertNotIn("FindButton 'Uninstall'", gc.RUN)

    def test_the_guide_command_is_run_as_the_guide_writes_it(self):
        self.assertIn('Set-Content -Path "$env:LOCALAPPDATA\\Thoron\\Application\\update-mode" -Value off', gc.RUN)


if __name__ == "__main__":
    unittest.main()
