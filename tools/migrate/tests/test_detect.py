# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""Finding the browsers of the Chromium family and their profiles (ROADMAP P3.13)."""
import json
import tempfile
import unittest
from pathlib import Path

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

    def test_a_broken_local_state_gives_no_profile(self):
        folder = Path(self.env["LOCALAPPDATA"]) / "Vivaldi" / "User Data"
        (folder / "Local State").write_text("not json")
        self.assertEqual(detect.profiles_of(folder, False), [])


if __name__ == "__main__":
    unittest.main()
