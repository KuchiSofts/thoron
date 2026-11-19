# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Finding the browsers of the Chromium family and their profiles (ROADMAP P3.13)."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.migrate import detect


def user_data(root: Path, rel: str, profiles: dict, running: bool = False) -> Path:
    folder = root / rel
    folder.mkdir(parents=True)
    (folder / "Local State").write_text(json.dumps({"profile": {"info_cache": {
        name: {"name": shown} for name, shown in profiles.items()}}}), encoding="utf-8")
    for name in profiles:
        (folder / name).mkdir()
        (folder / name / "Preferences").write_text("{}")
    if running:
        (folder / "lockfile").write_text("")
    return folder


class DetectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.env = {"LOCALAPPDATA": str(root / "Local"), "APPDATA": str(root / "Roaming")}
        local, roaming = root / "Local", root / "Roaming"
        user_data(local, "Thorium/User Data", {"Default": "Person 1", "Profile 1": "Work"})
        user_data(local, "Google/Chrome/User Data", {"Default": "Me"}, running=True)
        user_data(local, "Microsoft/Edge/User Data", {"Default": "Profile 1"})
        user_data(local, "BraveSoftware/Brave-Browser/User Data", {"Default": "Brave"})
        user_data(local, "Vivaldi/User Data", {"Default": "V"})
        opera = roaming / "Opera Software" / "Opera Stable"
        opera.mkdir(parents=True)
        (opera / "Local State").write_text("{}")
        (opera / "Preferences").write_text("{}")

    def tearDown(self):
        self.tmp.cleanup()

    def test_every_browser_of_the_stage_is_found(self):
        found = {b["browser"]: b for b in detect.detect(self.env)}
        self.assertEqual(sorted(found), ["Brave", "Chrome", "Edge", "Opera", "Thorium", "Vivaldi"])
        self.assertEqual([p["name"] for p in found["Thorium"]["profiles"]], ["Person 1", "Work"])
        self.assertEqual(found["Opera"]["profiles"], [{"folder": ".", "name": "Default"}])

    def test_a_running_browser_is_said_to_run(self):
        found = {b["browser"]: b for b in detect.detect(self.env)}
        self.assertTrue(found["Chrome"]["running"])
        self.assertFalse(found["Thorium"]["running"])

    def test_a_profile_without_its_folder_or_with_a_strange_name_is_left_out(self):
        folder = Path(self.env["LOCALAPPDATA"]) / "Thorium" / "User Data"
        state = json.loads((folder / "Local State").read_text())
        state["profile"]["info_cache"]["Profile 9"] = {"name": "gone"}
        state["profile"]["info_cache"]["../../x"] = {"name": "escape"}
        (folder / "Local State").write_text(json.dumps(state))
        names = [p["folder"] for p in detect.profiles_of(folder, False)]
        self.assertEqual(names, ["Default", "Profile 1"])

    def test_only_the_current_user_s_folders_are_looked_at(self):
        self.assertEqual(detect.detect({}), [])
        self.assertEqual(detect.detect({"LOCALAPPDATA": str(Path(self.tmp.name) / "nothing")}), [])

    def test_another_user_s_and_system_wide_folders_are_never_looked_at(self):
        # threat model I9: only the current user's own profile locations
        root = Path(self.tmp.name)
        someone_else = root / "Users" / "someone else"
        user_data(someone_else / "AppData" / "Local", "Google/Chrome/User Data", {"Default": "Theirs"})
        user_data(someone_else / "AppData" / "Local", "Chromium/User Data", {"Default": "Theirs too"})
        shared = root / "ProgramData"
        user_data(shared, "Chromium/User Data", {"Default": "Shared"})
        env = dict(self.env, PROGRAMDATA=str(shared), ALLUSERSPROFILE=str(shared), PUBLIC=str(shared),
                   PROGRAMFILES=str(shared), SYSTEMDRIVE=str(root), USERPROFILE=str(someone_else),
                   HOMEPATH=str(someone_else))
        found = detect.detect(env)
        self.assertEqual(sorted(b["browser"] for b in found),
                         ["Brave", "Chrome", "Edge", "Opera", "Thorium", "Vivaldi"])
        own = (Path(self.env["LOCALAPPDATA"]), Path(self.env["APPDATA"]))
        for browser in found:
            self.assertTrue(any(Path(browser["folder"]).is_relative_to(base) for base in own), browser["folder"])
        names = [p["name"] for b in found for p in b["profiles"]]
        for theirs in ("Theirs", "Theirs too", "Shared"):
            self.assertNotIn(theirs, names)

    def test_a_broken_local_state_gives_no_profile(self):
        folder = Path(self.env["LOCALAPPDATA"]) / "Vivaldi" / "User Data"
        (folder / "Local State").write_text("not json")
        self.assertEqual(detect.profiles_of(folder, False), [])

    def test_a_crafted_local_state_gives_no_profile_and_no_error(self):
        # threat model I3: another browser's file may hold anything
        folder = Path(self.env["LOCALAPPDATA"]) / "Vivaldi" / "User Data"
        for text in ("[" * 200_000, '{"profile": []}', '{"profile": {"info_cache": []}}',
                     '{"profile": {"info_cache": 5}}', '{"profile": null}', "[]", '"text"'):
            with self.subTest(text=text[:40]):
                (folder / "Local State").write_text(text, encoding="utf-8")
                self.assertEqual(detect.profiles_of(folder, False), [])
        # the other browsers are found as before
        found = {b["browser"]: b for b in detect.detect(self.env)}
        self.assertEqual(found["Vivaldi"]["profiles"], [])
        self.assertEqual(len(found["Thorium"]["profiles"]), 2)

    def test_a_local_state_larger_than_it_can_be_is_not_read(self):
        folder = Path(self.env["LOCALAPPDATA"]) / "Thorium" / "User Data"
        with mock.patch.object(detect, "MOST_LOCAL_STATE_BYTES", 10):
            self.assertEqual(detect.profiles_of(folder, False), [])
        self.assertEqual(len(detect.profiles_of(folder, False)), 2)


if __name__ == "__main__":
    unittest.main()
