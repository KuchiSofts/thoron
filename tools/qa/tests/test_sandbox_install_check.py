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
            ({"update_browser_before": 6, "update_browser_after": 0}, "ended the running browser"),
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

    def test_an_update_for_every_user_ends_the_browser_and_updates_in_place(self):
        system = {**UPDATED, "system_level": True, "update_status": 2, "update_new_exe_while_running": False,
                  "update_browser_before": 6, "update_browser_after": 0}
        self.assertEqual(sb.update_problems(system), [])
        self.assertEqual(sb.update_problems({**system, "update_exit_type": "SessionEnded"}), [])
        killed = sb.update_problems({**system, "update_exit_type": "Crashed"})
        self.assertEqual(len(killed), 1, killed)
        self.assertIn("without saving its session first (exit type Crashed", killed[0])
        found = sb.update_problems({**system, "update_browser_after": 6, "update_status": 30,
                                    "update_new_exe_while_running": True})
        self.assertEqual(len(found), 3, found)
        self.assertTrue(any("left the older browser running" in f for f in found))
        self.assertTrue(any("kept status 30, not 2" in f for f in found))
        self.assertTrue(any("new_thoron.exe after the update of an install for every user" in f for f in found))

    def test_the_newest_folder_is_found_by_number_not_by_text(self):
        self.assertEqual(sb.update_problems({**UPDATED, "update_from": "158.0.8127.999",
                                             "update_folders_while_running": ["158.0.8127.999", NEW],
                                             "update_to": NEW}), [])

    def test_a_script_that_stopped_counts_everywhere_it_left_gaps(self):
        found = sb.problems({"error": "boom", "install_exit": "timeout"})
        self.assertIn("the script stopped: boom", found["install"])
        self.assertTrue(found["start"] and found["uninstall"])


TASK = {"task": {"found": True, "Command": r"C:\Thoron\Application\158.0.8127.6500\ThoronSetup.exe",
                 "Arguments": "--scheduled --variant=win-x64-avx2", "LogonType": "InteractiveToken",
                 "RunLevel": "LeastPrivilege", "StartWhenAvailable": "true"},
        "task_run": {"run_exit": 0, "status": "Queued", "last_result": "0"}, "task_direct": 4, "task_after": False,
        "task_switched_off": 0, "task_install_again": 0}
TASK["task_again"] = {**TASK["task"], "Enabled": "false"}


class TaskTests(unittest.TestCase):
    def test_a_task_that_worked_and_its_place_among_the_steps(self):
        found = sb.problems({**GOOD, **TASK})
        self.assertEqual(list(found), ["install", "task", "start", "uninstall"])
        self.assertEqual(found["task"], [])

    def test_what_the_task_can_get_wrong(self):
        task = TASK["task"]
        cases = [
            ({"task": {"found": False}}, "registered no update task"),
            ({"task": {**task, "Command": task["Command"].replace("6500", "3010")}}, "not the installed version's"),
            ({"task": {**task, "Arguments": "--scheduled"}}, "arguments"),
            ({"task": {**task, "LogonType": "Password"}}, "user's own rights"),
            ({"task": {**task, "RunLevel": "HighestAvailable"}}, "user's own rights"),
            ({"task": {**task, "StartWhenAvailable": "false"}}, "is skipped"),
            ({"task_run": {"status": "Ready", "last_result": "267011"}}, "not held for the network"),
            ({"task_direct": 0}, "ended with 0"),
            ({"task_after": True}, "uninstall left the update task"),
            ({"task_switched_off": 1}, "could not switch the task off"),
            ({"task_install_again": 7}, "installing again ended with 7"),
            ({"task_again": {**task, "Command": r"C:\Windows\System32\where.exe", "Enabled": "false"}},
             "did not register Thoron's task again"),
            ({"task_again": {**task, "Enabled": "true"}}, "switched the task back on"),
        ]
        for change, words in cases:
            with self.subTest(change=change):
                found = sb.task_problems({**GOOD, **TASK, **change})
                self.assertEqual(len(found), 1, found)
                self.assertIn(words, found[0])

    def test_an_install_for_every_user_has_no_task(self):
        self.assertEqual(sb.task_problems({**GOOD, "system_level": True, "task": {"found": False}}), [])
        self.assertIn("every user", sb.task_problems({**GOOD, **TASK, "system_level": True})[0])

    def test_after_an_update_the_task_runs_the_newer_version(self):
        first = {**TASK["task"], "Command": TASK["task"]["Command"].replace(NEW, OLD)}
        newer = {**GOOD, **TASK, **UPDATED, "version_folders": [OLD], "task": first,
                 "update_task": {**TASK["task"]}}
        self.assertEqual(sb.task_problems(newer), [])
        stale = {**newer, "update_task": {**TASK["task"], "Command": TASK["task"]["Command"].replace(NEW, OLD)}}
        self.assertIn("after the update", sb.task_problems(stale)[0])

    def test_the_script_registers_runs_and_removes_nothing_itself(self):
        # it reads the task (/Query), starts it (/Run) and switches it off as a person would (/Change): the
        # installer registers it, the uninstaller removes it
        self.assertIn("'/Query', '/TN', $taskName, '/XML'", sb.RUN)
        self.assertIn("'/Run', '/TN', $taskName", sb.RUN)
        self.assertNotIn("/Create", sb.RUN)
        self.assertNotIn("/Delete", sb.RUN)


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


class DeltaTests(unittest.TestCase):
    GOOD = {"delta_from": OLD, "delta_to": NEW, "delta_exit": 0, "delta_folders": [OLD, NEW],
            "delta_staging_left": False, "delta_started": True, "delta_runs": NEW, "delta_marker_kept": True}

    def test_a_delta_that_worked(self):
        self.assertEqual(sb.delta_problems(self.GOOD), [])
        self.assertIn("delta", sb.problems({**GOOD, **self.GOOD}))

    def test_what_a_delta_can_get_wrong(self):
        for change, words in (({"delta_exit": 12}, "ended with 12"), ({"delta_folders": [OLD]}, "no folder"),
                              ({"delta_staging_left": True}, "staged files"), ({"delta_started": False}, "did not start"),
                              ({"delta_runs": OLD}, f"runs {OLD}, not {NEW}"), ({"delta_marker_kept": False}, "profile")):
            with self.subTest(change=change):
                found = sb.delta_problems({**self.GOOD, **change})
                self.assertEqual(len(found), 1, found)
                self.assertIn(words, found[0])

    def test_the_script_applies_the_delta_with_the_updater(self):
        self.assertIn('"--apply-installed-delta=$deltaCopy", "--from=$($r.delta_from)"', sb.RUN)


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
