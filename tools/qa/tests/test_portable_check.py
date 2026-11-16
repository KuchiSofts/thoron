# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""The Windows portable package: the real check's own judgement (ROADMAP P2.8)."""
import base64
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unicodedata
import unittest
from pathlib import Path
from unittest import mock

from tools.qa import portable_check as pc
from tools.release import portable as po

PACKAGE = Path("C:\\scratch\\a folder\\ThoronPortable")


def good(package: Path = PACKAGE, **changes) -> dict:
    found = {"launcher": 0, "launcher_s": 0.2, "port_file": True, "local_state": True, "preferences": True,
             "executable_path": str(package / "Application" / "thoron.exe"),
             "process": str(package / "Application" / "thoron.exe"),
             "profile_path": str(package / "User Data" / "Default"),
             "command_line": f'"{package}\\Application\\thoron.exe" --host-resolver-rules="{pc.OFFLINE}" --flag',
             "before": 16, "after": 17, "saved": 17, "left": 0, "key": "the Windows account (DPAPI)"}
    found.update(changes)
    return found


class JudgementTests(unittest.TestCase):
    def test_the_folders(self):
        self.assertTrue(Path(pc.__file__).read_bytes().isascii())       # the names are built from code points
        cases = {c["name"]: c for c in pc.cases()}
        self.assertEqual(list(cases), ["spaces", "scripts", "signs"])
        every = [c[key] for c in cases.values() for key in ("first", "second")]
        self.assertEqual(len(set(every)), len(every))
        self.assertEqual(len({c["value"] for c in cases.values()} | {pc.DEFAULT}), 4)
        self.assertIn("  ", cases["spaces"]["first"])
        kinds = {unicodedata.name(ch).split()[0] for ch in cases["scripts"]["first"] if not ch.isascii()}
        self.assertLessEqual({"LATIN", "CYRILLIC", "CJK", "HIRAGANA", "KATAKANA", "HANGUL"}, kinds)
        for folder in (cases["signs"]["first"], cases["signs"]["second"]):
            for sign in "&%!":
                self.assertIn(sign, folder)
        for folder in every:        # names Windows can make
            self.assertFalse(set(folder) & set('<>:"/\\|?*'), folder)
            self.assertFalse(folder.endswith((" ", ".")), folder)

    def test_the_start_line_is_a_double_click_with_arguments(self):
        line = pc.start_line(PACKAGE)
        self.assertTrue(line.startswith(f'"{PACKAGE / "Thoron.cmd"}" --headless=new '))
        self.assertIn(f'"--host-resolver-rules={pc.OFFLINE}"', line)
        self.assertIn("--remote-debugging-address=127.0.0.1 --remote-debugging-port=0", line)
        self.assertNotIn("user-data-dir", line)     # the profile's place is the launcher's business alone

    def test_a_good_start(self):
        self.assertEqual(pc.start_problems(PACKAGE, good()), [])
        if os.name == "nt":         # Windows does not tell upper and lower case apart
            upper = good(executable_path=str(PACKAGE / "Application" / "thoron.exe").upper())
            self.assertEqual(pc.start_problems(PACKAGE, upper), [])

    def test_what_a_start_can_get_wrong(self):
        elsewhere = "C:\\somewhere\\Thoron\\User Data\\Default"
        cases = {
            "the run failed: DevTools did not start": good(error="DevTools did not start"),
            "it waits for the browser": good(launcher=None),
            "the launcher ended with 1": good(launcher=1),
            "the browser names a program": good(executable_path="C:\\other\\Application\\thoron.exe"),
            "Windows names a program": good(process="C:\\other\\Application\\thoron.exe"),
            "its profile is not the one in the folder": good(profile_path=elsewhere),
            "did not reach the browser whole": good(command_line="thoron.exe --host-resolver-rules=MAP"),
            "the DevTools port file is not": good(port_file=False),
            "Local State is not": good(local_state=False),
            "Default\\Preferences is not": good(preferences=False),
            "had to be stopped": good(left=1),
        }
        for want, found in cases.items():
            with self.subTest(want):
                self.assertTrue([p for p in pc.start_problems(PACKAGE, found) if want in p],
                                pc.start_problems(PACKAGE, found))
        self.assertEqual(len(pc.start_problems(PACKAGE, {})), 8)    # nothing seen: everything is a problem

    def test_a_drive_letter_on_the_folder(self):
        drive = Path("C:\\")
        found = good(drive, process=str(PACKAGE / "Application" / "thoron.exe"))
        self.assertEqual(pc.start_problems(drive, found, real=PACKAGE), [])
        self.assertTrue(pc.start_problems(drive, found))    # without the folder behind the letter it is elsewhere
        self.assertTrue(pc.start_problems(drive, good(PACKAGE), real=PACKAGE))  # the profile must be the letter's

    def test_the_setting(self):
        self.assertEqual(pc.setting_problems(good(), 16, 17), [])
        self.assertEqual(pc.setting_problems(good(before=17, after=None), 17, None), [])
        self.assertIn("at the start", pc.setting_problems(good(before=17), 16, 17)[0])     # not a new profile
        self.assertIn("after the change", pc.setting_problems(good(after=16), 16, 17)[0])
        self.assertIn("on the disk", pc.setting_problems(good(saved=16), 16, 17)[0])
        self.assertIn("at the start", pc.setting_problems(good(before=16, saved=16), 17, None)[0])  # not read back
        self.assertEqual(len(pc.setting_problems({}, 16, 17)), 3)

    def test_the_folder(self):
        top = ["Application", "README.txt", "Thoron.cmd", "User Data"]
        browser = ["158.0.1.2/chrome.dll", "thoron.exe"]
        self.assertEqual(pc.folder_problems(top, ["Thoron spaces"], [], browser, browser), [])
        self.assertTrue(pc.folder_problems(top + ["debug.log"], ["Thoron spaces"], [], browser, browser))
        self.assertTrue(pc.folder_problems(top[:3], ["Thoron spaces"], [], browser, browser))   # no profile there
        self.assertIn("beside", pc.folder_problems(top, ["Thoron spaces", "User Data"], [], browser, browser)[0])
        self.assertIn("working directory", pc.folder_problems(top, ["Thoron spaces"], ["User Data"], browser, browser)[0])
        self.assertIn("debug.log", pc.folder_problems(top, ["Thoron spaces"], [], browser, browser + ["debug.log"])[0])

    def test_the_host(self):
        before = {"own": ["Application", "User Data"], "profile": ["Default", "Local State"], "none": None}
        self.assertEqual(pc.host_problems(before, before), [])
        gone = dict(before, profile=["Default"])
        self.assertEqual(pc.host_problems(before, gone), [])        # the PC's own browser may remove a file
        new = dict(before, profile=["Default", "DevToolsActivePort", "Local State"])
        self.assertEqual(pc.host_problems(before, new), ["new in profile: ['DevToolsActivePort']"])
        self.assertEqual(pc.host_problems(before, dict(before, none=[])), ["none was made"])
        self.assertEqual(pc.host_problems({}, {}), [])

    def test_the_registry_report(self):
        before = {"": 1, "BLBeacon": 2, "PreferenceMACs\\Default": 3}
        self.assertEqual(pc.registry_report(None, None), "no key")
        self.assertIn("the key was made, with ['BLBeacon'", pc.registry_report(None, before))
        self.assertEqual(pc.registry_report(before, before), "new keys: none; written during the runs: none")
        after = {"": 9, "BLBeacon": 8, "PreferenceMACs\\Default": 3, "StabilityMetrics": 7}
        self.assertEqual(pc.registry_report(before, after), "new keys: ['StabilityMetrics']; written during the runs: "
                                                            "['(the key itself)', 'BLBeacon']")

    def test_small_things(self):
        self.assertEqual(pc.masked(["scoped_dir12_345", "scoped_dir7_8", "a.tmp"]), {"a.tmp": 1, "scoped_dir#_#": 2})
        key = base64.b64encode(b"DPAPI" + b"\x01" * 20).decode()
        self.assertEqual(pc.key_kind({"os_crypt": {"encrypted_key": key}}), "the Windows account (DPAPI)")
        self.assertEqual(pc.key_kind({"os_crypt": {"encrypted_key": base64.b64encode(b"other").decode()}}), "another kind")
        self.assertEqual(pc.key_kind({}), "no key")
        self.assertEqual(pc.key_kind({"os_crypt": {"encrypted_key": "%%%"}}), "another kind")
        settings = {"a": {"b": ["C:\\x\\Old Place\\y", 5, {"C:/x/old place": True}]}, "c": "elsewhere",
                    "at Old Place": 1}
        self.assertEqual(pc.where_named(settings, "old place"), ["a.b", "a.b (a name in it)", "(a name)"])
        self.assertEqual(pc.where_named(settings, "nowhere"), [])
        self.assertTrue(pc.same(" c:\\SCRATCH\\a folder\\.\\ThoronPortable ", PACKAGE) or os.name != "nt")
        self.assertFalse(pc.same(None, PACKAGE))
        self.assertFalse(pc.same("C:\\scratch", PACKAGE))

    def test_what_a_start_left_on_the_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "User Data"
            self.assertEqual(pc.disk_facts(profile), {"local_state": False, "preferences": False, "saved": None,
                                                      "key": "no key"})
            (profile / "Default").mkdir(parents=True)
            (profile / "Local State").write_text(json.dumps({"os_crypt": {}}), encoding="utf-8")
            settings = {"webkit": {"webprefs": {"default_font_size": 19}}, "x": "was in an Old Place"}
            (profile / "Default" / "Preferences").write_text(json.dumps(settings), encoding="utf-8")
            self.assertEqual(pc.disk_facts(profile), {"local_state": True, "preferences": True, "saved": 19,
                                                      "key": "no key"})
            self.assertEqual(pc.mentions(profile, "old place"), ["Default/Preferences: x"])
            self.assertEqual(pc.names_in({"here": profile, "gone": profile / "nowhere"}),
                             {"here": ["Default", "Local State"], "gone": None})

    def test_unpacking_the_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "Chrome-bin"
            for name in ("thoron.exe", "158.0.1.2/chrome.dll"):
                (src / name).parent.mkdir(parents=True, exist_ok=True)
                (src / name).write_bytes(b"x")
            made = po.build(src, Path(tmp) / "dist", "win-x64-avx2")
            self.assertEqual(pc.unpack(made["zip"], Path(tmp) / "a place", made["package"]), [])
            (made["package"] / "Application" / "more.dll").write_bytes(b"x")    # the .zip is not this package's
            self.assertEqual(pc.unpack(made["zip"], Path(tmp) / "another", made["package"]),
                             ["the .zip does not unpack to the package's files"])

    def test_on_another_system_the_check_does_not_apply(self):
        out = io.StringIO()
        with mock.patch.object(pc, "supported", return_value=False), contextlib.redirect_stdout(out), \
                mock.patch.object(pc, "run", side_effect=AssertionError("nothing may be started")):
            self.assertEqual(pc.main(["--chrome-bin", "x", "--work", "y"]), 0)
        self.assertIn("does not apply", out.getvalue())

    def test_the_verdict(self):
        for problems, code, word in (([], 0, "PASSED"), (["host: new in x"], 1, "FAILED (1 problem(s))")):
            out = io.StringIO()
            with tempfile.TemporaryDirectory() as tmp, mock.patch.object(pc, "supported", return_value=True), \
                    mock.patch.object(pc, "run", return_value=problems) as run, contextlib.redirect_stdout(out):
                self.assertEqual(pc.main(["--chrome-bin", tmp, "--work", tmp, "--case", "signs"]), code)
            self.assertEqual(run.call_args.args[2:], ("win-x64-avx2", False, "signs"))
            self.assertIn(f"PORTABLE CHECK: {word}", out.getvalue())


@unittest.skipUnless(os.name == "nt", "Windows processes")
class ProcessTests(unittest.TestCase):
    """Telling the check's own processes from every other one, tried on a process this test starts itself."""

    def test_a_process_is_found_by_its_program_file_and_held(self):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            name = Path(sys.executable).name
            found = pc.own_processes(lambda program: True, name=name)
            self.assertIn(child.pid, [pid for pid, _ in found])
            self.assertEqual(pc.own_processes(lambda program: False, name=name), [])
            program = pc.program_of(child.pid)
            self.assertEqual(Path(program).name.lower(), name.lower())
            self.assertIn(child.pid, [pid for pid, _ in pc.own_processes(pc.only(Path(program)), name=name)])
            held = pc.Started(child.pid)
            try:
                self.assertEqual(held.program(), program)
                with self.assertRaises(subprocess.TimeoutExpired):
                    held.wait(timeout=0.2)
                child.kill()
                self.assertEqual(held.wait(timeout=20), 0)
            finally:
                held.close()
        finally:
            child.kill()
            child.wait()

    def test_a_process_that_is_not_there(self):
        self.assertIsNone(pc.program_of(0))
        with self.assertRaises(OSError):
            pc.Started(0)

    def test_nothing_of_ours_runs_so_nothing_is_stopped(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(pc.bench, "_stop") as stop:
            self.assertEqual(pc.stop_own(lambda program: False, Path(tmp), patience_s=0), 0)
        stop.assert_not_called()

    def test_a_free_drive_letter(self):
        letter = pc.free_letter()
        if letter is not None:
            self.assertFalse(os.path.exists(f"{letter}:\\"))

    def test_the_registry_listing_reads_names_and_times_only(self):
        self.assertIsNone(pc.registry_keys("Software\\Thoron portable check, no such key"))
        keys = pc.registry_keys("Environment")      # a key every Windows account has
        self.assertIn("", keys)
        self.assertTrue(all(isinstance(written, int) for written in keys.values()))


if __name__ == "__main__":
    unittest.main()
