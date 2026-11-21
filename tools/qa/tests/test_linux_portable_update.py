# Copyright 2026 KuchiSofts. Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
"""The update of a Linux portable copy (ROADMAP P3.12, P3.6): versions, the files list and the reading."""
import tempfile
import unittest
from pathlib import Path

from tools.qa import linux_portable_update as lu

PKG = "/home/tester/a b/ThoronPortable"


def start(version: str) -> dict:
    return {"executable_path": f"{PKG}/Application/{version}/thoron", "profile_path": f"{PKG}/User Data/Default",
            "home": lu.HOME}


def good() -> dict:
    return {"older": "158.0.8127.65", "newer": "158.0.8127.66", "start": start("158.0.8127.65"),
            "apply": [0, "applied"], "update": start("158.0.8127.66"),
            "status": [0, "current: 158.0.8127.66\nprevious: 158.0.8127.65\n"], "rollback_cli": [0, ""],
            "rollback": start("158.0.8127.65")}


class Tests(unittest.TestCase):
    def test_versions_and_files(self):
        self.assertEqual(lu.newer_than("158.0.8127.65"), "158.0.8127.66")
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "a").mkdir()
            (Path(d) / "a" / "b.pak").write_bytes(b"x")
            self.assertEqual(lu.files_list(Path(d)), [{"path": "a/b.pak", "size": 1, "sha256":
                             "2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881"}])

    def test_a_good_update_passes(self):
        self.assertEqual({k: v for k, v in lu.problems(good(), PKG).items() if v}, {})

    def test_each_failure_is_named(self):
        cases = {
            "update": lambda f: f.update(update=start("158.0.8127.65")),
            "status": lambda f: f.update(status=[0, "current: 158.0.8127.65\n"]),
            "rollback": lambda f: f["rollback"].update(home="https://example.com/other"),
            "start": lambda f: f["start"].update(profile_path="/home/tester/.config/thoron/Default"),
        }
        for step, change in cases.items():
            with self.subTest(step):
                found = good()
                change(found)
                self.assertTrue(lu.problems(found, PKG)[step], step)


if __name__ == "__main__":
    unittest.main()
