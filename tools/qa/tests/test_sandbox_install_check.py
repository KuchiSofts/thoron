# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Tests of the parts of sandbox_install_check.py that do not need Windows Sandbox."""
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from tools.qa import sandbox_install_check as sb

GOOD = {"install_exit": 0, "program": True, "version_folders": ["158.0.8127.6500"], "entry": True,
        "entry_name": "Thoron", "entry_version": "0.1.1", "started": True, "window": True,
        "closed_by_itself": True, "profile": True, "setup_found": True,
        "uninstall_exit": 19, "program_after": False, "entry_after": False, "profile_after": True,
        "local_state_after": True}
OLD, NEW = "158.0.8127.3010", "158.0.8127.6500"
UPDATED = {"update_started": True, "update_from": OLD, "update_exit": 0, "update_status": 30,
           "update_new_exe_while_running": True,
           "update_folders_while_running": [OLD, NEW], "update_closed_by_itself": True,
           "update_new_exe_after_close": False, "update_restarted": True, "update_to": NEW,
           "update_new_exe_after": False, "update_folders_after": [NEW], "update_marker_kept": True,
           "update_local_state": True}


class ProblemsTests(unittest.TestCase):
    def test_a_clean_run_has_no_problems(self):
        self.assertEqual(sb.problems(GOOD), {"install": [], "start": [], "uninstall": []})

    def test_each_failure_lands_in_its_step(self):
        cases = [
            ({"install_exit": 7}, "install", "ended with 7"),
            ({"install_exit": 4}, "install", "ended with 4"),            # a newer version is there already
            ({"install_exit": "timeout"}, "install", "ended with timeout"),
            ({"program": False}, "install", "no thoron.exe"),
            ({"version_folders": ["1.0.0.0", "2.0.0.0"]}, "install", "version folders"),
            ({"entry": False}, "install", "no entry"),
            ({"started": False}, "start", "did not start"),
            ({"window": False}, "start", "without a window"),
            ({"closed_by_itself": False}, "start", "did not close"),
            ({"profile": False}, "start", "no profile"),
            ({"setup_found": False}, "uninstall", "no uninstaller"),
            ({"uninstall_exit": 20}, "uninstall", "ended with 20"),
            ({"program_after": True}, "uninstall", "still there"),
            ({"entry_after": True}, "uninstall", "entry among the installed programs is still there"),
            ({"profile_after": False}, "uninstall", "profile was not kept"),
            ({"local_state_after": False}, "uninstall", "profile was not kept"),
        ]
        for change, step, words in cases:
            with self.subTest(change=change):
                found = sb.problems({**GOOD, **change})
                self.assertEqual(len(found[step]), 1, found)
                self.assertIn(words, found[step][0])
                self.assertEqual(sum(len(v) for v in found.values()), 1, found)

    def test_a_list_of_one_saved_as_a_string_still_counts_as_one_folder(self):
        self.assertEqual(sb.problems({**GOOD, "version_folders": "158.0.8127.3010"})["install"], [])
        self.assertEqual(sb.update_problems({**UPDATED, "update_folders_while_running": NEW,
                                             "update_from": OLD}), [])

    def test_the_steps_are_reported_in_the_order_they_run(self):
        self.assertEqual(list(sb.problems(GOOD)), ["install", "start", "uninstall"])
        self.assertEqual(list(sb.problems({**GOOD, **UPDATED})), ["install", "start", "update", "uninstall"])

    def test_an_in_use_update_that_worked(self):
        self.assertEqual(sb.update_problems(UPDATED), [])
        self.assertEqual(sb.update_problems({**UPDATED, "update_status": None}), [])   # no status kept

    def test_what_an_in_use_update_can_get_wrong(self):
        cases = [
            ({"update_from": ""}, "did not start before the update"),
            ({"update_exit": 7}, "the update ended with 7"),
            ({"update_exit": "timeout"}, "the update ended with timeout"),
            ({"update_status": 2}, "kept status 2, not 30"),
            ({"update_new_exe_while_running": False}, "no new_thoron.exe"),
            ({"update_folders_while_running": [OLD]}, "no newer version folder"),
            ({"update_folders_while_running": [OLD, "158.0.8127.1000"]}, "no newer version folder"),
            ({"update_closed_by_itself": False}, "did not close"),
            ({"update_restarted": False}, "did not start again"),
            ({"update_to": OLD}, f"runs {OLD}, not {NEW}"),
            ({"update_new_exe_after": True}, "still there after the restart"),
            ({"update_marker_kept": False}, "not kept through the update"),
            ({"update_local_state": False}, "not kept through the update"),
        ]
        for change, words in cases:
            with self.subTest(change=change):
                found = sb.update_problems({**UPDATED, **change})
                self.assertTrue(any(words in f for f in found), found)

    def test_the_newest_folder_is_found_by_number_not_by_text(self):
        self.assertEqual(sb.update_problems({**UPDATED, "update_from": "158.0.8127.999",
                                             "update_folders_while_running": ["158.0.8127.999", NEW],
                                             "update_to": NEW}), [])

    def test_a_script_that_stopped_counts_everywhere_it_left_gaps(self):
        found = sb.problems({"error": "boom", "install_exit": "timeout"})
        self.assertIn("the script stopped: boom", found["install"])
        self.assertTrue(found["start"] and found["uninstall"])


class ResultsTests(unittest.TestCase):
    def test_partial_and_half_written_results(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "results.json"
            self.assertEqual(sb.read_results(path), {})
            path.write_text('{"reached": "upd', encoding="utf-8")
            self.assertEqual(sb.read_results(path), {})
            path.write_bytes(b'\xef\xbb\xbf{"reached": "uninstall"}')
            self.assertEqual(sb.read_results(path), {"reached": "uninstall"})

    def test_the_script_saves_before_every_step_and_marks_its_end(self):
        self.assertGreaterEqual(sb.RUN.count("Mark '"), 9)
        self.assertIn("$r.done = $true", sb.RUN)


class ConfigurationTests(unittest.TestCase):
    def test_the_sandbox_is_shut_off_from_the_network_and_the_installer_folder_is_read_only(self):
        root = ET.fromstring(sb.wsb(Path(r"C:\work & co")))
        self.assertEqual(root.findtext("Networking"), "Disable")
        self.assertEqual(root.findtext("VGpu"), "Disable")
        self.assertEqual(root.findtext("ClipboardRedirection"), "Disable")
        folders = {f.findtext("SandboxFolder"): (f.findtext("HostFolder"), f.findtext("ReadOnly"))
                   for f in root.iter("MappedFolder")}
        self.assertEqual(folders[sb.INSIDE + r"\in"], (r"C:\work & co\in", "true"))
        self.assertEqual(folders[sb.INSIDE + r"\out"], (r"C:\work & co\out", "false"))
        self.assertIn(r"\in\run.ps1", root.findtext("LogonCommand/Command"))

    def test_the_script_installs_silently_from_the_sandbox_disk_and_shuts_down(self):
        self.assertIn("'--silent'", sb.RUN)
        self.assertIn("Copy-Item $shared.FullName $copy", sb.RUN)
        self.assertNotIn("--headless", sb.RUN)               # headless would use a throwaway profile
        self.assertIn("'--uninstall', '--force-uninstall'", sb.RUN)
        self.assertNotIn("--delete-profile", sb.RUN)
        self.assertTrue(sb.RUN.rstrip().endswith("Stop-Computer -Force"))

    def test_a_system_level_run_installs_and_uninstalls_for_every_user(self):
        self.assertIn("$level = @('--system-level')", sb.RUN)
        self.assertIn("+ $level) 300", sb.RUN.split("function Install")[1].split("function Entry")[0])
        self.assertIn("'--force-uninstall', '--verbose-logging') + $level", sb.RUN)
        self.assertIn("Join-Path $env:ProgramFiles 'Thoron\\Application'", sb.RUN)
        self.assertIn("$uninstallKey = if ($system) { 'HKLM:' } else { 'HKCU:' }", sb.RUN)


if __name__ == "__main__":
    unittest.main()
